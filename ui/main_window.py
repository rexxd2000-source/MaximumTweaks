"""Main application window: bottom glass dock navigation + stacked pages."""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QTimer,
    Qt,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from config.app_config import (
    APP_NAME,
    APP_VERSION,
    GITHUB_REPO,
    UPDATE_MANIFEST_URL,
)
from database import TWEAKS
from engine import activity
from maxlog import logger
from ui.categories import compatible_tweaks
from ui.context import AppContext
from ui.dock_nav import DockNav
from ui.pages.dashboard import DashboardPage
from ui.pages.detect import DetectPage, DetectWorker
from ui.pages.logs import LogsPage
from ui.pages.optimize import OptimizePage
from ui.pages.chat import ChatPage
from ui.pages.route_coming_soon import RouteComingSoonPage
from ui.pages.delay_destroyer import DelayDestroyerPage
from ui.pages.debloat import DebloatPage
from ui.pages.app_optimizers import AppOptimizersPage
from ui.pages.settings import SettingsPage
from ui.pages.tools import ToolsPage
from ui.pages.tweak_cards import TweakCardsPage
from ui.space import SpaceBackground


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def relaunch_as_admin() -> None:
    import subprocess
    params = " ".join(f'"{a}"' for a in sys.argv)
    if sys.executable.lower().endswith((".exe", "python.exe", "pythonw.exe")):
        cmd = f'powershell -NoProfile -Command "Start-Process -FilePath \'{sys.executable}\' -ArgumentList \'{params}\' -Verb RunAs"'
        try:
            subprocess.Popen(cmd, shell=True, creationflags=0x08000000)
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"relaunch as admin failed: {exc}")


class MainWindow(QWidget):
    # Pages built shortly after the window appears. Without this, the first
    # click on a page has to wait for its first load before the swap can happen
    # (the stack is no longer hidden, so the wait is now invisible rather than
    # a dark screen, but it is still a wait). Sequential and spaced out on
    # purpose: every one of these is a QWebEngineView with its own renderer, so
    # building them together spikes memory. Set the tuple empty to disable.
    PREWARM_PAGES = ("tweaks", "tools", "profiles")
    PREWARM_DELAY_MS = 1500
    PREWARM_GAP_MS = 700

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1320, 900)
        self.setMinimumSize(1100, 700)

        self.ctx = AppContext(self)
        self.pages = {}
        # The dock starts with no popover or selection; the guard below stops a
        # startup navigate() from fighting the dock before the app is up.
        self._nav_ready = False
        # The page currently on screen, so navigating to it again can be a no-op.
        self._cur_key = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Deep-space ambient background (glow orbs + stars) behind the pages.
        self.space = SpaceBackground(self)
        self.space.setGeometry(self.rect())
        self.space.lower()

        self.stack = QStackedWidget()
        # Clicks on page content and Escape both dismiss the dock popover;
        # an event filter on the stack sees every event from every page,
        # including the ones inside embedded QtWebEngine views.
        self.stack.installEventFilter(self)
        root.addWidget(self.stack, 1)

        # Floating glass dock: a raised, content-sized child of the window
        # (not a layout row), so it never reserves space, never splits the
        # window into pages + a dock strip, and just floats over the page.
        self.dock = DockNav(self)
        self.dock.requested.connect(self.navigate)
        self.dock.raise_()
        # The dock's plan badge reads the live entitlement, so it has to be
        # repainted whenever that changes: activating a key, letting one expire,
        # revoking it, or signing out. license_changed is the app's existing
        # "the license under us just moved" signal - the dashboard, settings and
        # sidebar card already hang off it.
        if hasattr(self.ctx, "license_changed"):
            self.ctx.license_changed.connect(self.dock.refresh_tier)

        self._register_pages()
        # The dock's frosted glass is produced on the Qt side from this stack,
        # so it needs a handle on it. Set after the pages exist.
        self.dock.set_stack(self.stack)
        # The app launches on the Dashboard, exactly like the original shell;
        # the dock's own logo navigates back here from anywhere.
        self.navigate("dashboard")
        self._nav_ready = True

        # Background system-state audit: reads live registry/power/service
        # state so every toggle reflects the real system, not just what this
        # app has applied. Runs off the UI thread; cards fill in as results land.
        self.ctx.start_full_audit()

        # Background hardware detection at startup.
        self._detect_worker = DetectWorker(self)
        self._detect_worker.done.connect(self._on_detected)
        self._detect_worker.error.connect(
            lambda msg: (logger.warn(f"startup detection: {msg}"),
                         activity.emit("error", f"System scan failed \u2014 {msg}")))
        self._detect_worker.start()
        activity.emit("info", f"{APP_NAME} v{APP_VERSION} started")
        logger.info(f"{APP_NAME} v{APP_VERSION} launched (admin={is_admin()})")

        # Silent background update check — an update banner appears if the
        # server is ahead of this build, otherwise nothing happens.
        self._update_worker = None
        self._check_for_update_background()

        self._prewarm_pages()

    def _prewarm_pages(self):
        """Build the heavy pages off the critical path, one at a time."""
        keys = list(self.PREWARM_PAGES)

        def step(i=0):
            if i >= len(keys):
                return
            key = keys[i]
            try:
                if key not in self.pages:
                    self._ensure_page(key)
                    logger.info(f"prewarm built {key}")
            except Exception as e:  # noqa: BLE001 - a warm page is optional
                logger.warn(f"prewarm {key} failed: {e}")
            QTimer.singleShot(self.PREWARM_GAP_MS, lambda: step(i + 1))

        if keys:
            QTimer.singleShot(self.PREWARM_DELAY_MS, step)

    def _on_detected(self, profile):
        self.ctx.set_profile(profile)
        ready = len(compatible_tweaks(TWEAKS, self.ctx.eval, self.ctx.profile))
        activity.emit(
            "scan", f"System scan completed \u2014 {ready} tweaks compatible with this PC")

    def _check_for_update_background(self):
        """Non-blocking update probe; shows a toast if a newer build exists."""
        if not GITHUB_REPO and not UPDATE_MANIFEST_URL:
            return  # updates not configured
        from ui.updater_dialog import FetchWorker
        worker = FetchWorker(self)
        worker.done.connect(self._on_bg_update)
        self._update_worker = worker  # keep a strong ref until finished
        worker.start()

    def _on_bg_update(self, payload):
        self._update_worker = None
        info = payload.get("info")
        if not info:
            return
        from ui.widgets import toast
        toast(
            f"Update available: v{info.get('version', '?')} \u2014 open Settings "
            "\u2192 Update to install.",
            "info", self)
        activity.emit("info", f"Update available: v{info.get('version')}")

    # ---------------- Pages ----------------

    def _register_pages(self):
        """Build pages lazily: only the requested page is constructed.

        Each page is built once on first navigation, so startup only pays for
        the dashboard instead of all 14 pages ~0.8s of eager widget work. The
        registry keeps the per-page constructor arguments so rebuilds are
        impossible — ``self.pages[key]`` is populated once and stays cached,
        preserving each page's live state across navigation.
        """
        self._page_builders = {
            "dashboard": lambda: DashboardPage(self.ctx, self.navigate),
            "detect": lambda: DetectPage(self.ctx),
            "tweaks": lambda: TweakCardsPage(self.ctx, self.navigate),
            "profiles": lambda: __import__(
                "ui.pages.profiles", fromlist=["ProfilesPage"]).ProfilesPage(self.ctx),
            "optimize": lambda: OptimizePage(self.ctx),
            "tools": lambda: ToolsPage(self.ctx, self.navigate),
            "chat": lambda: ChatPage(self.ctx),
            "delay_destroyer": lambda: DelayDestroyerPage(self.ctx),
            "debloat": lambda: DebloatPage(self.ctx),
            "app_optimizers": lambda: AppOptimizersPage(self.ctx),
            "controller": lambda: __import__(
                "ui.pages.controller", fromlist=["ControllerPage"]).ControllerPage(self.ctx),
            "qos": lambda: __import__(
                "ui.pages.qos", fromlist=["QosPage"]).QosPage(self.ctx),
            "diagnostics": lambda: __import__(
                "ui.pages.diagnostics", fromlist=["DiagnosticsPage"]).DiagnosticsPage(self.ctx),
            "route_analyzer": lambda: RouteComingSoonPage(self.ctx, self.navigate),
            "pricing": lambda: __import__(
                "ui.pages.pricing", fromlist=["PricingPage"]).PricingPage(self.ctx),
            "settings": lambda: SettingsPage(self.ctx, self.navigate),
            "logs": lambda: LogsPage(),
        }

    def _ensure_page(self, key):
        """Build (once) and return the page for ``key``, registering it in
        the stack. Missing keys return None."""
        page = self.pages.get(key)
        if page is not None:
            return page
        builder = self._page_builders.get(key)
        if builder is None:
            return None
        self.pages[key] = builder()
        self.stack.addWidget(self.pages[key])
        return self.pages[key]

    def navigate(self, key):
        # Already on this page: change nothing at all. Re-running the swap for
        # the page that is already on screen buys nothing and costs a rebuild of
        # the fade, a re-render and a visible flicker - most obviously when the
        # dock logo is clicked while the Dashboard is up. The dock's own
        # "am I already here?" check can then stay a pure UI shortcut.
        if self._nav_ready and key == getattr(self, "_cur_key", None):
            return
        self._cur_key = key
        self._nav_seq = getattr(self, "_nav_seq", 0) + 1
        token = self._nav_seq
        page_key = key
        # Whether this call is what builds the page. ``isLoading()`` cannot be
        # trusted here: QWebEnginePage::load() is dispatched asynchronously, so
        # a freshly built webview still reports "not loading" for a tick. A
        # page this call created is known to need its first load.
        created = page_key not in self.pages
        if key.startswith("tweak:"):
            # Dock tile: show the Tweaks master view pre-filtered.
            created = "tweaks" not in self.pages
            self._ensure_page("tweaks").select(key[len("tweak:"):])
            page_key = "tweaks"
        elif key.startswith("diagnostics:"):
            # Diagnostics test: open Diagnostics and pulse the matching card.
            created = "diagnostics" not in self.pages
            self._ensure_page("diagnostics").focus_card(key.split(":", 1)[1])
            page_key = "diagnostics"
        page = self._ensure_page(page_key)
        if page is None:
            return
        self._reveal_page(page, token, needs_load=created)
        self._mark_active(key)

    def _reveal_page(self, page, token=None, needs_load=False):
        """Swap the stack without ever taking the page area offline.

        The stack used to be hidden for the whole swap. That was wrong: hiding a
        QStackedWidget leaves only SpaceBackground visible, so every navigation
        to a page that was still loading painted the dark backdrop for as long
        as the load took (up to the 2.5s safety net) - the dark scrim. It was
        also what made the old page's last Chromium frame reappear on re-show.

        Instead the outgoing page stays on screen until the incoming one is
        genuinely ready, and the swap happens in one step. Readiness is
        loadFinished for a web page (isLoading() cannot be trusted: QWebEngine
        dispatches load() asynchronously, so a freshly built view reports "not
        loading" for a tick, hence the explicit needs_load flag), or immediately
        for a plain Qt page.
        """
        web = getattr(page, "_web", None)
        loading = web is not None and (needs_load or self._web_loading(web))
        state = {"done": False, "connected": False}

        def reveal():
            logger.info(f"reveal {type(page).__name__} loading={loading} "
                        f"token={token} nav={getattr(self, '_nav_seq', 0)}")
            if state["done"]:
                return
            state["done"] = True
            if state["connected"]:
                try:
                    web.loadFinished.disconnect(reveal)
                except Exception:  # noqa: BLE001 - already gone
                    pass
            # A newer click already claimed the stack: do not steal it back.
            if token is not None and token != getattr(self, "_nav_seq", 0):
                return
            self._clear_widget_fade()
            self._swap_to(page)

        if loading:
            state["connected"] = True
            web.loadFinished.connect(reveal)
            QTimer.singleShot(2500, reveal)  # safety net only
        else:
            reveal()

    def _swap_to(self, page):
        """Fade the incoming page up from nothing, without a full-opacity frame.

        _fade_page_in() injects its animation AFTER the page is already visible,
        so the page used to paint at full opacity for a frame, drop to opacity 0
        and fade back up - a visible flash on every navigation. Priming the new
        page to opacity 0 while it is still off screen means the swap itself
        happens at zero opacity, and the fade only ever runs forwards from there.
        """
        web = getattr(page, "_web", None)

        def do_swap(_=None):
            logger.info(f"swap -> {type(page).__name__} "
                        f"(from {type(self.stack.currentWidget()).__name__})")
            if self.stack.currentWidget() is not page:
                self.stack.setCurrentWidget(page)
            page._mx_revealed = True
            self._fade_page_in(page)

        if web is None:
            do_swap()
            return
        web.page().runJavaScript(
            "(function(){try{"
            "var s=document.getElementById('__mxPrime');"
            "if(!s){s=document.createElement('style');s.id='__mxPrime';"
            "(document.head||document.documentElement).appendChild(s);}"
            "s.textContent='body>*{opacity:0}';"
            "}catch(e){}})()",
            do_swap)

    def _fade_widget_page_in(self, page, ms=320):
        """Fade a plain Qt page in, so it matches the web pages.

        Plain Qt pages have no document to animate. ``_fade_page_in`` used to
        return immediately for them, so the page hard-cut into the stack while
        the dock panel was still animating closed over it. Coming out of a web
        page that eases in over 320ms, that cut is what read as a glitch - the
        transition was not slow, it was inconsistent, and it had no easing at
        all to sit next to the dock's own animation.

        A QGraphicsOpacityEffect still cannot be used when the page embeds a
        native QWebEngineView: Qt draws the effect into a texture that the
        native child never joins, so the page renders empty and the window
        backdrop shows through for the whole animation. Those pages keep the
        instant swap. Pages that do not embed one (the tweak card grids) fade
        normally.
        """
        if page.findChild(QWebEngineView) is not None:
            return
        # A second navigation landing mid-fade: drop the stale effect first so
        # the new page is not left stuck at a partial opacity.
        self._clear_widget_fade()
        try:
            eff = QGraphicsOpacityEffect(page)
            eff.setOpacity(0.0)
            page.setGraphicsEffect(eff)
        except Exception:  # noqa: BLE001 - never block a navigation on styling
            return
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(ms)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        # Keep a reference: a QPropertyAnimation with no owner is collected and
        # the fade dies halfway, leaving the page at partial opacity.
        self._widget_fade = anim
        self._widget_fade_page = page

        def _done():
            if getattr(self, "_widget_fade", None) is anim:
                self._widget_fade = None
                self._widget_fade_page = None
            # Clear the effect once done. Left in place it keeps the whole
            # subtree in an offscreen buffer, which is expensive for a card grid
            # and breaks the page's own painting after the animation ends.
            try:
                page.setGraphicsEffect(None)
            except Exception:  # noqa: BLE001
                pass

        anim.finished.connect(_done)
        anim.start()

    def _clear_widget_fade(self):
        """Drop any in-flight widget fade, leaving the page fully opaque.

        Stopping the animation is not enough on its own: the page keeps the
        QGraphicsOpacityEffect it was given, frozen part-way through. That left
        hidden pages holding a stale effect at a partial opacity and an
        offscreen buffer for their whole subtree, so the page came back dimmed
        the next time it was shown.
        """
        anim = getattr(self, "_widget_fade", None)
        page = getattr(self, "_widget_fade_page", None)
        if anim is not None:
            try:
                anim.stop()
            except Exception:  # noqa: BLE001
                pass
        self._widget_fade = None
        self._widget_fade_page = None
        if page is not None:
            try:
                page.setGraphicsEffect(None)
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _web_loading(web):
        try:
            return bool(web.page().isLoading())
        except Exception:  # noqa: BLE001 - treat unknown as "loaded"
            return False

    def _fade_page_in(self, page):
        """Ease the page in *inside its own document*.

        A QGraphicsOpacityEffect on the page widget cannot be used: the page
        hosts a native QWebEngineView, and Qt draws an effect into a texture
        that the native child never joins, so the page renders empty and the
        dark SpaceBackground shows through for the whole animation. Animating
        the document's own children keeps the page painted instead, and nothing
        outside the page is ever dimmed.

        These pages leave ``html``/``body`` transparent and paint the backdrop
        on a child, so fading that child would expose the dark window behind the
        page. The backdrop is therefore promoted onto ``html`` (copied from the
        element that already paints it) before the children fade. If no child
        paints a backdrop, the fade is skipped rather than risk a dark frame.
        Plain Qt pages have no document and simply appear.
        """
        web = getattr(page, "_web", None)
        if web is None:
            self._fade_widget_page_in(page)
            return
        web.page().runJavaScript(
            "(function(){try{"
            "var k='mxPageIn';"
            # Drop the off-screen prime first, on every path. It is what holds
            # the page at opacity 0 until this moment, so it has to go before
            # anything can return early - a page with no backdrop child used to
            # hit the 'skip' return and would otherwise stay invisible. The
            # mxPageIn animation starts from opacity 0, so handing over here
            # never shows a full-opacity frame.
            "var pr=document.getElementById('__mxPrime');if(pr)pr.remove();"
            "var kids=document.body?Array.prototype.slice.call("
            "document.body.children):[];"
            "var src=null;"
            "for(var i=0;i<kids.length;i++){var c=getComputedStyle(kids[i]);"
            "if(c.backgroundColor!=='rgba(0, 0, 0, 0)'||"
            "(c.backgroundImage&&c.backgroundImage!=='none')){src=kids[i];break;}}"
            "if(!src||!kids.length)return 'skip';"
            "var s=document.getElementById('__mxPageInStyle');"
            "if(!s){s=document.createElement('style');s.id='__mxPageInStyle';"
            "document.head.appendChild(s);}"
            "var sc=getComputedStyle(src);"
            "s.textContent='html{background-color:'+sc.backgroundColor+';"
            "background-image:'+sc.backgroundImage+';}'"
            "+'body>*.'+k+'{animation:mxPageIn .32s "
            "cubic-bezier(.22,1,.36,1) both}'"
            "+'@keyframes mxPageIn{from{opacity:0}}';"
            "for(var j=0;j<kids.length;j++){var e=kids[j];"
            "e.classList.remove(k);void e.offsetWidth;e.classList.add(k);}"
            "setTimeout(function(){for(var m=0;m<kids.length;m++)"
            "{kids[m].classList.remove(k);}},800);"
            "return 'ok:'+kids.length;}catch(e){return 'err:'+e;}})()")

    def eventFilter(self, obj, event):
        """Dismiss the dock popover on anything outside it.

        The popover is a glass overlay, so it has to be able to close when the
        user clicks the page behind it. Filtering on the stack catches clicks
        and key presses from every page, including the ones rendered inside
        embedded QtWebEngine views, which otherwise consume both."""
        if obj is self.stack:
            if event.type() == event.Type.MouseButtonPress:
                self.dock.close_panel()
            elif (event.type() == event.Type.KeyPress
                    and event.key() == Qt.Key_Escape):
                self.dock.close_panel()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.space.setGeometry(self.rect())
        self.dock.raise_()

    def closeEvent(self, event):
        dashboard = self.pages.get("dashboard")
        if dashboard is not None and dashboard.sampler is not None:
            dashboard.sampler.stop()
            dashboard.sampler.wait(2000)
        try:
            self.ctx.auditor.shutdown()
        except Exception:  # noqa: BLE001
            pass
        # Startup hardware detection is a one-shot WMI scan that can take ~15s.
        # If it is still running, wait for it so the QThread is not destroyed
        # while alive (otherwise Qt aborts the process on exit).
        if getattr(self, "_detect_worker", None) is not None:
            self._detect_worker.wait(20000)
        super().closeEvent(event)

    def _mark_active(self, key):
        """Point the dock's active tile at the page that is now showing, so a
        navigation raised from inside a page still lights up the dock."""
        if self._nav_ready:
            self.dock.sync(key)
