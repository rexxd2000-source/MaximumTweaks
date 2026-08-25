"""Global AI prompt bar — sits at the top of the center panel."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
    QVBoxLayout,
)

from config.app_config import THEME as T


class AIBar(QFrame):
    """Top-level AI assistant prompt input with send button."""

    prompt_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedHeight(56)
        self.setStyleSheet(
            f"#Card {{ background-color: {T['card']};"
            f" border: 1px solid {T['border']};"
            f" border-radius: 14px; }}")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 12, 0)
        lay.setSpacing(10)

        icon = QLabel("\u2728")
        icon.setStyleSheet(
            f"font-size: 18px; color: {T['accent']}; background: transparent;")
        lay.addWidget(icon)

        box = QVBoxLayout()
        box.setSpacing(0)
        title = QLabel("MAX Assistant")
        title.setStyleSheet(
            f"font-size: 11px; font-weight: 800; color: {T['text']};"
            " letter-spacing: 0.5px; background: transparent;")
        box.addWidget(title)

        self.input = QLineEdit()
        self.input.setPlaceholderText(
            "Ask anything — \"Fix my network ping\" or \"Remove bloatware\"")
        self.input.setStyleSheet(
            f"background: transparent; border: none; color: {T['text']};"
            " font-size: 13px; padding: 0;")
        self.input.returnPressed.connect(self._submit)
        box.addWidget(self.input)
        lay.addLayout(box, 1)

        send = QPushButton("\u27a4")
        send.setObjectName("Primary")
        send.setFixedSize(36, 36)
        send.setStyleSheet(
            f"QPushButton {{ background-color: {T['accent']};"
            f" color: {T['accent_dark']}; border: none; border-radius: 18px;"
            " font-size: 16px; font-weight: 800; }"
            f"QPushButton:hover {{ background-color: {T['accent_hover']}; }}")
        send.setCursor(Qt.PointingHandCursor)
        send.clicked.connect(self._submit)
        lay.addWidget(send, alignment=Qt.AlignVCenter)

    def _submit(self):
        text = self.input.text().strip()
        if text:
            self.prompt_submitted.emit(text)
            self.input.clear()
