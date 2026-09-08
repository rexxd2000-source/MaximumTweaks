"""Mandatory license-key gate screen.

Shown at every launch until a valid license session exists. Users without a
license never reach the main UI — the whole app is locked behind this screen.
Enter a key, activate it against the license server, and the app unlocks.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import (
    DISCORD_INVITE_URL,
    THEME as T,
    current_windows_user,
)
from engine import license as license_mgr
from ui.license import LicenseActivateWorker, publish_identity
from ui.widgets import qss_rgba, toast

ACCENT = T["accent"]


class GateWindow(QWidget):
    """Frameless fullscreen gate. Emits ``unlocked(session)`` once activated."""

    unlocked = Signal(object)

    def __init__(self, parent=None):
        # Plain top-level window: it may overlap the screen but NEVER stays
        # on top — the user must be able to tab out, minimize it, and have
        # other windows (e.g. the support page) come to the front.
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Window)
        self.setObjectName("GateWindow")
        self._busy = False
        self._license_worker = None
        self.setStyleSheet(
            "QWidget#GateWindow { background-color: #05070A; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 28, 40, 24)
        root.setSpacing(0)

        # ---- top bar: wordmark + status chip ----
        top = QHBoxLayout()
        wm = QLabel("MAXIMUM TWEAKS")
        wm.setStyleSheet(
            "color: #EEF4F8; font-size: 14px; font-weight: 900;"
            " letter-spacing: 4px;")
        top.addWidget(wm)
        top.addStretch()
        locked = QLabel("\u25cf LICENSE REQUIRED")
        locked.setStyleSheet(
            f"color: {T['warning']}; background: {qss_rgba(T['warning'], 0x1F)};"
            f" border: 1px solid {qss_rgba(T['warning'], 0x77)}; border-radius: 9px;"
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

        badge = QLabel("\u26d1")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(72, 72)
        badge.setStyleSheet(
            f"color: {ACCENT}; font-size: 34px; font-weight: 900;"
            f" background: {qss_rgba(ACCENT, 0x14)}; border: 1px solid {qss_rgba(ACCENT, 0x44)};"
            " border-radius: 36px;")
        pl.addWidget(badge, 0, Qt.AlignHCenter)

        title = QLabel("Activate Maximum Tweaks")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #F2F5F9; font-size: 26px; font-weight: 900;"
            " letter-spacing: 0.4px;")
        pl.addWidget(title)

        sub = QLabel(
            "Enter your license key to continue. This app is licensed per "
            "device \u2014 your key is bound to this PC the moment you activate.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color: {T['text_dim']}; font-size: 13px;")
        pl.addWidget(sub)

        pl.addSpacing(6)

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("MAX-XXXX-XXXX-XXXX")
        self.key_input.setAlignment(Qt.AlignCenter)
        self.key_input.setMinimumHeight(52)
        self.key_input.setMaxLength(20)
        self.key_input.setStyleSheet(
            "QLineEdit { background-color: #0D1219; border: 1px solid #26313E;"
            " border-radius: 12px; padding: 0 16px; font-size: 15px;"
            " font-weight: 800; letter-spacing: 2px; color: #F2F5F9; }"
            "QLineEdit:focus { border: 1px solid #8B5CF6; }")
        self.key_input.returnPressed.connect(self._on_activate)
        pl.addWidget(self.key_input)

        self.activate_btn = QPushButton("ACTIVATE LICENSE")
        self.activate_btn.setObjectName("Primary")
        self.activate_btn.setMinimumHeight(52)
        self.activate_btn.setStyleSheet(
            "QPushButton { font-size: 15px; font-weight: 900;"
            " letter-spacing: 0.4px; border-radius: 12px;"
            " padding: 0 22px; qproperty-cursor: pointinghand; }"
            "QPushButton:disabled { color: #6E8295; }")
        self.activate_btn.clicked.connect(self._on_activate)
        pl.addWidget(self.activate_btn)

        self.busy_label = QLabel("Contacting the license server \u2026")
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

        self.support_btn = QPushButton("Contact Support")
        self.support_btn.setObjectName("Ghost")
        self.support_btn.setCursor(Qt.PointingHandCursor)
        self.support_btn.clicked.connect(self._open_support)
        pl.addWidget(self.support_btn, 0, Qt.AlignHCenter)

        # Not-configured state: informative note only. A developer bypass is
        # NEVER part of the UI here — license_mgr.dev_bypass_enabled() is False
        # in any frozen (production) build.
        self.config_note = QLabel(
            "License server not configured. Set LICENSE_API_URL in "
            "config/app_config.py to require activation.")
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
            "Your license key is verified by the MAXIMUM TWEAKS license server. "
            "Only a hashed device fingerprint is sent \u2014 no personal data.")
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

    def _open_support(self):
        if not DISCORD_INVITE_URL:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(DISCORD_INVITE_URL))

    # ---------------- states ----------------

    def _refresh_config_state(self):
        configured = license_mgr.is_configured()
        self.key_input.setVisible(configured)
        self.activate_btn.setVisible(configured)
        self.config_note.setVisible(not configured)
        # Dev-only bypass: never visible in a production (frozen) build.
        self.owner_btn.setVisible(not configured
                                  and license_mgr.dev_bypass_enabled())

    def set_busy(self, busy: bool):
        self._busy = busy
        self.activate_btn.setEnabled(not busy)
        self.key_input.setEnabled(not busy)
        if busy:
            self.busy_label.show()
            self.error_label.hide()
        else:
            self.busy_label.hide()

    def _on_activate(self):
        if self._busy:
            return
        if not license_mgr.is_configured():
            return
        key = self.key_input.text().strip()
        if not key:
            self.error_label.setText("Please enter your license key.")
            self.error_label.show()
            return
        self.set_busy(True)
        worker = LicenseActivateWorker(key, self)
        self._license_worker = worker
        worker.done.connect(self._on_done)
        worker.start()

    def _on_done(self, sess, error):
        self.set_busy(False)
        self.error_label.hide()
        if error:
            self.error_label.setText(error)
            self.error_label.show()
            return
        if not sess:
            self.error_label.setText("The license server returned no session.")
            self.error_label.show()
            return
        try:
            publish_identity()
            toast(f"Welcome, {current_windows_user()} \u2014 license activated",
                  "success", self)
        finally:
            # Unlock no matter what so the gate never gets stuck on the key
            # prompt after a successful activation.
            self.unlocked.emit(sess)
