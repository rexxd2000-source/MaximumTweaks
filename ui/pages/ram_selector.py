"""RAM Size Selector — optimize Windows memory management based on installed RAM."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.app_config import THEME as T
from database import BY_ID
from ui.widgets import ProgressDialog


RAM_TIERS = {
    "4GB": {
        "ram_gb": 4,
        "label": "4 GB",
        "desc": "Entry-level systems",
        "color": "#EF4444",
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
        "color": "#F59E0B",
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
        "color": "#8B5CF6",
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


class RamTierCard(QFrame):
    """Clickable card representing one RAM size tier."""

    def __init__(self, tier_key, tier, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.tier_key = tier_key
        self.tier = tier
        self.selected = False
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(90)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(4)

        top = QHBoxLayout()
        lbl = QLabel(tier["label"])
        lbl.setStyleSheet(
            f"font-size: 20px; font-weight: 800; color: {tier['color']};")
        top.addWidget(lbl)
        top.addStretch()
        count = QLabel(f"{len(tier['tweaks'])} optimizations")
        count.setStyleSheet(f"color: {T['text_dim']}; font-size: 12px;")
        top.addWidget(count)
        outer.addLayout(top)

        desc = QLabel(tier["desc"])
        desc.setStyleSheet(f"color: {T['text']}; font-size: 13px;")
        outer.addWidget(desc)

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
        for i, key in enumerate(keys):
            tier = RAM_TIERS[key]
            card = RamTierCard(key, tier, ctx)
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
            card.setStyleSheet(
                card.styleSheet().replace("border: 2px solid " + T["accent"], "")
                if k != key else card.styleSheet()
            )
        # Highlight selected
        card = self._cards[key]
        card.setStyleSheet(
            f"QFrame#Card {{ border: 2px solid {T['accent']}; border-radius: 12px; "
            f"background: {T['card']}; }}"
        )
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
        pass
