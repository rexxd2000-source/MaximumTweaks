"""Main application window — new 3-panel layout.

Layout:
  [Sidebar] | [AI Bar] | [Center Pages] | [Actions Panel] | [Telemetry]
"""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from config.app_config import (
    APP_NAME, APP_VERSION, DIRS, GITHUB_REPO, ICONS,
    UPDATE_MANIFEST_URL,
)
from engine import activity
from rexlog import logger
from ui.context import AppContext
from ui.monitor_widgets import RexLogo
from ui.space import SpaceBackground
from ui.widgets import repolish


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


# ── Sidebar definition: (key, label, icon_char) ─────────────────────
SIDEBAR_ITEMS = [
    ("home",         "Home",         "\u2302"),
    ("backups",      "Backups",      "\u2601"),
    ("fixes",        "Fixes",        "\u26cf"),
    ("general",      "General",      "\u2699"),
    ("hardware",     "Hardware",     "\u2699"),
    ("debloat",      "Debloat",      "\u2716"),
    ("network",      "Network",      "\u2637"),
    ("gamemode",     "Game Mode",    "\u2605"),
    ("advanced",     "Advanced",     "\u2699"),
    ("bios",         "BIOS",         "\u2139"),
    ("premium",      "Premium",      "\u2b50"),
    # Separator
    ("_sep2", "", ""),
    ("settings",     "Settings",     "\u2699"),
    ("logs",         "Logs",         "\u2709"),
]


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1400, 900)
        self.setMinimumSize(1100, 700)

        self.ctx = AppContext(self)
        self.pages = {}
        self.nav_buttons = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Deep-space background
        self.space = SpaceBackground(self)
        self.space.setGeometry(self.rect())
        self.space.lower()

        # ── Sidebar (left rail) ──
        self.sidebar = self._build_sidebar()
        root.addWidget(self.sidebar)

        # ── Center + Right area ──
        right_area = QWidget()
        right_lay = QHBoxLayout(right_area)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        # Center: AI bar + pages + actions
        center = QWidget()
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(0)

        # AI Bar
        from ui.panels.ai_bar import AIBar
        self.ai_bar = AIBar()
        self.ai_bar.setContentsMargins(16, 12, 16, 8)
        center_lay.addWidget(self.ai_bar)

        # Pages stack
        self.stack = QStackedWidget()
        self.stack.setContentsMargins(0, 0, 0, 0)
        center_lay.addWidget(self.stack, 1)

        # Actions panel
        from ui.panels.actions_panel import ActionsPanel
        self.actions_panel = ActionsPanel()
        self.actions_panel.setContentsMargins(16, 8, 16, 12)
        center_lay.addWidget(self.actions_panel)

        right_lay.addWidget(center, 1)

        # Right telemetry panel
        from ui.panels.telemetry_panel import TelemetryPanel
        self.telemetry_panel = TelemetryPanel()
        self.telemetry_panel.setContentsMargins(12, 12, 12, 12)
        right_lay.addWidget(self.telemetry_panel)

        root.addWidget(right_area, 1)

        # ── Register pages ──
        self._register_pages()
        self.navigate("home")

        # ── Background systems ──
        self.ctx.start_full_audit()

        from ui.pages.detect import DetectWorker
        self._detect_worker = DetectWorker(self)
        self._detect_worker.done.connect(self._on_detected)
        self._detect_worker.error.connect(
            lambda msg: (logger.warn(f"startup detection: {msg}"),
                         activity.emit("error", f"System scan failed \u2014 {msg}")))
        self._detect_worker.start()
        activity.emit("info", f"{APP_NAME} v{APP_VERSION} started")
        logger.info(f"{APP_NAME} v{APP_VERSION} launched (admin={is_admin()})")

        self._update_worker = None
        self._check_for_update_background()

        # Connect AI bar
        self.ai_bar.prompt_submitted.connect(self._on_ai_prompt)

        # Connect actions panel
        self.actions_panel.action_triggered.connect(self._on_action)

    # ── Detection ──

    def _on_detected(self, profile):
        self.ctx.set_profile(profile)
        ready = sum(1 for e in self.ctx.eval.values() if e["state"] == "ready")
        activity.emit("scan", f"System scan completed \u2014 {ready} tweaks compatible")

    def _check_for_update_background(self):
        if not GITHUB_REPO and not UPDATE_MANIFEST_URL:
            return
        from ui.updater_dialog import FetchWorker
        worker = FetchWorker(self)
        worker.done.connect(self._on_bg_update)
        self._update_worker = worker
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

    # ── AI Bar ──

    def _on_ai_prompt(self, text: str):
        """Route AI prompts to the chat page or handle inline."""
        # Navigate to chat page with the prompt
        if "chat" in self.pages:
            self.navigate("chat")
            # Try to send the message
            chat_page = self.pages["chat"]
            if hasattr(chat_page, "send_message"):
                chat_page.send_message(text)
        else:
            from ui.widgets import toast
            toast("AI Assistant is loading...", "info", self)

    # ── Actions Panel ──

    def _on_action(self, action_title: str):
        """Route action card clicks."""
        action_map = {
            "Create Restore Point": lambda: self.navigate("backups"),
            "Create Backup": lambda: self.navigate("backups"),
            "Quick Optimize": lambda: self.navigate("general"),
            "System Info": lambda: self.navigate("advanced"),
            "Run Fixes": lambda: self.navigate("fixes"),
            "Create Restore Point": lambda: self.navigate("backups"),
            "Backup Registry": lambda: self.navigate("backups"),
            "Restore Backup": lambda: self.navigate("backups"),
            "Run SFC": lambda: self.navigate("fixes"),
            "Run DISM": lambda: self.navigate("fixes"),
            "Windows Update Fix": lambda: self.navigate("fixes"),
            "Disable Telemetry": lambda: self.navigate("general"),
            "Visual Tweaks": lambda: self.navigate("general"),
            "Power Plan": lambda: self.navigate("general"),
            "CPU Optimization": lambda: self.navigate("hardware"),
            "GPU Scheduling": lambda: self.navigate("hardware"),
            "RAM Cleanup": lambda: self.navigate("hardware"),
            "Remove Bloat": lambda: self.navigate("debloat"),
            "App Scan": lambda: self.navigate("debloat"),
            "Service Cleanup": lambda: self.navigate("debloat"),
            "Flush DNS": lambda: self.navigate("network"),
            "TCP Optimization": lambda: self.navigate("network"),
            "DNS Benchmark": lambda: self.navigate("network"),
            "Game Launch": lambda: self.navigate("gamemode"),
            "FPS Boost": lambda: self.navigate("gamemode"),
            "Timer Resolution": lambda: self.navigate("gamemode"),
            "Registry Editor": lambda: self.navigate("advanced"),
            "Group Policy": lambda: self.navigate("advanced"),
            "BCD Edit": lambda: self.navigate("advanced"),
        }
        handler = action_map.get(action_title)
        if handler:
            handler()

    # ── Sidebar ──

    def _nav_button(self, text, obj="Nav"):
        btn = QPushButton(text)
        btn.setObjectName(obj)
        btn.setProperty("active", "false")
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(220)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(1)

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

        # Nav items
        for key, label, icon in SIDEBAR_ITEMS:
            if key.startswith("_sep"):
                sec = QLabel("")
                sec.setObjectName("NavSection")
                nav_lay.addWidget(sec)
                continue

            btn = self._nav_button(f"  {icon}   {label}")
            btn.clicked.connect(lambda _=False, k=key: self.navigate(k))
            nav_lay.addWidget(btn)
            self.nav_buttons[key] = btn

        nav_lay.addStretch()
        scroll.setWidget(nav)
        lay.addWidget(scroll, 1)

        ver = QLabel(f"v{APP_VERSION} \u00b7 Maximum Engine")
        ver.setObjectName("Tag")
        lay.addWidget(ver, alignment=Qt.AlignHCenter)

        return side

    # ── Pages ──

    def _register_pages(self):
        from ui.pages.home import HomePage
        from ui.pages.backups import BackupsPage
        from ui.pages.fixes import FixesPage
        from ui.pages.general import GeneralPage
        from ui.pages.hardware import HardwarePage
        from ui.pages.debloat import DebloatPage
        from ui.pages.network_page import NetworkPage
        from ui.pages.gamemode import GameModePage
        from ui.pages.advanced import AdvancedPage
        from ui.pages.bios import BIOSPage
        from ui.pages.premium import PremiumPage
        from ui.pages.settings import SettingsPage
        from ui.pages.logs import LogsPage
        from ui.pages.chat import ChatPage

        nav = self.navigate
        self.pages["home"] = HomePage(self.ctx, nav)
        self.pages["backups"] = BackupsPage(self.ctx, nav)
        self.pages["fixes"] = FixesPage(self.ctx, nav)
        self.pages["general"] = GeneralPage(self.ctx, nav)
        self.pages["hardware"] = HardwarePage(self.ctx, nav)
        self.pages["debloat"] = DebloatPage(self.ctx)
        self.pages["network"] = NetworkPage(self.ctx, nav)
        self.pages["gamemode"] = GameModePage(self.ctx, nav)
        self.pages["advanced"] = AdvancedPage(self.ctx, nav)
        self.pages["bios"] = BIOSPage(self.ctx, nav)
        self.pages["premium"] = PremiumPage(self.ctx, nav)
        self.pages["settings"] = SettingsPage(self.ctx, nav)
        self.pages["logs"] = LogsPage()
        self.pages["chat"] = ChatPage(self.ctx)

        for page in self.pages.values():
            self.stack.addWidget(page)

    def navigate(self, key):
        if key not in self.pages:
            return
        self.stack.setCurrentWidget(self.pages[key])
        self._mark_active(key)
        self.actions_panel.set_category(key)

    def _mark_active(self, key):
        for k, btn in self.nav_buttons.items():
            active = (k == key)
            if btn.property("active") != active:
                btn.setProperty("active", "true" if active else "false")
                repolish(btn)

    # ── Events ──

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.space.setGeometry(self.rect())

    def closeEvent(self, event):
        # Stop telemetry sampler if active (from old dashboard)
        for page in self.pages.values():
            if hasattr(page, "sampler") and page.sampler is not None:
                page.sampler.stop()
                page.sampler.wait(2000)
        try:
            self.ctx.auditor.shutdown()
        except Exception:  # noqa: BLE001
            pass
        if getattr(self, "_detect_worker", None) is not None:
            self._detect_worker.wait(20000)
        super().closeEvent(event)
