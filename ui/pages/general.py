"""General page — visual effects, privacy, telemetry, startup, power plans.
Uses sub-tabs to organize the 374+ tweaks into digestible groups.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from config.app_config import THEME as T
from database.tweaks import TWEAKS
from ui.categories import CATEGORY_GROUPS, group_tweaks, CATEGORY_LABELS
from ui.widgets import PageHeader, TweakCard, BatchWorker, clear_layout, toast, repolish
from ui.monitor_widgets import GlassCard


# Sub-tab definitions: label -> list of DB category group keys
_SUB_TABS = {
    "All": ["system", "power"],
    "Input": ["mouse", "keyboard"],
    "Display": ["display", "monitor"],
    "Audio": ["audio"],
    "Privacy": ["system"],
    "Power": ["power"],
    "Startup": ["system"],
    "Services": ["system"],
    "Storage": ["storage"],
    "USB": ["system"],
}


class GeneralPage(QWidget):
    """General system tweaks — visual effects, privacy, telemetry, startup, power."""

    def __init__(self, ctx, navigate=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._cards: list[TweakCard] = []
        self._current_tab = "All"

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._content = QWidget()
        self._main_layout = QVBoxLayout(self._content)
        self._main_layout.setContentsMargins(28, 24, 28, 24)
        self._main_layout.setSpacing(16)

        self._main_layout.addWidget(PageHeader(
            "General",
            "Windows visual effects, privacy toggles, telemetry, startup apps, and power plans."))

        # Sub-tab bar
        self._tab_bar = QHBoxLayout()
        self._tab_bar.setSpacing(6)
        self._tab_buttons: dict[str, QPushButton] = {}
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)

        for i, label in enumerate(_SUB_TABS):
            btn = QPushButton(label)
            btn.setObjectName("SegToggle")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            self._btn_group.addButton(btn, i)
            btn.clicked.connect(lambda _=False, l=label: self._switch_tab(l))
            self._tab_bar.addWidget(btn)
            self._tab_buttons[label] = btn
        self._tab_bar.addStretch()

        self._main_layout.addLayout(self._tab_bar)

        # Cards grid area
        self._grid_area = QWidget()
        self._grid_layout = QVBoxLayout(self._grid_area)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(12)
        self._main_layout.addWidget(self._grid_area, 1)

        # Set first tab active
        self._tab_buttons["All"].setChecked(True)
        repolish(self._tab_buttons["All"])

        scroll.setWidget(self._content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._load_cards()

    def _switch_tab(self, label: str):
        if label == self._current_tab:
            return
        self._current_tab = label
        for lbl, btn in self._tab_buttons.items():
            active = lbl == label
            if btn.property("active") != active:
                btn.setProperty("active", "true" if active else "false")
                repolish(btn)
        self._load_cards()

    def _load_cards(self):
        clear_layout(self._grid_layout)
        self._cards.clear()

        tab = self._current_tab
        if tab == "All":
            # Show a curated set from General categories
            cats = set()
            for gk in ("system", "power", "mouse", "keyboard", "audio",
                       "storage", "display", "monitor"):
                for db_cat in CATEGORY_GROUPS.get(gk, {}).get("db", []):
                    cats.add(db_cat)
            tweaks = [t for t in TWEAKS if t["category"] in cats][:40]
        else:
            group_keys = _SUB_TABS.get(tab, [])
            cats = set()
            for gk in group_keys:
                for db_cat in CATEGORY_GROUPS.get(gk, {}).get("db", []):
                    cats.add(db_cat)
            tweaks = [t for t in TWEAKS if t["category"] in cats][:30]

        if not tweaks:
            lbl = QLabel("No tweaks found for this category.")
            lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 13px; padding: 20px;")
            self._grid_layout.addWidget(lbl)
            return

        from PySide6.QtWidgets import QGridLayout
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, tweak in enumerate(tweaks):
            card = TweakCard(self.ctx, tweak)
            card.apply_requested.connect(self._on_apply)
            card.revert_requested.connect(self._on_revert)
            grid.addWidget(card, i // 2, i % 2)
            self._cards.append(card)
        self._grid_layout.addLayout(grid)
        self._grid_layout.addStretch()

    def _on_apply(self, tid):
        BatchWorker([tid], "apply", self).start()
        self.ctx.note_state_change()

    def _on_revert(self, tid):
        BatchWorker([tid], "revert", self).start()
        self.ctx.note_state_change()
