"""Discord verification UI: worker thread + identity widgets.

The OAuth2 flow in engine.discord_auth does real network + browser work, so it
always runs on a worker QThread here. These widgets render the persisted
session (avatar, name, verified badge) and drive login/logout.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import THEME as T
from engine import discord_auth, state as state_mgr
from ui.widgets import Avatar, IconTile, clear_layout, initials, repolish, toast

_ACCENT = T["accent"]


def _publish_identity():
    """Keep the ui.context identity globals in sync with the persisted
    session: a verified Discord name, or guest (None) until verified."""
    from ui import context
    prof = discord_auth.session()
    if prof and prof.get("verified"):
        name = discord_auth.display_name(prof)
        first = context.DISCORD_USERNAME is None
        context.DISCORD_USERNAME = name
        context.DISCORD_FIRST_VERIFY = first
    else:
        context.DISCORD_USERNAME = None
        context.DISCORD_FIRST_VERIFY = False


class _BlinkDot(QWidget):
    """Small status dot that blinks on a timer (live indicator)."""

    def __init__(self, size: int = 8, color=_ACCENT, interval: int = 450,
                 parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._color = QColor(color)
        self._on = True
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._toggle)
        self._timer.start(interval)

    def _toggle(self):
        self._on = not self._on
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(self._color)
        col.setAlpha(255 if self._on else 70)
        p.setBrush(col)
        p.setPen(Qt.NoPen)
        d = self.width()
        p.drawEllipse(QRectF(0, 0, d, d))


# ---------------------------------------------------------------------------
# Worker threads
# ---------------------------------------------------------------------------

class DiscordLoginWorker(QThread):
    url_ready = Signal(str)  # authorize URL, emitted before the flow blocks
    done = Signal(object, str)  # profile-or-None, error-message

    def __init__(self, parent=None, open_browser: bool = True):
        super().__init__(parent)
        self._open_browser = open_browser

    def run(self):
        try:
            prof = discord_auth.login(
                open_browser=self._open_browser,
                on_url=self.url_ready.emit)
        except Exception as exc:  # noqa: BLE001
            self.done.emit(None, str(exc))
            return
        self.done.emit(prof, "")


class DiscordLogoutWorker(QThread):
    done = Signal()

    def run(self):
        try:
            discord_auth.logout()
        finally:
            self.done.emit()


class DiscordValidateWorker(QThread):
    done = Signal(bool)

    def run(self):
        try:
            ok = discord_auth.validate_session()
        except Exception:  # noqa: BLE001
            ok = False
        self.done.emit(ok)


_STARTUP_WORKER: DiscordValidateWorker | None = None


def validate_startup():
    """Best-effort background token check so identities stay fresh."""
    global _STARTUP_WORKER
    prof = discord_auth.session()
    if not prof or _STARTUP_WORKER and _STARTUP_WORKER.isRunning():
        return
    _publish_identity()
    _STARTUP_WORKER = DiscordValidateWorker()
    _STARTUP_WORKER.start()


def login(ctx, view):
    """Start a Discord login; updates the view + emits ctx signals on return."""
    worker = getattr(view, "_discord_worker", None)
    if worker is not None and worker.isRunning():
        return
    if not discord_auth.is_configured():
        toast("Discord verification is not configured yet "
              "(set AUTH_SERVER_URL in config/app_config.py).",
              "warning", view)
        return
    view.set_busy(True)
    worker = DiscordLoginWorker(view)
    view._discord_worker = worker

    def done(profile, error):
        view.set_busy(False)
        if error:
            toast(f"Discord verification failed: {error}", "error", view)
        elif profile:
            toast(f"Verified as {profile.get('name', 'Discord user')}",
                  "success", view)
            ctx.discord_changed.emit()
    worker.done.connect(done)
    worker.start()


def logout(ctx, view):
    worker = getattr(view, "_discord_worker", None)
    if worker is not None and worker.isRunning():
        return
    view.set_busy(True)
    worker = DiscordLogoutWorker(view)
    view._discord_worker = worker

    def done():
        view.set_busy(False)
        ctx.discord_changed.emit()
        toast("Disconnected from Discord", "info", view)
    worker.done.connect(done)
    worker.start()


# ---------------------------------------------------------------------------
# Compact header chip
# ---------------------------------------------------------------------------

class DiscordChip(QFrame):
    """Clickable pill showing login state / the verified Discord identity."""

    clicked = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("DiscordChip")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Discord verification keeps the community clean.")
        self._busy = False
        self._discord_worker = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)
        self.avatar = Avatar(24)
        lay.addWidget(self.avatar)
        self.text = QLabel()
        self.text.setStyleSheet("font-size: 12px; font-weight: 700;")
        lay.addWidget(self.text)
        self.flag = QLabel()
        self.flag.setStyleSheet("font-size: 9.5px; font-weight: 800;")
        lay.addWidget(self.flag)

        ctx.discord_changed.connect(self._refresh)
        ctx.pfp_changed.connect(self._refresh)
        self._refresh()

    def set_busy(self, busy: bool):
        self._busy = busy
        self._refresh()

    def _refresh(self):
        _publish_identity()
        prof = discord_auth.session()
        self.avatar.set_letter(initials(discord_auth.display_name(prof) or "R"))
        self.avatar.set_avatar(state_mgr.discord_avatar_path())

        if self._busy:
            self.text.setText("Verifying\u2026")
            self.flag.setText("")
            self.setStyleSheet(
                f"QFrame#DiscordChip {{ background-color: #0B0F14;"
                f" border: 1px solid {_ACCENT}55; border-radius: 16px; }}")
        elif prof:
            verified = prof.get("verified")
            if verified:
                name = discord_auth.display_name(prof)
                self.text.setText(name)
                self.flag.setText("VERIFIED")
                self.flag.setStyleSheet(
                    f"font-size: 9px; font-weight: 800; letter-spacing: 0.5px;"
                    f" color: {_ACCENT};"
                    f" background: {_ACCENT}1A; border: 1px solid {_ACCENT}44;"
                    " border-radius: 8px; padding: 2px 7px;")
                self.setStyleSheet(
                    f"QFrame#DiscordChip {{ background-color: #0B1217;"
                    f" border: 1px solid {_ACCENT}66; border-radius: 16px; }}")
            else:
                # Not yet verified -> always treated as a guest, never "CONNECTED".
                self.text.setText("Guest")
                self.flag.setText("NOT VERIFIED")
                self.flag.setStyleSheet(
                    "font-size: 9px; font-weight: 800; letter-spacing: 0.5px;"
                    " color: #8A93A3; background: #10161D;"
                    " border: 1px solid #2A323D; border-radius: 8px;"
                    " padding: 2px 7px;")
                self.setStyleSheet(
                    "QFrame#DiscordChip { background-color: #10161D;"
                    " border: 1px solid #2A323D; border-radius: 16px; }")
        else:
            if discord_auth.is_configured():
                self.text.setText("\u25c9  Verify with Discord")
                self.setStyleSheet(
                    f"QFrame#DiscordChip {{ background-color: #10161D;"
                    f" border: 1px solid {_ACCENT}88; border-radius: 16px; }}"
                    "QFrame#DiscordChip:hover { background-color: #16202A; }")
            else:
                self.text.setText("Discord not configured")
                self.setStyleSheet(
                    "QFrame#DiscordChip { background-color: #0B0F14;"
                    " border: 1px solid #2A323D; border-radius: 16px; }")
            self.flag.setText("")
        self.text.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {T['text']};")
        repolish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self._busy:
            self.clicked.emit()
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Sidebar account block card
# ---------------------------------------------------------------------------

class SidebarDiscordCard(QFrame):
    """Large Discord block card pinned to the bottom of the sidebar.

    Matches the sizing/style of the main Tweak Cards. Connected state shows
    the verified identity + a Disconnect action; disconnected state shows the
    verification prompt directly inside the card.
    """

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("SidebarDiscordCard")
        self._busy = False
        self._discord_worker = None

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(12, 12, 12, 12)
        self.root.setSpacing(8)
        self._rebuild()

        ctx.discord_changed.connect(self._rebuild)
        ctx.pfp_changed.connect(self._rebuild)

    def set_busy(self, busy: bool):
        self._busy = busy
        self._rebuild()

    def _rebuild(self):
        _publish_identity()
        clear_layout(self.root)
        lay = self.root

        prof = discord_auth.session()
        configured = discord_auth.is_configured()

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addStretch()
        t = QLabel("Discord Account")
        t.setStyleSheet("font-size: 12px; font-weight: 800;")
        head.addWidget(t)
        head.addWidget(_BlinkDot(8))
        head.addStretch()
        lay.addLayout(head)

        if self._busy:
            note = QLabel("Opening Discord in your browser \u2026")
            note.setObjectName("CardDetail")
            note.setWordWrap(True)
            lay.addWidget(note)
            return

        if prof:
            body = QHBoxLayout()
            body.setSpacing(10)
            av = Avatar(42)
            av.set_letter(initials(discord_auth.display_name(prof) or "R"))
            av.set_avatar(state_mgr.discord_avatar_path())
            body.addWidget(av, 0, Qt.AlignVCenter)
            box = QVBoxLayout()
            box.setSpacing(0)
            nm = QLabel(discord_auth.display_name(prof))
            nm.setStyleSheet("font-size: 13px; font-weight: 800;")
            box.addWidget(nm)
            tag = QLabel(f"@{prof.get('username', '')}  \u00b7  "
                         f"{prof.get('id', '')}")
            tag.setStyleSheet(f"color: {T['text_dim']}; font-size: 10px;")
            box.addWidget(tag)
            box.addStretch()
            body.addLayout(box, 1)
            lay.addLayout(body)

            status = QLabel(
                "Verified Discord member" if prof.get("verified")
                else "Guest \u00b7 not yet verified")
            status.setStyleSheet(
                f"color: {_ACCENT if prof.get('verified') else T['warning']};"
                " font-size: 11px; font-weight: 700;")
            lay.addWidget(status)

            out = QPushButton("Disconnect")
            out.setObjectName("Secondary")
            out.clicked.connect(lambda: logout(self.ctx, self))
            lay.addWidget(out)
        elif not configured:
            note = QLabel(
                "Discord verification is not configured. Set AUTH_SERVER_URL "
                "in config/app_config.py to require verified logins.")
            note.setObjectName("CardDetail")
            note.setWordWrap(True)
            lay.addWidget(note)
        else:
            desc = QLabel(
                "Verify with Discord to attach a verified identity to this "
                "session \u2014 keeps the community clean.")
            desc.setObjectName("CardDetail")
            desc.setWordWrap(True)
            lay.addWidget(desc)

            verify = QPushButton("\u25c9  Verify with Discord")
            verify.setObjectName("Primary")
            verify.clicked.connect(lambda: login(self.ctx, self))
            lay.addWidget(verify)


# ---------------------------------------------------------------------------
# Settings account card
# ---------------------------------------------------------------------------

class DiscordAccountCard(QFrame):
    """Standout account card under Settings showing the connected Discord."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("DiscordCard")
        self._busy = False
        self._discord_worker = None

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(18, 16, 18, 16)
        self.root.setSpacing(12)
        self._rebuild()

        ctx.discord_changed.connect(self._rebuild)
        ctx.pfp_changed.connect(self._rebuild)

    def set_busy(self, busy: bool):
        self._busy = busy
        self._rebuild()

    def _rebuild(self):
        _publish_identity()
        # Fully clear every child (widgets + nested layouts) so no stale
        # identity elements survive after a disconnect and overlap the new
        # state.
        clear_layout(self.root)
        lay = self.root

        prof = discord_auth.session()
        configured = discord_auth.is_configured()

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(IconTile("\u25c9", _ACCENT, size=30, font_scale=0.5))
        t = QLabel("Discord Account")
        t.setStyleSheet("font-size: 14px; font-weight: 800;")
        head.addWidget(t)
        head.addStretch()

        state = QLabel()
        state.setStyleSheet(
            f"color: {_ACCENT}; background: {_ACCENT}1A;"
            f" border: 1px solid {_ACCENT}44; border-radius: 9px;"
            " padding: 3px 10px; font-size: 10px; font-weight: 800;"
            " letter-spacing: 0.6px;")
        if self._busy:
            state.setText("\u25cf WORKING")
        elif prof:
            state.setText("\u25cf VERIFIED" if prof.get("verified")
                          else "\u25cf GUEST")
        else:
            state.setText("\u25cf NOT VERIFIED")
        head.addWidget(state)
        lay.addLayout(head)

        if self._busy:
            note = QLabel("Opening Discord in your browser \u2026 sign in and "
                          "authorize Rex Tweaks. This window stays usable.")
            note.setObjectName("CardDetail")
            note.setWordWrap(True)
            lay.addWidget(note)
        elif prof:
            body = QHBoxLayout()
            body.setSpacing(20)
            av = Avatar(92)
            av.set_letter(initials(discord_auth.display_name(prof) or "R"))
            av.set_avatar(state_mgr.discord_avatar_path())
            body.addWidget(av, 0, Qt.AlignVCenter)
            box = QVBoxLayout()
            box.setSpacing(4)
            nm = QLabel(discord_auth.display_name(prof))
            nm.setStyleSheet("font-size: 24px; font-weight: 900;")
            box.addWidget(nm)
            tag = QLabel(f"@{prof.get('username', '')}  \u00b7  {prof.get('id', '')}")
            tag.setStyleSheet(f"color: {T['text_dim']}; font-size: 12px;")
            box.addWidget(tag)
            status = QLabel(
                "Verified Discord member" if prof.get("verified")
                else "Guest \u00b7 not yet verified")
            status.setStyleSheet(
                f"color: {_ACCENT if prof.get('verified') else T['warning']};"
                " font-size: 12px; font-weight: 700;")
            box.addWidget(status)
            if prof.get("email"):
                email = QLabel(prof["email"])
                email.setStyleSheet(f"color: {T['text_faint']}; font-size: 12px;")
                box.addWidget(email)
            box.addStretch()
            body.addLayout(box, 1)
            lay.addLayout(body)

            desc = QLabel(
                "Your Discord identity is verified against the REX TWEAKS "
                "server (you\u2019re a member with the Verified role) and stored "
                "locally in your Rex Tweaks data folder. Nothing is ever "
                "shared without your consent.")
            desc.setObjectName("CardDetail")
            desc.setWordWrap(True)
            lay.addWidget(desc)

            btns = QHBoxLayout()
            btns.setSpacing(8)
            out = QPushButton("Disconnect Discord")
            out.setObjectName("Secondary")
            out.clicked.connect(lambda: logout(self.ctx, self))
            btns.addWidget(out)
            btns.addStretch()
            lay.addLayout(btns)
        elif not configured:
            note = QLabel(
                "Discord verification is not configured. Set AUTH_SERVER_URL "
                "in config/app_config.py to point at the auth backend, then "
                "restart the app to enable verified logins.")
            note.setObjectName("CardDetail")
            note.setWordWrap(True)
            lay.addWidget(note)
        else:
            desc = QLabel(
                "Verify your Discord account to attach a verified identity to "
                "this app \u2014 stable user ID plus verified-email flag \u2014 "
                "which helps keep the community clean and trustworthy.")
            desc.setObjectName("CardDetail")
            desc.setWordWrap(True)
            lay.addWidget(desc)

            verify = QPushButton("\u25c9  Verify with Discord")
            verify.setObjectName("Primary")
            verify.clicked.connect(lambda: login(self.ctx, self))
            lay.addWidget(verify, 0, Qt.AlignLeft)
