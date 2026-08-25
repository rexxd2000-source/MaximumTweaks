"""Bottom recommended actions panel — contextual quick-action cards."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from config.app_config import THEME as T


class ActionCard(QFrame):
    """Clickable action card with icon, title and description."""

    clicked = Signal()

    def __init__(self, icon, title, desc, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(80)
        self.setStyleSheet(
            f"#Card {{ background-color: {T['card']};"
            f" border: 1px solid {T['border']};"
            f" border-radius: 12px; }}"
            f"#Card:hover {{ border-color: {T['accent']};"
            f" background-color: {T['card_alt']}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(8)
        ic = QLabel(icon)
        ic.setStyleSheet(
            f"font-size: 18px; color: {T['accent']}; background: transparent;")
        head.addWidget(ic)
        t = QLabel(title)
        t.setStyleSheet(
            f"font-size: 13px; font-weight: 800; color: {T['text']};"
            " background: transparent;")
        head.addWidget(t, 1)
        lay.addLayout(head)

        d = QLabel(desc)
        d.setStyleSheet(
            f"font-size: 11px; color: {T['text_dim']}; background: transparent;")
        d.setWordWrap(True)
        lay.addWidget(d)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ActionsPanel(QWidget):
    """Bottom bar with contextual quick-action cards."""

    action_triggered = Signal(str)

    # Default home-page actions
    HOME_ACTIONS = [
        ("\u2601", "Create Backup", "Save a restore point before changes"),
        ("\u26a1", "Quick Optimize", "Apply recommended tweaks for your hardware"),
        ("\u2139", "System Info", "View your hardware specifications"),
        ("\u26cf", "Run Fixes", "Scan and repair system issues"),
    ]

    # Actions mapped to specific categories
    CATEGORY_ACTIONS = {
        "backups": [
            ("\u2601", "Create Restore Point", "Save a Windows restore point"),
            ("\u2696", "Backup Registry", "Export current registry state"),
            ("\u21a9", "Restore Backup", "Roll back to a previous state"),
        ],
        "fixes": [
            ("\u26cf", "Run SFC", "System File Checker scan"),
            ("\u2699", "Run DISM", "Repair Windows component store"),
            ("\u2139", "Windows Update Fix", "Reset Windows Update components"),
        ],
        "general": [
            ("\u26a1", "Disable Telemetry", "Block Windows data collection"),
            ("\u2630", "Visual Tweaks", "Optimize Windows visual effects"),
            ("\u2139", "Power Plan", "Switch to high-performance power plan"),
        ],
        "hardware": [
            ("\u2b22", "CPU Optimization", "Apply CPU-specific tweaks"),
            ("\u25c6", "GPU Scheduling", "Enable hardware-accelerated GPU scheduling"),
            ("\u2588", "RAM Cleanup", "Optimize memory management"),
        ],
        "debloat": [
            ("\u2716", "Remove Bloat", "Scan and remove unwanted apps"),
            ("\u2139", "App Scan", "Identify removable UWP packages"),
            ("\u26cf", "Service Cleanup", "Disable unnecessary services"),
        ],
        "network": [
            ("\u2637", "Flush DNS", "Clear DNS resolver cache"),
            ("\u2139", "TCP Optimization", "Tune TCP/IP stack settings"),
            ("\u26cf", "DNS Benchmark", "Find the fastest DNS server"),
        ],
        "gamemode": [
            ("\u2605", "Game Launch", "Optimize and launch a game"),
            ("\u26a1", "FPS Boost", "Apply maximum FPS tweaks"),
            ("\u2139", "Timer Resolution", "Set high-resolution timer"),
        ],
        "advanced": [
            ("\u2699", "Registry Editor", "Open Windows Registry Editor"),
            ("\u26cf", "Group Policy", "Open Group Policy Editor"),
            ("\u2139", "BCD Edit", "Boot configuration options"),
        ],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(110)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        title = QLabel("QUICK ACTIONS")
        title.setStyleSheet(
            f"font-size: 10px; font-weight: 800; color: {T['text_faint']};"
            " letter-spacing: 2px; padding-left: 2px; background: transparent;")
        outer.addWidget(title)

        self._cards_layout = QHBoxLayout()
        self._cards_layout.setSpacing(10)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self._cards_layout)

        self._current_category = None
        self._cards: list[ActionCard] = []

    def set_category(self, category: str | None):
        """Update the action cards to match the current sidebar category."""
        if category == self._current_category:
            return
        self._current_category = category
        self._clear_cards()

        actions = self.CATEGORY_ACTIONS.get(category, self.HOME_ACTIONS)
        for icon, title, desc in actions:
            card = ActionCard(icon, title, desc)
            card.clicked.connect(lambda t=title: self.action_triggered.emit(t))
            self._cards_layout.addWidget(card)
            self._cards.append(card)
        self._cards_layout.addStretch()

    def _clear_cards(self):
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        # remove the stretch
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
