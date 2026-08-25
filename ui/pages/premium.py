"""Premium page — premium/locked features placeholder."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from config.app_config import THEME as T
from ui.widgets import PageHeader
from ui.monitor_widgets import GlassCard


class PremiumPage(QWidget):
    """Premium features — locked behind a license key."""

    def __init__(self, ctx, navigate=None, parent=None):
        super().__init__(parent)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        layout.addWidget(PageHeader(
            "Premium",
            "Exclusive premium features for licensed users."))

        # Coming soon card
        card = GlassCard()
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(24, 24, 24, 24)
        card_lay.setSpacing(16)

        icon = QLabel("\u2b50")
        icon.setStyleSheet(f"font-size: 48px; background: transparent;")
        card_lay.addWidget(icon, alignment=Qt.AlignHCenter)

        title = QLabel("Premium Features Coming Soon")
        title.setStyleSheet(
            f"font-size: 20px; font-weight: 900; color: {T['text']};")
        title.setAlignment(Qt.AlignHCenter)
        card_lay.addWidget(title)

        desc = QLabel(
            "Premium users will get access to advanced optimization profiles, "
            "AI-powered system analysis, priority support, and exclusive "
            "game profiles. Stay tuned for updates.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {T['text_dim']}; font-size: 13px;")
        desc.setAlignment(Qt.AlignHCenter)
        card_lay.addWidget(desc)

        layout.addWidget(card)
        layout.addStretch()

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
