"""Main application window: premium sidebar navigation + stacked pages."""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QUrl,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.app_config import (
    APP_NAME,
    APP_VERSION,
    GITHUB_REPO,
    GITHUB_URL,
    ICONS,
    UPDATE_MANIFEST_URL,
)
from engine import activity, discord_auth
from rexlog import logger
from ui.categories import SIDEBAR_TWEAKS
from ui.context import AppContext
from ui.discord import SidebarDiscordCard
from ui.goodbye import GoodbyeScreen
from ui.pages.dashboard import DashboardPage
from ui.pages.detect import DetectPage, DetectWorker
from ui.pages.logs import LogsPage
from ui.pages.optimize import OptimizePage
from ui.premium_widgets import ComingSoonPage
from ui.pages.settings import SettingsPage
from ui.pages.tools import ToolsPage
from ui.pages.tweaks import ALL_KEY, TweaksPage
from ui.monitor_widgets import RexLogo
from ui.widgets import repolish


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
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1320, 840)
        self.setMinimumSize(1100, 700)

        self.ctx = AppContext(self)
        self.pages = {}
        self.nav_buttons = {}
        self.goodbye: GoodbyeScreen | None = None
        self._locked = False
        self.ctx.discord_changed.connect(self._on_discord_changed)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = self._build_sidebar()
        root.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._register_pages()
        self.navigate("dashboard")
        self._on_discord_changed()

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

    def _on_detected(self, profile):
        self.ctx.set_profile(profile)
        ready = sum(1 for e in self.ctx.eval.values() if e["state"] == "ready")
        activity.emit("scan", f"System scan completed \u2014 {ready} tweaks compatible")

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

    def _on_discord_changed(self):
        # Run after ctx emits a change. The sidebar card rebuilds itself off
        # this signal; here we handle lock/unlock on live disconnects.
        if not discord_auth.session():
            self.on_disconnect()
        else:
            self._unlock()

    def on_disconnect(self):
        """Public hook: handed off by main.py when a fresh launch finds the
        session already signed out (there is no signal for that case)."""
        self._lock_away()

    def _lock_away(self):
        """Signed out mid-session: fade out and hand off to the goodbye screen."""
        if self._locked:
            return
        self._locked = True
        if self.goodbye is None:
            self.goodbye = GoodbyeScreen(self.ctx)
        self.goodbye.pick_quote()
        self.goodbye.resize(self.size())
        self.fade_window(self, 450, done=self._show_goodbye)

    def _show_goodbye(self):
        self.hide()
        self.goodbye.setGeometry(self.frameGeometry())
        self.goodbye.show()
        self.goodbye.raise_()
        self.fade_window(self.goodbye, 350, fade_in=True)

    def _unlock(self):
        """Back online: tear down the goodbye screen and restore the window."""
        if not self._locked:
            return
        self._locked = False
        if self.goodbye is not None:
            self.goodbye.hide()
        self.show()
        self.raise_()
        self.fade_window(self, 450, fade_in=True)

    @staticmethod
    def fade_window(widget, duration_ms: int, done=None, fade_in: bool = False):
        """Simple opacity cross-fade that flushes its effect out afterwards."""
        from PySide6.QtCore import QEasingCurve, QPropertyAnimation
        anim = QPropertyAnimation(widget, b"windowOpacity", widget)
        anim.setDuration(duration_ms)
        start = widget.windowOpacity()
        target = 1.0 if fade_in else 0.0
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _finish():
            widget.setWindowOpacity(1.0)
            if done:
                done()
        anim.finished.connect(_finish)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


    # ---------------- Sidebar ----------------

    def _nav_button(self, text, obj="Nav"):
        btn = QPushButton(text)
        btn.setObjectName(obj)
        btn.setProperty("active", "false")
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(244)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(2)

        # Scrollable navigation (prevents overflow at small window sizes).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        nav = QWidget()
        nav_lay = QVBoxLayout(nav)
        nav_lay.setContentsMargins(0, 0, 0, 0)
        nav_lay.setSpacing(2)

        # Branding
        brand = QHBoxLayout()
        brand.setSpacing(10)
        self.avatar = RexLogo(36)
        brand.addWidget(self.avatar)
        bbox = QVBoxLayout()
        bbox.setSpacing(0)
        btitle = QLabel(APP_NAME)
        btitle.setObjectName("BrandTitle")
        bbox.addWidget(btitle)
        brand.addLayout(bbox)
        brand.addStretch()
        nav_lay.addLayout(brand)
        nav_lay.addSpacing(10)

        # ---- MAIN
        sec = QLabel("MAIN")
        sec.setObjectName("NavSection")
        nav_lay.addWidget(sec)
        btn = self._nav_button(f"{ICONS['dashboard']}   Dashboard")
        btn.clicked.connect(lambda _=False: self.navigate("dashboard"))
        nav_lay.addWidget(btn)
        self.nav_buttons["dashboard"] = btn

        # ---- TWEAKS (collapsible section with sub-categories)
        tweak_header = QPushButton("TWEAKS  \u25be")
        tweak_header.setObjectName("NavSectionBtn")
        tweak_header.setCursor(Qt.PointingHandCursor)
        tweak_header.clicked.connect(lambda: self._toggle_section("tweaks"))
        nav_lay.addWidget(tweak_header)
        self._section_headers = {"tweaks": tweak_header}

        self.tweak_sub = QWidget()
        tweak_sub_lay = QVBoxLayout(self.tweak_sub)
        tweak_sub_lay.setContentsMargins(0, 0, 0, 0)
        tweak_sub_lay.setSpacing(1)
        btn = self._nav_button(f"{ICONS['tweaks']}   Tweaks")
        btn.clicked.connect(lambda _=False: self.navigate("tweaks"))
        tweak_sub_lay.addWidget(btn)
        self.nav_buttons["tweaks"] = btn
        for cat_key, label in SIDEBAR_TWEAKS:
            sub_btn = self._nav_button(label, "NavSub")
            nav_key = f"tweak:{cat_key}"
            sub_btn.clicked.connect(
                lambda _=False, k=cat_key: self.navigate(f"tweak:{k}"))
            tweak_sub_lay.addWidget(sub_btn)
            self.nav_buttons[nav_key] = sub_btn
        nav_lay.addWidget(self.tweak_sub)
        self._sections = {"tweaks": self.tweak_sub}

        # ---- PROFILES
        sec = QLabel("PROFILES")
        sec.setObjectName("NavSection")
        nav_lay.addWidget(sec)
        btn = self._nav_button(f"{ICONS['profiles']}   Game Profiles")
        btn.clicked.connect(lambda _=False: self.navigate("profiles"))
        nav_lay.addWidget(btn)
        self.nav_buttons["profiles"] = btn

        # ---- TOOLS
        sec = QLabel("TOOLS")
        sec.setObjectName("NavSection")
        nav_lay.addWidget(sec)
        btn = self._nav_button(f"{ICONS['tools']}   Tools")
        btn.clicked.connect(lambda _=False: self.navigate("tools"))
        nav_lay.addWidget(btn)
        self.nav_buttons["tools"] = btn

        # ---- SETTINGS
        sec = QLabel("SYSTEM")
        sec.setObjectName("NavSection")
        nav_lay.addWidget(sec)
        btn = self._nav_button(f"{ICONS['settings']}   Settings")
        btn.clicked.connect(lambda _=False: self.navigate("settings"))
        nav_lay.addWidget(btn)
        self.nav_buttons["settings"] = btn

        nav_lay.addStretch()

        # Pinned Discord identity block card at the foot of the navigation.
        self.sidebar_discord = SidebarDiscordCard(self.ctx)
        nav_lay.addWidget(self.sidebar_discord)

        scroll.setWidget(nav)
        lay.addWidget(scroll, 1)

        if GITHUB_URL and GITHUB_URL != "https://github.com":
            gh = QPushButton(f"{ICONS['flag']}   Open GitHub")
            gh.setObjectName("Ghost")
            gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
            lay.addWidget(gh)

        ver = QLabel(f"v{APP_VERSION} \u00b7 Rex Engine")
        ver.setObjectName("Tag")
        lay.addWidget(ver, alignment=Qt.AlignHCenter)

        return side

    # ---------------- Pages ----------------

    def _register_pages(self):
        self.pages["dashboard"] = DashboardPage(self.ctx, self.navigate)
        self.pages["detect"] = DetectPage(self.ctx)
        self.pages["tweaks"] = TweaksPage(self.ctx)
        self.pages["profiles"] = ComingSoonPage("Game Profiles")
        self.pages["optimize"] = OptimizePage(self.ctx)
        self.pages["tools"] = ToolsPage(self.ctx, self.navigate)
        self.pages["settings"] = SettingsPage(self.ctx, self.navigate)
        self.pages["logs"] = LogsPage()
        for page in self.pages.values():
            self.stack.addWidget(page)

    def navigate(self, key):
        page_key = key
        if key == "tweaks":
            self.pages["tweaks"].select(ALL_KEY)
        elif key.startswith("tweak:"):
            # Sidebar sub-category: show the Tweaks master view pre-filtered.
            self.pages["tweaks"].select(key[len("tweak:"):])
            page_key = "tweaks"
        if page_key not in self.pages:
            return
        self.stack.setCurrentWidget(self.pages[page_key])
        self._mark_active(key)

    def _toggle_section(self, name):
        container = self._sections.get(name)
        if container is None:
            return
        visible = not container.isVisible()
        container.setVisible(visible)
        header = self._section_headers.get(name)
        if header is not None:
            header.setText(f"TWEAKS  {'\u25be' if visible else '\u25b8'}")
        container.update()

    def closeEvent(self, event):
        dashboard = self.pages.get("dashboard")
        if dashboard is not None and dashboard.sampler is not None:
            dashboard.sampler.stop()
            dashboard.sampler.wait(2000)
        if self.goodbye is not None:
            self.goodbye.hide()
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
        for k, btn in self.nav_buttons.items():
            active = (k == key)
            if btn.property("active") != active:
                btn.setProperty("active", "true" if active else "false")
                repolish(btn)
