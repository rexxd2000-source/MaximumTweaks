"""Tweaks page: single clean view of all tweak categories.

Top down:
  * Page header (title + subtitle, reflects the active category)
  * Toolbar  - search field, sort dropdown, live "X/Y APPLIED" counter,
               Apply All (primary), Revert All (secondary)
  * Responsive toggle-card grid + pagination

Category switching is driven entirely by the left sidebar (no pill bar).
The page drives its own apply/revert batches (background worker + toast), so
cards flip instantly and the UI never blocks.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpacerItem,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from database import BY_ID
from engine import state as state_mgr
from ui.categories import (
    ALL_TWEAK_KEYS,
    CATEGORY_GROUPS,
    cpu_filter_tweaks,
    gpu_filter_tweaks,
    group_tweaks,
    recommended_count,
)
from ui.widgets import (
    BatchWorker,
    GuideDialog,
    TweakCard,
    clear_layout,
    toast,
)

PAGER_H = 46

SORT_MODES = [
    ("recommended", "Recommended first"),
    ("impact", "Impact: High \u2192 Low"),
    ("risk", "Risk: Safe first"),
    ("name", "Name A\u2013Z"),
]
IMPACT_RANK = {"extreme": 6, "high": 5, "moderate": 4, "low": 3, "very low": 2}
RISK_RANK = {"safe": 0, "low": 1, "moderate": 2, "advanced": 3}
REC_RANK = {
    "recommended": 0, "optional": 1, "experimental": 2,
    "advanced": 3, "guide": 4, "not_recommended": 5,
}

# mouse-tweaks-panel.html palette + button styles (translated to QSS).
_P = {
    "surface": "#0c0c15",
    "chip": "#101019",
    "line": "rgba(255,255,255,0.08)",
    "line_soft": "rgba(255,255,255,0.05)",
    "text": "#f2f1f7",
    "text_dim": "#8b8a99",
    "text_dim2": "#5f5e6b",
    "purple": "#7c6df0",
    "purple_2": "#9d8cff",
    "green": "#4ade80",
}
_CAT_GHOST = (
    "QPushButton{{background:transparent;border:none;border-radius:0;"
    "padding:9px 14px;color:{text_dim};font-size:12.5px;font-weight:600;}}"
    "QPushButton:hover:enabled{{color:{text};}}"
)
_CAT_PRIMARY = (
    "QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
    "stop:0 {purple_2}, stop:1 {purple});border:none;border-radius:0;"
    "color:#ffffff;padding:9px 16px;font-size:12.5px;font-weight:600;}}"
    "QPushButton:hover:enabled{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
    "stop:0 #b4a3ff, stop:1 #8b7cf6);}}"
)
_CAT_BTN = (
    "QPushButton{{background:{chip};border:1px solid {line};border-radius:0;"
    "color:{text_dim};padding:9px 16px;font-size:12.5px;font-weight:600;}}"
    "QPushButton:hover:enabled{{color:{text};"
    "border-color:rgba(255,255,255,0.22);}}"
)
_PNP_CACHE: dict = {}

ALL_KEY = "__all__"

# Page-header titles per sidebar category (fall back to CATEGORY_GROUPS).
HEADER_TITLES = {
    "cpu": "CPU Tweaks",
    "gpu": "GPU Optimizations",
    "ram": "RAM Tweaks",
    "input": "Pointer & Input Tweaks",
    "mouse": "Mouse Tweaks",
    "keyboard": "Keyboard Tweaks",
    "network": "Network Tweaks",
    "storage": "Storage / SSD Tweaks",
    "system": "Windows / System",
    "performance": "Performance Tweaks",
    "fortnite": "Fortnite Tweaks",
    "games": "Game Tweaks",
    "laptop": "Laptop Tweaks",
    "power": "Power Tweaks",
}

HEADER_ICONS = {
    "cpu": "\u2b22",
    "gpu": "\u25c6",
    "ram": "\u2588",
    "input": "\u2694",
    "mouse": "\u21a8",
    "keyboard": "\u2328",
    "network": "\u2637",
    "storage": "\u25b6",
    "system": "\u2699",
    "performance": "\u26a1",
    "fortnite": "\u25c9",
    "games": "\u2605",
    "laptop": "\u25c8",
    "power": "\u26a1",
}


class TweaksPage(QWidget):
    """All tweaks in one place — sidebar-driven, searchable, sortable."""

    MIN_CARD_W = 240
    MAX_COLS = 6
    GAP = 14

    def __init__(self, ctx, parent=None, fixed_group=None):
        super().__init__(parent)
        self.ctx = ctx
        self.fixed_group = fixed_group
        self.key = fixed_group or ALL_KEY
        self.page = 1
        self._pages = 1
        self._filtered: list[dict] = []
        self._cards: dict[str, TweakCard] = {}
        self._busy = False
        self._worker = None
        self._relayout_pending = False
        self._in_flight: set[str] = set()
        self._batch_ids: list[str] = []
        self._batch_mode = "apply"
        self._gpu_selected_vendor: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Scrollable content (header + toolbar + card grid) fills the page and
        # scrolls internally; the pager is pinned below it so it is never
        # clipped off the bottom of the window.
        # Background: reference .main atmosphere (blobs + masked dot grid),
        # fixed behind the scrolling content.
        self._atmo = _TweakAtmosphere(self)
        self._atmo.setGeometry(0, 0, 10, 10)
        self._atmo.lower()

        self.scroll = QScrollArea(self)
        scroll = self.scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea>QWidget>QWidget{background:transparent;}")

        wrapper = QWidget()
        wrapper.setObjectName("category-view-wrapper")
        # NOTE: scope with #objectName — a bare "background:transparent" on
        # an ancestor cascades to ALL children and overrides app-level
        # QPushButton#Primary fills (button would render unfilled).
        wrapper.setStyleSheet(
            "#category-view-wrapper{background:transparent;}")
        root = QVBoxLayout(wrapper)
        root.setContentsMargins(20, 40, 20, 40)
        root.setSpacing(0)

        # ---- Card grid (expands to fill the viewport so no raw page
        # background ever shows around the cards; the last row stretches)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("tweaks-grid")
        self.grid_host.installEventFilter(self)
        self.grid_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(self.GAP)

        if fixed_group:
            root.addWidget(self.grid_host, 1)
        else:
            # -------- full-width .panel (fills the viewport) --------
            center = QHBoxLayout()
            center.setContentsMargins(0, 0, 0, 0)
            center.setSpacing(0)
            self.panel = QFrame()
            self.panel.setObjectName("TweakPanel")
            self.panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.panel.setStyleSheet(
                f"#TweakPanel{{ background:{_P['surface']};"
                f" border:1px solid {_P['line']}; border-radius:0px; }}")
            pl = QVBoxLayout(self.panel)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.setSpacing(0)

            self._build_panel_head(pl)
            self._build_panel_search(pl)
            self.opt_host = self._build_panel_toolbar(pl)
            pl.addWidget(self.panel_facts)
            self.ram_selector = self._build_ram_selector()
            pl.addWidget(self.ram_selector)
            self.gpu_selector = self._build_gpu_selector()
            pl.addWidget(self.gpu_selector)
            pl.addSpacing(16)
            pl.addWidget(self.grid_host, 1)

            center.addWidget(self.panel, 1)
            root.addLayout(center, 1)

        outer.addWidget(scroll, 1)
        scroll.setWidget(wrapper)

        # ---- Pager: fixed bar below the scroll area (always visible)
        self.pager = QWidget()
        self.pager.setObjectName("PageBar")
        self.pager.setFixedHeight(PAGER_H)
        self.pager.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.pager_lay = QHBoxLayout(self.pager)
        self.pager_lay.setContentsMargins(10, 0, 10, 0)
        self.pager_lay.setSpacing(6)
        self.pager_lay.setAlignment(Qt.AlignLeft)
        outer.addWidget(self.pager)

        self.ctx.state_changed.connect(self.refresh)
        self.ctx.live_state_changed.connect(self._on_live_state)
        QTimer.singleShot(0, self.refresh)

    # ---------------- Panel head (reference .p-head) ----------------

    def _build_panel_head(self, pl):
        # Reference .p-head: h1 + subtitle left, .stat-pill right, separated
        # by a 1px bottom border. No icon tile, no pills — pure typography.
        head = QFrame()
        head.setObjectName("PanelHead")
        head.setStyleSheet(
            f"#PanelHead{{background:transparent;"
            f" border-bottom:1px solid {_P['line']};}}")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(28, 26, 28, 22)
        hl.setSpacing(20)
        hl.setAlignment(Qt.AlignTop)

        box = QVBoxLayout()
        box.setSpacing(6)
        self.title_lbl = QLabel("Optimize Your PC")
        self.title_lbl.setStyleSheet(
            "font-family: 'Space Grotesk', 'Segoe UI'; font-size: 24px;"
            f" font-weight: 700; color: {_P['text']};"
            " letter-spacing: -0.01em; background: transparent;")
        self.blurb_lbl = QLabel(
            "Toggle the optimizations you want \u2014 tweaks are pre-checked for "
            "your hardware, and each flips instantly.")
        self.blurb_lbl.setStyleSheet(
            f"font-size: 13.5px; color: {_P['text_dim']}; background: transparent;")
        self.blurb_lbl.setWordWrap(True)
        box.addWidget(self.title_lbl)
        box.addWidget(self.blurb_lbl)
        hl.addLayout(box, 1)

        # Reference .stat-pill: two mono stats side by side, 1px divider.
        pill = QFrame()
        pill.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        pill.setStyleSheet(
            f"QFrame{{background:{_P['chip']}; border:1px solid {_P['line']};}}")
        ppl = QHBoxLayout(pill)
        ppl.setContentsMargins(16, 9, 16, 9)
        ppl.setSpacing(14)
        mono = ("font-family: 'JetBrains Mono', monospace; font-size: 11.5px;"
                " background: transparent;")
        self.stat_rec = QLabel()
        self.stat_rec.setStyleSheet(mono)
        self.stat_cat = QLabel()
        self.stat_cat.setStyleSheet(mono)
        ppl.addWidget(self.stat_rec)
        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setFixedHeight(14)
        divider.setStyleSheet(
            f"background: {_P['line']}; border: none;")
        ppl.addWidget(divider)
        ppl.addWidget(self.stat_cat)
        hl.addWidget(pill, 0, Qt.AlignTop)

        self.panel_head = head
        pl.addWidget(head)
        return head

    @staticmethod
    def _dot_stat(color: str, number, label: str) -> str:
        return (f"<span style='color:{color};'>\u25cf</span>"
                f"<span style='color:{_P['text']};font-weight:600;'>&nbsp;{number}</span>"
                f"<span style='color:{_P['text_dim']}'>&nbsp;{label}</span>")

    def _header_for(self, key) -> tuple[str, str]:
        if key == ALL_KEY:
            return ("Optimize Your PC",
                    "Toggle the optimizations you want \u2014 tweaks are pre-checked "
                    "for your hardware, and each flips instantly.")

        meta = CATEGORY_GROUPS.get(key)
        if meta:
            return (HEADER_TITLES.get(key, meta["title"]), meta["blurb"])
        return (HEADER_TITLES.get(key, "Tweaks"), "")

    def _update_header(self):
        if not hasattr(self, "title_lbl"):
            return
        title, blurb = self._header_for(self.key)
        self.title_lbl.setText(title)
        self.blurb_lbl.setText(blurb)
        self.title_lbl.setToolTip(title)
        # .top-stats (recommended / catalogued) for the active view.
        src = self._source_tweaks() if hasattr(self, "_source_tweaks") else []
        try:
            rec = recommended_count(src)
            cat = len(src)
        except Exception:
            rec = cat = 0
        if hasattr(self, "stat_rec"):
            self.stat_rec.setText(
                self._dot_stat("#4ade80", rec, "recommended"))
            self.stat_cat.setText(
                self._dot_stat("#5f5e6b", cat, "catalogued"))
            self.stat_rec.setVisible(True)
            self.stat_cat.setVisible(True)

    # ---------------- Panel search row (reference .p-search) ----------------

    def _build_panel_search(self, pl):
        # Reference .search-row: search box (flex) + sort pill side by side,
        # separated from the head by a 1px bottom border.
        bar = QWidget()
        bar.setObjectName("PanelSearch")
        bar.setStyleSheet(
            f"#PanelSearch{{background:transparent;"
            f" border-bottom:1px solid {_P['line']};}}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(28, 18, 28, 18)
        lay.setSpacing(10)

        self.search_box = QFrame()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setStyleSheet(
            f"QFrame#SearchBox{{background:{_P['chip']};"
            f" border:1px solid {_P['line']};}}")
        sl = QHBoxLayout(self.search_box)
        sl.setContentsMargins(14, 11, 14, 11)
        sl.setSpacing(10)
        icon = QLabel("\u2315")
        icon.setStyleSheet(
            f"color: {_P['text_dim2']}; font-size: 15px; background: transparent;")
        sl.addWidget(icon)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search tweaks\u2026")
        self.search.setClearButtonEnabled(True)
        self.search.setStyleSheet(
            f"QLineEdit{{background:transparent;border:none;"
            f" font-size:13.5px;color:{_P['text']};}}"
            f"QLineEdit::placeholder{{color:{_P['text_dim2']};}}")
        self.search.textChanged.connect(lambda _: self._on_filters())
        self.search.installEventFilter(self)
        sl.addWidget(self.search, 1)
        lay.addWidget(self.search_box, 1)

        self.sort_combo = QComboBox()
        for key, label in SORT_MODES:
            self.sort_combo.addItem(label, key)
        self.sort_combo.setFixedWidth(220)
        self.sort_combo.setCursor(Qt.PointingHandCursor)
        self.sort_combo.setStyleSheet(
            f"QComboBox {{ background: {_P['chip']};"
            f" border: 1px solid {_P['line']}; color: {_P['text_dim']};"
            " font-size: 12.5px; font-weight: 500; padding: 0 12px;"
            " border-radius: 0; }}"
            f"QComboBox:hover {{ border-color: rgba(124,109,240,0.4);"
            f" color: {_P['text']}; }}"
            "QComboBox::drop-down { border: none; width: 28px; }"
            "QComboBox::down-arrow {"
            f" border-left: 4px solid transparent; border-right: 4px solid transparent;"
            f" border-top: 5px solid {_P['text_dim2']}; margin-right: 12px; }}"
            f"QComboBox QAbstractItemView {{ background: {_P['chip']};"
            f" border: 1px solid {_P['line']}; color: {_P['text']};"
            " selection-background-color: #7c6df0; selection-color: #ffffff;"
            " padding: 4px; }}")
        self.sort_combo.currentIndexChanged.connect(lambda _: self._on_filters())
        lay.addWidget(self.sort_combo)

        self.panel_search = bar
        pl.addWidget(bar)
        return bar

    # ---------------- Panel toolbar (reference .p-toolbar) ----------------

    def _build_panel_toolbar(self, pl):
        # Reference .action-row: left = ghost Scan + primary Optimize + device
        # badge, right = mono progress text + glass Apply all / ghost Revert all.
        host = QWidget()
        host.setObjectName("PanelToolbar")
        host.setStyleSheet("#PanelToolbar{background:transparent;}")
        self.panel_toolbar = host
        row = QHBoxLayout(host)
        row.setContentsMargins(28, 18, 28, 18)
        row.setSpacing(18)

        self.opt_left = QWidget()
        self.opt_left.setStyleSheet("background:transparent;")
        self.opt_lay = QHBoxLayout(self.opt_left)
        self.opt_lay.setContentsMargins(0, 0, 0, 0)
        self.opt_lay.setSpacing(10)
        row.addWidget(self.opt_left)

        # Device badge (HID / USB / Bluetooth...) — a sibling of the left
        # cluster (NOT inside opt_lay: clear_layout() would delete it while
        # rebuilding the Scan/Optimize buttons). Shown/hidden by
        # _update_optimizer_bar when the active category has a device.
        self.device_badge = QLabel("")
        self.device_badge.setStyleSheet(
            f"background: {_P['chip']}; border: 1px solid {_P['line_soft']};"
            " padding: 8px 12px; font-family: 'JetBrains Mono', monospace;"
            f" font-size: 11px; color: {_P['text_dim']};")
        self.device_badge.setVisible(False)
        row.addWidget(self.device_badge)

        # Reference .toolbar-right: progress-txt, bordered Apply all, ghost
        # Revert all (gap 16px).
        self._right_cluster = QHBoxLayout()
        self._right_cluster.setSpacing(16)
        self.counter_lbl = QLabel()
        self.counter_lbl.setStyleSheet(
            "font-family: 'JetBrains Mono', monospace;"
            f" font-size: 12px; color: {_P['text_dim']}; background: transparent;")
        self._right_cluster.addWidget(self.counter_lbl)

        self.btn_apply_all = QPushButton("Apply all")
        self.btn_apply_all.setStyleSheet(_CAT_BTN.format(**_P))
        self.btn_apply_all.setCursor(Qt.PointingHandCursor)
        self.btn_apply_all.clicked.connect(self._apply_all)
        self._apply_all_text = "Apply all"
        self._right_cluster.addWidget(self.btn_apply_all)

        self.btn_revert_all = QPushButton("Revert all")
        self.btn_revert_all.setStyleSheet(_CAT_GHOST.format(**_P))
        self.btn_revert_all.setCursor(Qt.PointingHandCursor)
        self.btn_revert_all.clicked.connect(self._revert_all)
        self._right_cluster.addWidget(self.btn_revert_all)

        cluster_wrap = QWidget()
        cluster_wrap.setLayout(self._right_cluster)
        cluster_wrap.setStyleSheet("background:transparent;")
        row.addWidget(cluster_wrap)
        row.addStretch(1)

        # Facts strip: live hardware detection facts for the active category.
        # Collapsed until a scan produces content (added to the panel layout
        # directly after this toolbar row).
        self.panel_facts = QFrame()
        self.panel_facts.setStyleSheet(
            f"QFrame {{ background: {_P['chip']}; border: 1px solid {_P['line']}; }}"
            " QLabel { background: transparent; }")
        fl = QHBoxLayout(self.panel_facts)
        fl.setContentsMargins(28, 7, 28, 7)
        fl.setSpacing(0)
        self.opt_facts = QLabel()
        self.opt_facts.setStyleSheet(
            "font-family: 'JetBrains Mono', monospace;"
            f" font-size: 11px; color: {_P['text_dim']}; background: transparent;")
        self.opt_facts.setWordWrap(True)
        fl.addWidget(self.opt_facts)
        self.panel_facts.setVisible(False)

        self._facts_cache: dict = {}
        self._scan_worker = None
        pl.addWidget(host)
        return host

    def _build_ram_selector(self):
        import ui.pages.ram_selector as ram_mod
        from ui.pages.ram_selector import RAM_TIERS, RamTierCard
        host = QWidget()
        host.setObjectName("ram-selector-bar")
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # ---- module strip: Scan / Optimize RAM + live specs ----
        strip = QWidget()
        striple = QHBoxLayout(strip)
        striple.setContentsMargins(0, 0, 0, 0)
        striple.setSpacing(10)

        # Clear hierarchy: Optimize RAM is the primary action (filled), Scan
        # is a quiet secondary (ghost) — same height so they read as one unit.
        self.ram_scan_btn = QPushButton("Scan")
        self.ram_scan_btn.setObjectName("Ghost")
        self.ram_scan_btn.setMinimumHeight(32)
        self.ram_scan_btn.setCursor(Qt.PointingHandCursor)
        self.ram_scan_btn.setToolTip("Re-detect this system's installed memory.")
        self.ram_scan_btn.clicked.connect(lambda: self._scan_group(self.key))
        striple.addWidget(self.ram_scan_btn)

        self.ram_opt_btn = QPushButton("Optimize RAM")
        self.ram_opt_btn.setObjectName("Primary")
        self.ram_opt_btn.setMinimumHeight(32)
        self.ram_opt_btn.setCursor(Qt.PointingHandCursor)
        self.ram_opt_btn.setToolTip(
            "Scan, validate and apply the recommended RAM tweaks for this "
            "category \u2014 every change is verified against the live system.")
        self.ram_opt_btn.clicked.connect(
            lambda _=False: self._open_optimizer_group(self.key))
        striple.addWidget(self.ram_opt_btn)

        striple.addSpacing(8)

        # live specs grouped in one subtle card, divided so they scan at a
        # glance instead of running together.
        specs_card = QFrame()
        specs_card.setObjectName("ram-specs")
        specs_card.setStyleSheet(
            "QFrame#ram-specs { background: rgba(255,255,255,0.032); "
            "border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; }")
        sl = QHBoxLayout(specs_card)
        sl.setContentsMargins(16, 7, 16, 7)
        sl.setSpacing(14)
        self._ram_specs = {}
        for i, label in enumerate(("Total", "Modules", "Speed", "Configured")):
            if i:
                vd = QFrame()
                vd.setFixedWidth(1)
                vd.setStyleSheet(
                    "background: rgba(255,255,255,0.07); border: none;")
                sl.addWidget(vd)
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(2)
            cap = QLabel(label)
            cap.setStyleSheet(
                "font-size: 9.5px; font-weight: 700; letter-spacing: 1.2px; "
                "color: #575C6B; background: transparent;")
            bl.addWidget(cap)
            val = QLabel("\u2014")
            val.setStyleSheet(
                "font-family: 'JetBrains Mono', monospace; "
                "font-size: 14px; font-weight: 700; color: #EFF0F4; "
                "background: transparent;")
            bl.addWidget(val)
            self._ram_specs[label] = val
            sl.addWidget(box)
        striple.addWidget(specs_card)
        striple.addStretch()
        lay.addWidget(strip)

        # ---- section label (breathes equally from the strip above and the
        # grid below: 12px each way) ----
        lay.addSpacing(12)
        section = QLabel("Select your installed RAM size")
        section.setStyleSheet(
            "font-size: 17px; font-weight: 700; color: #EDEEF2;"
            " background: transparent;")
        lay.addWidget(section)
        lay.addSpacing(12)

        # ---- tier grid ----
        self._ram_rec_key = ram_mod.recommended_ram_key(self.ctx.profile)
        profile = self.ctx.profile or {}
        gb = profile.get("ram_gb") or 0
        channels = max(1, profile.get("ram_channels") or 1)
        per_module = gb / channels if gb else 0
        grid = QGridLayout()
        grid.setSpacing(10)
        self._ram_cards = {}
        for i, (key, tier) in enumerate(RAM_TIERS.items()):
            sub = ram_mod.TIER_SUB.get(key)
            if key == self._ram_rec_key and gb:
                sub = f"Matches your installed {gb:g} GB pair"
            card = RamTierCard(
                key, tier, self.ctx,
                recommended=(key == self._ram_rec_key),
                sub=sub,
                bar_pct=ram_mod.TIER_BAR_PCT.get(key))
            card._on_click = lambda k, c=card: self._on_ram_tier_clicked(k, manual=True)
            grid.addWidget(card, i // 3, i % 3)
            self._ram_cards[key] = card
        lay.addLayout(grid)

        # ---- foot note: confirmation strip (high contrast, can't be missed)
        self._ram_status_box = QFrame()
        self._ram_status_box.setObjectName("ram-status")
        self._ram_status_box.setStyleSheet(
            "QFrame#ram-status { background: rgba(139,124,246,0.10); "
            "border: 1px solid rgba(139,124,246,0.28); "
            "border-radius: 10px; }")
        sbl = QVBoxLayout(self._ram_status_box)
        sbl.setContentsMargins(14, 10, 14, 10)
        self._ram_status = QLabel()
        self._ram_status.setObjectName("PageSub")
        self._ram_status.setWordWrap(True)
        self._ram_status.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #E7E3F8; "
            "background: transparent;")
        self._ram_status.setText(
            "Select the RAM tier that matches your installed memory \u2014 "
            "its recommended tweaks are pre-checked below.")
        sbl.addWidget(self._ram_status)
        lay.addSpacing(12)
        lay.addWidget(self._ram_status_box)

        self._ram_selected_tier = None
        self._ram_auto_selected = False
        self._ram_user_picked = False
        self._update_ram_specs()
        self.ctx.profile_changed.connect(self._update_ram_specs)
        host.setVisible(False)
        return host

    def _update_ram_specs(self):
        import ui.pages.ram_selector as ram_mod
        profile = self.ctx.profile or {}
        gb = profile.get("ram_gb") or 0
        channels = max(1, profile.get("ram_channels") or 1)
        mtps = profile.get("ram_mtps") or 0
        per_module = gb / channels if gb else 0
        module_gb = round(per_module) if per_module else 0
        self._ram_specs["Total"].setText(f"{gb:g} GB")
        self._ram_specs["Modules"].setText(f"{channels} \u00d7 {module_gb}.0 GB")
        self._ram_specs["Speed"].setText(f"{mtps:g} MT/s")
        self._ram_specs["Configured"].setText(f"{mtps:g} MT/s")
        self._ram_rec_key = ram_mod.recommended_ram_key(profile)
        for key, card in self._ram_cards.items():
            if gb and key == self._ram_rec_key:
                card.set_recommended(True, f"Matches your installed {gb:g} GB pair")
            else:
                card.set_recommended(False, ram_mod.TIER_SUB.get(key, ""))
        if gb and not self._ram_user_picked and not self._ram_auto_selected:
            self._ram_auto_select()

    def _ram_auto_select(self):
        if self._ram_auto_selected or not self._ram_cards:
            return
        self._ram_auto_selected = True
        self._on_ram_tier_clicked(self._ram_rec_key, manual=False)

    def _on_ram_tier_clicked(self, key, manual=False):
        from ui.pages.ram_selector import RAM_TIERS
        if manual:
            self._ram_user_picked = True
        self._ram_selected_tier = key
        for k, card in self._ram_cards.items():
            card.set_selected(k == key)
        tier = RAM_TIERS[key]
        self._ram_status.setText(
            f"\u2713  <span style='color:#C9C0FF;'><b>{tier['label']} "
            f"({tier['desc']})</b></span> selected \u2014 "
            f"{len(tier['tweaks'])} recommended tweaks are checked below; "
            f"adjust any of them, then click Apply All.")
        for tid in tier["tweaks"]:
            if tid in self._cards:
                self._cards[tid].toggle.setChecked(True)

    def _build_gpu_selector(self):
        from config.app_config import THEME as T
        host = QWidget()
        host.setObjectName("gpu-selector-bar")
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        prompt = QLabel("Select your GPU")
        prompt.setStyleSheet(
            "font-size: 18px; font-weight: 700; color: #F6F4FC;"
            " background: transparent;")
        prompt.setAlignment(Qt.AlignCenter)
        lay.addWidget(prompt)

        sub = QLabel("Choose your GPU vendor to see only the optimizations "
                     "that apply to your hardware.")
        sub.setObjectName("PageSub")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addSpacing(4)

        grid = QGridLayout()
        grid.setSpacing(12)
        self._gpu_cards = {}
        gpu_vendors = [
            ("nvidia", "NVIDIA", "GeForce RTX / GTX", "Reflex, Low Latency Mode, PowerMizer, persistence, telemetry", "#76B900"),
            ("amd", "AMD", "Radeon RX", "Anti-Lag, FreeSync, SAM, shader cache, tessellation", "#ED1C24"),
            ("integrated", "Integrated", "Intel UHD / Arc", "ReBAR, XeSS, VSync, Speed Shift, Turbo Boost", "#0071C5"),
        ]
        for i, (key, label, sublabel, features, color) in enumerate(gpu_vendors):
            card = QFrame()
            card.setObjectName("GpuVendorCard")
            card.setCursor(Qt.PointingHandCursor)
            card.setFixedHeight(100)
            card.setStyleSheet(
                f"QFrame#GpuVendorCard {{ border: 2px solid {T['border']}; "
                f"border-radius: 14px; background: {T['card']}; padding: 4px; }}"
                f"QFrame#GpuVendorCard:hover {{ border: 2px solid {color}; }}")
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(18, 14, 18, 14)
            card_lay.setSpacing(4)
            top = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {color};")
            top.addWidget(lbl)
            top.addStretch()
            card_lay.addLayout(top)
            sub_lbl = QLabel(sublabel)
            sub_lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 12px; font-weight: 600;")
            card_lay.addWidget(sub_lbl)
            feat_lbl = QLabel(features)
            feat_lbl.setStyleSheet(f"color: {T['text']}; font-size: 11px;")
            card_lay.addWidget(feat_lbl)
            card.mousePressEvent = lambda _, k=key: self._on_gpu_vendor_clicked(k)
            grid.addWidget(card, 0, i)
            self._gpu_cards[key] = card
        lay.addLayout(grid)

        self._gpu_status = QLabel()
        self._gpu_status.setObjectName("PageSub")
        self._gpu_status.setAlignment(Qt.AlignCenter)
        self._gpu_status.setWordWrap(True)
        self._gpu_status.setText(
            "Click a GPU vendor above to filter optimizations")
        self._gpu_status.setStyleSheet(
            f"color: {T['accent']}; font-size: 13px; font-weight: 700;")
        lay.addWidget(self._gpu_status)

        self._gpu_selected_vendor = state_mgr.get_gpu_selection()
        host.setVisible(False)
        return host

    def _on_gpu_vendor_clicked(self, vendor):
        from config.app_config import THEME as T
        self._gpu_selected_vendor = vendor
        state_mgr.set_gpu_selection(vendor)
        for k, card in self._gpu_cards.items():
            if k == vendor:
                card.setStyleSheet(
                    f"QFrame#GpuVendorCard {{ border: 2px solid {T['accent']}; "
                    f"border-radius: 14px; background: {T['card']}; padding: 4px; }}")
            else:
                card.setStyleSheet(
                    f"QFrame#GpuVendorCard {{ border: 2px solid {T['border']}; "
                    f"border-radius: 14px; background: {T['card']}; padding: 4px; }}")
        labels = {"nvidia": "NVIDIA", "amd": "AMD", "integrated": "Integrated"}
        self._gpu_status.setText(
            f"\u2713  Showing {labels[vendor]} GPU optimizations")
        self._gpu_status.setStyleSheet(
            f"color: #10B981; font-size: 13px; font-weight: 700;")
        self.page = 1
        self.refresh()

    def _update_optimizer_bar(self):
        if self.fixed_group or not hasattr(self, "opt_host"):
            return
        from engine.optimizer import BUTTON_LABELS, GROUP_OPTIMIZERS
        clear_layout(self.opt_lay)
        if not self.key or self.key == ALL_KEY:
            self.opt_left.setVisible(False)
            self.device_badge.setVisible(False)
            self._set_facts()
            return
        if self.key == "ram":
            # The RAM selector strip has its own Scan / Optimize RAM buttons
            # and live specs, so the generic optimizer bar is hidden here.
            self.opt_left.setVisible(False)
            self.device_badge.setVisible(False)
            self._set_facts()
            return
        if self.key == "gpu" and not self._gpu_selected_vendor:
            self.opt_left.setVisible(False)
            self.device_badge.setVisible(False)
            self._set_facts()
            return
        keys = GROUP_OPTIMIZERS.get(self.key)
        if not keys:
            self.opt_left.setVisible(False)
            self.device_badge.setVisible(False)
            self._set_facts()
            return
        self.opt_left.setVisible(True)

        scan = QPushButton("Scan")
        scan.setStyleSheet(_CAT_GHOST.format(**_P))
        scan.setCursor(Qt.PointingHandCursor)
        scan.setToolTip("Re-detect this system's hardware for the active category.")
        scan.clicked.connect(lambda: self._scan_group(self.key))
        self.opt_lay.addWidget(scan)

        btn = QPushButton(
            f"Optimize {BUTTON_LABELS.get(self.key) or BUTTON_LABELS.get(keys[0], self.key)}")
        btn.setStyleSheet(_CAT_PRIMARY.format(**_P))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(
            "Scan, validate and apply the recommended tweaks for this "
            "entire category \u2014 every change is verified against the "
            "live system.")
        btn.clicked.connect(lambda _=False: self._open_optimizer_group(self.key))
        self.opt_lay.addWidget(btn)

        badge = self._badge_text()
        if badge:
            self.device_badge.setText(badge)
            self.device_badge.setVisible(True)
        else:
            self.device_badge.setVisible(False)

        self._set_facts()
        if self.key not in self._facts_cache:
            QTimer.singleShot(0, lambda: self._scan_group(self.key, silent=True))

    def _set_facts(self):
        text = self._facts_text(self.key) if self.key else ""
        if hasattr(self, "opt_facts"):
            self.opt_facts.setText(text)
        if hasattr(self, "panel_facts"):
            self.panel_facts.setVisible(bool(text))

    def _badge_text(self) -> str:
        if self.key not in ("mouse", "keyboard"):
            return ""
        name, conn = self._pnp_hardware()
        if not name:
            return ""
        return (f"<span style='color:{_P['text_dim']};'><b>Device</b>&nbsp; "
                f"{name}</span>"
                f"<span style='color:{_P['text_dim2']};'>&nbsp;\u00b7&nbsp;</span>"
                f"<span style='color:{_P['text_dim']};'><b>Connection</b>&nbsp; "
                f"{conn}</span>")

    def _pnp_hardware(self):
        if not _PNP_CACHE:
            try:
                from hardware.probes import _pnp_devices
                devs = _pnp_devices(["Mouse", "Keyboard"]) or []
            except Exception as exc:  # noqa: BLE001
                from maxlog import logger
                logger.warn(f"device badge probe: {type(exc).__name__}: {exc}")
                devs = []
            _PNP_CACHE["mouse"] = [d for d in devs
                                   if d.get("status", "").strip().lower() == "ok"]
            _PNP_CACHE["keyboard"] = [d for d in devs
                                      if d.get("status", "").strip().lower() == "ok"]
        for d in (_PNP_CACHE.get(self.key) or []):
            name = str(d.get("name") or "").strip()
            if name and name.lower() not in ("unknown device", "unknown"):
                return name, str(d.get("connection") or "Unknown")
        return "", ""

    def _facts_text(self, group) -> str:
        facts = self._facts_cache.get(group) or {}
        parts = []
        for key, rows in facts.items():
            for k, v in rows[:3]:
                parts.append(f"{k}: {v}")
        return "   \u00b7   ".join(parts)

    def _scan_group(self, group, silent=False):
        from engine.optimizer import GROUP_OPTIMIZERS, OPTIMIZERS
        keys = GROUP_OPTIMIZERS.get(group)
        if not keys:
            return
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        if not silent and hasattr(self, "opt_facts"):
            self.opt_facts.setText("Scanning\u2026")
        opts = [OPTIMIZERS[k] for k in keys]
        worker = _GroupScanWorker(opts, self)
        self._scan_worker = worker
        worker.done.connect(lambda w=worker: self._on_group_scanned(group, w))
        worker.start()

    def _on_group_scanned(self, group, worker):
        self._facts_cache[group] = worker.facts
        if not self.key or self.key == ALL_KEY or group != self.key:
            return
        if hasattr(self, "opt_facts"):
            text = self._facts_text(group)
            self.opt_facts.setText(text)
        if hasattr(self, "panel_facts"):
            self.panel_facts.setVisible(bool(text))

    def _open_optimizer_group(self, group):
        from engine.optimizer import GROUP_OPTIMIZERS, OPTIMIZERS
        from ui.optimize_dialog import OptimizeDialog
        # Prevent double-click: ignore if a dialog is already open.
        if hasattr(self, "_opt_dialog") and self._opt_dialog is not None:
            return
        keys = GROUP_OPTIMIZERS.get(group)
        if not keys:
            return
        opts = [OPTIMIZERS[k] for k in keys]
        self._opt_dialog = OptimizeDialog(self.ctx, opts, parent=self)
        self._opt_dialog.finished.connect(lambda: setattr(self, "_opt_dialog", None))
        self._opt_dialog.exec()

    # ---------------- Public API ----------------

    def select(self, key):
        if self.fixed_group:
            return
        changed = key != self.key
        self.key = key
        if changed:
            self.page = 1
            self.search.clear()
        if hasattr(self, "ram_selector"):
            self.ram_selector.setVisible(key == "ram")
            if key == "ram":
                self._ram_auto_select()
        if hasattr(self, "gpu_selector"):
            is_gpu = key == "gpu"
            self.gpu_selector.setVisible(is_gpu)
            if is_gpu:
                from config.app_config import THEME as T
                labels = {"nvidia": "NVIDIA", "amd": "AMD", "integrated": "Integrated"}
                if self._gpu_selected_vendor:
                    self._gpu_status.setText(
                        f"\u2713  Showing {labels.get(self._gpu_selected_vendor, self._gpu_selected_vendor)} GPU optimizations")
                    self._gpu_status.setStyleSheet(
                        f"color: #10B981; font-size: 13px; font-weight: 700;")
                    card = self._gpu_cards.get(self._gpu_selected_vendor)
                    if card:
                        card.setStyleSheet(
                            f"QFrame#GpuVendorCard {{ border: 2px solid {T['accent']}; "
                            f"border-radius: 14px; background: {T['card']}; padding: 4px; }}")
                else:
                    self._gpu_status.setText(
                        "\u2191 Click a GPU vendor above to filter optimizations \u2191")
                    self._gpu_status.setStyleSheet(
                        f"color: {T['accent']}; font-size: 13px; font-weight: 700;")
        self.refresh()

    def refresh(self, audit=True):
        if not self.key:
            return
        self._set_stats()
        self._filtered = self._visible_tweaks()
        self._set_toolbar()
        self._update_header()
        self._update_optimizer_bar()
        self._schedule_relayout()
        if audit:
            self._request_audit()

    def _request_audit(self):
        """Background-check the live system state of the current group."""
        if not self.key:
            return
        self.ctx.request_audit(self._source_tweaks())

    def _on_live_state(self, tid, value):
        if tid in self._in_flight:
            return  # stale audit result; a batch is in progress for this tweak
        card = self._cards.get(tid)
        if card is not None:
            card.set_detected(value)
        self._set_stats()

    # ---------------- Actions ----------------

    def _apply(self, tid):
        self._run_batch([tid], "apply")

    def _revert(self, tid):
        self._run_batch([tid], "revert")

    def _show_guide(self, tid):
        tweak = BY_ID.get(tid)
        if tweak is None:
            return
        GuideDialog(tweak, self).exec()

    def _apply_all(self):
        from engine.safety import preflight as _preflight
        profile = self.ctx.profile or None
        ids, skipped = [], []
        for t in self._visible_tweaks():
            if t.get("guidance"):
                continue
            if t.get("recommended") != "recommended":
                continue
            if self.ctx.live_active(t["id"]):
                continue
            pf = _preflight(t, profile=profile)
            if pf["allowed"]:
                ids.append(t["id"])
            else:
                skipped.append((t["id"], pf["reason"]))
        if not ids:
            if skipped:
                toast("Nothing to apply \u2014 every visible tweak is already active "
                      "or blocked (see the first blocked reason in the log).", "info", self)
            else:
                toast("Nothing to apply \u2014 every visible tweak is already active "
                      "on your system.", "info", self)
            return
        block_note = ""
        if skipped:
            block_note = (f"\n\nSkipping {len(skipped)} tweak(s) that are blocked "
                          f"(validation status, wrong Windows version, undetected "
                          f"hardware, or conflicting with an applied tweak).")
        risky_ids = [i for i in ids if BY_ID.get(i, {}).get("confirm")]
        risk_note = ""
        if risky_ids:
            risk_note = (
                f"\n\n\u26a0\ufe0f {len(risky_ids)} of these tweaks adjust low-level "
                f"CPU boost or power-management settings. These are ordinary "
                f"Windows settings, and everything can be reverted with Revert All.")
        if not self._confirm(
                "Apply All",
                f"Apply {len(ids)} visible compatible tweak(s) to your system?\n\n"
                "This changes registry, services and power settings. Everything "
                "can be reverted with Revert All." + block_note + risk_note):
            return
        toast(f"Applying {len(ids)} tweaks\u2026", "info", self)
        self._run_batch(ids, "apply")

    def _revert_all(self):
        ids = [
            t["id"] for t in self._visible_tweaks()
            if self.ctx.state_of(t["id"]) not in ("incompatible", "not_for_you")
            and self.ctx.live_active(t["id"])
        ]
        if not ids:
            toast("Nothing to revert \u2014 no active tweaks in view.", "info", self)
            return
        if not self._confirm(
                "Revert All",
                f"Revert {len(ids)} applied tweak(s) back to their defaults?"):
            return
        toast(f"Reverting {len(ids)} tweaks\u2026", "info", self)
        self._run_batch(ids, "revert")

    @staticmethod
    def _confirm(title, text) -> bool:
        box = QMessageBox()
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Warning)
        yes = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _run_batch(self, ids, mode):
        if self._busy:
            toast("A batch is already running \u2014 wait a moment.", "warning", self)
            return
        self._busy = True
        self._in_flight.update(ids)
        self._batch_ids = list(ids)
        self._batch_mode = mode
        self._last_results = {}
        self._set_toolbar()
        # Clean up any previous worker.
        if self._worker and self._worker.isRunning():
            if hasattr(self._worker, "cancel"):
                self._worker.cancel()
            self._worker.wait(5000)
        self._worker = BatchWorker(ids, mode, self, profile=self.ctx.profile)
        self._worker.batch_done.connect(self._on_batch_done)
        self._worker.batch_error.connect(self._on_batch_error)
        self._worker.progress.connect(self._on_batch_progress)
        self._worker.start()

    def _on_batch_progress(self, done, total, tid, ok, summary):
        """Live run feedback: update Apply All with a running counter so a long
        batch never looks like a frozen app. Called once per tweak from the
        worker thread via a queued signal, so it runs on the GUI thread."""
        if not self._busy:
            return
        if self.fixed_group or not hasattr(self, "btn_apply_all"):
            return
        name = (BY_ID.get(tid) or {}).get("name", tid) if tid else ""
        text = f"{done}/{total} \u2014 {name}" if name else f"{done}/{total} \u2026"
        self.btn_apply_all.setText(text)
        self.btn_apply_all.setToolTip(
            f"Working\u2026 {done} of {total} tweak(s) completed\n"
            + (summary or ""))

    def _restore_batch_buttons(self):
        if hasattr(self, "btn_apply_all"):
            self.btn_apply_all.setText(self._apply_all_text)
            self.btn_apply_all.setToolTip("")

    def _post_batch(self, ids):
        """Invalidate cached reads and re-check the real system state so the
        toggles converge on what the user chose (even if an older audit is
        still streaming stale results)."""
        # The user's decision wins: an executed apply records the tweak as
        # applied, an executed revert records it as disabled -- regardless of
        # whether the live system could be verified. This keeps a toggle OFF
        # once the user turns it off, even when the target still matches.
        results = getattr(self, "_last_results", {})
        # Collapse the per-tweak mark_applied/mark_disabled writes into ONE
        # state.json write instead of re-serializing the whole file per tweak.
        with state_mgr.state_batch():
            for tid in self._batch_ids:
                r = results.get(tid) or {}
                ok = r.get("ok") and r.get("status") != "dry_run"
                if not ok:
                    self.ctx.live.pop(tid, None)
                    continue
                if self._batch_mode == "revert":
                    state_mgr.unmark_applied(tid)
                    state_mgr.mark_disabled(tid)
                    self.ctx.live[tid] = False
                else:
                    state_mgr.mark_applied(tid)
                    state_mgr.unmark_disabled(tid)
                    self.ctx.live[tid] = True
        self._in_flight.clear()
        self.ctx.invalidate_state()
        self.ctx.force_audit_ids(ids)
        self.ctx.note_state_change()
        # Rebuild the visible cards so every toggle reflects the recorded
        # outcome (including failures) once the batch settles. Audit=False:
        # only the batch tweaks are re-checked (force_audit_ids above), so
        # applying one tweak never flips a chain of shared-setting tweaks on.
        self._built_sig = None
        self.refresh(audit=False)

    def _on_batch_done(self, result):
        self._busy = False
        self._restore_batch_buttons()
        results = result.get("results", {})
        self._last_results = results
        ok_ids = [tid for tid, r in results.items()
                  if r.get("ok") and r.get("status") != "dry_run"]
        failed = len(results) - len(ok_ids)
        total = len(results)
        verb = ("Reverted" if self._batch_mode == "revert"
                else "Applied" if total else "Done")
        if failed:
            msg = (f"{len(ok_ids)} of {total} tweaks "
                   f"\u2014 {failed} failed or blocked.")
            toast(msg.strip(), "warning", self)
        else:
            toast(f"{verb} {total} tweak{'s' if total != 1 else ''} "
                  "successfully.", "success", self)
        self._post_batch(ok_ids)

    def _on_batch_error(self, msg):
        self._busy = False
        self._restore_batch_buttons()
        self._in_flight.clear()
        self._set_toolbar()
        toast(f"Batch error \u2014 {msg}", "error", self)
        self.ctx.invalidate_state()
        self.ctx.note_state_change()
        self.refresh()

    # ---------------- Data / filters / sort ----------------

    def _source_tweaks(self) -> list[dict]:
        if self.key == ALL_KEY:
            out = []
            for k in ALL_TWEAK_KEYS:
                out.extend(group_tweaks(k))
            return out
        if self.key == "gpu" and self._gpu_selected_vendor:
            return gpu_filter_tweaks("gpu", self._gpu_selected_vendor)
        if self.key == "gpu" and not self._gpu_selected_vendor:
            return []
        if self.key == "cpu":
            profile = self.ctx.profile or {}
            return cpu_filter_tweaks(
                "cpu",
                cpu_vendor=profile.get("cpu_vendor"),
                is_laptop=profile.get("laptop"),
            )
        return group_tweaks(self.key)

    def _visible_tweaks(self) -> list[dict]:
        text = ""
        if hasattr(self, "search"):
            text = self.search.text().strip().lower()
        tweaks = self._source_tweaks()
        if text:
            tweaks = [
                t for t in tweaks
                if (text in t["id"].lower()
                    or text in t["name"].lower()
                    or text in (t.get("desc") or "").lower()
                    or text in (t.get("category") or "").lower()
                    or text in " ".join(t.get("tags") or []).lower())
            ]
        mode = self.sort_combo.currentData() if hasattr(self, "sort_combo") else None
        if mode == "impact":
            tweaks.sort(key=lambda t: -IMPACT_RANK.get(t.get("impact", "low"), 0))
        elif mode == "risk":
            tweaks.sort(key=lambda t: RISK_RANK.get(t.get("risk", "safe"), 0))
        elif mode == "name":
            tweaks.sort(key=lambda t: t["name"].lower())
        else:
            tweaks.sort(
                key=lambda t: (REC_RANK.get(t.get("recommended", "optional"), 9),
                               t["name"].lower()))
        return tweaks

    def _on_filters(self):
        self.page = 1
        self.refresh()

    # ---------------- Stats / toolbar state ----------------

    def _set_stats(self):
        if self.fixed_group or not hasattr(self, "counter_lbl"):
            return
        all_tweaks = self._source_tweaks()
        # Count matches the cards: what the user turned on (recorded), not what
        # shared registry state happens to detect.
        applied_ids = state_mgr.applied_ids()
        applied = sum(1 for t in all_tweaks if t["id"] in applied_ids)
        rec = recommended_count(all_tweaks)
        self.counter_lbl.setText(
            f"<span style='color:{_P['purple_2']}; font-weight:600;'>"
            f"{applied} / {len(all_tweaks)}</span>"
            f"<span style='color:{_P['text_dim']}';&nbsp; applied "
            f"&nbsp;\u00b7&nbsp; {rec} recommended</span>")

    def _set_toolbar(self):
        if self.fixed_group or not hasattr(self, "btn_apply_all"):
            return
        self.btn_apply_all.setEnabled(not self._busy)
        self.btn_revert_all.setEnabled(not self._busy)

    # ---------------- Grid layout / pagination ----------------

    def _geometry(self) -> tuple[int, int]:
        width = max(10, self.grid_host.width())
        cols = max(1, min(self.MAX_COLS, (width + self.GAP) // (self.MIN_CARD_W + self.GAP)))
        # Rows are derived from the visible scroll viewport (minus the chrome
        # above the grid) so pagination never underestimates and the last page
        # never leaves a dead band at the bottom. The chrome is measured from
        # the live panel sections (they vary per category once the RAM/GPU
        # selector strips are shown).
        chrome = self._top_chrome_height() if not self.fixed_group else 0
        view_h = max(10, self.scroll.viewport().height() - chrome)
        rows = max(1, view_h // (TweakCard.GRID_HEIGHT + self.GAP))
        return cols, rows

    def _top_chrome_height(self) -> int:
        h = 40 + 40  # wrapper vertical margins
        if hasattr(self, "panel") and self.panel.isVisible():
            for attr in ("panel_head", "panel_search", "panel_toolbar",
                         "panel_facts", "ram_selector", "gpu_selector"):
                w = getattr(self, attr, None)
                if w is not None and w.isVisible():
                    h += w.height() or w.sizeHint().height()
        return h

    def _schedule_relayout(self):
        if self._relayout_pending:
            return
        self._relayout_pending = True
        QTimer.singleShot(0, self._do_relayout)

    def _do_relayout(self):
        self._relayout_pending = False
        self._relayout()

    def _relayout(self):
        if self._busy:
            return
        cols, rows = self._geometry()
        per_page = cols * rows
        total = len(self._filtered)
        self._pages = max(1, (total + per_page - 1) // per_page)
        if self.page > self._pages:
            self.page = self._pages
        # Idempotency guard: rebuilding clears + recreates every card, and the
        # layout churn emits Resize events that re-trigger this method, so skip
        # the rebuild entirely when the visible state is unchanged. The ids are
        # part of the signature so switching category/page/search always rebuilds.
        start = (self.page - 1) * per_page
        cards = self._filtered[start:start + per_page]
        width = max(10, self.grid_host.width())
        cols = max(1, min(cols, len(cards)))
        card_w = max(self.MIN_CARD_W, (width - self.GAP * (cols - 1)) // cols)
        sig = (cols, rows, self.page, self._pages, total,
               tuple(t["id"] for t in cards), card_w)
        if sig == getattr(self, "_built_sig", None):
            return
        self._built_sig = sig
        self._rebuild_grid(cols, rows, per_page)
        self._rebuild_pager()

    def _rebuild_grid(self, cols, rows, per_page):
        clear_layout(self.grid)
        self._cards.clear()
        start = (self.page - 1) * per_page
        cards = self._filtered[start:start + per_page]
        # Shrink the column count to the actual number of cards so every page
        # fills the full viewport width (a lone partial row no longer leaves a
        # dead column of raw background on the right edge).
        cols = max(1, min(cols, len(cards)))
        width = max(10, self.grid_host.width())
        card_w = max(self.MIN_CARD_W, (width - self.GAP * (cols - 1)) // cols)
        n_rows = max(1, (len(cards) + cols - 1) // cols)
        card_h = TweakCard.GRID_HEIGHT
        for idx, t in enumerate(cards):
            card = TweakCard(self.ctx, t)
            self._cards[t["id"]] = card
            card.apply_requested.connect(self._apply)
            card.revert_requested.connect(self._revert)
            card.guide_requested.connect(self._show_guide)
            card.setMinimumSize(card_w, card_h)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            r, c = divmod(idx, cols)
            self.grid.addWidget(card, r, c)
        # Equal column stretch makes the cards fill the grid width uniformly.
        # Rows are NOT stretched (a trailing spacer row absorbs leftover
        # vertical space) so a short last page never turns its cards into
        # giant boxes — extra space pools below the grid instead.
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)
        for r in range(n_rows):
            self.grid.setRowStretch(r, 0)
        self.grid.setRowStretch(n_rows, 1)
        self.grid.addItem(QSpacerItem(1, 1, QSizePolicy.Minimum,
                                      QSizePolicy.Expanding),
                          n_rows, 0, 1, cols)

    def _rebuild_pager(self):
        clear_layout(self.pager_lay)
        if self._pages <= 1:
            self.pager.setVisible(False)
            return
        self.pager.setVisible(True)
        prev = QPushButton("\u2039")
        prev.setObjectName("PageNav")
        prev.setEnabled(self.page > 1)
        prev.clicked.connect(lambda: self._go(self.page - 1))
        self.pager_lay.addWidget(prev)
        self.pager_lay.addSpacing(4)
        for num in self._page_window():
            btn = QPushButton(str(num))
            btn.setObjectName("PageNum")
            btn.setProperty("current", "true" if num == self.page else "false")
            btn.clicked.connect(lambda _=False, n=num: self._go(n))
            self.pager_lay.addWidget(btn)
        self.pager_lay.addSpacing(4)
        nxt = QPushButton("Next  \u203a")
        nxt.setObjectName("PageNav")
        nxt.setEnabled(self.page < self._pages)
        nxt.clicked.connect(lambda: self._go(self.page + 1))
        self.pager_lay.addWidget(nxt)
        self.pager_lay.addStretch(1)

    def _page_window(self) -> list[int]:
        total, cur = self._pages, self.page
        if total <= 7:
            return list(range(1, total + 1))
        pages = {1, total, cur - 1, cur, cur + 1}
        if cur <= 3:
            pages.update({2, 3, 4})
        if cur >= total - 2:
            pages.update({total - 3, total - 2, total - 1})
        return sorted(p for p in pages if 1 <= p <= total)

    def _go(self, page):
        if 1 <= page <= self._pages:
            self.page = page
            self._relayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_atmo"):
            self._atmo.setGeometry(self.rect())
            self._atmo.lower()
        if self.key:
            self._schedule_relayout()

    def eventFilter(self, obj, event):
        if (hasattr(self, "search") and obj is self.search
                and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut)):
            self._set_search_focus(event.type() == QEvent.Type.FocusIn)
        if obj is self.grid_host and event.type() == QEvent.Type.Resize and self.key:
            self._schedule_relayout()
        return super().eventFilter(obj, event)

    def _set_search_focus(self, focused):
        if not hasattr(self, "search_box"):
            return
        border = ("1px solid rgba(124,109,240,0.5)" if focused
                  else f"1px solid {_P['line']}")
        self.search_box.setStyleSheet(
            f"QFrame#SearchBox{{background:{_P['chip']}; border:{border};}}")


class _TweakAtmosphere(QWidget):
    """Background for the tweaks content, matching the reference .main layers:
    #08060F base + violet .blob.a (left:100 top:-220, 520px, rgba(139,107,255,
    0.16)) + cyan .blob.b (bottom-right, 480px, rgba(75,232,216,0.07)) + the
    .dots 34px grid (rgba(200,190,240,0.35), 0.5 opacity) masked around 60% 20%.
    Fixed to the viewport, so it does not scroll with the cards (position:fixed).
    """

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#08060F"))

        # .blob.a — violet, center (~360, ~40), ~380px effective radius.
        ga = QRadialGradient(QPointF(360, 40), 380)
        ga.setColorAt(0.0, QColor(139, 107, 255, 41))
        ga.setColorAt(0.55, QColor(139, 107, 255, 12))
        ga.setColorAt(1.0, QColor(139, 107, 255, 0))
        p.fillRect(self.rect(), ga)

        # .blob.b — cyan, center (w-140, h), ~340px radius.
        gb = QRadialGradient(QPointF(w - 140, h), 340)
        gb.setColorAt(0.0, QColor(75, 232, 216, 18))
        gb.setColorAt(0.6, QColor(75, 232, 216, 6))
        gb.setColorAt(1.0, QColor(75, 232, 216, 0))
        p.fillRect(self.rect(), gb)

        # .dots — 34px grid, masked radial fading out past 85%.
        p.setPen(QColor(200, 190, 240, 45))  # 0.35 * 0.5 opacity
        cx, cy = 0.60 * w, 0.20 * h
        rx, ry = 0.70 * w, 0.60 * h
        if rx > 0 and ry > 0:
            y = 17.0
            while y < h:
                x = 17.0
                while x < w:
                    t = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
                    t **= 0.5
                    if t < 0.85:
                        alpha = int(45 * (1.0 - t / 0.85))
                        if alpha > 3:
                            p.setPen(QColor(200, 190, 240, alpha))
                            p.drawPoint(QPointF(x, y))
                    x += 34.0
                y += 34.0
        p.end()


class _GroupScanWorker(QThread):
    """Detects the hardware facts for every optimizer on a category page."""

    done = Signal()

    def __init__(self, optimizers, parent=None):
        super().__init__(parent)
        self.optimizers = optimizers
        self.facts: dict = {}

    def run(self):
        for opt in self.optimizers:
            try:
                det = opt.detect(refresh=False)
                self.facts[opt.key] = list(det.get("facts") or [])
            except Exception as exc:  # noqa: BLE001
                from maxlog import logger
                logger.warn(f"group scan {opt.key}: {type(exc).__name__}: {exc}")
                self.facts[opt.key] = []
        self.done.emit()
