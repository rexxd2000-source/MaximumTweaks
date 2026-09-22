"""Mandatory license gate: activation / banned / timeout / key-revoked.

Port of the four reference HTML screens (01-boot-activation, 02-banned,
03-timeout, 04-key-revoked) into the PySide6 app. Shown at every launch until
a valid license session exists, and re-shown the instant the heartbeat learns
the key was banned / revoked / suspended mid-session — no restart required.

Pages (QStackedWidget):
  * activation — key entry + "reconnect to verify" flows.
  * banned     — the operator permanently banned this account (red).
  * timeout    — temporary suspension with a live countdown that auto-unlocks
                 when the timer reaches zero (amber).
  * revoked    — a staff member revoked this key (magenta).

The page is chosen from the structured ``payload`` returned by the server when
it refuses a key (see engine.license.last_refusal()).
"""
from __future__ import annotations

import time as _time
from datetime import datetime, timezone

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.app_config import (
    APP_VERSION,
    DISCORD_INVITE_URL,
    current_windows_user,
)
from engine import license as license_mgr
from ui.license import LicenseActivateWorker, LicenseHeartbeatWorker, \
    publish_identity, mask_key
from ui.monitor_widgets import AppLogo
from ui.widgets import qss_rgba, toast

MONO = '"JetBrains Mono", "Cascadia Mono", monospace'
DISPLAY = '"Space Grotesk", "Segoe UI", sans-serif'

# ---------------------------------------------------------------------------
# Shared chrome (topbar brand + live clock, footer statusbar)
# ---------------------------------------------------------------------------

class _TopBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(32, 22, 32, 22)
        lay.setSpacing(10)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        mark = AppLogo(size=26)
        brand.addWidget(mark)
        word = QLabel("Maximum Tweaks")
        word.setStyleSheet(
            f"font-family: {DISPLAY}; font-weight: 600; font-size: 14px;"
            f" color: #eae7f8;")
        brand.addWidget(word)
        lay.addLayout(brand)

        lay.addStretch()

        self.clock = QLabel("00:00:00")
        self.clock.setStyleSheet(
            f"font-family: {MONO}; font-size: 12px;"
            f" letter-spacing: .08em; color: #524d6b;")
        lay.addWidget(self.clock)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    def _tick(self):
        self.clock.setText(_time.strftime("%H:%M:%S"))


class _Footer(QWidget):
    def __init__(self, pill_text: str, pill_color: str,
                 pill_dot: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Foot")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 14, 28, 14)
        lay.setSpacing(12)
        ver = QLabel(f"MAXIMUM ENGINE \u00b7 v{APP_VERSION}")
        ver.setStyleSheet(
            f"font-family: {MONO}; font-size: 11px;"
            f" letter-spacing: .04em; color: #524d6b;")
        lay.addWidget(ver)
        lay.addStretch()

        self.pill = QFrame()
        self.pill.setObjectName("PulsePill")
        self.pill.setFrameShape(QFrame.Shape.NoFrame)  # never double-draw a native frame
        self.pill.setLineWidth(0)
        pl = QHBoxLayout(self.pill)
        pl.setContentsMargins(10, 5, 10, 5)
        pl.setSpacing(6)
        self.dot = QLabel("\u25cf")
        pl.addWidget(self.dot)
        self.txt = QLabel(pill_text)
        pl.addWidget(self.txt)
        lay.addWidget(self.pill)

        self.set_pill(pill_text, pill_color, pill_dot)

    def set_pill(self, pill_text: str, pill_color: str, pill_dot: str):
        self.pill.setStyleSheet(
            "QFrame#PulsePill { background: transparent;"
            f" border: 1px solid {qss_rgba(pill_dot, 90)};"
            f" border-radius: 12px; }}")
        self.dot.setStyleSheet(f"color: {pill_dot}; font-size: 8px;")
        self.txt.setText(pill_text)
        self.txt.setStyleSheet(
            f"font-family: {MONO}; font-size: 10px;"
            f" letter-spacing: .06em; color: {pill_color};")


# ---------------------------------------------------------------------------
# Field blocks (REASON / KEY / BAN ID / dates) reused by the status pages
# ---------------------------------------------------------------------------

class _ProgressBar(QWidget):
    """Self-painting progress track (fill width always tracks its own size,
    so it never depends on sibling-layout timing)."""

    def __init__(self, fill_from, fill_to, track="rgba(255,179,64,.12)",
                 height=4, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self._fill_from = fill_from
        self._fill_to = fill_to
        self._fraction = 1.0
        self._track = QColor(track)

    def set_fraction(self, fraction: float):
        self._fraction = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QColor, QLinearGradient, QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(self._track)
        p.drawRoundedRect(0, 0, w, h, 2, 2)
        fw = int(w * self._fraction)
        if fw <= 0:
            return
        g = QLinearGradient(0, 0, fw, 0)
        g.setColorAt(0.0, QColor(self._fill_from))
        g.setColorAt(1.0, QColor(self._fill_to))
        p.setBrush(g)
        p.drawRoundedRect(0, 0, fw, h, 2, 2)


class _Field(QFrame):
    """Labled value block like the HTML .field: dark inset, tiny uppercase key."""

    def __init__(self, key_text: str, value_text: str = "—",
                 key_color="#524d6b", value_color="#eae7f8",
                 border="rgba(139,124,246,.18)", parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background: rgba(0,0,0,.32); border: 1px solid {border};"
            f" border-radius: 10px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)
        k = QLabel(key_text)
        k.setStyleSheet(
            f"font-family: {MONO}; font-size: 10px;"
            f" letter-spacing: .14em; color: {key_color};")
        lay.addWidget(k)
        self.value = QLabel(value_text)
        self.value.setWordWrap(True)
        self.value.setStyleSheet(
            f"font-family: {DISPLAY}; font-size: 13px; color: {value_color};"
            f" line-height: 1.55;")
        lay.addWidget(self.value)

    def set_value(self, text: str):
        self.value.setText(text or "—")


class _MetaField(_Field):
    """Half-width field used in the BAN ID / ISSUED / REVOKED-BY rows."""

    def __init__(self, key_text: str, value_text: str = "—",
                 border="rgba(139,124,246,.18)", parent=None):
        super().__init__(key_text, value_text, border=border, parent=parent)


# ---------------------------------------------------------------------------
# Page: activation (key entry + reconnect-to-verify)
# ---------------------------------------------------------------------------

class _ActivationPage(QWidget):
    activate_requested = Signal(str)      # key text
    retry_requested = Signal()            # reconnect-to-verify round
    support_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._formatting = False
        lay = QVBoxLayout(self)
        lay.addStretch(1)

        card = QFrame()
        card.setObjectName("ActivationCard")
        card.setFixedWidth(420)
        card.setFrameShape(QFrame.Shape.NoFrame)
        card.setLineWidth(0)
        card.setStyleSheet(
            "QFrame#ActivationCard {"
            " background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "   stop:0 #141026, stop:1 #100d1c);"
            " border: 1px solid rgba(139,124,246,.16); border-radius: 16px; }")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(34, 38, 34, 30)
        cl.setSpacing(0)

        icon = QLabel("\u26ed")
        icon.setFixedSize(46, 46)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            f"color: #9f7bff; font-size: 20px; border-radius: 12px;"
            f" background: qradialgradient(cx:.3,cy:.25,radius:1,"
            f"   fx:.3,fy:.25, stop:0 rgba(159,123,255,.35),"
            f"   stop:1 rgba(124,92,255,.08));"
            f" border: 1px solid rgba(139,124,246,.32);")
        cl.addWidget(icon, 0, Qt.AlignHCenter)
        cl.addSpacing(18)

        title = QLabel("Activate Maximum Tweaks")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-family: {DISPLAY}; font-weight: 600; font-size: 20px;"
            f" letter-spacing: -0.01em; color: #eae7f8;")
        cl.addWidget(title)
        cl.addSpacing(10)

        desc = QLabel(
            "Enter your license key to continue. This app is licensed per "
            "device \u2014 your key binds to this PC the moment you activate.")
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-family: {MONO}; font-size: 12.5px; line-height: 1.6;"
            f" color: #8b87a3;")
        desc.setMinimumHeight(desc.heightForWidth(card.width() - 68))
        cl.addWidget(desc)
        cl.addSpacing(24)

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        self.key_input.setAlignment(Qt.AlignCenter)
        self.key_input.setMinimumHeight(48)
        self.key_input.setMaxLength(19)
        self.key_input.setStyleSheet(
            f"QLineEdit {{ background: rgba(0,0,0,.35);"
            f" border: 1px solid rgba(139,124,246,.32); border-radius: 10px;"
            f" padding: 0 16px; font-family: {MONO}; font-size: 14px;"
            f" letter-spacing: .08em; color: #eae7f8; }}"
            f"QLineEdit:focus {{ border: 1px solid #9f7bff;"
            f" background: rgba(0,0,0,.4); }}")
        self.key_input.returnPressed.connect(self._emit_activate)
        self.key_input.textChanged.connect(self.format_key)
        cl.addWidget(self.key_input)

        self.activate_btn = QPushButton("Activate license")
        self.activate_btn.setCursor(Qt.PointingHandCursor)
        self.activate_btn.setMinimumHeight(46)
        self.activate_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "   stop:0 #7c5cff, stop:1 #4c2fb8); color: #fff; border: none;"
            " border-radius: 10px; font-family: " + DISPLAY +
            "; font-weight: 600; font-size: 14.5px; }"
            "QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "   stop:0 #8a6cff, stop:1 #5a3cc8); }"
            "QPushButton:pressed { background: #4c2fb8; }"
            "QPushButton:disabled { opacity: .6; }")
        self.activate_btn.clicked.connect(self._emit_activate)
        cl.addSpacing(14)
        cl.addWidget(self.activate_btn)

        # Reconnect-to-verify block: shown instead of the key prompt when a
        # session exists but the 30-day offline grace has run out.
        self.reconnect_box = QFrame()
        self.reconnect_box.setStyleSheet(
            "QFrame { background: rgba(0,0,0,.32);"
            " border: 1px solid rgba(139,124,246,.26); border-radius: 12px; }")
        rl = QVBoxLayout(self.reconnect_box)
        rl.setContentsMargins(20, 16, 20, 16)
        rl.setSpacing(10)

        rt = QLabel("RECONNECT TO VERIFY")
        rt.setAlignment(Qt.AlignCenter)
        rt.setStyleSheet(
            f"font-family: {MONO}; font-size: 11px; font-weight: 600;"
            f" letter-spacing: .12em; color: #9f7bff;")
        rl.addWidget(rt)

        rd = QLabel(
            "This license has not been confirmed by the license server in "
            "over 30 days. Connect to the internet and try again \u2014 once "
            "the server answers, Maximum Tweaks unlocks right away.")
        rd.setAlignment(Qt.AlignCenter)
        rd.setWordWrap(True)
        rd.setStyleSheet(
            f"font-family: {MONO}; font-size: 12.5px; color: #8b87a3;")
        rl.addWidget(rd)

        self.reconnect_btn = QPushButton("Try again")
        self.reconnect_btn.setCursor(Qt.PointingHandCursor)
        self.reconnect_btn.setMinimumHeight(42)
        self.reconnect_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "   stop:0 #7c5cff, stop:1 #4c2fb8); color: #fff; border: none;"
            " border-radius: 10px; font-family: " + DISPLAY +
            "; font-weight: 600; font-size: 13px; }")
        self.reconnect_btn.clicked.connect(self.retry_requested.emit)
        rl.addWidget(self.reconnect_btn)

        self.reconnect_status = QLabel("")
        self.reconnect_status.setAlignment(Qt.AlignCenter)
        self.reconnect_status.setWordWrap(True)
        self.reconnect_status.setStyleSheet(
            f"font-family: {MONO}; font-size: 12px; color: #ff6b7a;")
        self.reconnect_status.hide()
        rl.addWidget(self.reconnect_status)

        self.reconnect_box.hide()
        cl.addWidget(self.reconnect_box)

        # Inline feedback line (busy / error / success).
        self.feedback = QLabel("")
        self.feedback.setAlignment(Qt.AlignCenter)
        self.feedback.setWordWrap(True)
        self.feedback.setStyleSheet(
            f"font-family: {MONO}; font-size: 12px; color: #ff6b7a;")
        self.feedback.hide()
        cl.addWidget(self.feedback)
        cl.addSpacing(8)

        support = QPushButton("Contact support")
        support.setCursor(Qt.PointingHandCursor)
        support.setFlat(True)
        support.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            " color: #8b87a3; font-family: " + MONO +
            "; font-size: 12px; }"
            "QPushButton:hover { color: #9f7bff; }")
        support.clicked.connect(self.support_requested.emit)
        cl.addWidget(support, 0, Qt.AlignHCenter)
        cl.addSpacing(20)

        fine = QLabel(
            "Your license key is verified by the Maximum Tweaks license "
            "server. Only a hashed device fingerprint is sent \u2014 no "
            "personal data.")
        fine.setAlignment(Qt.AlignCenter)
        fine.setWordWrap(True)
        fine.setStyleSheet(
            f"font-family: {MONO}; font-size: 11px; line-height: 1.7;"
            f" color: #524d6b; border-top: 1px solid rgba(139,124,246,.16);"
            f" padding-top: 16px;")
        fine.setMinimumHeight(fine.heightForWidth(card.width() - 68) + 30)
        cl.addWidget(fine)
        cl.addSpacing(8)

        # Not-configured note (dev only; never visible in a frozen build).
        self.config_note = QLabel(
            "License server not configured. Set LICENSE_API_URL in "
            "config/app_config.py to require activation.")
        self.config_note.setAlignment(Qt.AlignCenter)
        self.config_note.setWordWrap(True)
        self.config_note.setStyleSheet(
            f"font-family: {MONO}; font-size: 11px; color: #c9b564;")
        self.config_note.hide()
        cl.addWidget(self.config_note)

        lay.addWidget(card, 1, Qt.AlignHCenter)
        lay.addStretch(1)

    def _emit_activate(self):
        key = self.key_input.text().strip()
        if not key:
            self.show_feedback("Enter your license key.", error=True)
            return
        self.activate_requested.emit(key)

    def set_busy(self, busy: bool):
        self.activate_btn.setEnabled(not busy)
        self.key_input.setEnabled(not busy)
        self.reconnect_btn.setEnabled(not busy)
        if busy:
            self.show_feedback("Verifying with license server \u2026",
                               busy=True, error=False)
        elif not self._has_error:
            self.feedback.hide()

    def show_feedback(self, text: str, error: bool = False,
                      busy: bool = False):
        self._has_error = error
        if busy:
            self.feedback.setStyleSheet(
                f"font-family: {MONO}; font-size: 12px; color: #9f7bff;")
        else:
            self.feedback.setStyleSheet(
                f"font-family: {MONO}; font-size: 12px; color: "
                + ("#ff6b7a;" if error else "#3fd68f;"))
        self.feedback.setText(text)
        self.feedback.show()

    def hide_feedback(self):
        self._has_error = False
        self.feedback.hide()

    def format_key(self, text: str = ""):
        """Live format the key as XXXX-XXXX-XXXX-XXXX while the user types."""
        if self._formatting:
            return
        self._formatting = True
        try:
            raw = "".join(ch for ch in self.key_input.text().upper()
                          if ch.isalnum())[:16]
            if len(raw) < 12:
                groups = [raw[i:i + 4] for i in range(0, len(raw), 4)]
                self.key_input.setText("-".join(groups))
                return
            groups = [raw[i:i + 4] for i in range(0, len(raw), 4)]
            self.key_input.setText("-".join(groups))
        finally:
            self._formatting = False


# ---------------------------------------------------------------------------
# Page: timeout (live countdown handled by the gate)
# ---------------------------------------------------------------------------

class _TimeoutPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._total_seconds = 0
        lay = QVBoxLayout(self)
        lay.addStretch(1)

        WARN = "#ffb340"
        WARN_2 = "#e2951f"
        WARN_DEEP = "#7a4d12"
        BORDER = "rgba(255,176,64,.18)"

        card = QFrame()
        card.setFixedWidth(440)
        card.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "   stop:0 #1c150d, stop:1 #16110c);"
            f" border: 1px solid {BORDER}; border-radius: 16px; }}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(36, 40, 36, 30)
        cl.setSpacing(0)

        icon = QLabel("\u23f3")
        icon.setFixedSize(56, 56)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            f"color: {WARN}; font-size: 24px; border-radius: 14px;"
            f" background: qradialgradient(cx:.3,cy:.25,radius:1,"
            f"   fx:.3,fy:.25, stop:0 rgba(255,179,64,.4), stop:1 rgba(226,149,31,.08));"
            f" border: 1px solid rgba(255,176,64,.38);")
        cl.addWidget(icon, 0, Qt.AlignHCenter)
        cl.addSpacing(20)

        title = QLabel("Your key is on timeout")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-family: {DISPLAY}; font-weight: 700; font-size: 22px;"
            f" color: #f6efe6;")
        cl.addWidget(title)
        cl.addSpacing(8)

        self.sub = QLabel(
            "Access is temporarily suspended. It will restore automatically "
            "when the timer reaches zero.")
        self.sub.setAlignment(Qt.AlignCenter)
        self.sub.setWordWrap(True)
        self.sub.setStyleSheet(
            f"font-family: {MONO}; font-size: 12.5px; color: #a99a86;")
        cl.addWidget(self.sub)
        cl.addSpacing(28)

        self.countdown = QLabel("00:00:00")
        self.countdown.setAlignment(Qt.AlignCenter)
        self.countdown.setStyleSheet(
            f"font-family: {DISPLAY}; font-weight: 700; font-size: 52px;"
            f" color: {WARN}; letter-spacing: .02em;")
        cl.addWidget(self.countdown)

        cd_label = QLabel("TIME REMAINING")
        cd_label.setAlignment(Qt.AlignCenter)
        cd_label.setStyleSheet(
            f"font-family: {MONO}; font-size: 11px;"
            f" letter-spacing: .2em; color: #5c5142;")
        cl.addWidget(cd_label)
        cl.addSpacing(26)

        self.bar = _ProgressBar("#7a4d12", "#ffb340",
                                track="rgba(255,179,64,.12)", height=4)
        cl.addWidget(self.bar)
        cl.addSpacing(22)

        self.reason_field = _Field("REASON", "—", key_color="#5c5142",
                                   value_color="#ffd699", border=BORDER)
        cl.addWidget(self.reason_field)

        self.key_field = _Field("KEY", "—", key_color="#5c5142",
                                value_color="#f6efe6", border=BORDER)
        cl.addWidget(self.key_field)

        self.note = QLabel(
            "No action is needed. Keep this window open and Maximum Tweaks "
            "will unlock automatically once the timeout ends.")
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setWordWrap(True)
        self.note.setStyleSheet(
            f"font-family: {MONO}; font-size: 11.5px; line-height: 1.6;"
            f" color: #5c5142; border-top: 1px solid {BORDER};"
            f" padding-top: 16px;")
        cl.addWidget(self.note)

        lay.addWidget(card, 0, Qt.AlignHCenter)
        lay.addStretch(1)

    def configure(self, total_seconds: int, reason: str, masked_key: str):
        self._total_seconds = max(1, total_seconds)
        self.reason_field.set_value(reason)
        self.key_field.set_value(masked_key)
        self._render(self._total_seconds)

    def _render(self, remaining: int):
        h = remaining // 3600
        m = (remaining % 3600) // 60
        s = remaining % 60
        self.countdown.setText(f"{h:02d}:{m:02d}:{s:02d}")
        pct = max(0.0, min(1.0, remaining / self._total_seconds))
        self.bar.set_fraction(pct)

    def tick(self, remaining: int):
        if remaining <= 0:
            self.countdown.setText("00:00:00")
            self.bar.set_fraction(0.0)
            self.sub.setText("Timeout complete. Access has been restored.")
            return
        self._render(remaining)


# ---------------------------------------------------------------------------
# Page: banned
# ---------------------------------------------------------------------------

class _BannedPage(QWidget):
    support_requested = Signal()
    appeal_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        DANGER = "#ff4d63"
        DANGER_2 = "#e21f3e"
        DANGER_DEEP = "#7a1226"
        BORDER = "rgba(255,90,110,.18)"

        lay = QVBoxLayout(self)
        lay.addStretch(1)

        card = QFrame()
        card.setFixedWidth(460)
        card.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "   stop:0 #170f16, stop:1 #120c14);"
            f" border: 1px solid {BORDER}; border-radius: 16px; }}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(36, 40, 36, 30)
        cl.setSpacing(0)

        icon = QLabel("\u26d4")
        icon.setFixedSize(56, 56)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            f"color: {DANGER}; font-size: 24px; border-radius: 14px;"
            f" background: qradialgradient(cx:.3,cy:.25,radius:1,"
            f"   fx:.3,fy:.25, stop:0 rgba(255,77,99,.4), stop:1 rgba(226,31,62,.08));"
            f" border: 1px solid rgba(255,90,110,.38);")
        cl.addWidget(icon, 0, Qt.AlignHCenter)
        cl.addSpacing(20)

        title = QLabel("You have been banned")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-family: {DISPLAY}; font-weight: 700; font-size: 22px;"
            f" color: #f4eef0;")
        cl.addWidget(title)
        cl.addSpacing(8)

        sub = QLabel("This account is permanently blocked from Maximum Tweaks.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"font-family: {MONO}; font-size: 12.5px; color: #a68b90;")
        cl.addWidget(sub)
        cl.addSpacing(26)

        self.reason_field = _Field("REASON", "—", key_color="#5c4a4e",
                                   value_color="#ffb3bd", border=BORDER)
        cl.addWidget(self.reason_field)
        cl.addSpacing(12)

        meta = QHBoxLayout()
        meta.setSpacing(12)
        self.ban_id_field = _MetaField("BAN ID", "—", border=BORDER)
        self.ban_date_field = _MetaField("ISSUED", "—", border=BORDER)
        meta.addWidget(self.ban_id_field)
        meta.addWidget(self.ban_date_field)
        cl.addLayout(meta)
        cl.addSpacing(18)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        read_btn = QPushButton("Read appeal policy")
        read_btn.setCursor(Qt.PointingHandCursor)
        read_btn.setStyleSheet(
            "QPushButton { background: rgba(255,77,99,.06);"
            " color: #f4eef0; border: 1px solid rgba(255,90,110,.38);"
            " border-radius: 10px; font-family: " + DISPLAY +
            "; font-weight: 600; font-size: 13px; }"
            "QPushButton:hover { background: rgba(255,77,99,.14); }")
        read_btn.clicked.connect(self.support_requested.emit)
        actions.addWidget(read_btn)

        appeal_btn = QPushButton("Submit appeal")
        appeal_btn.setCursor(Qt.PointingHandCursor)
        appeal_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "   stop:0 #e21f3e, stop:1 #7a1226); color: #fff; border: none;"
            " border-radius: 10px; font-family: " + DISPLAY +
            "; font-weight: 600; font-size: 13px; }")
        appeal_btn.clicked.connect(self.appeal_requested.emit)
        actions.addWidget(appeal_btn)

        cl.addLayout(actions)
        cl.addSpacing(18)

        note = QLabel(
            "Bans are enforced per device and account. Attempting to bypass "
            "this ban may result in permanent denial of any future appeal.")
        note.setAlignment(Qt.AlignCenter)
        note.setWordWrap(True)
        note.setStyleSheet(
            f"font-family: {MONO}; font-size: 11.5px; line-height: 1.6;"
            f" color: #5c4a4e; border-top: 1px solid {BORDER};"
            f" padding-top: 16px;")
        cl.addWidget(note)

        lay.addWidget(card, 0, Qt.AlignHCenter)
        lay.addStretch(1)

    def configure(self, payload: dict):
        reason = payload.get("reason") or (
            "Use of an unauthorized configuration alongside Maximum Tweaks.")
        self.reason_field.set_value(reason)
        self.ban_id_field.set_value(self._ban_id(payload))
        self.ban_date_field.set_value(self._issued(payload))

    @staticmethod
    def _ban_id(payload: dict) -> str:
        revoked_at = payload.get("revoked_at") or ""
        if revoked_at:
            digest = revoked_at.replace("-", "").replace(" ", "")[:8]
            return f"BAN-{digest.upper()}"
        return "—"

    @staticmethod
    def _issued(payload: dict) -> str:
        revoked_at = payload.get("revoked_at") or ""
        if not revoked_at:
            return "—"
        try:
            dt = datetime.strptime(revoked_at, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%b %d, %Y")
        except Exception:  # noqa: BLE001
            return revoked_at


# ---------------------------------------------------------------------------
# Page: key revoked
# ---------------------------------------------------------------------------

class _RevokedPage(QWidget):
    support_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        MAG = "#c66eff"
        MAG_2 = "#a238e8"
        MAG_DEEP = "#4c1573"
        RED_EDGE = "#ff4d63"
        BORDER = "rgba(196,110,255,.18)"

        lay = QVBoxLayout(self)
        lay.addStretch(1)

        card = QFrame()
        card.setFixedWidth(440)
        card.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "   stop:0 #150f22, stop:1 #100d1c);"
            f" border: 1px solid {BORDER}; border-radius: 16px; }}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(36, 40, 36, 30)
        cl.setSpacing(0)

        icon = QLabel("\U0001f511")
        icon.setFixedSize(56, 56)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            f"color: {MAG}; font-size: 24px; border-radius: 14px;"
            f" background: qradialgradient(cx:.3,cy:.25,radius:1,"
            f"   fx:.3,fy:.25, stop:0 rgba(198,110,255,.4), stop:1 rgba(162,56,232,.08));"
            f" border: 1px solid rgba(196,110,255,.38);")
        cl.addWidget(icon, 0, Qt.AlignHCenter)
        cl.addSpacing(20)

        title = QLabel("License key revoked")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-family: {DISPLAY}; font-weight: 700; font-size: 22px;"
            f" color: #efe7f8;")
        cl.addWidget(title)
        cl.addSpacing(8)

        sub = QLabel(
            "A Maximum staff member has revoked this key. It can no longer "
            "activate the app on any device.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"font-family: {MONO}; font-size: 12.5px; color: #988aa3;")
        cl.addWidget(sub)
        cl.addSpacing(26)

        self.key_display = QFrame()
        self.key_display.setStyleSheet(
            f"background: rgba(0,0,0,.32); border: 1px solid {BORDER};"
            f" border-radius: 10px;")
        kl = QVBoxLayout(self.key_display)
        kl.setContentsMargins(16, 14, 16, 14)
        kl.setSpacing(8)
        kk = QLabel("REVOKED KEY")
        kk.setAlignment(Qt.AlignCenter)
        kk.setStyleSheet(
            f"font-family: {MONO}; font-size: 10px;"
            f" letter-spacing: .14em; color: #524a5c;")
        kl.addWidget(kk)
        self.revoked_key = QLabel("—")
        self.revoked_key.setAlignment(Qt.AlignCenter)
        self.revoked_key.setStyleSheet(
            f"font-family: {MONO}; font-size: 17px; letter-spacing: .12em;"
            f" color: #988aa3;")
        canceled = self.revoked_key.font()
        canceled.setStrikeOut(True)
        self.revoked_key.setFont(canceled)
        kl.addWidget(self.revoked_key)
        cl.addWidget(self.key_display)
        cl.addSpacing(18)

        self.reason_field = _Field("REASON", "—", key_color="#524a5c",
                                   value_color="#e6bfff", border=BORDER)
        cl.addWidget(self.reason_field)
        cl.addSpacing(12)

        meta = QHBoxLayout()
        meta.setSpacing(12)
        self.revoked_by_field = _MetaField("REVOKED BY", "Staff",
                                           border=BORDER)
        self.revoked_on_field = _MetaField("REVOKED ON", "—", border=BORDER)
        meta.addWidget(self.revoked_by_field)
        meta.addWidget(self.revoked_on_field)
        cl.addLayout(meta)
        cl.addSpacing(18)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        support_btn = QPushButton("Contact support")
        support_btn.setCursor(Qt.PointingHandCursor)
        support_btn.setStyleSheet(
            "QPushButton { background: rgba(198,110,255,.06);"
            " color: #efe7f8; border: 1px solid rgba(196,110,255,.38);"
            " border-radius: 10px; font-family: " + DISPLAY +
            "; font-weight: 600; font-size: 13px; }"
            "QPushButton:hover { background: rgba(198,110,255,.14); }")
        support_btn.clicked.connect(self.support_requested.emit)
        actions.addWidget(support_btn)

        new_key_btn = QPushButton("Request new key")
        new_key_btn.setCursor(Qt.PointingHandCursor)
        new_key_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"   stop:0 {MAG_2}, stop:1 {MAG_DEEP}); color: #fff; border: none;"
            " border-radius: 10px; font-family: " + DISPLAY +
            "; font-weight: 600; font-size: 13px; }")
        new_key_btn.clicked.connect(self.support_requested.emit)
        actions.addWidget(new_key_btn)

        cl.addLayout(actions)
        cl.addSpacing(18)

        note = QLabel(
            "If you believe this was a mistake, contact support with your "
            "order reference so it can be reviewed.")
        note.setAlignment(Qt.AlignCenter)
        note.setWordWrap(True)
        note.setStyleSheet(
            f"font-family: {MONO}; font-size: 11.5px; line-height: 1.6;"
            f" color: #524a5c; border-top: 1px solid {BORDER};"
            f" padding-top: 16px;")
        cl.addWidget(note)

        lay.addWidget(card, 0, Qt.AlignHCenter)
        lay.addStretch(1)

    def configure(self, payload: dict):
        sess = license_mgr.session()
        key = (sess or {}).get("license") or ""
        masked = mask_key(key) if key else "MAX-\u2022\u2022\u2022\u2022-\u2022\u2022\u2022\u2022"
        self.revoked_key.setText(masked)
        self.reason_field.set_value(
            payload.get("reason")
            or payload.get("revoked_reason")
            or "This key was revoked by a staff member.")
        self.revoked_on_field.set_value(self._date(payload))

    @staticmethod
    def _date(payload: dict) -> str:
        revoked_at = payload.get("revoked_at") or ""
        if not revoked_at:
            return "—"
        try:
            dt = datetime.strptime(revoked_at, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%b %d, %Y")
        except Exception:  # noqa: BLE001
            return revoked_at


# ---------------------------------------------------------------------------
# Gate window
# ---------------------------------------------------------------------------

class GateWindow(QWidget):
    """Frameless fullscreen gate. Emits ``unlocked(session)`` once unlocked."""

    PAGE_ACTIVATION = 0
    PAGE_TIMEOUT = 1
    PAGE_BANNED = 2
    PAGE_REVOKED = 3

    unlocked = Signal(object)

    def __init__(self, parent=None, payload=None):
        # Plain top-level window: it may overlap the screen but NEVER stays
        # on top — the user must be able to tab out and reach support pages.
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Window)
        self.setObjectName("GateWindow")
        self.setStyleSheet(
            "QWidget#GateWindow { background-color: #07060c; }")

        self._busy = False
        self._license_worker = None
        self._reconnect_worker = None
        self._countdown_worker = None
        self._countdown_total = 0
        self._countdown_last_state = None
        self._current_payload = dict(payload) if payload else {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(_TopBar(self))

        self.stack = QStackedWidget(self)
        self.page_activation = _ActivationPage(self)
        self.page_timeout = _TimeoutPage(self)
        self.page_banned = _BannedPage(self)
        self.page_revoked = _RevokedPage(self)

        self.stack.addWidget(self.page_activation)
        self.stack.addWidget(self.page_timeout)
        self.stack.addWidget(self.page_banned)
        self.stack.addWidget(self.page_revoked)

        self.page_activation.activate_requested.connect(self._on_activate)
        self.page_activation.retry_requested.connect(self._on_reconnect)
        self.page_activation.support_requested.connect(self._open_support)
        self.page_banned.support_requested.connect(self._open_support)
        self.page_banned.appeal_requested.connect(self._open_support)
        self.page_revoked.support_requested.connect(self._open_support)

        root.addWidget(self.stack, 1)

        # Footer status pill depends on the active page; rebuild on switch.
        self.footer = _Footer("ACCESS REVOKED", "#ff4d63", "#ff4d63", self)
        self._footer_for_page: dict[int, tuple[str, str, str]] = {
            self.PAGE_ACTIVATION: ("LICENSE REQUIRED", "#c9b564", "#c9b564"),
            self.PAGE_TIMEOUT: ("KEY ON TIMEOUT", "#ffb340", "#ffb340"),
            self.PAGE_BANNED: ("ACCESS REVOKED", "#ff4d63", "#ff4d63"),
            self.PAGE_REVOKED: ("KEY REVOKED", "#c66eff", "#c66eff"),
        }
        self.stack.currentChanged.connect(self._update_footer)
        self.stack.layout().setContentsMargins(0, 0, 0, 0)

        quit_row = QHBoxLayout()
        quit_row.setContentsMargins(28, 0, 28, 16)
        quit_row.addStretch()
        quit_btn = QPushButton("Quit")
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.setFlat(True)
        quit_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            " color: #524d6b; font-family: " + MONO +
            "; font-size: 12px; }"
            "QPushButton:hover { color: #eae7f8; }")
        quit_btn.clicked.connect(lambda: self._quit())
        quit_row.addWidget(quit_btn)
        root.addLayout(quit_row)

        root.addWidget(self.footer)
        root.addSpacing(8)

        self._refresh_config_state()
        self._route_from_payload()
        self._update_footer(self.stack.currentIndex())
        self._fade_in()

    # ---------------- routing ----------------

    def _route_from_payload(self):
        """Pick the initial page based on the server refusal payload."""
        code = (self._current_payload.get("code") or "").lower()

        if code == "license_suspended":
            self.page_timeout.configure(
                total_seconds=int(self._remaining_seconds()),
                reason=self._current_payload.get("reason")
                or self._current_payload.get("message")
                or "Access is temporarily suspended by the operator.",
                masked_key=mask_key((license_mgr.session() or {})
                                    .get("license", "")))
            self.stack.setCurrentIndex(self.PAGE_TIMEOUT)
            if self._remaining_seconds() > 0:
                self._start_countdown()
            else:
                QTimer.singleShot(0, self._on_countdown_zero)
            return

        if code == "license_banned":
            self.page_banned.configure(self._current_payload)
            self.stack.setCurrentIndex(self.PAGE_BANNED)
            return

        if code == "license_revoked":
            self.page_revoked.configure(self._current_payload)
            self.stack.setCurrentIndex(self.PAGE_REVOKED)
            return

        # Default: activation page (fresh key prompt or reconnect flow).
        self.stack.setCurrentIndex(self.PAGE_ACTIVATION)

    def _remaining_seconds(self) -> int:
        until = self._current_payload.get("suspended_until")
        if not until:
            return 0
        try:
            until_ts = datetime.strptime(until, "%Y-%m-%d %H:%M:%S") \
                .replace(tzinfo=timezone.utc).timestamp()
        except Exception:  # noqa: BLE001
            return 0
        return int(until_ts - _time.time())

    def _update_footer(self, index: int):
        text, color, dot = self._footer_for_page.get(index, (
            "LICENSE REQUIRED", "#c9b564", "#c9b564"))
        self.footer.set_pill(text, color, dot)

    def _open_support(self):
        if not DISCORD_INVITE_URL:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(DISCORD_INVITE_URL))

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
        self._stop_countdown()
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

    # ---------------- config / busy states ----------------

    def _refresh_config_state(self):
        configured = license_mgr.is_configured()
        self._reconnect_required = (
            configured and license_mgr.needs_reverify())
        show_key_flow = configured and not self._reconnect_required
        self.page_activation.key_input.setVisible(show_key_flow)
        self.page_activation.activate_btn.setVisible(show_key_flow)
        self.page_activation.reconnect_box.setVisible(
            configured and self._reconnect_required and not self._busy)
        self.page_activation.config_note.setVisible(not configured)
        if self._reconnect_required and not self._busy:
            self.page_activation.reconnect_status.hide()
            QTimer.singleShot(0, self._on_reconnect)

    def set_busy(self, busy: bool):
        self._busy = busy
        self.page_activation.set_busy(busy)

    # ---------------- activation ----------------

    def _on_activate(self, key: str):
        if self._busy:
            return
        if not license_mgr.is_configured():
            self._refresh_config_state()
            return
        key = key.strip()
        if len(key.replace("-", "").replace(" ", "")) < 12:
            self.page_activation.show_feedback(
                "Enter a complete license key.", error=True)
            return
        self.set_busy(True)
        worker = LicenseActivateWorker(key, self)
        self._license_worker = worker
        worker.done.connect(self._on_done)
        worker.start()

    # ---------------- reconnect to verify ----------------

    def _on_reconnect(self):
        if self._busy:
            return
        if not license_mgr.is_configured():
            self._refresh_config_state()
            return
        self.set_busy(True)
        self.page_activation.reconnect_status.hide()
        worker = LicenseHeartbeatWorker(self)
        self._reconnect_worker = worker
        worker.done.connect(self._on_reconnect_done)
        worker.start()

    def _on_reconnect_done(self, status, message):
        self.set_busy(False)
        if status == "ok":
            sess = license_mgr.session()
            publish_identity()
            toast("License re-verified \u2014 welcome back", "success", self)
            self.unlocked.emit(sess)
            return
        if status == "refused":
            # The key is genuinely gone / paused server-side — reroute to the
            # matching status screen from the refusal payload.
            license_mgr.set_session(None)
            publish_identity()
            self._current_payload = dict(license_mgr.last_refusal() or {})
            self.page_activation.hide_feedback()
            self._route_from_payload()
            return
        # offline / transient — keep the session (offline grace), report.
        self.page_activation.reconnect_status.setText(
            message or "Couldn't reach the license server. Check your "
                       "internet connection and try again.")
        self.page_activation.reconnect_status.show()

    # ---------------- activation result ----------------

    def _on_done(self, sess, error):
        self.set_busy(False)
        self.page_activation.hide_feedback()
        if error:
            # If the server refused with a structured reason (banned /
            # revoked / suspended) open the matching page; otherwise show it
            # inline on the key prompt.
            refusal = license_mgr.last_refusal()
            self._current_payload = dict(refusal or {})
            code = refusal.get("code", "") if refusal else ""
            if code in ("license_banned", "license_revoked",
                        "license_suspended"):
                self._route_from_payload()
                return
            self.page_activation.show_feedback(error, error=True)
            return
        if not sess:
            self.page_activation.show_feedback(
                "The license server returned no session.", error=True)
            return
        try:
            publish_identity()
            toast(f"Welcome, {current_windows_user()} \u2014 license activated",
                  "success", self)
        finally:
            self.unlocked.emit(sess)

    # ---------------- timeout countdown ----------------

    def _start_countdown(self):
        self._stop_countdown()
        self._countdown_total = max(1, self._remaining_seconds())
        self.page_timeout.configure(
            total_seconds=self._countdown_total,
            reason=self._current_payload.get("reason")
            or self._current_payload.get("message")
            or "Access is temporarily suspended by the operator.",
            masked_key=mask_key((license_mgr.session() or {})
                                .get("license", "")))
        self._countdown_last_state = self._countdown_total
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._tick_countdown)
        self._countdown_timer.start(1000)

    def _stop_countdown(self):
        self._countdown_last_state = None
        if getattr(self, "_countdown_timer", None) is not None:
            self._countdown_timer.stop()
            self._countdown_timer.deleteLater()
            self._countdown_timer = None

    def _tick_countdown(self):
        remaining = self._remaining_seconds()
        self.page_timeout.tick(remaining)
        if remaining <= 0:
            self._stop_countdown()
            self._on_countdown_zero()

    def _on_countdown_zero(self):
        """Auto-unlock when the timeout expires: re-check in with the server."""
        if self._countdown_worker is not None:
            if self._countdown_worker.isRunning():
                return
        worker = LicenseHeartbeatWorker(self)
        self._countdown_worker = worker
        worker.done.connect(self._on_countdown_done)
        worker.start()

    def _on_countdown_done(self, status, message):
        if status == "ok":
            sess = license_mgr.session()
            publish_identity()
            toast("Timeout complete \u2014 Maximum Tweaks unlocked",
                  "success", self)
            self.unlocked.emit(sess)
            return
        if status == "refused":
            license_mgr.set_session(None)
            publish_identity()
            self._current_payload = dict(license_mgr.last_refusal() or {})
            self._route_from_payload()
            return
        # offline / suspended again — keep counting from the fresh payload.
        self._current_payload = dict(license_mgr.last_refusal() or {}) \
            if license_mgr.last_refusal() else self._current_payload
        if self._remaining_seconds() > 0:
            self._start_countdown()
        else:
            # Server momentarily down; retry shortly so it still auto-unlocks.
            from PySide6.QtCore import QTimer as _Q
            _Q.singleShot(30000, self._on_countdown_zero)