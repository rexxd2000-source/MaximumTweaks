"""Full-screen disconnect landing: shown the moment a session drops.

Styled after the cinematic splash so leaving feels as intentional as booting:
a dark stage, the Rex mark, a random leaving quote, and a single prominent
"Verify with Discord" action to re-attach the identity and resume.
"""
from __future__ import annotations

import random

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import APP_VERSION, THEME as T
from engine import discord_auth
from ui.discord import login
from ui.monitor_widgets import RexLogo

ACCENT = T["accent"]

GOODBYE_QUOTES = [
    "Every optimization is a step toward glory \u2014 come back for the rest.",
    "The neon dims when you leave, but your tweaks are saved.",
    "Don't be gone for long \u2014 your rig misses you.",
    "The registry is quiet now. It won't stay that way.",
    "Farewell, pilot. Your settings are warm and waiting.",
    "Low latency, high standards \u2014 see you on the next boot.",
    "Even the best sessions deserve a proper sign-off.",
]


class GoodbyeScreen(QWidget):
    """Frameless fullscreen landing that replaces the app while signed out."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Window)
        self.ctx = ctx
        self._busy = False
        self._discord_worker = None
        self.setObjectName("GoodbyeScreen")
        self.setStyleSheet(
            "QWidget#GoodbyeScreen { background-color: #05070A; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 28, 40, 24)
        root.setSpacing(0)

        # ---- top bar: wordmark + status chip ----
        top = QHBoxLayout()
        wm = QLabel("REX TWEAKS")
        wm.setStyleSheet(
            "color: #EEF4F8; font-size: 14px; font-weight: 900;"
            " letter-spacing: 4px;")
        top.addWidget(wm)
        top.addStretch()
        chip = QLabel("\u25cf DISCONNECTED")
        chip.setStyleSheet(
            f"color: {T['warning']}; background: {T['warning']}1F;"
            f" border: 1px solid {T['warning']}77; border-radius: 9px;"
            " padding: 4px 11px; font-size: 10px; font-weight: 800;"
            " letter-spacing: 0.8px;")
        top.addWidget(chip)
        root.addLayout(top)

        root.addStretch(1)

        # ---- center panel ----
        panel = QFrame()
        panel.setObjectName("GatePanel")
        panel.setStyleSheet(
            "QFrame#GatePanel { background-color: #0B1016;"
            " border: 1px solid #1C2430; border-radius: 18px; }")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(44, 40, 44, 40)
        pl.setSpacing(12)

        pl.addWidget(RexLogo(72), 0, Qt.AlignHCenter)

        title = QLabel("Sad to See You Leave")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #F2F5F9; font-size: 26px; font-weight: 900;"
            " letter-spacing: 0.4px;")
        pl.addWidget(title)

        self.quote = QLabel("")
        self.quote.setAlignment(Qt.AlignCenter)
        self.quote.setWordWrap(True)
        self.quote.setStyleSheet(
            f"color: {T['text_dim']}; font-size: 14px;")
        pl.addWidget(self.quote)
        self.pick_quote()

        pl.addSpacing(6)

        sub = QLabel(
            "Disconnecting paused this session. Re-verify with Discord to "
            "re-attach your identity and pick up exactly where you left off.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {T['text_faint']}; font-size: 12px;")
        pl.addWidget(sub)

        pl.addSpacing(8)

        self.verify_btn = QPushButton("\u25c9   Verify with Discord")
        self.verify_btn.setObjectName("Primary")
        self.verify_btn.setMinimumHeight(52)
        self.verify_btn.setStyleSheet(
            "QPushButton { font-size: 15px; font-weight: 900;"
            " letter-spacing: 0.4px; border-radius: 12px;"
            " padding: 0 22px; qproperty-cursor: pointinghand; }"
            "QPushButton:disabled { color: #6E8295; }")
        self.verify_btn.clicked.connect(self._on_verify)
        pl.addWidget(self.verify_btn, 0, Qt.AlignHCenter)

        self.busy_label = QLabel("Opening Discord in your browser \u2026")
        self.busy_label.setAlignment(Qt.AlignCenter)
        self.busy_label.setStyleSheet(
            f"color: {ACCENT}; font-size: 12px; font-weight: 700;")
        self.busy_label.hide()
        pl.addWidget(self.busy_label)

        self.error_label = QLabel("")
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(
            f"color: {T['danger']}; font-size: 12px; font-weight: 700;")
        self.error_label.hide()
        pl.addWidget(self.error_label)

        self.config_note = QLabel(
            "Discord verification is not configured. Set AUTH_SERVER_URL in "
            "config/app_config.py to require verified sessions.")
        self.config_note.setAlignment(Qt.AlignCenter)
        self.config_note.setWordWrap(True)
        self.config_note.setStyleSheet(
            f"color: {T['warning']}; font-size: 11px;")
        self.config_note.hide()
        pl.addWidget(self.config_note)

        pw = QWidget()
        pw.setFixedWidth(560)
        pwl = QVBoxLayout(pw)
        pwl.setContentsMargins(0, 0, 0, 0)
        pwl.addWidget(panel)
        root.addWidget(pw, 0, Qt.AlignHCenter)

        root.addStretch(1)

        # ---- bottom bar ----
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel(f"REX ENGINE \u00b7 v{APP_VERSION}"),
                         alignment=Qt.AlignLeft)
        bottom.addStretch()
        quit_btn = QPushButton("Quit")
        quit_btn.setObjectName("Ghost")
        quit_btn.clicked.connect(lambda: self._quit())
        bottom.addWidget(quit_btn)
        root.addLayout(bottom)

        self._refresh_config_state()

    # ---------------- lifecycle ----------------

    def _quit(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    def pick_quote(self):
        self.quote.setText(random.choice(GOODBYE_QUOTES))

    # ---------------- states ----------------

    def _refresh_config_state(self):
        configured = discord_auth.is_configured()
        self.verify_btn.setVisible(configured)
        self.config_note.setVisible(not configured)

    def set_busy(self, busy: bool):
        self._busy = busy
        self.verify_btn.setEnabled(not busy)
        if busy:
            self.busy_label.show()
            self.error_label.hide()
        else:
            self.busy_label.hide()

    def _on_verify(self):
        if self._busy:
            return
        if not discord_auth.is_configured():
            return
        self.set_busy(True)
        self.error_label.hide()
        login(self.ctx, self)
