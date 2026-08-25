"""Network page — TCP/IP, DNS, adapter tweaks, bufferbloat reduction."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from config.app_config import THEME as T
from database.tweaks import TWEAKS
from ui.categories import CATEGORY_GROUPS
from ui.widgets import PageHeader, TweakCard, BatchWorker, clear_layout, repolish


_SUB_TABS = ["All", "TCP/IP", "DNS", "Ethernet", "Wi-Fi"]


class NetworkPage(QWidget):
    """Network tweaks — TCP/IP stack tuning, DNS, adapter settings, bufferbloat."""

    def __init__(self, ctx, navigate=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._cards: list[TweakCard] = []
        self._current_tab = "All"

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(28, 24, 28, 24)
        main.setSpacing(16)

        main.addWidget(PageHeader(
            "Network",
            "TCP/IP stack tuning, DNS optimization, adapter tweaks, and bufferbloat reduction."))

        tab_bar = QHBoxLayout()
        tab_bar.setSpacing(6)
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
            tab_bar.addWidget(btn)
            self._tab_buttons[label] = btn
        tab_bar.addStretch()
        main.addLayout(tab_bar)

        self._grid_area = QWidget()
        self._grid_layout = QVBoxLayout(self._grid_area)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(12)
        main.addWidget(self._grid_area, 1)

        self._tab_buttons["All"].setChecked(True)
        repolish(self._tab_buttons["All"])

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._load_cards()

    def _switch_tab(self, label):
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

        cats = set()
        for db_cat in ("Network", "Ethernet", "Wi-Fi"):
            cats.add(db_cat)
        tweaks = [t for t in TWEAKS if t["category"] in cats][:40]

        if not tweaks:
            lbl = QLabel("No network tweaks found.")
            lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 13px; padding: 20px;")
            self._grid_layout.addWidget(lbl)
            return

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
