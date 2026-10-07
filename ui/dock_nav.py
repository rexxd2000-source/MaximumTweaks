"""Floating bottom dock.

Renders ``ui/dock_nav.html`` inside a transparent QtWebEngine view that floats
above the main window's page stack and exposes a QWebChannel bridge under
``window.pywebview.api``.

Geometry contract
-----------------
The dock is a single fixed element inside the page (``bottom:0``, horizontally
centred, ``z-index`` 999). This widget is therefore *not* part of any layout: it
is a plain child of the window, raised above the page stack.

The widget is created at one fixed size (560x340) and is **never resized**. A
QWebEngineView only re-lays-out and re-rasterises its content after a resize, so
resizing the widget during an open or close leaves the DOM painting its old
frame for a few frames while the widget has already moved on - that is what drew
a ghost copy of the dock bar in the middle of the window, and what made the
popover appear to open late or not at all after a fast double-click. The old
design fed a measurement back from the page on every open/close to size the
widget to its content, so every click resized it.

Because the widget is now always the full size of the bar *plus* the popover,
the empty area above the bar is covered by a click-through mask instead: when the
panel is closed only the bottom strip is interactive (``CLOSED_MASK_H``), and
when it is open the mask is cleared so the panel takes clicks. Nothing is ever
resized, so there is no frame in which the web content can lag the widget.

``apply_geometry()`` only ever *moves* the widget, and only in response to a
window resize. The main window's minimum height (700) guarantees the dock always
fits, so no clamping is needed.
"""
from __future__ import annotations

import base64
import json
import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QObject, QRect, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QRegion
from PySide6.QtWebChannel import QWebChannel  # noqa: F401 - registers qtwebchannel.js
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWidgets import QVBoxLayout, QWidget

from config.app_config import ROOT
from ui.pages._web import make_webview

HTML_REL = "ui/dock_nav.html"
# The mark shown on the Dashboard's home button. logo-64.png is the current
# artwork; assets/logo.png stays as the fallback so a broken/partial install
# still renders a logo instead of an empty circle.
BRAND_REL = "assets/logo-64.png"
LOGO_REL = "assets/logo.png"

# The home button is 44 CSS px (see .logo in dock_nav.html). The mark is
# re-emitted at 2x its source and flattened onto its own dark field, so the
# browser only ever downscales (crisp at 100/150/200% display scaling) and no
# semi-transparent edge is left for the glass behind it to bleed through.
BRAND_PX = 128
BRAND_FIELD = (0x0F, 0x08, 0x1A)  # the logo's field colour, matches .logo in CSS

# The clearance between the dock and the window's bottom edge. The page itself
# is bottom-anchored at 0; this is the one place the 24px gap is set.
BOTTOM_GAP = 24
# The page's fixed element is intrinsically this wide (the popover width).
DOCK_W = 560
# Bar height (plus its shadow pocket), used only to place the closed mask and to
# tell floating UI where the bar's top edge is.
DOCK_BAR_H = 110
# The widget's one and only size: the bar, the 12px gap, the 212px popover and
# slack. Set once in __init__ and never changed.
DOCK_H = 340
# While the panel is closed, only the bottom strip of the widget accepts clicks
# so the page underneath stays reachable. The extra 20px over DOCK_BAR_H keeps
# the lifted/hovered orbs inside the interactive area.
CLOSED_MASK_H = DOCK_BAR_H + 20


def _asset(rel: str) -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    base = Path(meipass) if meipass else ROOT
    return base / rel


def _html_path() -> Path:
    return _asset(HTML_REL)


def _image_uri(img) -> str:
    """base64 PNG for a QImage, lossless by construction.

    The dock's frosted glass is the only JPEG in this file; artwork handed to
    the page must never be, or its edges pick up compression noise."""
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(bytes(buf.data())).decode("ascii")


@lru_cache(maxsize=64)
def _fluent_svg(key: str) -> str:
    """One Microsoft Fluent filled icon (assets/icons/fluent/<key>.svg) as raw
    SVG markup, or "" if the file is missing.

    The fluent set is downloaded from @fluentui/svg-icons (MIT) with its fill
    normalized to ``fill="currentColor"`` so the dock's orb/tile markup is
    inlined into the page and recolored by CSS ``color`` -- a plain <img>
    cannot re-tint a currentColor icon. Keeping the raw file text allows the
    page to own the colour, matching the dock's violet family exactly."""
    p = _asset(f"assets/icons/fluent/{key}.svg")
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@lru_cache(maxsize=1)
def _brand_uri() -> str:
    """The brand mark for the dock's 44px Dashboard home button.

    The artwork is never re-encoded lossily and is used as supplied - only the
    frame around it is fixed:

    * Read from BRAND_REL, falling back to the older assets/logo.png.
    * Re-emitted at BRAND_PX (2x the source) so the browser downscales from
      real pixels at any devicePixelRatio instead of inventing them.
    * Composited onto BRAND_FIELD, so the result is fully opaque. The source
      carries an alpha channel, and the dock's glass behind the button is a
      blurred JPEG; that halo would otherwise let the JPEG's noise show through
      the edge of the ring as speckles. Opaque edges make that impossible.
    * Always a lossless PNG. This is never re-encoded as JPEG.
    """
    from PySide6.QtGui import QColor, QImage, QPainter

    img = QImage()
    for rel in (BRAND_REL, LOGO_REL):
        candidate = QImage(str(_asset(rel)))
        if not candidate.isNull():
            img = candidate
            break
    if img.isNull():
        return ""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    out = QImage(BRAND_PX, BRAND_PX, QImage.Format.Format_RGB32)
    out.fill(QColor(*BRAND_FIELD))
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.drawImage(out.rect(), img)
    p.end()
    return _image_uri(out)


# ONE icon set everywhere: Microsoft Fluent System Icons, filled weight
# (MIT, from @fluentui/svg-icons), bundled as raw inline SVG markup that uses
# `currentColor`, so the page recolors them with CSS to the dock's violet
# family. The same glyph can serve both a dock orb and a flyout tile (docked
# as keys "orb:<...>" to keep namespaces apart).

# Category orb key -> Fluent glyph file (assets/icons/fluent/<glyph>.svg).
_ORB_GLYPHS = {
    "fpsboost": "gauge",
    "monitor": "desktop",
    "input": "cursor",
    "tools": "wrench",
    "profiles": "contact_card",
    "settings": "settings",
}

# Flyout tile key -> Fluent glyph file. Every tile gets a matching glyph.
_TILE_GLYPHS = {
    "cpu": "developer_board",
    "gpu": "video_clip",
    "ram": "storage",
    "games": "games",
    "gauge": "rocket",            # FPS boost
    "system": "window_dev_tools",
    "storage": "hard_drive",
    "audio": "speaker_2",
    "network": "wifi_1",
    "hourglass": "data_trending",  # Network QoS
    "keyboard": "keyboard",
    "mouse": "cursor_hover",
    "input": "cursor_click",
    "delay_destroyer": "flash",
    "tools": "wrench",
    "controller": "xbox_controller",
    "app_optimizers": "apps",
    "debloat": "broom",
    "route_analyzer": "map",
    "activity": "pulse",           # Diagnostics
    "profiles": "xbox_controller",
    "fortnite": "options",
    "chat": "bot",
    "settings": "settings",
}


def _assets_json() -> str:
    """Build the JS object literal of ``key -> data URI / svg markup`` handed
    to the page.

    Everything is Fluent filled inline SVG under ``__svg`` -- dock orbs are
    keyed ``orb:fpsboost`` etc. so they never collide with same-named tiles
    (tools/profiles/settings), tiles use their plain key. The page recolors the
    inlined currentColor markup via CSS. The brand lockup is a real PNG
    data-URI under ``brand`` (drawn as an <img>, not tintable and not masked).
    """
    out = {"brand": _brand_uri()}
    svg_map: dict[str, str] = {}
    for orb_key, glyph in _ORB_GLYPHS.items():
        markup = _fluent_svg(glyph)
        if markup:
            svg_map["orb:" + orb_key] = markup
    for tile_key, glyph in _TILE_GLYPHS.items():
        markup = _fluent_svg(glyph)
        if markup:
            svg_map[tile_key] = markup
    svg_json = json.dumps(svg_map, separators=(",", ":"))
    return ("{" + ",".join(f'"{k}":"{v}"' for k, v in out.items() if v) +
            ",\"__svg\":" + svg_json + "}")


class _DockPage(QWebEnginePage):
    """Forwards the page's console output into the app log.

    The dock's open/close logic lives in the page, so its state transitions are
    only observable from inside the page. Mirroring console output into
    maxlog is what makes a real interaction reproducible after the fact.
    """

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        from maxlog import logger

        if str(message).startswith("DOCK"):
            logger.info(f"dock-page {message}  (line {line})")


class _DockBridge(QObject):
    """Registered as ``window.pywebview.api`` on the page's QWebChannel."""

    def __init__(self, nav, parent=None):
        super().__init__(parent)
        self._nav = nav

    @Slot(str)
    def navigate(self, key):
        self._nav.requested.emit(key)

    @Slot(bool)
    def panel(self, is_open):
        self._nav.set_panel_open(bool(is_open))


class DockNav(QWidget):
    """Floating bottom dock: a raised, fixed-size child of the window.

    It takes no part in the window layout, so no page is ever pushed down or
    given a background of its own; the only thing between the dock and the
    pages is the glass it draws. The widget is created at a fixed size and is
    never resized - see the module docstring for why.
    """

    requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._open = False
        self._ready = False
        self._mask_strip = -1
        self._stack = None
        self._bd_busy = False
        self._bd_timer = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._web = make_webview(self)
        self._web.setPage(_DockPage(self._web))
        self._web.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._web.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._web.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._web.page().setBackgroundColor(QColor(0, 0, 0, 0))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._web)

        settings = self._web.settings()
        settings.setAttribute(
            settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(
            settings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(settings.WebAttribute.JavascriptCanOpenWindows, False)

        self._bridge = _DockBridge(self, self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("api", self._bridge)
        self._web.page().setWebChannel(self._channel)

        self._web.loadFinished.connect(self._on_load_finished)

        # Fixed for the widget's whole life. Nothing below resizes it.
        self.setFixedSize(DOCK_W, DOCK_H)
        self._apply_mask()

        html = _html_path()
        if html.is_file():
            self._web.load(QUrl.fromLocalFile(str(html)))
        else:
            self._web.setHtml(
                "<body style='background:transparent;color:#9a93b8;"
                "font-family:sans-serif;padding:12px;'>"
                f"dock_nav.html not found at<br><code>{html}</code></body>")

        if parent is not None:
            parent.installEventFilter(self)

    # ---- click-through mask (this is what replaced all the resizing) ----

    def set_panel_open(self, is_open):
        """Grow or shrink the interactive area to match the panel's state.

        The page pushes this through the ``panel`` slot as its single source of
        truth, so the mask can never disagree with what is on screen. Nothing
        here resizes the widget, so the web content never has to catch up.
        """
        is_open = bool(is_open)
        if is_open == self._open:
            return
        self._open = is_open
        self._apply_mask()

    def _apply_mask(self):
        # While closed, only the bottom strip takes clicks so the page above the
        # dock stays reachable. While open, the whole widget is interactive.
        want = None if self._open else min(self.height(), CLOSED_MASK_H)
        if want == self._mask_strip:
            return
        self._mask_strip = want
        if want is None:
            self.clearMask()
        else:
            self.setMask(QRegion(0, self.height() - want, self.width(), want))

    # ---- placement: only ever move() ----

    def apply_geometry(self):
        """Pin the dock to the bottom centre of the window, over the pages.

        This deliberately does not resize. The main window's minimum height is
        700, which always leaves room for DOCK_H + BOTTOM_GAP, so there is no
        short-window case to clamp.
        """
        window = self.window()
        if window is None:
            return
        self.move((window.width() - DOCK_W) // 2,
                  window.height() - DOCK_H - BOTTOM_GAP)
        self._apply_mask()
        self.raise_()

    def top_edge(self):
        """Window y of the dock **bar's** top, so floating UI can stay clear.

        This is the bar, not the widget: the widget is always DOCK_H tall so the
        popover has somewhere to live even while it is closed and invisible.
        Returning the widget's top edge would push toasts ~230px up the screen.
        """
        return self.geometry().bottom() - DOCK_BAR_H + 1

    def eventFilter(self, obj, event):
        if obj is self.window() and event.type() == event.Type.Resize:
            self.apply_geometry()
            self.refresh_backdrop()
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        self.apply_geometry()

    # ---- shell-side controls ----

    def _run(self, js):
        if self._ready:
            self._web.page().runJavaScript(js)

    def _on_load_finished(self, ok):
            self._ready = bool(ok)
            if not ok:
                return
            # The dock stays invisible until the real icons and logo are in place,
            # so it never paints a frame of empty boxes.
            self._run(f"setAssets({_assets_json()})")
            # Paint the plan badge from the live entitlement, not a literal.
            self.refresh_tier()
            self.apply_geometry()

    def close_panel(self):
        self._run("closePanel()")

    # ---- real frosted glass ----

    def refresh_backdrop(self):
        """Feed the dock a blurred snapshot of the page behind it.

        CSS ``backdrop-filter`` cannot do this job here. The dock is a child
        widget with a transparent web view, and the pages are a *sibling* widget
        painted underneath it, so the page never appears in the dock's own
        rendering tree and there is no backdrop for the filter to sample -
        Chromium supports the property, it would simply have nothing to read.
        So the blur is produced on the Qt side: grab the part of the page stack
        the dock covers, shrink it, grow it back, and hand the result to the
        document as its background. Measured at ~7ms for the 560x340 region.

        Only the stack is grabbed, never the window, so the dock cannot end up
        photographing itself.
        """
        stack = self._stack
        if stack is None or not self._ready or not self.isVisible():
            return
        self._bd_busy = True
        try:
            region = QRect(stack.mapFromGlobal(self.geometry().topLeft()),
                           self.size())
            region = region.intersected(stack.rect())
            if region.width() < 8 or region.height() < 8:
                return
            shot = stack.grab(region)
            if shot.isNull():
                logger.warning(f"backdrop grab returned a null pixmap "
                               f"(region {region.width()}x{region.height()})")
                return
            small = shot.scaled(max(1, shot.width() // 8), max(1, shot.height() // 8),
                                Qt.AspectRatioMode.IgnoreAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            blurred = small.scaled(region.width(), region.height(),
                                   Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            blob = QByteArray()
            buf = QBuffer(blob)
            buf.open(QBuffer.OpenModeFlag.WriteOnly)
            # q88, not q72: this snapshot is the only thing behind the dock's
            # glass, and at the lower quality its noise showed as speckle
            # around the high-contrast edges (including the home button).
            ok = blurred.save(buf, "JPG", 88)
            buf.close()
            if not ok or blob.isEmpty():
                logger.warning(f"backdrop encode failed (ok={ok}, "
                               f"{blob.size()} bytes)")
                return
        except Exception as e:  # noqa: BLE001 - glass is decoration, never fatal
            logger.warning(f"backdrop refresh failed: {type(e).__name__}: {e}")
            return
        finally:
            self._bd_busy = False
        if not blob:
            return
        data = base64.b64encode(bytes(blob)).decode("ascii")
        # The image is exactly the widget's viewport, so the layer can simply
        # stretch to fill it and land pixel-aligned behind the bar and panel.
        self._run("setBackdrop('data:image/jpeg;base64," + data + "')")

    def set_stack(self, stack):
        """The page stack the glass samples. Set once by the main window."""
        self._stack = stack
        self._ensure_backdrop_timer()
        self.refresh_backdrop()

    def _ensure_backdrop_timer(self):
        """A slow safety net so the glass never sits on a stale snapshot.

        Pages with live content (the dashboard's charts keep moving) would
        otherwise show a frozen blur until the next navigation. Refreshes are
        coalesced, so a slow page update cannot pile up work.
        """
        if self._bd_timer is None:
            self._bd_timer = QTimer(self)
            self._bd_timer.setInterval(1000)
            self._bd_timer.timeout.connect(self._on_bd_tick)
            self._bd_timer.start()

    def _on_bd_tick(self):
        # One refresh in flight: a slow grab must not queue up behind the tick.
        if self._bd_busy:
            return
        self.refresh_backdrop()

    def sync(self, key):
        """Point the dock's active tile at ``key`` after navigation that did
        not come from the dock (a page button, a deep link, the home logo)."""
        self._run(f"sync({key!r})")

    def refresh_tier(self):
        """Re-paint the dock's plan badge from the live entitlement.

        Reads ``current_tier()`` - the canonical helper behind the locked cards
        and the tweaks header - rather than caching a value, so the dock cannot
        show a different plan than the rest of the app. Called on load and again
        on every ``ctx.license_changed``, which is what makes activation,
        expiry and revocation show up without a restart.
        """
        from config.app_config import APP_VERSION
        from config.plans import PLAN_LABEL
        from engine.entitlements import current_tier

        tier = current_tier()
        label = PLAN_LABEL.get(tier, "Free")
        self._run(f"setTier({tier!r}, {label!r}, {APP_VERSION!r})")
