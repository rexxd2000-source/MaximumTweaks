"""Main application window: premium sidebar navigation + stacked pages."""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import (
    QSize,
    Qt,
)
from PySide6.QtGui import QIcon
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
    ICONS,
    UPDATE_MANIFEST_URL,
)
from engine import activity
from rexlog import logger
from ui.categories import SIDEBAR_TWEAKS, logo_path
from ui.context import AppContext
from ui.license import SidebarLicenseCard
from ui.pages.dashboard import DashboardPage
from ui.pages.detect import DetectPage, DetectWorker
from ui.pages.logs import LogsPage
from ui.pages.optimize import OptimizePage
from ui.pages.chat import ChatPage
from ui.premium_widgets import ComingSoonPage
from ui.pages.settings import SettingsPage
from ui.pages.tools import ToolsPage
from ui.pages.tweaks import ALL_KEY, TweaksPage
from ui.monitor_widgets import RexLogo
from ui.space import SpaceBackground
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
        self.resize(1320, 900)
        self.setMinimumSize(1100, 700)

        self.ctx = AppContext(self)
        self.pages = {}
        self.nav_buttons = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Deep-space ambient background (glow orbs + stars) behind the pages.
        self.space = SpaceBackground(self)
        self.space.setGeometry(self.rect())
        self.space.lower()

        self.sidebar = self._build_sidebar()
        root.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._register_pages()
        self.navigate("dashboard")

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

    def _show_license_gate(self):
        """Re-open the license gate (e.g. the sidebar Activate button)."""
        from ui.gate import GateWindow
        gate = GateWindow()
        gate.setGeometry(self.frameGeometry())
        gate.show()

        def unlock(_session):
            gate.fade_out(600)
        gate.unlocked.connect(unlock)


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
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(1)

        # Scrollable navigation (prevents overflow at small window sizes).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        nav = QWidget()
        nav_lay = QVBoxLayout(nav)
        nav_lay.setContentsMargins(0, 0, 0, 0)
        nav_lay.setSpacing(1)

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
            logo = logo_path(cat_key)
            if logo.is_file():
                sub_btn.setIcon(QIcon(str(logo)))
                sub_btn.setIconSize(QSize(15, 15))
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

        # ---- AI ASSISTANT
        btn = self._nav_button("\u2728   AI Assistant")
        btn.clicked.connect(lambda _=False: self.navigate("chat"))
        nav_lay.addWidget(btn)
        self.nav_buttons["chat"] = btn

        # ---- SETTINGS
        sec = QLabel("SYSTEM")
        sec.setObjectName("NavSection")
        nav_lay.addWidget(sec)
        btn = self._nav_button(f"{ICONS['settings']}   Settings")
        btn.clicked.connect(lambda _=False: self.navigate("settings"))
        nav_lay.addWidget(btn)
        self.nav_buttons["settings"] = btn

        nav_lay.addStretch()

        scroll.setWidget(nav)
        lay.addWidget(scroll, 1)

        # License status block pinned below the nav (outside the scroll area)
        # so its rounded corners are never clipped by the sidebar viewport.
        self.sidebar_license = SidebarLicenseCard(self.ctx)
        self.sidebar_license.activate_requested.connect(self._show_license_gate)
        lay.addWidget(self.sidebar_license)

        ver = QLabel(f"v{APP_VERSION} \u00b7 Maximum Engine")
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
        self.pages["chat"] = ChatPage(self.ctx)
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.space.setGeometry(self.rect())

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
        for k, btn in self.nav_buttons.items():
            active = (k == key)
            if btn.property("active") != active:
                btn.setProperty("active", "true" if active else "false")
                repolish(btn)
