"""Mandatory Discord-verification gate screen.

Shown at every launch until a Discord identity is attached. Users who are not
verified never reach the main UI \u2014 the whole app is locked behind it. The
owner keeps a dev bypass when Discord credentials are not yet configured.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import THEME as T
from engine import discord_auth
from ui.discord import DiscordLoginWorker, toast

ACCENT = T["accent"]


class GateWindow(QWidget):
    """Frameless fullscreen gate. Emits ``unlocked(profile)`` once verified."""

    unlocked = Signal(object)

    def __init__(self, parent=None):
        # Plain top-level window: it may overlap the screen but NEVER stays
        # on top — the user must be able to tab out, minimize it, and have
        # other windows (e.g. the Discord browser tab) come to the front.
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Window)
        self.setObjectName("GateWindow")
        self._busy = False
        self._discord_worker = None
        self.setStyleSheet(
            "QWidget#GateWindow { background-color: #05070A; }")

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
        locked = QLabel("\u25cf VERIFICATION REQUIRED")
        locked.setStyleSheet(
            f"color: {T['warning']}; background: {T['warning']}1F;"
            f" border: 1px solid {T['warning']}77; border-radius: 9px;"
            " padding: 4px 11px; font-size: 10px; font-weight: 800;"
            " letter-spacing: 0.8px;")
        top.addWidget(locked)
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

        badge = QLabel("\u25c9")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(72, 72)
        badge.setStyleSheet(
            f"color: {ACCENT}; font-size: 40px; font-weight: 900;"
            f" background: {ACCENT}14; border: 1px solid {ACCENT}44;"
            " border-radius: 36px;")
        pl.addWidget(badge, 0, Qt.AlignHCenter)

        title = QLabel("Verify to Unlock Rex Tweaks")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #F2F5F9; font-size: 26px; font-weight: 900;"
            " letter-spacing: 0.4px;")
        pl.addWidget(title)

        sub = QLabel(
            "Continue with Discord so we know you\u2019re a real person. "
            "Verified identity keeps abusers, bots and ban evaders out of the "
            "app and its community.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color: {T['text_dim']}; font-size: 13px;")
        pl.addWidget(sub)

        bullets = QLabel(
            "\u2022  One click, fully reversible\n"
            "\u2022  Your Discord avatar appears on your account card\n"
            "\u2022  Stable identity \u2014 not just a throwaway email")
        bullets.setStyleSheet(f"color: {T['text_faint']}; font-size: 12px;")
        pl.addWidget(bullets, 0, Qt.AlignHCenter)

        pl.addSpacing(8)

        self.verify_btn = QPushButton("\u25c9   Continue with Discord")
        self.verify_btn.setObjectName("Primary")
        self.verify_btn.setMinimumHeight(52)
        self.verify_btn.setStyleSheet(
            "QPushButton { font-size: 15px; font-weight: 900;"
            " letter-spacing: 0.4px; border-radius: 12px;"
            " padding: 0 22px; qproperty-cursor: pointinghand; }"
            "QPushButton:disabled { color: #6E8295; }")
        self.verify_btn.clicked.connect(self._on_verify)
        pl.addWidget(self.verify_btn, 0, Qt.AlignHCenter)

        self.busy_label = QLabel("Waiting for Discord in your browser \u2026")
        self.busy_label.setAlignment(Qt.AlignCenter)
        self.busy_label.setStyleSheet(
            f"color: {ACCENT}; font-size: 12px; font-weight: 700;")
        self.busy_label.hide()
        pl.addWidget(self.busy_label)

        self.manual_link = QPushButton("")
        self.manual_link.setObjectName("Ghost")
        self.manual_link.setCursor(Qt.PointingHandCursor)
        self.manual_link.clicked.connect(self._open_manual)
        self.manual_link.hide()
        pl.addWidget(self.manual_link, 0, Qt.AlignHCenter)

        self.error_label = QLabel("")
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(
            f"color: {T['danger']}; font-size: 12px; font-weight: 700;")
        self.error_label.hide()
        pl.addWidget(self.error_label)

        # Not-configured state: owner dev bypass so the app is never locked out.
        self.config_note = QLabel(
            "Discord verification is not configured. Set AUTH_SERVER_URL in "
            "config/app_config.py to require verification.")
        self.config_note.setAlignment(Qt.AlignCenter)
        self.config_note.setWordWrap(True)
        self.config_note.setStyleSheet(
            f"color: {T['warning']}; font-size: 11px;")
        self.config_note.hide()
        pl.addWidget(self.config_note)

        self.owner_btn = QPushButton("Enter as Owner (dev bypass)")
        self.owner_btn.setObjectName("Ghost")
        self.owner_btn.clicked.connect(lambda: self.unlocked.emit(None))
        self.owner_btn.hide()
        pl.addWidget(self.owner_btn, 0, Qt.AlignHCenter)

        note = QLabel(
            "Only metadata (Discord ID, username, verified flag) is stored "
            "locally in your Rex Tweaks data folder. Nothing is shared.")
        note.setAlignment(Qt.AlignCenter)
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {T['text_faint']}; font-size: 10.5px;")
        pl.addWidget(note)

        pw = QWidget()
        pw.setFixedWidth(560)
        pwl = QVBoxLayout(pw)
        pwl.setContentsMargins(0, 0, 0, 0)
        pwl.addWidget(panel)
        root.addWidget(pw, 0, Qt.AlignHCenter)

        root.addStretch(1)

        # ---- bottom bar ----
        bottom = QHBoxLayout()
        bottom.addStretch()
        quit_btn = QPushButton("Quit")
        quit_btn.setObjectName("Ghost")
        quit_btn.clicked.connect(lambda: self._quit())
        bottom.addWidget(quit_btn)
        root.addLayout(bottom)

        self._refresh_config_state()
        self._fade_in()

        # Owner escape hatch: Ctrl+Shift+O skips verification (dev).
        hotkey = QShortcut(QKeySequence("Ctrl+Shift+O"), self)
        hotkey.activated.connect(lambda: self.unlocked.emit(None))

    # ---------------- lifecycle ----------------

    def _fade_in(self):
        self.setWindowOpacity(0.0)
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(450)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _quit(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    def fade_out(self, duration_ms: int = 600, on_done=None):
        """Fade the gate away to reveal the unlocked app behind it."""
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(duration_ms)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _finish():
            self.hide()
            if on_done:
                on_done()
        anim.finished.connect(_finish)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # ---------------- states ----------------

    def _refresh_config_state(self):
        configured = discord_auth.is_configured()
        self.verify_btn.setVisible(configured)
        self.config_note.setVisible(not configured)
        self.owner_btn.setVisible(not configured)

    def set_busy(self, busy: bool):
        self._busy = busy
        self.verify_btn.setEnabled(not busy)
        if busy:
            self.busy_label.show()
            self.error_label.hide()
            self.manual_link.hide()
        else:
            self.busy_label.hide()

    def _on_verify(self):
        if self._busy:
            return
        if not discord_auth.is_configured():
            return
        self.set_busy(True)
        # Auto-open in the app's own browser opener from the UI thread, and
        # keep a manual fallback link in case it ever fails to surface.
        worker = DiscordLoginWorker(self, open_browser=False)
        self._discord_worker = worker
        worker.url_ready.connect(self._on_auth_url)
        worker.done.connect(self._on_done)
        worker.start()

    def _on_auth_url(self, url: str):
        self._auth_url = url
        self._open_browser_url(url)
        self.manual_link.setText("Browser didn't open? Click here to continue")
        self.manual_link.show()

    def _open_browser_url(self, url: str):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))

    def _open_manual(self):
        url = getattr(self, "_auth_url", "")
        if url:
            self._open_browser_url(url)

    def _on_done(self, profile, error):
        self.set_busy(False)
        self.error_label.hide()
        self.manual_link.hide()
        if error:
            self.error_label.setText(f"Verification failed: {error}")
            self.error_label.show()
            return
        if not profile and discord_auth.is_configured():
            self.error_label.setText("Verification returned no identity.")
            self.error_label.show()
            return
        toast(f"Welcome, {profile.get('name', '')} \u2014 identity verified",
              "success", self)
        self.unlocked.emit(profile)