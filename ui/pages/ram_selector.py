"""RAM Tweaks — optimize Windows memory management based on installed RAM.

The category page's RAM selector now mirrors the reference "RAM Tweaks"
dashboard: a module strip with live specs, a "Select your installed RAM size"
section label, and a 3-column grid of tier cards with mono sizing, check
boxes, progress bars and a Recommended badge.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from database import BY_ID
from ui.widgets import ProgressDialog


RAM_TIERS = {
    "4GB": {
        "ram_gb": 4,
        "label": "4 GB",
        "desc": "Entry-level systems",
        "color": "#FF6F6F",
        "tweaks": [
            "ram-059",  # Disable Paging Executive
            "ram-058",  # Io Page Lock Limit auto
            "ram-060",  # System Pages auto
            "ram-061",  # Paged Pool auto
            "ram-042",  # Service Shutdown Timeout
            "ram-043",  # Disable Boot Memory Diagnostic
            "ram-063",  # SharedSection desktop heap
            "ram-029",  # Disable Windows Search Indexing
            "ram-034",  # Disable BITS
            "ram-035",  # Disable WAP Push
            "net-019",  # Disable RSS on Low RAM
        ],
    },
    "8GB": {
        "ram_gb": 8,
        "label": "8 GB",
        "desc": "Standard gaming",
        "color": "#FFB454",
        "tweaks": [
            "ram-059",  # Disable Paging Executive
            "ram-058",  # Io Page Lock Limit auto
            "ram-060",  # System Pages auto
            "ram-061",  # Paged Pool auto
            "ram-062",  # Enable Memory Compression
            "ram-042",  # Service Shutdown Timeout
            "ram-043",  # Disable Boot Memory Diagnostic
            "ram-063",  # SharedSection desktop heap
            "ram-029",  # Disable Windows Search Indexing
            "ram-034",  # Disable BITS
            "ram-035",  # Disable WAP Push
            "ram-047",  # Disable Full Memory Diagnostic Task
            "ram-048",  # Disable Memory Diagnostic Events
            "ram-049",  # Disable Compatibility Appraiser
            "ram-050",  # Disable Program Data Updater
        ],
    },
    "16GB": {
        "ram_gb": 16,
        "label": "16 GB",
        "desc": "Sweet spot for gaming",
        "color": "#10B981",
        "tweaks": [
            "ram-059",  # Disable Paging Executive
            "ram-058",  # Io Page Lock Limit auto
            "ram-060",  # System Pages auto
            "ram-061",  # Paged Pool auto
            "ram-062",  # Enable Memory Compression
            "ram-057",  # Large System Cache
            "ram-042",  # Service Shutdown Timeout
            "ram-043",  # Disable Boot Memory Diagnostic
            "ram-063",  # SharedSection desktop heap
            "ram-029",  # Disable Windows Search Indexing
            "ram-034",  # Disable BITS
            "ram-035",  # Disable WAP Push
            "ram-047",  # Disable Full Memory Diagnostic Task
            "ram-048",  # Disable Memory Diagnostic Events
            "ram-049",  # Disable Compatibility Appraiser
            "ram-050",  # Disable Program Data Updater
            "ram-051",  # Disable CEIP Consolidator
            "ram-052",  # Disable WER Queue Reporting
        ],
    },
    "32GB": {
        "ram_gb": 32,
        "label": "32 GB",
        "desc": "High-end gaming / streaming",
        "color": "#3B82F6",
        "tweaks": [
            "ram-059",  # Disable Paging Executive
            "ram-058",  # Io Page Lock Limit auto
            "ram-060",  # System Pages auto
            "ram-061",  # Paged Pool auto
            "ram-062",  # Enable Memory Compression
            "ram-057",  # Large System Cache
            "ram-041",  # Unload Unused DLLs
            "ram-042",  # Service Shutdown Timeout
            "ram-043",  # Disable Boot Memory Diagnostic
            "ram-063",  # SharedSection desktop heap
            "ram-029",  # Disable Windows Search Indexing
            "ram-034",  # Disable BITS
            "ram-035",  # Disable WAP Push
            "ram-047",  # Disable Full Memory Diagnostic Task
            "ram-048",  # Disable Memory Diagnostic Events
            "ram-049",  # Disable Compatibility Appraiser
            "ram-050",  # Disable Program Data Updater
            "ram-051",  # Disable CEIP Consolidator
            "ram-052",  # Disable WER Queue Reporting
            "ram-053",  # Remove Solitaire
            "ram-054",  # Remove Xbox Gaming Overlay
            "ram-055",  # Disable Print Spooler
        ],
    },
    "64GB": {
        "ram_gb": 64,
        "label": "64 GB",
        "desc": "Workstation / content creation",
        "color": "#8B6BFF",
        "tweaks": [
            "ram-059",  # Disable Paging Executive
            "ram-058",  # Io Page Lock Limit auto
            "ram-060",  # System Pages auto
            "ram-061",  # Paged Pool auto
            "ram-062",  # Enable Memory Compression
            "ram-057",  # Large System Cache
            "ram-041",  # Unload Unused DLLs
            "ram-042",  # Service Shutdown Timeout
            "ram-043",  # Disable Boot Memory Diagnostic
            "ram-063",  # SharedSection desktop heap
            "ram-029",  # Disable Windows Search Indexing
            "ram-034",  # Disable BITS
            "ram-035",  # Disable WAP Push
            "ram-036",  # Disable Diagnostics Hub
            "ram-037",  # Disable Fax Service
            "ram-044",  # Disable Data Sharing Service
            "ram-045",  # Disable Tablet Input Service
            "ram-046",  # Disable Push Notifications
            "ram-047",  # Disable Full Memory Diagnostic Task
            "ram-048",  # Disable Memory Diagnostic Events
            "ram-049",  # Disable Compatibility Appraiser
            "ram-050",  # Disable Program Data Updater
            "ram-051",  # Disable CEIP Consolidator
            "ram-052",  # Disable WER Queue Reporting
            "ram-053",  # Remove Solitaire
            "ram-054",  # Remove Xbox Gaming Overlay
            "ram-055",  # Disable Print Spooler
        ],
    },
    "128GB": {
        "ram_gb": 128,
        "label": "128 GB",
        "desc": "Extreme / server-class",
        "color": "#EC4899",
        "tweaks": [
            "ram-059",  # Disable Paging Executive
            "ram-058",  # Io Page Lock Limit auto
            "ram-060",  # System Pages auto
            "ram-061",  # Paged Pool auto
            "ram-062",  # Enable Memory Compression
            "ram-057",  # Large System Cache
            "ram-041",  # Unload Unused DLLs
            "ram-042",  # Service Shutdown Timeout
            "ram-043",  # Disable Boot Memory Diagnostic
            "ram-063",  # SharedSection desktop heap
            "ram-029",  # Disable Windows Search Indexing
            "ram-030",  # Disable Telemetry
            "ram-031",  # Disable Maps Broker
            "ram-032",  # Disable WMP Sharing
            "ram-033",  # Disable Retail Demo
            "ram-034",  # Disable BITS
            "ram-035",  # Disable WAP Push
            "ram-036",  # Disable Diagnostics Hub
            "ram-037",  # Disable Fax Service
            "ram-038",  # Disable WER
            "ram-039",  # Disable PCA
            "ram-044",  # Disable Data Sharing Service
            "ram-045",  # Disable Tablet Input Service
            "ram-046",  # Disable Push Notifications
            "ram-047",  # Disable Full Memory Diagnostic Task
            "ram-048",  # Disable Memory Diagnostic Events
            "ram-049",  # Disable Compatibility Appraiser
            "ram-050",  # Disable Program Data Updater
            "ram-051",  # Disable CEIP Consolidator
            "ram-052",  # Disable WER Queue Reporting
            "ram-053",  # Remove Solitaire
            "ram-054",  # Remove Xbox Gaming Overlay
            "ram-055",  # Disable Print Spooler
            "ram-040",  # Disable Memory Compression (128GB+ too much RAM)
        ],
    },
}


# Reference-tier metadata: second line of description + progress-bar width.
TIER_SUB = {
    "4GB": "Minimal footprint, aggressive paging",
    "8GB": "Balanced for everyday titles",
    "16GB": "Sweet spot for modern gaming",
    "32GB": "Headroom for capture and overlays",
    "64GB": "Large caches, heavy multitasking",
    "128GB": "Large VMs, in-memory datasets",
}
TIER_BAR_PCT = {
    "4GB": 31,
    "8GB": 44,
    "16GB": 53,
    "32GB": 65,
    "64GB": 79,
    "128GB": 100,
}

# RAM selector accent, matching the reference dashboard rather than the
# sidebar's pink RAM chip.
RAM_VIOLET = "#8B7CF6"
RAM_VIOLET_SOFT = "#C3B8FC"


def recommended_ram_key(profile: dict | None) -> str:
    """Pick the tier that matches the machine's total installed RAM."""
    if not profile:
        return "16GB"
    gb = profile.get("ram_gb") or 0
    if not gb:
        return "16GB"
    return min(
        RAM_TIERS,
        key=lambda k: abs(RAM_TIERS[k]["ram_gb"] - gb),
    )


class RamTierCard(QFrame):
    """Clickable tier card matching the RAM Tweaks reference dashboard."""

    def __init__(self, tier_key, tier, ctx, parent=None,
                 recommended=False, sub=None, bar_pct=None):
        super().__init__(parent)
        self.ctx = ctx
        self.tier_key = tier_key
        self.tier = tier
        self.selected = False
        self.recommended = recommended
        self.setObjectName("RamTierCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(118)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 3px left accent bar (violet when selected, like the reference).
        self.accent = QLabel()
        self.accent.setFixedWidth(3)
        self.accent.setObjectName("RamAccent")
        root.addWidget(self.accent)

        inner = QVBoxLayout()
        inner.setContentsMargins(16, 15, 16, 13)
        inner.setSpacing(4)
        root.addLayout(inner, 1)

        # top row: mono size + Recommended badge + check box
        top = QHBoxLayout()
        top.setSpacing(8)
        top.setAlignment(Qt.AlignVCenter)
        self.size_lbl = QLabel(tier["label"])
        self.size_lbl.setObjectName("RamSize")
        self.size_lbl.setStyleSheet(
            f"font-family: 'JetBrains Mono', monospace; "
            f"font-size: 21px; font-weight: 600; color: #EFF0F4;")
        top.addWidget(self.size_lbl)
        top.addStretch()
        self.badge_lbl = QLabel("Recommended")
        self.badge_lbl.setObjectName("RamRecBadge")
        self.badge_lbl.setVisible(self.recommended)
        top.addWidget(self.badge_lbl)
        self.check_lbl = QLabel("\u2713")
        self.check_lbl.setObjectName("RamCheck")
        self.check_lbl.setFixedSize(19, 19)
        self.check_lbl.setAlignment(Qt.AlignCenter)
        top.addWidget(self.check_lbl)
        inner.addLayout(top)

        self.label_lbl = QLabel(tier["desc"])
        self.label_lbl.setObjectName("RamTierLabel")
        self.label_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #EFF0F4;")
        inner.addWidget(self.label_lbl)

        self.desc_lbl = QLabel(sub if sub is not None else TIER_SUB.get(tier_key, ""))
        self.desc_lbl.setObjectName("RamTierDesc")
        self.desc_lbl.setStyleSheet("font-size: 11.5px; color: #9399A9;")
        self.desc_lbl.setWordWrap(True)
        inner.addWidget(self.desc_lbl)

        bl = QHBoxLayout()
        bl.setSpacing(8)
        bl.setAlignment(Qt.AlignVCenter)
        self.bar = QProgressBar()
        self.bar.setObjectName("RamBar")
        self.bar.setRange(0, 100)
        self.bar.setValue(bar_pct if bar_pct is not None else TIER_BAR_PCT.get(tier_key, 0))
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        bl.addWidget(self.bar, 1)
        count = QLabel(f"{len(tier['tweaks'])} tweaks")
        count.setObjectName("RamCount")
        count.setStyleSheet(
            "font-family: 'JetBrains Mono', monospace; "
            "font-size: 11px; color: #575C6B;")
        bl.addWidget(count)
        inner.addLayout(bl)

        self._apply_style()

    # ---------------- Styling ----------------

    def _apply_style(self):
        sel = self.selected
        violet, soft = RAM_VIOLET, RAM_VIOLET_SOFT

        border = f"1px solid {violet};" if sel else "1px solid rgba(255, 255, 255, 0.055);"
        bg = (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, "
              f"stop:0 rgba(139,124,246,0.14), stop:1 rgba(255,255,255,0.032));"
              if sel else "rgba(255, 255, 255, 0.032);")
        card = (
            f"QFrame#RamTierCard {{ background: {bg}; border: {border}; "
            f"border-radius: 13px; }}"
            f"QFrame#RamTierCard:hover {{ border-color: "
            f"{soft if sel else 'rgba(255,255,255,0.24)'}; }}"
        )
        accent = (
            f"QLabel#RamAccent {{ background: {violet}; border-radius: 2px; "
            f"border-top-left-radius: 12px; border-bottom-left-radius: 12px; }}"
            if sel else "QLabel#RamAccent { background: transparent; }"
        )
        size_color = soft if sel else "#EFF0F4"
        size = f"QLabel#RamSize {{ color: {size_color}; }}"
        check_fill = (
            f"background: {violet}; border: 1px solid {violet};"
            if sel else "background: transparent; border: 1.5px solid rgba(255,255,255,0.28);"
        )
        check_icon = "#08090C" if sel else "transparent"
        check = (
            f"QLabel#RamCheck {{ {check_fill} border-radius: 6px; color: {check_icon}; "
            f"font-size: 12px; font-weight: 700; }}"
        )
        badge = (
            f"QLabel#RamRecBadge {{ font-size: 9.5px; font-weight: 700; color: {soft}; "
            f"background: rgba(139,124,246,0.15); border: 1px solid rgba(139,124,246,0.4); "
            f"border-radius: 100px; padding: 3px 8px; }}"
        )
        bar_fill = violet if sel else "rgba(255,255,255,0.22)"
        bar = (
            f"QProgressBar#RamBar {{ background: rgba(255,255,255,0.06); "
            f"border: none; border-radius: 3px; }}"
            f"QProgressBar#RamBar::chunk {{ background: {bar_fill}; "
            f"border-radius: 3px; }}"
        )
        self.setStyleSheet(card + accent + size + check + badge + bar)

    def set_selected(self, selected: bool):
        self.selected = bool(selected)
        self._apply_style()

    def set_recommended(self, recommended: bool, sub: str | None = None):
        self.recommended = bool(recommended)
        self.badge_lbl.setVisible(self.recommended)
        if sub is not None:
            self.desc_lbl.setText(sub)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if hasattr(self, "_on_click"):
            self._on_click(self.tier_key)


class RamSelectorPage(QWidget):
    """Full page for selecting RAM size and applying memory optimizations."""

    def __init__(self, ctx, navigate, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.navigate = navigate
        self._selected = None
        self._cards = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        title = QLabel("RAM Optimizer")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        sub = QLabel(
            "Select your installed RAM size. Maximum Tweaks will automatically "
            "optimize Windows memory-management settings: Memory Compression, "
            "I/O page-lock limits, SvcHost split threshold, pagefile behavior, "
            "background services, and many other RAM-specific settings.")
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        root.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(4, 0, 12, 0)
        grid.setSpacing(14)

        keys = list(RAM_TIERS.keys())
        rec_key = recommended_ram_key(ctx.profile)
        for i, key in enumerate(keys):
            tier = RAM_TIERS[key]
            card = RamTierCard(key, tier, ctx, recommended=(key == rec_key))
            card._on_click = self._select_tier
            grid.addWidget(card, i // 2, i % 2)
            self._cards[key] = card

        body.setLayout(grid)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # Apply button area
        self._apply_frame = QFrame()
        self._apply_frame.setObjectName("Card")
        af_layout = QVBoxLayout(self._apply_frame)
        af_layout.setContentsMargins(18, 14, 18, 14)
        af_layout.setSpacing(8)

        self._status = QLabel("Select your RAM size above, then click Apply.")
        self._status.setObjectName("PageSub")
        self._status.setWordWrap(True)
        af_layout.addWidget(self._status)

        row = QHBoxLayout()
        self._btn_apply = QPushButton("Apply Memory Optimizations")
        self._btn_apply.setObjectName("Primary")
        self._btn_apply.setEnabled(False)
        self._btn_apply.clicked.connect(self._apply)
        row.addWidget(self._btn_apply)
        row.addStretch()
        af_layout.addLayout(row)

        root.addWidget(self._apply_frame)

        self.ctx.profile_changed.connect(self._refresh_status)
        self._refresh_status()

    def _select_tier(self, key):
        self._selected = key
        for k, card in self._cards.items():
            card.set_selected(k == key)
        tier = RAM_TIERS[key]
        self._status.setText(
            f"<b>{tier['label']} ({tier['desc']})</b> — "
            f"{len(tier['tweaks'])} memory optimizations will be applied.")
        self._btn_apply.setEnabled(True)

    def _apply(self):
        if not self._selected:
            return
        tier = RAM_TIERS[self._selected]
        ids = [tid for tid in tier["tweaks"] if tid in BY_ID]
        if not ids:
            return
        dlg = ProgressDialog(
            self, ids, "apply",
            f"Optimizing memory for {tier['label']}…",
            profile=self.ctx.profile)
        dlg.exec()
        self.ctx.note_state_change()
        self._refresh_status()

    def _refresh_status(self):
        profile = self.ctx.profile or {}
        gb = profile.get("ram_gb") or 0
        rec_key = recommended_ram_key(profile)
        for key, card in self._cards.items():
            if gb and key == rec_key:
                card.set_recommended(True, f"Matches your installed {gb:g} GB")
            else:
                card.set_recommended(False)
