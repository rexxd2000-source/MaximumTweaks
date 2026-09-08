"""License UI: worker threads + identity widgets.

All network work (activate / validate / deactivate) runs on worker QThreads —
the GUI never blocks on the license server. These widgets render the persisted
license session and drive activation/deactivation.
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

from config.app_config import ICONS, THEME as T
from engine import license as license_mgr
from ui.widgets import IconTile, clear_layout, qss_rgba, repolish, toast

_ACCENT = T["accent"]


def publish_identity():
    """Keep the ui.context license globals in sync with the persisted session:
    an authorized owner name, or guest (None) until a license is active."""
    from ui import context
    sess = license_mgr.session()
    if sess and license_mgr.is_authorized():
        name = license_mgr.owner_name(sess)
        first = context.LICENSE_NAME is None
        context.LICENSE_NAME = name
        context.LICENSE_FIRST_VERIFY = first
    else:
        context.LICENSE_NAME = None
        context.LICENSE_FIRST_VERIFY = False


def mask_key(key: str) -> str:
    """Show only the last group of a license key (MAX-XXXX-XXXX-XXXX)."""
    if not key:
        return ""
    parts = str(key).split("-")
    if len(parts) >= 3:
        return "MAX-\u2022\u2022\u2022\u2022-\u2022\u2022\u2022\u2022-" + parts[-1]
    return key


def plan_label(sess: dict | None = None) -> str:
    """Human-friendly subscription name for the session's plan, e.g. 'Maximum
    Lifetime'. The raw key code is never shown in the UI."""
    sess = sess or license_mgr.session()
    if not sess:
        return "Maximum Lifetime"
    plan = str(sess.get("plan") or "lifetime").lower()
    pretty = {
        "lifetime": "Lifetime",
        "monthly": "Monthly",
        "yearly": "Yearly",
        "custom": "Custom",
    }.get(plan, plan.capitalize())
    return f"Maximum {pretty}"


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

class LicenseActivateWorker(QThread):
    done = Signal(object, str)  # session-or-None, error-message

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self._key = key

    def run(self):
        try:
            sess = license_mgr.activate(self._key)
        except license_mgr.LicenseError as exc:
            self.done.emit(None, exc.message)
            return
        except Exception as exc:  # noqa: BLE001
            self.done.emit(None, str(exc) or "Activation failed.")
            return
        self.done.emit(sess, "")


class LicenseValidateWorker(QThread):
    done = Signal(bool, str)  # ok, message

    def run(self):
        try:
            ok, message = license_mgr.validate()
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, str(exc) or "License check failed.")
            return
        self.done.emit(ok, message)


class LicenseDeactivateWorker(QThread):
    done = Signal()

    def run(self):
        try:
            license_mgr.deactivate()
        finally:
            self.done.emit()


_STARTUP_WORKER: LicenseValidateWorker | None = None


def validate_startup():
    """Best-effort background token refresh so sessions stay fresh."""
    global _STARTUP_WORKER
    sess = license_mgr.session()
    if not sess or (_STARTUP_WORKER and _STARTUP_WORKER.isRunning()):
        return
    publish_identity()
    _STARTUP_WORKER = LicenseValidateWorker()
    _STARTUP_WORKER.start()


def deactivate(ctx, view):
    """Deactivate this device and clear the local session."""
    worker = getattr(view, "_license_worker", None)
    if worker is not None and worker.isRunning():
        return
    view.set_busy(True)
    worker = LicenseDeactivateWorker(view)
    view._license_worker = worker

    def done():
        view.set_busy(False)
        publish_identity()
        ctx.license_changed.emit()
        toast("License deactivated on this device", "info", view)
    worker.done.connect(done)
    worker.start()


# ---------------------------------------------------------------------------
# Sidebar account block card
# ---------------------------------------------------------------------------

class SidebarLicenseCard(QFrame):
    """License status block pinned to the bottom of the sidebar."""

    activate_requested = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("SidebarLicenseCard")
        self._busy = False
        self._license_worker = None

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(12, 12, 12, 12)
        self.root.setSpacing(8)
        self._rebuild()

        ctx.license_changed.connect(self._rebuild)

    def set_busy(self, busy: bool):
        self._busy = busy
        self._rebuild()

    def _rebuild(self):
        publish_identity()
        clear_layout(self.root)
        lay = self.root

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(IconTile(ICONS.get("shield", "\u26d1"), _ACCENT,
                                size=30, font_scale=0.5))
        t = QLabel("License")
        t.setStyleSheet("font-size: 12px; font-weight: 800;")
        head.addWidget(t)
        head.addStretch()
        head.addWidget(_BlinkDot(8))
        lay.addLayout(head)

        if self._busy:
            note = QLabel("Working\u2026")
            note.setObjectName("CardDetail")
            note.setWordWrap(True)
            lay.addWidget(note)
            return

        sess = license_mgr.session()
        authorized = bool(sess and license_mgr.is_authorized())

        if authorized:
            body = QHBoxLayout()
            body.setSpacing(10)
            av = IconTile("K", _ACCENT, size=36, font_scale=0.55)
            body.addWidget(av, 0, Qt.AlignVCenter)
            box = QVBoxLayout()
            box.setSpacing(0)
            nm = QLabel(license_mgr.owner_name(sess))
            nm.setStyleSheet("font-size: 13px; font-weight: 800;")
            box.addWidget(nm)
            tag = QLabel(plan_label(sess))
            tag.setStyleSheet(f"color: {T['text_dim']}; font-size: 10px;")
            box.addWidget(tag)
            box.addStretch()
            body.addLayout(box, 1)
            lay.addLayout(body)

            status = QLabel("LICENSE ACTIVE")
            status.setStyleSheet(
                f"color: {_ACCENT}; font-size: 11px; font-weight: 700;")
            lay.addWidget(status)

            out = QPushButton("Deactivate")
            out.setObjectName("Secondary")
            out.clicked.connect(lambda: deactivate(self.ctx, self))
            lay.addWidget(out)
        elif not license_mgr.is_configured():
            note = QLabel(
                "License server not configured. Set LICENSE_API_URL in "
                "config/app_config.py to require activation.")
            note.setObjectName("CardDetail")
            note.setWordWrap(True)
            lay.addWidget(note)
            if license_mgr.dev_bypass_enabled():
                owner = QPushButton("Enter as Owner (dev bypass)")
                owner.setObjectName("Ghost")
                owner.clicked.connect(self.activate_requested)
                lay.addWidget(owner)
        else:
            desc = QLabel(
                "No active license. Enter your key to unlock Maximum Tweaks.")
            desc.setObjectName("CardDetail")
            desc.setWordWrap(True)
            lay.addWidget(desc)

            activate = QPushButton("Activate License")
            activate.setObjectName("Primary")
            activate.clicked.connect(self.activate_requested)
            lay.addWidget(activate)


# ---------------------------------------------------------------------------
# Dashboard license account card
# ---------------------------------------------------------------------------

class LicenseAccountCard(QFrame):
    """License status / sign-out card for the dashboard (replaces the old
    Discord community block). Shows the key owner name + plan only — never the
    key code itself."""

    activate_requested = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("LicenseAccountCard")
        self._busy = False
        self._license_worker = None

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 14, 16, 14)
        self.root.setSpacing(10)
        self._rebuild()

        ctx.license_changed.connect(self._rebuild)

    def set_busy(self, busy: bool):
        self._busy = busy
        self._rebuild()

    def _rebuild(self):
        publish_identity()
        clear_layout(self.root)
        lay = self.root

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(IconTile(ICONS.get("shield", "\u26d1"), _ACCENT,
                                size=32, font_scale=0.5))
        t = QLabel("License")
        t.setStyleSheet("font-size: 13px; font-weight: 800;"
                        " letter-spacing: 0.4px;")
        head.addWidget(t)
        head.addStretch()
        head.addWidget(_BlinkDot(8))
        lay.addLayout(head)

        if self._busy:
            note = QLabel("Working\u2026")
            note.setObjectName("CardDetail")
            note.setWordWrap(True)
            lay.addWidget(note)
            return

        sess = license_mgr.session()
        authorized = bool(sess and license_mgr.is_authorized())

        if authorized:
            body = QHBoxLayout()
            body.setSpacing(12)
            av = IconTile("K", _ACCENT, size=44, font_scale=0.55)
            body.addWidget(av, 0, Qt.AlignVCenter)
            box = QVBoxLayout()
            box.setSpacing(0)
            nm = QLabel(license_mgr.owner_name(sess))
            nm.setStyleSheet("font-size: 15px; font-weight: 800;")
            box.addWidget(nm)
            sub = QLabel(plan_label(sess))
            sub.setStyleSheet(
                f"color: {_ACCENT}; font-size: 11px; font-weight: 700;")
            box.addWidget(sub)
            box.addStretch()
            body.addLayout(box, 1)
            lay.addLayout(body)

            status = QLabel("\u25cf LICENSED")
            status.setStyleSheet(
                f"color: {_ACCENT}; font-size: 10px; font-weight: 800;"
                " letter-spacing: 0.8px;")
            lay.addWidget(status)

            out = QPushButton("Sign Out (Deactivate)")
            out.setObjectName("Secondary")
            out.clicked.connect(lambda: deactivate(self.ctx, self))
            lay.addWidget(out)
        elif not license_mgr.is_configured():
            note = QLabel(
                "License server not configured. Set LICENSE_API_URL in "
                "config/app_config.py to require activation.")
            note.setObjectName("CardDetail")
            note.setWordWrap(True)
            lay.addWidget(note)
            if license_mgr.dev_bypass_enabled():
                owner = QPushButton("Enter as Owner (dev bypass)")
                owner.setObjectName("Ghost")
                owner.clicked.connect(self.activate_requested)
                lay.addWidget(owner)
        else:
            desc = QLabel(
                "No active license. Enter your key to unlock Maximum Tweaks.")
            desc.setObjectName("CardDetail")
            desc.setWordWrap(True)
            lay.addWidget(desc)

            activate = QPushButton("Activate License")
            activate.setObjectName("Primary")
            activate.clicked.connect(self.activate_requested)
            lay.addWidget(activate)
