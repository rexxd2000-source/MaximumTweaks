"""Main application window: premium sidebar navigation + stacked pages."""
from __future__ import annotations

import ctypes
import sys

import math

from PySide6.QtCore import (
    QPoint,
    QPointF,
    QRectF,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.app_config import (
    APP_NAME,
    APP_VERSION,
    GITHUB_REPO,
    UPDATE_MANIFEST_URL,
)
from engine import activity
from maxlog import logger
from ui.categories import logo_path
from ui.context import AppContext
from ui.monitor_widgets import AppLogo
from ui.pages.dashboard import DashboardPage
from ui.pages.detect import DetectPage, DetectWorker
from ui.pages.logs import LogsPage
from ui.widgets import NavDot, NavRow, nav_icon_pixmap
from ui.pages.optimize import OptimizePage
from ui.pages.chat import ChatPage
from ui.premium_widgets import ComingSoonPage
from ui.pages.route_coming_soon import RouteComingSoonPage
from ui.pages.route_analyzer import RouteAnalyzerPage
from ui.pages.delay_destroyer import DelayDestroyerPage
from ui.pages.debloat import DebloatPage
from ui.pages.settings import SettingsPage
from ui.pages.tools import ToolsPage
from ui.pages.tweaks import ALL_KEY, TweaksPage
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


class _SidebarBackdrop(QWidget):
    """sidebar-background-fix.html layers: violet glow top-left, cyan glow
    bottom-left, a 28px dot grid faded at both ends (kept a bit lighter than
    the reference 0.5 opacity), and a hairline seam of light on the right
    border."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(parent.rect())
        parent.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() == event.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        # .sb-glow.top — 280px orb, center at (50, 20), rgba(139,107,255,.16)
        g1 = QRadialGradient(QPointF(50, 20), 196)
        g1.setColorAt(0.0, QColor(139, 107, 255, 41))
        g1.setColorAt(1.0, QColor(139, 107, 255, 0))
        p.fillRect(self.rect(), g1)
        # .sb-glow.bottom — 240px orb, center at (60, h-20), cyan .08
        g2 = QRadialGradient(QPointF(60, h - 20), 168)
        g2.setColorAt(0.0, QColor(75, 232, 216, 20))
        g2.setColorAt(1.0, QColor(75, 232, 216, 0))
        p.fillRect(self.rect(), g2)
        # .sb-dots — 28px grid, vertical fade; a bit lighter than reference
        y = 14.0
        while y < h:
            frac = y / max(1, h)
            if frac < 0.18:
                m = frac / 0.18
            elif frac > 0.75:
                m = max(0.0, (1.0 - frac) / 0.25)
            else:
                m = 1.0
            a = int(28 * m)          # reference peaks ~45 — lighter per request
            if a > 3:
                p.setPen(QColor(200, 190, 240, a))
                x = 14.0
                while x < w:
                    p.drawPoint(QPointF(x, y))
                    x += 28.0
            y += 28.0
        # .sb-edge — right-border seam: rgba(150,130,235,.35) 30-70%
        seam = QLinearGradient(0, 0, 0, h)
        seam.setColorAt(0.0, QColor(150, 130, 235, 0))
        seam.setColorAt(0.30, QColor(150, 130, 235, 89))
        seam.setColorAt(0.70, QColor(150, 130, 235, 89))
        seam.setColorAt(1.0, QColor(150, 130, 235, 0))
        p.fillRect(QRectF(w - 1.0, 0, 1.0, h), seam)
        p.end()


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

# ---------------- Sidebar ----------------

    # Category accent colors (matching the color-coded sidebar reference).
    CAT_INK = "#928AAD"
    CAT_FPS = "#3FDC98"
    CAT_SYSTEM = "#6C93FF"
    CAT_INPUT = "#FF6F6F"
    CAT_TOOLS = "#FFB454"
    CAT_DIAG = "#4BE8D8"
    CAT_PROFILES = "#E879C9"
    CAT_META = "#9AA5D1"

    def _cat_color(self, cat):
        return {
            "fps": self.CAT_FPS,
            "system": self.CAT_SYSTEM,
            "input": self.CAT_INPUT,
            "tools": self.CAT_TOOLS,
            "diag": self.CAT_DIAG,
            "profiles": self.CAT_PROFILES,
            "meta": self.CAT_META,
        }[cat]

    def _nav_row(self, label, color, icon_key=None, nav_key=None,
                 target=None, badge=None, line_only=False):
        """Create a NavRow. Icons are pre-colored glossy assets (PNG, bundled),
        each already tinted to its category color; lucide renderer is only a
        fallback in case an asset is missing. line_only=True forces the lucide
        line icon (tinted to this row's category color) — used where the
        glossy asset's baked color doesn't match the section (Diagnostics)."""
        row = NavRow(label)
        pm = QPixmap()
        if icon_key is not None and not line_only:
            path = logo_path(icon_key)
            if path.is_file():
                pm = QPixmap(str(path))
        if pm.isNull() and icon_key is not None:
            pm = nav_icon_pixmap(icon_key, color=color, size=16)
        row.set_icon_pm(pm)
        if badge:
            row.add_badge(badge)
        dest = nav_key if target is None else target
        row.clicked.connect(lambda k=dest: self.navigate(k))
        if nav_key is not None:
            self.nav_buttons[nav_key] = row
        return row

    def _nav_line(self):
        line = QFrame()
        line.setObjectName("NavLine")
        line.setFixedHeight(1)
        return line

    def _nav_header(self, title, cat):
        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 2, 10, 10)
        hl.setSpacing(7)
        dot = NavDot(self._cat_color(cat))
        dot.setObjectName("NavDot")
        hl.addWidget(dot)
        lbl = QLabel(title)
        lbl.setObjectName("NavSectionLabel")
        hl.addWidget(lbl)
        hl.addStretch()
        header.setCursor(Qt.PointingHandCursor)
        return header

    def _add_nav_section(self, parent, title, cat, items, badges=None,
                         line_only=False):
        """Collapsible group: divider, header (colored dot + uppercase label),
        then the item rows. *items* are (nav_key, label, icon_key)."""
        badges = badges or {}
        parent.addSpacing(12)
        parent.addWidget(self._nav_line())
        parent.addSpacing(18)

        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(1)
        for nav_key, label, icon_key in items:
            row = self._nav_row(
                label, self._cat_color(cat), icon_key=icon_key,
                nav_key=nav_key, badge=badges.get(nav_key),
                line_only=line_only)
            cl.addWidget(row)

        header = self._nav_header(title, cat)
        header.mousePressEvent = (
            lambda _e, t=title: self._toggle_section(t))
        parent.addWidget(header)
        parent.addWidget(container)
        self._sections[title] = container
        return container

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(272)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(16, 24, 16, 18)
        lay.setSpacing(0)

        # sidebar-background-fix.html layers: violet glow top + cyan glow
        # bottom + dot grid (kept a touch lighter than the 0.5 reference
        # opacity) + hairline edge seam on the right border.
        self._sb_back = _SidebarBackdrop(side)
        self._sb_back.lower()

        # Scrollable navigation (prevents overflow at small window sizes).
        scroll = QScrollArea()
        self._nav_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        nav = QWidget()
        nav.setMaximumWidth(240)
        nav_lay = QVBoxLayout(nav)
        nav_lay.setContentsMargins(0, 0, 0, 0)
        nav_lay.setSpacing(1)

        self._sections = {}   # title -> container widget

        # ---- Branding ----
        brand = QHBoxLayout()
        brand.setSpacing(12)
        brand.setContentsMargins(8, 6, 8, 22)
        mark = AppLogo(size=38)
        brand.addWidget(mark)
        bbox = QVBoxLayout()
        bbox.setSpacing(2)
        btitle = QLabel(APP_NAME)
        btitle.setObjectName("BrandTitle")
        bbox.addWidget(btitle)
        bsub = QLabel("Performance Suite")
        bsub.setObjectName("BrandSub")
        bbox.addWidget(bsub)
        brand.addLayout(bbox)
        brand.addStretch()
        nav_lay.addLayout(brand)

        # ---- Dashboard ----
        nav_lay.addSpacing(16)
        nav_lay.addWidget(self._nav_row(
            "Dashboard", self.CAT_INK, icon_key="home",
            nav_key="dashboard", target="dashboard"))

        # ---- FPS (collapsible) ----
        self._add_nav_section(nav_lay, "FPS", "fps", [
            ("tweak:cpu", "CPU", "cpu"),
            ("tweak:gpu", "GPU", "gpu"),
            ("tweak:ram", "RAM", "ram"),
            ("tweak:games", "Games", "games"),
            ("tweak:fpsboost", "FPS boost", "fpsboost"),
        ])

        # ---- SYSTEM TWEAKS (collapsible) ----
        self._add_nav_section(nav_lay, "System tweaks", "system", [
            ("tweak:system", "Windows / system", "system"),
            ("tweak:storage", "Storage", "storage"),
            ("tweak:audio", "Audio", "audio"),
            ("tweak:network", "Network", "network"),
            ("qos", "Network QoS", "network"),
        ])

        # ---- INPUT DELAY (collapsible) ----
        self._add_nav_section(nav_lay, "Input delay", "input", [
            ("tweak:keyboard", "Keyboard", "keyboard"),
            ("tweak:mouse", "Mouse", "mouse"),
            ("tweak:input", "Input", "input"),
        ])

        # ---- TOOLS (collapsible) ----
        self._add_nav_section(nav_lay, "Tools", "tools", [
            ("tools", "Tools", "tools"),
            ("controller", "Controller overclock", "controller"),
            ("delay_destroyer", "Delay destroyer", "delay_destroyer"),
            ("debloat", "Smart debloater", "debloat"),
            ("route_analyzer", "Route analyzer", "route_analyzer"),
        ], badges={"route_analyzer": "SOON"})

        # ---- DIAGNOSTICS: one entry; every test/scan lives on the page ----
        nav_lay.addSpacing(12)
        nav_lay.addWidget(self._nav_line())
        nav_lay.addSpacing(18)
        nav_lay.addWidget(self._nav_row(
            "Diagnostics", self.CAT_DIAG, icon_key="route_analyzer",
            nav_key="diagnostics", target="diagnostics"))

        # ---- PROFILES (collapsible) ----
        self._add_nav_section(nav_lay, "Profiles", "profiles", [
            ("profiles", "Game profiles", "profiles"),
            ("tweak:fortnite", "Fortnite settings", "fortnite"),
            ("chat", "AI assistant", "chat"),
        ])

        # ---- SYSTEM (collapsible) ----
        self._add_nav_section(nav_lay, "System", "meta", [
            ("settings", "Settings", "settings"),
        ])

        nav_lay.addStretch()

        scroll.setWidget(nav)
        lay.addWidget(scroll, 1)

        # ---- Footer ----
        lay.addSpacing(10)
        lay.addWidget(self._nav_line())
        foot = QHBoxLayout()
        foot.setContentsMargins(12, 14, 12, 4)
        foot.setSpacing(0)
        ver = QLabel(f"v{APP_VERSION} \u00b7 Maximum Engine")
        ver.setObjectName("Tag")
        foot.addWidget(ver)
        foot.addStretch()
        plan = QLabel("PRO")
        plan.setObjectName("PlanPill")
        foot.addWidget(plan)
        lay.addLayout(foot)

        return side

    # ---- Collapsible sidebar helpers ----

    def _toggle_section(self, title):
        container = self._sections.get(title)
        if container is None:
            return
        container.setVisible(not container.isVisible())

    # ---------------- Pages ----------------

    def _register_pages(self):
        self.pages["dashboard"] = DashboardPage(self.ctx, self.navigate)
        self.pages["detect"] = DetectPage(self.ctx)
        self.pages["tweaks"] = TweaksPage(self.ctx)
        from ui.pages.profiles import ProfilesPage
        self.pages["profiles"] = ProfilesPage(self.ctx)
        self.pages["optimize"] = OptimizePage(self.ctx)
        self.pages["tools"] = ToolsPage(self.ctx, self.navigate)
        self.pages["chat"] = ChatPage(self.ctx)
        self.pages["delay_destroyer"] = DelayDestroyerPage(self.ctx)
        self.pages["debloat"] = DebloatPage(self.ctx)
        from ui.pages.controller import ControllerPage
        self.pages["controller"] = ControllerPage(self.ctx)
        from ui.pages.qos import QosPage
        self.pages["qos"] = QosPage(self.ctx)
        from ui.pages.diagnostics import DiagnosticsPage
        self.pages["diagnostics"] = DiagnosticsPage(self.ctx)
        self.pages["route_analyzer"] = RouteComingSoonPage(self.ctx, self.navigate)
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
        elif key.startswith("diagnostics:"):
            # Sidebar test: open Diagnostics and pulse the matching card.
            self.pages["diagnostics"].focus_card(key.split(":", 1)[1])
            page_key = "diagnostics"
        if page_key not in self.pages:
            return
        self.stack.setCurrentWidget(self.pages[page_key])
        self._mark_active(key)

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
        active = None
        for k, row in self.nav_buttons.items():
            on = (k == key)
            row.set_active(on)
            if on:
                active = row
        # keep the clicked row visible in the scrollable nav
        if active is not None:
            sb = self._nav_scroll.verticalScrollBar()
            y = active.mapTo(self._nav_scroll.widget(), QPoint(0, 0)).y()
            vh = self._nav_scroll.viewport().height()
            if y < sb.value() or y + active.height() > sb.value() + vh:
                sb.setValue(max(0, y - vh // 2))
