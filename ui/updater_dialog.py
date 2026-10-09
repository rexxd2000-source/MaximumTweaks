"""Update UI — port of update_dialog_v2.html.

A frameless, modal update popup that renders the same chrome for every state
(checking / update available / downloading / installing / up to date / error):
a round brand-mark logo, the app name, a small purple state label and a close button
over a 440px (or 520px with the changelog) panel, dimmed by a blurred-looking
overlay.

It is a live port, not a mock: the version, download size, progress, speed and
changelog all come from ``engine.updater``.  The state list mirrors the mockup
exactly:

  * checking     — spinning ring, "Checking for updates…"
  * available     — version ring, "Tuned up and ready", version row, spec chips,
                    the changelog, and Remind me later / Skip this version /
                    Update now
  * downloading   — progress ring + bar + "x of y MB" + live speed + Cancel
  * installing    — spinning ring, indeterminate bar, then "Restarting …"
  * up_to_date    — green check ring, "You're up to date", Done
  * error         — red ring, the real message, Try again / Close

The modal hugs its content (height auto, capped at ``calc(100vh - 48px)``) and
animates between states: width 440<->520 and height over 280ms ease-out, the
new content fades + slides up over 240ms, and opening fades + scales the panel
over 250ms.  All motion is skipped under the OS reduced-motion setting.
"""
from __future__ import annotations

import os
import re
import time

from PySide6.QtCore import (
    Property as QtProperty,
    QByteArray,
    QEasingCurve,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    QPropertyAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtSvg import QSvgRenderer

from config.app_config import APP_NAME, APP_VERSION, ROOT, THEME as TH
from engine.state import LOGO_CACHE_FILE, STATE_DIR
from maxlog import logger

# Brand logo: the bundled ``assets/logo-64.png`` artwork (the same mark the dock
# and dashboard use).  Loaded from disk so the dialog never depends on the
# network for its identity.
_LOGO_REL = "assets/logo-64.png"
_LOGO_CACHE = LOGO_CACHE_FILE

# Checkmark: a proper vector icon (Lucide's ``check``, ISC) fetched from the
# jsDelivr CDN, cached on disk, and rendered through QtSvg.  The exact same
# markup is embedded as an offline fallback so the tick always renders.
_CHECK_SVG_URL = "https://cdn.jsdelivr.net/npm/lucide-static/icons/check.svg"
_CHECK_CACHE = os.path.join(STATE_DIR, "check_icon.svg")
_CHECK_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
    b'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    b'stroke-linecap="round" stroke-linejoin="round">'
    b'<path d="M20 6 9 17l-5-5"/></svg>'
)

# ---------------------------------------------------------------------------
# Palette — the reference's roles mapped onto the app's live THEME tokens.
# ---------------------------------------------------------------------------
C = {
    "top": "#171230",          # dialog top (lighter violet)
    "surface": TH["card"],     # #0C0A16
    "surface2": TH["card_alt"],   # #12101F
    "surface3": TH["card_hover"],  # #171428
    "log": "#0D0A18",
    "line": TH["border"],      # #1D1B28
    "line_soft": TH["border_soft"],
    "edge": "#3A2F63",         # dialog border (violet)
    "track": "#2A2248",        # ring track
    "tx": TH["text"],          # #F6F4FC
    "mut": TH["text_dim"],     # #928AAD
    "faint": TH["text_faint"],
    "pri": TH["accent"],       # #8B6BFF
    "pri2": TH["accent2"],     # #C9C0FF
    "pri_deep": "#7C4DFF",
    "ok": TH["success"],       # #3DDC97
    "err": TH["red"],          # #FF6F6F
}

SANS = "Segoe UI"
MONO = "JetBrains Mono"

_TITLES = {
    "checking": "CHECKING FOR UPDATES",
    "up_to_date": "UP TO DATE",
    "available": "UPDATE AVAILABLE",
    "downloading": "DOWNLOADING",
    "installing": "INSTALLING",
    "error": "UPDATE FAILED",
}

# Width per state: roomy (520) when the changelog / progress bar is on screen,
# compact (440) for checking / up-to-date / installing / error.
_STATE_WIDTH = {
    "available": 520, "downloading": 520,
    "checking": 440, "up_to_date": 440, "installing": 440, "error": 440,
}
_HEAD_H = 60
_BODY_MARGINS = (18, 20, 18, 18)
_LOG_MIN = 96
_LOG_MAX = 190
_RING = 68.0
_RING_R = 28.0
_RING_C = 2.0 * 3.141592653589793 * _RING_R  # ~175.93 (matches the mock's 176)


def _sans(pixel: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(SANS, 1)
    f.setPixelSize(pixel)
    f.setWeight(weight)
    return f


def _mono(pixel: int, weight: QFont.Weight = QFont.Weight.Medium) -> QFont:
    f = QFont(MONO, 1)
    f.setPixelSize(pixel)
    f.setWeight(weight)
    return f


# -- reduced motion -----------------------------------------------------
_REDUCED_MOTION_CACHE: bool | None = None


def _prefers_reduced_motion() -> bool:
    """Honour the OS "animate controls" setting (the Windows equivalent of the
    web ``prefers-reduced-motion`` media query). MT_REDUCED_MOTION=1 forces it
    on for testing."""
    global _REDUCED_MOTION_CACHE
    if _REDUCED_MOTION_CACHE is not None:
        return _REDUCED_MOTION_CACHE
    env = (os.environ.get("MT_REDUCED_MOTION")
           or os.environ.get("REDUCED_MOTION"))
    if env is not None:
        _REDUCED_MOTION_CACHE = env.strip().lower() not in ("0", "", "false", "no")
        return _REDUCED_MOTION_CACHE
    reduced = False
    try:
        import ctypes
        enabled = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(enabled), 0)
        if ok and enabled.value == 0:
            reduced = True
    except Exception:  # noqa: BLE001 - non-Windows / restricted => play safe
        reduced = False
    _REDUCED_MOTION_CACHE = reduced
    return reduced


def _no_select(w: QWidget) -> QWidget:
    try:
        if isinstance(w, QLabel):
            w.setTextInteractionFlags(Qt.NoTextInteraction)
    except Exception:  # noqa: BLE001
        pass
    try:
        w.setFocusPolicy(Qt.NoFocus)
    except Exception:  # noqa: BLE001
        pass
    return w


# -- bundled assets + SVG icons -----------------------------------------
def _asset_path(rel: str) -> str:
    """Resolve a repo-relative asset in dev and frozen (``_MEIPASS``) builds."""
    import sys
    base = getattr(sys, "_MEIPASS", None)
    root = base if base else str(ROOT)
    return os.path.join(root, *rel.replace("\\", "/").split("/"))


_SVG_PIX_CACHE: dict = {}


def _svg_pixmap(svg, size: int, color: str | None = None) -> QPixmap:
    """Rasterise SVG bytes at ``size`` logical px (HiDPI-crisp), optionally
    recolouring any ``currentColor`` stroke/fill."""
    if isinstance(svg, str):
        svg = svg.encode("utf-8")
    key = (hash(bytes(svg)), int(size), color)
    hit = _SVG_PIX_CACHE.get(key)
    if hit is not None and not hit.isNull():
        return hit
    data = bytes(svg)
    if color:
        data = data.replace(b"currentColor", color.encode("ascii"))
    renderer = QSvgRenderer(QByteArray(data))
    dpr = 1.0
    try:
        app = QApplication.instance()
        if app is not None:
            dpr = float(app.devicePixelRatio() or 1.0)
    except Exception:  # noqa: BLE001
        dpr = 1.0
    pm = QPixmap(int(round(size * dpr)), int(round(size * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(p)
    p.end()
    _SVG_PIX_CACHE[key] = pm
    return pm


def _check_svg_bytes() -> bytes:
    """The fetched check SVG (cached) or the embedded Lucide fallback."""
    try:
        if os.path.isfile(_CHECK_CACHE):
            with open(_CHECK_CACHE, "rb") as f:
                data = f.read()
            if b"<svg" in data:
                return data
    except OSError:
        pass
    return _CHECK_SVG


def _check_pixmap(size: int, color: str) -> QPixmap:
    return _svg_pixmap(_check_svg_bytes(), size, color)


def _draw_pm_center(p: QPainter, pm: QPixmap, cx: float, cy: float) -> None:
    if pm is None or pm.isNull():
        return
    dpr = pm.devicePixelRatio() or 1.0
    w = pm.width() / dpr
    h = pm.height() / dpr
    p.drawPixmap(
        QRectF(cx - w / 2.0, cy - h / 2.0, w, h), pm,
        QRectF(0.0, 0.0, pm.width(), pm.height()))


# ---------------------------------------------------------------------------
# Ring — 68px progress / spinner ring with a violet (or green / red) arc.
# ---------------------------------------------------------------------------
class _Ring(QWidget):
    """Progress ring.  ``set_progress(0..1)`` fills the arc; ``start_spin()``
    turns it into an indeterminate spinner; ``set_tone('ok', check=True)`` draws
    the full green ring with a checkmark, ``'err'`` a red ring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(int(_RING), int(_RING))
        self._offset = _RING_C        # fully empty
        self._tone = "pri"            # pri | ok | err
        self._check = False
        self._check_pm = None
        self._spin = False
        self._angle = 0.0
        self._spin_anim = None
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._label.setGeometry(0, 0, int(_RING), int(_RING))
        self._label.setFont(_mono(15, QFont.Weight.DemiBold))
        self._label.setStyleSheet(f"color:{C['tx']}; background:transparent;")

    # -- api
    def set_text(self, text: str):
        self._label.setText(text or "")

    def set_tone(self, tone: str, check: bool = False):
        self._tone = tone
        self._check = check
        if check:
            # The tick is a real vector icon drawn in paintEvent; never a text
            # glyph, so it can't collide with a second stroke.
            self._label.setText("")
        elif tone == "err":
            self._label.setFont(_sans(22, QFont.Weight.Bold))
            self._label.setStyleSheet(f"color:{C['err']}; background:transparent;")
        else:
            self._label.setFont(_mono(15, QFont.Weight.DemiBold))
            self._label.setStyleSheet(f"color:{C['tx']}; background:transparent;")
        self.update()

    def set_check_pixmap(self, pm) -> None:
        self._check_pm = pm if (pm and not pm.isNull()) else None
        self.update()

    def set_progress(self, frac: float):
        frac = max(0.0, min(1.0, float(frac)))
        self._offset = _RING_C * (1.0 - frac)
        self.update()

    def set_offset(self, offset: float):
        """Direct stroke-dashoffset control (the mock's 22 / 120 values)."""
        self._offset = max(0.0, min(_RING_C, float(offset)))
        self.update()

    def start_spin(self):
        if self._spin:
            return
        self._spin = True
        self._check = False
        self._label.setText("")
        anim = QPropertyAnimation(self, b"angle", self)
        anim.setDuration(1000)
        anim.setStartValue(0.0)
        anim.setEndValue(360.0)
        anim.setLoopCount(-1)
        anim.setEasingCurve(QEasingCurve.Linear)
        self._spin_anim = anim
        if not _prefers_reduced_motion():
            anim.start()

    def stop_spin(self):
        if self._spin_anim is not None:
            self._spin_anim.stop()
            self._spin_anim = None
        self._spin = False

    def _get_angle(self) -> float:
        return self._angle

    def _set_angle(self, v: float):
        self._angle = float(v)
        self.update()

    angle = QtProperty(float, fget=_get_angle, fset=_set_angle)

    # -- paint
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(6, 6, _RING_R * 2, _RING_R * 2)
        # track
        pen = QPen(QColor(C["track"]), 5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 0, 360 * 16)

        if self._tone == "ok":
            arc_color, glow = QColor(C["ok"]), QColor(61, 220, 151, 70)
            span = 360 * 16
        elif self._tone == "err":
            arc_color, glow = QColor(C["err"]), QColor(255, 111, 111, 70)
            span = int((_RING_C - self._offset) / _RING_C * 360 * 16)
        else:
            arc_color, glow = None, QColor(139, 107, 255, 70)
            span = int((_RING_C - self._offset) / _RING_C * 360 * 16)

        if self._spin:
            span = int(0.32 * 360 * 16)

        if span <= 0:
            p.end()
            return

        p.save()
        if self._spin:
            p.translate(_RING / 2, _RING / 2)
            p.rotate(self._angle)
            p.translate(-_RING / 2, -_RING / 2)

        # soft outer glow behind the arc
        gpen = QPen(glow, 10)
        gpen.setCapStyle(Qt.RoundCap)
        p.setPen(gpen)
        p.drawArc(rect, 90 * 16, -span)

        if arc_color is not None:
            fpen = QPen(arc_color, 5)
        else:
            grad = QLinearGradient(0, 0, _RING, _RING)
            grad.setColorAt(0.0, QColor(C["pri2"]))
            grad.setColorAt(1.0, QColor(C["pri_deep"]))
            fpen = QPen(grad, 5)
        fpen.setCapStyle(Qt.RoundCap)
        p.setPen(fpen)
        p.drawArc(rect, 90 * 16, -span)

        p.restore()

        if self._check:
            pm = self._check_pm
            if pm is None:
                pm = _check_pixmap(int(_RING * 0.46), C["ok"])
            _draw_pm_center(p, pm, _RING / 2.0, _RING / 2.0)
        p.end()


# ---------------------------------------------------------------------------
# Progress bar (determinate + indeterminate sweep)
# ---------------------------------------------------------------------------
class _Bar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._frac = 0.0
        self._ind = False
        self._sweep = 0.0
        self._anim = None
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_frac(self, frac: float):
        self._frac = max(0.0, min(1.0, float(frac)))
        self.update()

    def start_indeterminate(self):
        if self._ind:
            return
        self._ind = True
        anim = QPropertyAnimation(self, b"sweep", self)
        anim.setDuration(1300)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setLoopCount(-1)
        anim.setEasingCurve(QEasingCurve.InOutSine)
        self._anim = anim
        if not _prefers_reduced_motion():
            anim.start()
        else:
            self._sweep = 0.5
            self.update()

    def stop_indeterminate(self):
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._ind = False
        self.update()

    def _get_sweep(self) -> float:
        return self._sweep

    def _set_sweep(self, v: float):
        self._sweep = float(v)
        self.update()

    sweep = QtProperty(float, fget=_get_sweep, fset=_set_sweep)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["surface2"]))
        p.drawRoundedRect(r, 4, 4)
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0.0, QColor(C["pri_deep"]))
        grad.setColorAt(1.0, QColor(C["pri2"]))
        if self._ind:
            w = self.width() * 0.35
            x = -w + self._sweep * (self.width() + w)
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(x, 0, w, self.height()), 4, 4)
        elif self._frac > 0:
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(0, 0, self.width() * self._frac,
                                     self.height()), 4, 4)
        p.end()


# ---------------------------------------------------------------------------
# Logo — 30px circular badge: purple radial gradient with the bundled brand
# mark (assets/logo-64.png) clipped to the circle, plus a soft violet glow.
# ---------------------------------------------------------------------------
class _Logo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(30, 30)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._pm = None
        glow = QGraphicsDropShadowEffect(self)
        glow.setBlurRadius(14)
        glow.setOffset(0, 0)
        glow.setColor(QColor(0x8B, 0x5C, 0xF6, 0x66))
        self.setGraphicsEffect(glow)

    def set_pixmap(self, pm) -> None:
        self._pm = pm if (pm and not pm.isNull()) else None
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        grad = QRadialGradient(r.left() + r.width() * 0.32,
                               r.top() + r.height() * 0.28,
                               r.width() * 0.95)
        grad.setColorAt(0.0, QColor(C["pri"]))
        grad.setColorAt(1.0, QColor("#2A1458"))
        path = QPainterPath()
        path.addEllipse(r)
        p.fillPath(path, grad)
        if self._pm is not None:
            clip = QPainterPath()
            clip.addEllipse(r)
            p.setClipPath(clip)
            scaled = self._pm.scaled(self.width(), self.height(),
                                     Qt.KeepAspectRatioByExpanding,
                                     Qt.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        else:
            p.setPen(QColor("#E9DDFF"))
            p.setFont(_sans(13, QFont.Weight.Bold))
            p.drawText(self.rect(), Qt.AlignCenter, "M")
        p.end()


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------
class FetchWorker(QThread):
    """Check for an update in the background."""

    done = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._err = ""

    def run(self):
        from engine import updater
        import traceback
        try:
            result = updater.fetch_update()
        except updater.UpdaterError as exc:
            self._err = str(exc)
            logger.info(f"updater: check failed: {exc}")
            result = None
        except Exception:  # noqa: BLE001
            logger.error("updater: unexpected check error:\n"
                         f"{traceback.format_exc()}")
            self._err = ("Update check failed unexpectedly. "
                         "Please try again, or run the latest build manually.")
            result = None
        if result is None and self._err:
            if any(
                s in self._err.lower() for s in
                ("http", "network", "timeout", "connection", "internet",
                 "offline", "rate-limit", "refused", "dns", "tls")
            ):
                self._err += ("\n\nThis looks like a connectivity issue, not a "
                              "VPN or firewall toggling in the app. Check that "
                              "the device has internet access, wait a few "
                              "minutes, then Retry. If it keeps failing, "
                              "download the latest build manually and run it.")
        self.done.emit({"info": result, "error": self._err})


class DownloadWorker(QThread):
    """Download the staged update; reports byte progress and 0..1 fraction."""

    bytes = Signal(int, int)     # got bytes, total bytes
    progress = Signal(float)
    done = Signal(object, str)   # new_exe path or None, error message

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._err = ""
        self._dest = None
        self._cancel = False
        self._checksum_url = ""
        self._sha256 = ""
        self._filename = ""

    def cancel(self):
        self._cancel = True

    def _progress(self, got, total):
        self.bytes.emit(int(got), int(total))
        if total > 0:
            self.progress.emit(min(1.0, got / total))

    def run(self):
        from engine import updater
        try:
            self._dest = updater.download(
                self._url, progress_cb=self._progress,
                checksum_url=self._checksum_url,
                expected_sha256=self._sha256,
                filename=self._filename,
                cancel_cb=lambda: self._cancel)
        except updater.DownloadCancelled:
            self.done.emit(None, "")
            return
        except updater.UpdaterError as exc:
            self._err = str(exc)
        except Exception as exc:  # noqa: BLE001
            self._err = str(exc)
            logger.warn(f"updater: download error: {exc}")
        self.done.emit(self._dest, self._err)


class SizeWorker(QThread):
    """Best-effort HEAD probe for the download size when the manifest omits it."""

    done = Signal(int)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url

    def run(self):
        from engine import updater
        try:
            size = updater.probe_size(self._url)
        except Exception:  # noqa: BLE001
            size = 0
        self.done.emit(int(size))


class LogoWorker(QThread):
    """Fetch the check mark SVG into the state cache dir.

    Kept under its historical name so existing imports keep working; it now
    services the vector tick used by the ring and the Done button rather than
    the (bundled) brand logo."""

    done = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""

    def run(self):
        import urllib.request
        import urllib.error
        try:
            req = urllib.request.Request(
                _CHECK_SVG_URL,
                headers={"User-Agent": "MaximumTweaks-updater/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            if data and b"<svg" in data:
                os.makedirs(os.path.dirname(_CHECK_CACHE) or ".", exist_ok=True)
                with open(_CHECK_CACHE, "wb") as f:
                    f.write(data)
                self._path = _CHECK_CACHE
        except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
            logger.warn(f"updater: check icon fetch failed: {exc}")
        self.done.emit(self._path)


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------
_QSS = f"""
#Head {{
    background: transparent; border: none;
    border-bottom: 1px solid {C['line']};
}}
#AppName {{ color: {C['tx']}; background: transparent; border: none; }}
#StateLbl {{ color: {C['pri2']}; background: transparent; border: none; }}
#XBtn {{
    background: transparent; border: none; border-radius: 9px;
    color: {C['mut']};
}}
#XBtn:hover {{ background: rgba(255,255,255,0.08); color: {C['tx']}; }}
#XBtn:disabled {{ color: {C['faint']}; }}
#Page, #LogHost, #LogRow {{ background: transparent; border: none; }}
#H1 {{ color: {C['tx']}; background: transparent; border: none; }}
#Sub {{ color: {C['mut']}; background: transparent; border: none; }}
#OkText {{ color: {C['ok']}; background: transparent; border: none; }}
#Foot {{ color: {C['ok']}; background: transparent; border: none; }}
#Note {{ color: {C['mut']}; background: transparent; border: none; }}
#Lab {{ color: {C['mut']}; background: transparent; border: none; }}
#Bullet {{ color: {C['pri2']}; background: transparent; border: none; }}
#LogText {{ color: {C['tx']}; background: transparent; border: none; }}
#LogNone {{ color: {C['mut']}; background: transparent; border: none; }}
#Chip {{
    background: #171325; border: 1px solid #2a2340;
    border-radius: 10px; color: {C['mut']};
    padding: 6px 10px;
}}
#BtnGhost {{
    background: transparent; border: none; color: {C['mut']};
}}
#BtnGhost:hover {{ color: {C['tx']}; }}
#Btn {{
    background: {C['surface2']}; border: 1px solid {C['line']};
    border-radius: 11px; color: {C['tx']};
}}
#Btn:hover {{ border-color: {C['pri2']}; background: {C['surface3']}; }}
#BtnPrimary {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {C['pri2']}, stop:1 {C['pri_deep']});
    border: 1px solid {C['pri2']}; border-radius: 11px; color: #ffffff;
}}
#BtnPrimary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #b9a8ff, stop:1 #8a5bff);
}}
#BtnPrimary:disabled {{
    background: {C['surface2']}; color: {C['faint']}; border-color: {C['line']};
}}
#BodyScroll {{ background: transparent; border: none; }}
#BodyScroll > QWidget > QWidget {{ background: transparent; }}
#LogBox {{
    background: {C['log']}; border: 1px solid {C['line']};
    border-radius: 12px;
}}
#LogBox > QWidget > QWidget {{ background: transparent; }}
#Flash {{
    background: {C['surface3']}; border: 1px solid {C['pri']};
    border-radius: 12px; color: {C['tx']};
}}
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: #3A2D66; border-radius: 3px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: #4A3B80; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0; background: transparent;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""


# ---------------------------------------------------------------------------
# Modal panel — paints the gradient body, violet border, soft shadow + top glow.
# ---------------------------------------------------------------------------
class _Modal(QFrame):
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        grad = QLinearGradient(0, 0, 0, max(140.0, self.height()))
        grad.setColorAt(0.0, QColor(C["top"]))
        grad.setColorAt(1.0, QColor(C["surface"]))
        p.setPen(QPen(QColor(C["edge"]), 1))
        p.setBrush(grad)
        p.drawRoundedRect(r, 20, 20)

        # thin glowing gradient line along the top edge
        line = QLinearGradient(0, 0, self.width(), 0)
        line.setColorAt(0.0, QColor(201, 192, 255, 0))
        line.setColorAt(0.5, QColor(C["pri2"]))
        line.setColorAt(1.0, QColor(201, 192, 255, 0))
        pen = QPen(line, 2)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.drawLine(QPointF(16, 1.5), QPointF(self.width() - 16, 1.5))
        p.end()


class UpdateDialog(QDialog):
    """Check for updates, download with progress, install + restart."""

    def __init__(self, parent=None, check_on_open: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Update Available")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet(_QSS)

        self._host = parent.window() if parent is not None else None
        self._info = None
        self._new_exe = None
        self._mode = None
        self._retry = "check"
        self._worker = None
        self._size_worker = None
        self._logo_worker = None
        self._bytes_got = 0
        self._bytes_total = 0
        self._known_size = 0
        self._dl_start = 0.0
        self._last_t = 0.0
        self._last_bytes = 0
        self._speed = 0.0
        self._geom_anim = None
        self._fade_anim = None
        self._open_anim = None
        self._opacity = 1.0
        self._slide = 0
        self._slide_page = None

        self._modal = _Modal(self)
        shadow = QGraphicsDropShadowEffect(self._modal)
        shadow.setBlurRadius(60)
        shadow.setOffset(0, 18)
        shadow.setColor(QColor(124, 77, 255, 90))
        self._modal.setGraphicsEffect(shadow)

        m = QVBoxLayout(self._modal)
        m.setContentsMargins(0, 0, 0, 0)
        m.setSpacing(0)

        # ---------- header ----------
        head = QFrame()
        head.setObjectName("Head")
        head.setFixedHeight(_HEAD_H)
        h = QHBoxLayout(head)
        h.setContentsMargins(18, 0, 14, 0)
        h.setSpacing(11)

        self._logo = _Logo()
        h.addWidget(self._logo)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        name = QLabel("Maximum Tweaks")
        name.setObjectName("AppName")
        name.setFont(_sans(14, QFont.Weight.DemiBold))
        name.setFixedHeight(round(14 * 1.2))          # line-height: 1.2
        name.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._state_lbl = QLabel(_TITLES["checking"])
        self._state_lbl.setObjectName("StateLbl")
        sf = _sans(11, QFont.Weight.DemiBold)
        sf.setLetterSpacing(QFont.AbsoluteSpacing, 1.4)
        self._state_lbl.setFont(sf)
        self._state_lbl.setFixedHeight(round(11 * 1.2))   # line-height: 1.2
        self._state_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # Stretches above and below keep the title + state label together in
        # the vertical centre. Without them Qt splits the header's spare height
        # evenly between the two labels, opening a ~15px gap between them.
        titles.addStretch(1)
        titles.addWidget(name)
        titles.addWidget(self._state_lbl)
        titles.addStretch(1)
        h.addLayout(titles, 1)

        self._x = QToolButton()
        self._x.setObjectName("XBtn")
        self._x.setFixedSize(30, 30)
        self._x.setText("\u2715")
        self._x.setFont(_sans(14))
        self._x.setCursor(Qt.PointingHandCursor)
        self._x.clicked.connect(self.reject)
        h.addWidget(self._x, 0, Qt.AlignVCenter)

        m.addWidget(head)

        # ---------- body (header pinned, body scrolls) ----------
        self._body_scroll = QScrollArea()
        self._body_scroll.setObjectName("BodyScroll")
        self._body_scroll.setWidgetResizable(True)
        self._body_scroll.setFrameShape(QFrame.NoFrame)
        self._body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._body_scroll.setMinimumHeight(0)
        self._body = QWidget()
        self._body.setObjectName("BodyHost")
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(*_BODY_MARGINS)
        self._body_lay.setSpacing(0)
        self._body_scroll.setWidget(self._body)
        m.addWidget(self._body_scroll)

        self._pages = {}
        self._build_pages()

        self._noselect_all()
        self._load_logo()
        self._load_check_icon()
        if check_on_open:
            self._check()

    # ------------------------------------------------------------------
    # page builders
    # ------------------------------------------------------------------
    def _new_page(self) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        w.setObjectName("Page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._body_lay.addWidget(w)
        return w, lay

    @staticmethod
    def _row() -> tuple[QWidget, QHBoxLayout]:
        row = QWidget()
        row.setObjectName("Page")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        return row, lay

    @staticmethod
    def _vtext(head: QLabel, sub: QLabel) -> QWidget:
        box = QWidget()
        box.setObjectName("Page")
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        v.addWidget(head)
        v.addWidget(sub)
        v.addStretch(1)
        return box

    def _mk_chip(self) -> QLabel:
        lbl = QLabel("")
        lbl.setObjectName("Chip")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFont(_sans(12))
        lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return lbl

    def _btn(self, text: str, primary: bool = False, ghost: bool = False) -> QToolButton:
        b = QToolButton()
        b.setObjectName("BtnPrimary" if primary else ("BtnGhost" if ghost else "Btn"))
        b.setText(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedHeight(38)
        if ghost:
            b.setFont(_sans(12))
            b.setStyleSheet(f"#BtnGhost {{ padding: 0 4px; }}")
        else:
            b.setFont(_sans(12, QFont.Weight.DemiBold))
            b.setStyleSheet(
                f"#{b.objectName()} {{ padding: 0 16px; }}")
        return b

    def _bullet_row(self, text: str) -> QWidget:
        row = QWidget()
        row.setObjectName("LogRow")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        b = QLabel("\u2022")
        b.setObjectName("Bullet")
        b.setFixedWidth(10)
        b.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        b.setFont(_sans(13))
        t = QLabel(text)
        t.setObjectName("LogText")
        t.setWordWrap(True)
        t.setFont(_sans(13))
        t.setMinimumWidth(0)
        t.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        rl.addWidget(b, 0, Qt.AlignTop)
        rl.addWidget(t, 1)
        return row

    def _build_pages(self):
        # ---- checking ----
        w, lay = self._new_page()
        row, r = self._row()
        self._ring_check = _Ring()
        r.addWidget(self._ring_check, 0, Qt.AlignVCenter)
        h1 = QLabel("Checking for updates\u2026")
        h1.setObjectName("H1")
        h1.setFont(_sans(16, QFont.Weight.DemiBold))
        sub = QLabel("This only takes a moment.")
        sub.setObjectName("Sub")
        sub.setFont(_sans(13))
        r.addWidget(self._vtext(h1, sub), 1)
        lay.addWidget(row)
        lay.addStretch(1)
        self._pages["checking"] = w

        # ---- up to date ----
        w, lay = self._new_page()
        row, r = self._row()
        self._ring_ok = _Ring()
        r.addWidget(self._ring_ok, 0, Qt.AlignVCenter)
        h1 = QLabel("You\u2019re up to date")
        h1.setObjectName("H1")
        h1.setFont(_sans(16, QFont.Weight.DemiBold))
        self._ok_sub = QLabel("")
        self._ok_sub.setObjectName("OkText")
        self._ok_sub.setFont(_sans(13))
        r.addWidget(self._vtext(h1, self._ok_sub), 1)
        lay.addWidget(row)
        lay.addSpacing(20)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        btns.addStretch(1)
        self._btn_done = self._btn("Done", primary=True)
        # A real vector tick (the same internet SVG as the ring), never the
        # "✓" text glyph.
        self._btn_done.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._btn_done.setIcon(QIcon(_check_pixmap(14, "#FFFFFF")))
        self._btn_done.setIconSize(QSize(14, 14))
        self._btn_done.clicked.connect(self.accept)
        btns.addWidget(self._btn_done)
        lay.addLayout(btns)
        lay.addStretch(1)
        self._pages["up_to_date"] = w

        # ---- update available ----
        w, lay = self._new_page()
        row, r = self._row()
        self._ring_up = _Ring()
        r.addWidget(self._ring_up, 0, Qt.AlignVCenter)
        h1 = QLabel("Tuned up and ready")
        h1.setObjectName("H1")
        h1.setFont(_sans(16, QFont.Weight.DemiBold))
        self._up_sub = QLabel("")
        self._up_sub.setObjectName("Sub")
        self._up_sub.setFont(_sans(13))
        r.addWidget(self._vtext(h1, self._up_sub), 1)
        lay.addWidget(row)
        lay.addSpacing(18)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self._chip_dl = self._mk_chip()
        self._chip_install = self._mk_chip()
        self._chip_date = self._mk_chip()
        self._chip_install.setText("<b>~2 min</b> install")
        chips.addWidget(self._chip_dl, 1)
        chips.addWidget(self._chip_install, 1)
        chips.addWidget(self._chip_date, 1)
        lay.addLayout(chips)
        lay.addSpacing(18)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        self._btn_remind = self._btn("Remind me later", ghost=True)
        self._btn_remind.clicked.connect(self._remind)
        btns.addWidget(self._btn_remind)
        btns.addStretch(1)
        self._btn_skip = self._btn("Skip this version")
        self._btn_skip.clicked.connect(self._skip)
        btns.addWidget(self._btn_skip)
        self._btn_update = self._btn("\u2b07  Update now", primary=True)
        self._btn_update.clicked.connect(self._on_update_clicked)
        btns.addWidget(self._btn_update)
        lay.addLayout(btns)
        lay.addSpacing(20)
        lab = QLabel("What\u2019s changed")
        lab.setObjectName("Lab")
        lf = _sans(11, QFont.Weight.DemiBold)
        lf.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        lab.setFont(lf)
        lay.addWidget(lab)
        lay.addSpacing(8)
        self._log_scroll = QScrollArea()
        self._log_scroll.setObjectName("LogBox")
        self._log_scroll.setWidgetResizable(True)
        self._log_scroll.setFrameShape(QFrame.NoFrame)
        self._log_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._log_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._log_scroll.setMinimumHeight(_LOG_MIN)
        self._log_scroll.setMaximumHeight(_LOG_MAX)
        self._log_host = QWidget()
        self._log_host.setObjectName("LogHost")
        self._log_lay = QVBoxLayout(self._log_host)
        self._log_lay.setContentsMargins(14, 12, 14, 12)
        self._log_lay.setSpacing(6)
        self._log_scroll.setWidget(self._log_host)
        lay.addWidget(self._log_scroll)
        lay.addSpacing(16)
        foot = QLabel("A newer build is ready \u2014 hit Update now")
        foot.setObjectName("Foot")
        foot.setFont(_sans(13))
        lay.addWidget(foot)
        lay.addSpacing(8)
        note = QLabel("Maximum Tweaks will restart automatically")
        note.setObjectName("Note")
        note.setAlignment(Qt.AlignCenter)
        note.setFont(_sans(12))
        lay.addWidget(note)
        lay.addStretch(1)
        self._pages["available"] = w

        # ---- downloading ----
        w, lay = self._new_page()
        row, r = self._row()
        self._ring_dl = _Ring()
        r.addWidget(self._ring_dl, 0, Qt.AlignVCenter)
        h1 = QLabel("Downloading update\u2026")
        h1.setObjectName("H1")
        h1.setFont(_sans(16, QFont.Weight.DemiBold))
        self._dl_sub = QLabel("")
        self._dl_sub.setObjectName("Sub")
        self._dl_sub.setFont(_sans(13))
        r.addWidget(self._vtext(h1, self._dl_sub), 1)
        lay.addWidget(row)
        lay.addSpacing(18)
        self._bar_dl = _Bar()
        lay.addWidget(self._bar_dl)
        lay.addSpacing(6)
        stat = QHBoxLayout()
        self._dl_progress = QLabel("0 of 0 MB")
        self._dl_progress.setObjectName("Sub")
        self._dl_progress.setFont(_sans(12))
        self._dl_speed = QLabel("")
        self._dl_speed.setObjectName("Sub")
        self._dl_speed.setFont(_sans(12))
        stat.addWidget(self._dl_progress)
        stat.addStretch(1)
        stat.addWidget(self._dl_speed)
        lay.addLayout(stat)
        lay.addSpacing(18)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self._btn_cancel = self._btn("Cancel")
        self._btn_cancel.clicked.connect(self._cancel_download)
        btns.addWidget(self._btn_cancel)
        lay.addLayout(btns)
        lay.addStretch(1)
        self._pages["downloading"] = w

        # ---- installing ----
        w, lay = self._new_page()
        row, r = self._row()
        self._ring_install = _Ring()
        r.addWidget(self._ring_install, 0, Qt.AlignVCenter)
        self._install_h1 = QLabel("Installing update\u2026")
        self._install_h1.setObjectName("H1")
        self._install_h1.setFont(_sans(16, QFont.Weight.DemiBold))
        sub = QLabel("Please don\u2019t close the app.")
        sub.setObjectName("Sub")
        sub.setFont(_sans(13))
        r.addWidget(self._vtext(self._install_h1, sub), 1)
        lay.addWidget(row)
        lay.addSpacing(18)
        self._bar_install = _Bar()
        lay.addWidget(self._bar_install)
        lay.addSpacing(10)
        note = QLabel("Maximum Tweaks will restart automatically")
        note.setObjectName("Note")
        note.setAlignment(Qt.AlignCenter)
        note.setFont(_sans(12))
        lay.addWidget(note)
        lay.addStretch(1)
        self._pages["installing"] = w

        # ---- error ----
        w, lay = self._new_page()
        row, r = self._row()
        self._ring_err = _Ring()
        r.addWidget(self._ring_err, 0, Qt.AlignVCenter)
        self._err_h1 = QLabel("Update failed")
        self._err_h1.setObjectName("H1")
        self._err_h1.setFont(_sans(16, QFont.Weight.DemiBold))
        self._err_sub = QLabel("")
        self._err_sub.setObjectName("Sub")
        self._err_sub.setFont(_sans(13))
        self._err_sub.setWordWrap(True)
        r.addWidget(self._vtext(self._err_h1, self._err_sub), 1)
        lay.addWidget(row)
        lay.addSpacing(20)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        btns.addStretch(1)
        self._btn_retry = self._btn("Try again", primary=True)
        self._btn_retry.clicked.connect(self._retry_action)
        btns.addWidget(self._btn_retry)
        self._btn_close = self._btn("Close")
        self._btn_close.clicked.connect(self.reject)
        btns.addWidget(self._btn_close)
        lay.addLayout(btns)
        lay.addStretch(1)
        self._pages["error"] = w

        for name, page in self._pages.items():
            page.setVisible(name == "checking")
        self._mode = "checking"

    # ------------------------------------------------------------------
    # brand logo (bundled) + vector check mark (fetched, cached)
    # ------------------------------------------------------------------
    def _load_logo(self):
        """Show the bundled ``assets/logo-64.png`` brand mark."""
        pm = QPixmap(_asset_path(_LOGO_REL))
        if pm.isNull():
            pm = QPixmap(_LOGO_CACHE)
        self._apply_logo_pixmap(pm)

    def _apply_logo_pixmap(self, pm):
        if pm is None or pm.isNull():
            return
        self._logo.set_pixmap(pm)

    def _load_check_icon(self):
        """Refresh the check mark SVG from the internet (cached on disk)."""
        self._logo_worker = LogoWorker(self)
        self._logo_worker.done.connect(self._on_check_icon_done)
        self._logo_worker.finished.connect(self._logo_gc)
        self._logo_worker.start()

    def _on_check_icon_done(self, path):
        if not path:
            return
        # Drop the cached raster so the next paint re-renders from the fresh
        # SVG; refresh anything already showing a tick.
        try:
            _SVG_PIX_CACHE.clear()
            self._ring_ok.update()
            self._btn_done.setIcon(QIcon(_check_pixmap(14, "#FFFFFF")))
        except RuntimeError:
            pass  # dialog torn down while the fetch was in flight

    def _logo_gc(self):
        self._logo_worker = None

    # ------------------------------------------------------------------
    # sizing + animation
    # ------------------------------------------------------------------
    def _noselect_all(self):
        for lbl in self.findChildren(QLabel):
            _no_select(lbl)

    def _sync_overlay_geometry(self):
        geo = None
        host = self._host
        if host is not None and host.isVisible():
            g = host.frameGeometry()
            if g.isValid() and not g.isEmpty():
                geo = g
        if geo is None:
            scr = QApplication.primaryScreen()
            if scr is not None:
                geo = scr.availableGeometry()
        if geo is None:
            geo = QRect(0, 0, 1280, 800)
        self.setGeometry(geo)

    def _modal_target(self, w: int, h: int) -> QRect:
        rect = self.rect()
        x = rect.x() + (rect.width() - w) // 2
        y = rect.y() + (rect.height() - h) // 2
        return QRect(x, y, w, h)

    def _max_h(self) -> int:
        # max-height: calc(100vh - 48px) — the overlay already is the viewport.
        return max(120, self.height() - 48)

    def _measure_log(self, dialog_w: int) -> int:
        if self._pages["available"].isHidden():
            return 0
        host_w = max(160, dialog_w - _BODY_MARGINS[0] - _BODY_MARGINS[2])
        m = self._log_lay.contentsMargins()
        inner = max(60, host_w - m.left() - m.right() - 2)
        total = m.top() + m.bottom()
        n = self._log_lay.count()
        for i in range(n):
            item = self._log_lay.itemAt(i)
            row = item.widget() if item is not None else None
            if row is None:
                continue
            rl = row.layout()
            if rl is None:
                continue
            rm = rl.contentsMargins()
            lbl = row.findChild(QLabel, "LogText")
            if lbl is None:
                total += 18 + rm.top() + rm.bottom()
                continue
            tw = inner - rm.left() - rm.right() - 10 - rl.spacing()
            lh = lbl.heightForWidth(max(40, tw))
            total += max(18, lh) + rm.top() + rm.bottom()
        if n > 1:
            total += (n - 1) * self._log_lay.spacing()
        return max(_LOG_MIN, min(_LOG_MAX, total))

    def _adopt_widgets(self, animate: bool | None = None):
        if animate is None:
            animate = self.isVisible()
        self._noselect_all()
        old = self._modal.geometry()
        w = _STATE_WIDTH.get(self._mode or "checking", 452)

        self._body_scroll.setMinimumHeight(0)
        self._modal.resize(w, max(old.height(), 1))
        self._modal.layout().activate()
        self._body_lay.activate()

        page = self._pages.get(self._mode)
        if self._mode == "available":
            box_h = self._measure_log(w)
            self._log_scroll.setFixedHeight(box_h or _LOG_MIN)
            self._log_scroll.updateGeometry()
            self._log_host.updateGeometry()
        if page is not None and page.layout() is not None:
            # Invalidate the page's cached sizeHint so the freshly pinned
            # changelog height is reflected *synchronously* (otherwise the
            # body is measured with the previous state's height).
            page.layout().invalidate()
            page.layout().activate()
            page.updateGeometry()
        self._body_lay.invalidate()
        self._body_lay.activate()

        body_h = self._body_lay.sizeHint().height()
        max_h = self._max_h()
        body_h = max(1, min(body_h, max_h - _HEAD_H))
        self._body_scroll.setFixedHeight(body_h)
        self._body_scroll.updateGeometry()

        total_h = _HEAD_H + body_h
        target = self._modal_target(w, total_h)
        if self._geom_anim is not None:
            prev_anim = self._geom_anim
            self._geom_anim = None
            prev_anim.stop()
            prev_anim.deleteLater()
        if (not animate) or _prefers_reduced_motion() or old == target:
            self._modal.setGeometry(target)
            return
        anim = QPropertyAnimation(self._modal, b"geometry", self)
        anim.setDuration(280)
        anim.setStartValue(old)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _done_geo():
            if self._geom_anim is anim:
                self._geom_anim = None
            anim.deleteLater()

        anim.finished.connect(_done_geo)
        self._geom_anim = anim
        anim.start()

    def _fade_in(self, page: QWidget):
        # slide: start 4px lower, ease to 0 over 240ms
        self._slide_page = page
        self._set_slide(4 if not _prefers_reduced_motion() else 0)
        slide = QPropertyAnimation(self, b"slide_offset", self)
        slide.setDuration(240)
        slide.setStartValue(4.0 if not _prefers_reduced_motion() else 0.0)
        slide.setEndValue(0.0)
        slide.setEasingCurve(QEasingCurve.OutCubic)
        slide.start(QPropertyAnimation.DeleteWhenStopped)

        if self._fade_anim is not None:
            prev_fade = self._fade_anim
            self._fade_anim = None
            prev_fade.stop()
            prev_fade.deleteLater()
        if _prefers_reduced_motion():
            try:
                page.setGraphicsEffect(None)
            except Exception:  # noqa: BLE001
                pass
            return
        eff = QGraphicsOpacityEffect(page)
        eff.setOpacity(0.0)
        page.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(240)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _done():
            try:
                if page.graphicsEffect() is eff:
                    page.setGraphicsEffect(None)
            except Exception:  # noqa: BLE001
                pass
            if self._fade_anim is anim:
                self._fade_anim = None
            anim.deleteLater()

        anim.finished.connect(_done)
        self._fade_anim = anim
        anim.start()

    def _get_slide(self) -> int:
        return self._slide

    def _set_slide(self, v):
        self._slide = int(v)
        page = self._slide_page
        if page is not None and page.layout() is not None:
            m = page.layout().contentsMargins()
            page.layout().setContentsMargins(m.left(), int(v), m.right(), m.bottom())

    slide_offset = QtProperty(int, fget=_get_slide, fset=_set_slide)

    # overlay fade used by paintEvent
    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, v):
        self._opacity = float(v)
        self.update()

    overlay_opacity = QtProperty(float, fget=_get_opacity, fset=_set_opacity)

    def paintEvent(self, _event):
        p = QPainter(self)
        a = int(255 * 0.62 * max(0.0, min(1.0, self._opacity)))
        p.fillRect(self.rect(), QColor(5, 3, 12, a))
        p.end()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_overlay_geometry()
        self._adopt_widgets(animate=False)
        self.setFocus()
        if _prefers_reduced_motion():
            self._opacity = 1.0
            return
        target = self._modal.geometry()
        start = QRect(target)
        start.setWidth(int(target.width() * 0.97))
        start.setHeight(int(target.height() * 0.97))
        start.moveCenter(target.center())
        start.translate(0, 14)
        self._modal.setGeometry(start)
        self._opacity = 0.0
        fade = QPropertyAnimation(self, b"overlay_opacity", self)
        fade.setDuration(200)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.start(QPropertyAnimation.DeleteWhenStopped)
        anim = QPropertyAnimation(self._modal, b"geometry", self)
        anim.setDuration(250)
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._open_anim = anim

    # ------------------------------------------------------------------
    # state machine
    # ------------------------------------------------------------------
    def _show_state(self, name: str, fade: bool = True):
        prev = self._mode
        self._mode = name
        for key, page in self._pages.items():
            page.setVisible(key == name)
        self._state_lbl.setText(_TITLES.get(name, ""))
        if name == "installing":
            self._x.setEnabled(False)
        else:
            self._x.setEnabled(True)
        self._adopt_widgets()
        if fade and prev != name and not _prefers_reduced_motion():
            self._fade_in(self._pages[name])

    def _clear_log(self):
        while self._log_lay.count():
            item = self._log_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _clear_workers(self):
        for attr in ("_worker", "_size_worker"):
            w = getattr(self, attr, None)
            if w is not None and hasattr(w, "isRunning") and w.isRunning():
                if hasattr(w, "cancel"):
                    w.cancel()
                else:
                    w.quit()
                w.wait(2500)
            setattr(self, attr, None)

    # -- flow
    def _check(self):
        self._show_state("checking")
        self._ring_check.start_spin()
        self._worker = FetchWorker(self)
        self._worker.done.connect(self._on_checked)
        self._worker.start()

    def _on_checked(self, payload):
        info = payload.get("info")
        error = payload.get("error")
        self._ring_check.stop_spin()
        if error:
            self._show_error(error, retry="check")
            return
        if info is None:
            self._show_up_to_date()
            return
        self._info = info
        self._show_available(info)

    def _on_update_clicked(self):
        if self._mode == "available":
            self._download()

    def _download(self):
        if self._info is None:
            return
        self._show_state("downloading")
        self._ring_dl.set_tone("pri")
        self._ring_dl.set_progress(0.0)
        self._ring_dl.set_text("0%")
        self._bar_dl.set_frac(0.0)
        self._bytes_got = 0
        self._bytes_total = int(self._info.get("size") or self._known_size or 0)
        self._dl_start = time.monotonic()
        self._last_bytes = 0
        self._last_t = self._dl_start
        self._speed = 0.0
        new = str(self._info.get("version") or "").lstrip("v")
        self._dl_sub.setText(f"Maximum Tweaks <em>v{new}</em>")
        self._update_dl_stat()
        self._worker = DownloadWorker(str(self._info.get("url") or ""), self)
        self._worker._checksum_url = str(self._info.get("checksum_url") or "")
        self._worker._sha256 = str(self._info.get("sha256") or "")
        self._worker._filename = str(self._info.get("filename") or "")
        self._worker.bytes.connect(self._on_bytes)
        self._worker.done.connect(self._on_downloaded)
        self._worker.start()

    def _on_bytes(self, got: int, total: int):
        self._bytes_got = int(got or 0)
        if total:
            self._bytes_total = int(total)
        frac = (self._bytes_got / self._bytes_total) if self._bytes_total else 0.0
        self._ring_dl.set_progress(frac)
        self._ring_dl.set_text(f"{int(frac * 100)}%")
        self._bar_dl.set_frac(frac)
        now = time.monotonic()
        if now - self._last_t >= 0.35:
            dt = now - self._last_t
            self._speed = (self._bytes_got - self._last_bytes) / dt if dt > 0 else 0.0
            self._last_bytes = self._bytes_got
            self._last_t = now
        self._update_dl_stat()

    def _update_dl_stat(self):
        if self._bytes_total:
            got = self._bytes_got / 1048576
            total = self._bytes_total / 1048576
            self._dl_progress.setText(f"{got:.1f} of {total:.1f} MB")
        else:
            self._dl_progress.setText(f"{self._bytes_got / 1048576:.1f} MB")
        self._dl_speed.setText(
            f"{self._speed / 1048576:.1f} MB/s" if self._speed else "")

    def _on_downloaded(self, new_exe, error):
        self._worker = None
        if error:
            self._show_error(error, retry="download")
            return
        if new_exe is None:  # cancelled
            self._show_available(self._info)
            self._flash("Download cancelled")
            return
        self._new_exe = new_exe
        if not self._known_size and self._bytes_total:
            self._known_size = self._bytes_total
        self._install()

    def _cancel_download(self):
        if self._worker is not None:
            self._worker.cancel()
        else:
            self._show_available(self._info)
            self._flash("Download cancelled")

    def _install(self):
        self._show_state("installing")
        self._ring_install.start_spin()
        self._bar_install.start_indeterminate()
        self._install_h1.setText("Installing update\u2026")
        QTimer.singleShot(1200, self._restarting)
        QTimer.singleShot(1600, self._do_install)

    def _restarting(self):
        if self._mode == "installing":
            self._install_h1.setText("Restarting Maximum Tweaks\u2026")

    def _do_install(self):
        if self._mode != "installing":
            return
        from engine import updater, state
        new = str((self._info or {}).get("version") or "").lstrip("v")
        try:
            state.set_meta("updated_to_version", new or None)
            state.set_meta("updated_from_version", APP_VERSION)
            state.set_meta("update_remind_at", None)
            state.set_meta("skipped_update_version", None)
        except Exception:  # noqa: BLE001
            pass
        try:
            updater.install_and_restart(self._new_exe)
        except updater.UpdaterError as exc:
            self._ring_install.stop_spin()
            self._bar_install.stop_indeterminate()
            self._show_error(str(exc), retry="install")
            return
        logger.info("updater: quitting to apply update")
        host = self._host
        try:
            if host is not None and hasattr(host, "close"):
                host.close()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
        os._exit(0)

    def _show_available(self, info: dict):
        self._info = info or self._info or {}
        self._ring_up.stop_spin()
        cur = APP_VERSION.lstrip("v")
        new = str(self._info.get("version") or "").strip().lstrip("v")
        self._ring_up.set_tone("pri")
        self._ring_up.set_offset(22)
        self._ring_up.set_text(new)
        self._up_sub.setText(
            f"<s style='opacity:0.65'>v{cur}</s> "
            f"\u2192 <b style='color:{C['pri2']}'>v{new}</b>")
        self._known_size = int(self._info.get("size") or self._known_size or 0)
        self._chip_dl.setText(self._size_chip_text())
        self._chip_date.setText(self._date_chip_text(self._info.get("published_at")))
        self._clear_log()
        bullets = _parse_notes(self._info.get("notes") or "")
        if bullets:
            for text in bullets:
                self._log_lay.addWidget(self._bullet_row(text))
        else:
            none = QLabel("No changelog provided.")
            none.setObjectName("LogNone")
            none.setFont(_sans(13))
            self._log_lay.addWidget(none)
        self._log_lay.addStretch(0)
        self._show_state("available")
        if not self._known_size:
            self._probe_size()

    def _probe_size(self):
        url = str((self._info or {}).get("url") or "")
        if not url:
            return
        self._size_worker = SizeWorker(url, self)
        self._size_worker.done.connect(self._on_size_probed)
        self._size_worker.start()

    def _on_size_probed(self, size: int):
        self._size_worker = None
        if size and self._mode == "available":
            self._known_size = int(size)
            self._chip_dl.setText(self._size_chip_text())

    def _size_chip_text(self) -> str:
        if self._known_size:
            return f"<b>{self._known_size / 1048576:.0f} MB</b> download"
        return "<b>Download</b> update"

    def _date_chip_text(self, published_at) -> str:
        text = str(published_at or "").strip()
        if not text:
            return "<b>Latest release</b>"
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            days = (now - dt).days
            if days <= 0:
                return "<b>Released today</b>"
            if days == 1:
                return "<b>Released yesterday</b>"
            if days < 7:
                return f"<b>Released {days} days ago</b>"
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            return f"<b>Released {months[dt.month - 1]} {dt.day}</b>"
        except Exception:  # noqa: BLE001
            return "<b>Latest release</b>"

    def _show_up_to_date(self):
        cur = APP_VERSION.lstrip("v")
        self._ring_ok.stop_spin()
        self._ring_ok.set_tone("ok", check=True)
        self._ok_sub.setText(f"Latest release \u00b7 v{cur} installed")
        self._show_state("up_to_date")

    def _show_error(self, message: str, retry: str = "check"):
        self._retry = retry
        if retry == "check":
            self._state_lbl.setText("CHECK FAILED")
            self._err_h1.setText("Couldn\u2019t check for updates")
        else:
            self._state_lbl.setText("UPDATE FAILED")
            self._err_h1.setText("Update failed")
        self._ring_err.stop_spin()
        self._ring_err.set_tone("err")
        self._ring_err.set_offset(22)
        self._ring_err.set_text("!")
        self._err_sub.setText(message or "Something went wrong.")
        self._btn_retry.setText("Try again")
        self._show_state("error")

    def _retry_action(self):
        if self._retry == "download" and self._info is not None:
            self._download()
        elif self._retry == "install" and self._new_exe is not None:
            self._install()
        else:
            self._check()

    # ------------------------------------------------------------------
    # popup toast (used while the dialog stays open, e.g. cancel)
    # ------------------------------------------------------------------
    def _flash(self, text: str):
        lbl = QLabel(text, self)
        lbl.setObjectName("Flash")
        lbl.setFont(_sans(12, QFont.Weight.DemiBold))
        lbl.setContentsMargins(18, 10, 18, 10)
        lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lbl.adjustSize()
        geo = self._modal.geometry()
        x = geo.x() + (geo.width() - lbl.width()) // 2
        y = geo.y() + geo.height() + 12
        if y + lbl.height() > self.height() - 12:
            y = geo.y() - lbl.height() - 12
        lbl.move(x, y)
        lbl.show()
        lbl.raise_()
        if _prefers_reduced_motion():
            QTimer.singleShot(2200, lbl.deleteLater)
            return
        eff = QGraphicsOpacityEffect(lbl)
        lbl.setGraphicsEffect(eff)
        eff.setOpacity(0.0)
        fin = QPropertyAnimation(eff, b"opacity", self)
        fin.setDuration(180)
        fin.setStartValue(0.0)
        fin.setEndValue(1.0)
        fin.start(QPropertyAnimation.DeleteWhenStopped)
        out = QPropertyAnimation(eff, b"opacity", self)
        out.setDuration(300)
        out.setStartValue(1.0)
        out.setEndValue(0.0)
        out.finished.connect(lbl.deleteLater)
        QTimer.singleShot(2000, out.start)

    # ------------------------------------------------------------------
    # actions that close the dialog
    # ------------------------------------------------------------------
    def _new_version(self) -> str:
        return str((self._info or {}).get("version") or "").strip()

    def _skip(self):
        version = self._new_version().lstrip("v")
        try:
            from engine import state
            if version:
                state.set_meta("skipped_update_version", version)
                state.set_meta("update_remind_at", None)
        except Exception:  # noqa: BLE001
            pass
        self._toast_after_close(f"Skipped v{version}" if version else "Version skipped")

    def _remind(self):
        try:
            from engine import state
            state.set_meta("update_remind_at", time.time() + 86400)
        except Exception:  # noqa: BLE001
            pass
        self._toast_after_close("We\u2019ll remind you later")

    def _toast_after_close(self, message: str):
        host = self.parentWidget() or self._host
        self._clear_workers()
        super().reject()

        def _show():
            try:
                from ui.widgets import toast
                toast(message, "info", host)
            except Exception:  # noqa: BLE001
                pass

        QTimer.singleShot(40, _show)

    # ------------------------------------------------------------------
    # close handling
    # ------------------------------------------------------------------
    def reject(self):
        if self._mode == "installing":
            return
        if self._mode == "downloading" and self._worker is not None:
            self._worker.cancel()
        self._clear_workers()
        super().reject()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._mode == "installing":
                return
            if not self._modal.geometry().contains(event.position().toPoint()):
                self.reject()
                return
        super().mousePressEvent(event)

    def closeEvent(self, event):
        if self._mode == "installing":
            event.ignore()
            return
        if self._mode == "downloading" and self._worker is not None:
            self._worker.cancel()
        self._clear_workers()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Changelog parsing
# ---------------------------------------------------------------------------
def _parse_notes(notes: str) -> list[str]:
    """Turn a notes blob (markdown-ish) into a list of plain bullet strings."""
    out: list[str] = []
    for raw in str(notes or "").replace("\r", "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)          # markdown headings
        line = re.sub(r"^[-*+\u2022]\s*", "", line)     # list bullets
        line = re.sub(r"^\d+[.)]\s*", "", line)         # ordered list
        line = line.replace("**", "").replace("__", "")
        line = line.strip("`").strip()
        if line:
            out.append(line)
    return out


def _parse_notes_for_test(notes: str) -> list[str]:
    return _parse_notes(notes)


# Backwards-compatible name used by older callers.
def parse_notes(notes: str) -> list[str]:
    return _parse_notes(notes)
