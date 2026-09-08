"""Cinematic boot splash for Maximum Tweaks.

A restrained, premium boot sequence at 60 fps: a near-black stage with slow
drifting aurora glows, a thin self-drawing emblem ring, a clean two-tone
wordmark that fades in with expanding letter-spacing, a hairline that draws
from center, a single cycling status line, and a slim progress bar. No noise,
no garish particles \u2014 just calm, expensive motion.

API:
    splash = CinematicSplash(); splash.setGeometry(...); splash.show()
    splash.start()
    splash.build_now.connect(build_main_window)   # ~80%
    splash.finished.connect(show_window_and_fade) # 100%

Update flow (inline loading step, no popup):
    splash.update_checking()                      # hold progress at HOLD_PCT
    on check result: update_ok() or update_available(cur, new, notes)
    while downloading: update_progress(frac); then set_installing()
    on failure: update_error(msg)
    install_clicked / skip_clicked / retry_clicked report the user's choice.
"""
from __future__ import annotations

import math

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import APP_VERSION

ACCENT = QColor("#8B5CF6")
TEXT = QColor(238, 244, 248)
DIM = QColor(124, 147, 166)
FAINT = QColor(64, 80, 96)
BG_TOP = QColor(4, 6, 10)
BG_BOTTOM = QColor(9, 13, 18)

STATUS_SEQ = [
    "INITIALIZING",
    "LOADING TWEAKS",
    "ARMING SAFETY NET",
    "INITIALIZING TELEMETRY",
    "CALIBRATING HARDWARE",
    "SYSTEM READY",
]

HOLD_PCT = 78  # progress plateau while the update check is unresolved

# Rapid hardware/system detection toasts shown near the center of the stage.
# Each entry: (prefix, base text, kind). `kind` lets real detected values fill
# the label once the lightweight probe thread reports back.
TOAST_DEFS = [
    ("[+]", "Detecting GPU", "gpu"),
    ("[+]", "Detecting System Memory & CPU", "cpu"),
    ("[+]", "Verifying License", "license"),
    ("[+]", "Loading Tweaks & System Hooks", "tweaks"),
]

_dur = 7000


def _ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def _ease_in_out(t: float) -> float:
    return t * t * (3 - 2 * t)


def _clamp01(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def _monotonic_ms() -> float:
    import time as _time
    return _time.monotonic() * 1000.0


_UPDATE_QSS = """
#UpdPanel {
    background-color: rgba(10, 16, 23, 240);
    border: 1px solid #1D2B37;
    border-radius: 14px;
}
#UpdTitle {
    color: #8B5CF6;
    font-size: 13px;
    font-weight: 900;
    letter-spacing: 2px;
    background: transparent;
    border: none;
}
#UpdMsg {
    color: #AAB8C3;
    font-size: 12px;
    background: transparent;
    border: none;
}
#UpdBar {
    background-color: #151D25;
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
}
#UpdBar::chunk {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                      stop: 0 #7C3AED, stop: 1 #8B5CF6);
    border-radius: 3px;
}
#UpdPrimary {
    background-color: #8B5CF6;
    color: #F2F5F9;
    border: none;
    border-radius: 8px;
    padding: 8px 20px;
    font-size: 12px;
    font-weight: 800;
}
#UpdPrimary:hover {
    background-color: #A78BFA;
}
#UpdPrimary:disabled {
    background-color: #1E1B2E;
    color: #4C6B7A;
}
#UpdGhost {
    background-color: transparent;
    color: #8FA6B8;
    border: 1px solid #2A3A46;
    border-radius: 8px;
    padding: 8px 20px;
    font-size: 12px;
}
#UpdGhost:hover {
    color: #DCE8F0;
    border-color: #3C5262;
}
#UpdGhost:disabled {
    color: #3E4F5C;
    border-color: #1E2A33;
}
"""


class _UpdatePanel(QWidget):
    """Inline update card layered over the splash stage.

    Modes:
      info         — "Update available vX → vY" with Install / Skip
      downloading  — progress bar, actions hidden
      installing   — full progress bar, actions disabled
      error        — message + Retry / Skip
    """

    install = Signal()
    skip = Signal()
    retry = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("UpdPanel")
        self.setStyleSheet(_UPDATE_QSS)
        self._mode = "info"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 16)
        lay.setSpacing(10)

        self._title = QLabel("UPDATE AVAILABLE")
        self._title.setObjectName("UpdTitle")
        self._title.setAlignment(Qt.AlignCenter)

        self._msg = QLabel("")
        self._msg.setObjectName("UpdMsg")
        self._msg.setAlignment(Qt.AlignCenter)
        self._msg.setWordWrap(True)

        self._bar = QProgressBar()
        self._bar.setObjectName("UpdBar")
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)

        self._primary = QPushButton("Install Update")
        self._primary.setObjectName("UpdPrimary")
        self._primary.setCursor(Qt.PointingHandCursor)
        self._skip = QPushButton("Skip")
        self._skip.setObjectName("UpdGhost")
        self._skip.setCursor(Qt.PointingHandCursor)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch()
        row.addWidget(self._skip)
        row.addWidget(self._primary)
        row.addStretch()

        lay.addWidget(self._title)
        lay.addWidget(self._msg)
        lay.addWidget(self._bar)
        lay.addLayout(row)

        self._primary.clicked.connect(self._on_primary)
        self._skip.clicked.connect(self.skip)

    # ---------------- modes ----------------

    def show_info(self, current: str, new: str, notes: str = ""):
        self._mode = "info"
        self._title.setText("UPDATE AVAILABLE")
        text = f"Maximum Tweaks v{current} \u2192 v{new}"
        if notes:
            text += f"\n\n{notes[:320].strip()}"
        self._msg.setText(text)
        self._bar.hide()
        self._primary.show()
        self._primary.setEnabled(True)
        self._primary.setText("Install Update")
        self._skip.show()
        self._skip.setEnabled(True)
        self._skip.setText("Skip")

    def show_download(self, frac: float):
        self._mode = "downloading"
        self._title.setText("DOWNLOADING UPDATE")
        self._msg.setText("Downloading the new build\u2026")
        self._bar.show()
        self._bar.setValue(int(round(_clamp01(frac) * 100)))
        self._primary.hide()
        self._skip.setEnabled(False)
        self._skip.setText("Please wait\u2026")

    def show_installing(self):
        self._mode = "installing"
        self._title.setText("INSTALLING UPDATE")
        self._msg.setText("Applying the update \u2014 the app will restart\u2026")
        self._bar.show()
        self._bar.setValue(100)
        self._primary.hide()
        self._skip.setEnabled(False)
        self._skip.setText("Please wait\u2026")

    def show_error(self, message: str):
        self._mode = "error"
        self._title.setText("UPDATE ERROR")
        self._msg.setText(message or "Could not check for updates.")
        self._bar.hide()
        self._primary.show()
        self._primary.setEnabled(True)
        self._primary.setText("Retry")
        self._skip.show()
        self._skip.setEnabled(True)
        self._skip.setText("Skip")

    def _on_primary(self):
        if self._mode == "info":
            self.install.emit()
        elif self._mode == "error":
            self.retry.emit()


class _ProbeThread(QThread):
    """Best-effort hardware probe for the splash toasts.

    Kept deliberately fast and failure-tolerant: any error leaves the toast
    showing its default '...' text instead of blocking the boot sequence.
    """

    result = Signal(dict)

    def run(self):
        values: dict = {}
        try:
            import psutil
            values["cpu"] = f"{psutil.cpu_count(logical=False) or '?'} cores / " \
                            f"{psutil.cpu_count(logical=True) or '?'} threads"
        except Exception:  # noqa: BLE001
            values["cpu"] = "?"
        try:
            import psutil
            gb = psutil.virtual_memory().total / (1024 ** 3)
            values["ram"] = f"{gb:.1f} GB"
        except Exception:  # noqa: BLE001
            values["ram"] = "?"
        try:
            import csv
            import io
            import subprocess
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-CimInstance Win32_VideoController | "
                 "Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=6,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            names = [line.strip() for line in (proc.stdout or "").splitlines()
                     if line.strip()]
            values["gpu"] = " / ".join(names)[:42] or "GPU"
        except Exception:  # noqa: BLE001
            values["gpu"] = "GPU"
        try:
            from engine import license as license_mgr
            sess = license_mgr.session()
            if sess and license_mgr.is_authorized():
                values["license"] = f"OK \u00b7 {license_mgr.owner_name(sess)}"
            else:
                values["license"] = "None"
        except Exception:  # noqa: BLE001
            values["license"] = "..."
        values["tweaks"] = ""
        self.result.emit(values)


class CinematicSplash(QWidget):
    """Frameless boot screen. Emits build_now ~80% in, finished at 100%.

    The update check runs as an inline loading step: progress holds at
    HOLD_PCT until the check resolves. If a newer build exists the splash
    shows the ``_UpdatePanel`` (install / skip) and ``finished`` is held until
    the user decides. drive via update_checking() / update_ok() /
    update_available() / update_progress() / set_installing() /
    update_error().
    """

    build_now = Signal()
    finished = Signal()
    install_clicked = Signal()
    skip_clicked = Signal()
    retry_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background-color: #05070A;")
        self._t0: float | None = None
        self._dur_ms = _dur
        self._done_emitted = False
        self._build_emitted = False
        self._started = False

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._toast_values: dict = {}
        self._probe: "_ProbeThread" | None = None

        # Boot phase (spec-detection toasts + boot bar) finishes first, then —
        # only if the update check is still unresolved — the splash switches to
        # a dedicated update loading screen so the two never overlap.
        self._update_phase = False
        self._entered_phase = False
        self._pending_panel = None  # callable shown once the update phase starts

        # Update flow state. "held" parks the progress bar and blocks
        # `finished` while a network decision is pending on the splash.
        self._update_state = "idle"
        self._held = False
        self._ok_hold_until: float | None = None
        self._download_frac = 0.0
        self._panel = _UpdatePanel(self)
        self._panel.hide()
        self._panel.install.connect(self.install_clicked)
        self._panel.skip.connect(self.skip_clicked)
        self._panel.retry.connect(self.retry_clicked)

    # ---------------- lifecycle ----------------

    def start(self, duration_ms: int | None = None):
        if duration_ms is not None:
            self._dur_ms = int(duration_ms)
        self._done_emitted = False
        self._build_emitted = False
        self._started = True
        self._update_phase = False
        self._entered_phase = False
        self._pending_panel = None
        self._t0 = None
        self._timer.start()
        self._start_probe()
        self.update()

    def _start_probe(self):
        """Kick off a fast background probe so toasts can show real hardware."""
        if self._probe is not None and self._probe.isRunning():
            return
        self._probe = _ProbeThread(self)
        self._probe.result.connect(self._on_probe_result)
        self._probe.start()

    def _on_probe_result(self, values: dict):
        self._toast_values.update(values)
        self.update()

    # ---------------- inline update flow ----------------

    def update_checking(self):
        """Announce the update check loading step and park the bar."""
        self._update_state = "checking"
        self._held = True
        self._ok_hold_until = None
        self._panel.hide()
        self.update()

    def _enter_update_phase(self):
        """Boot/detection is done — switch to the dedicated update screen.

        Only entered when the update check is still unresolved (its result was
        deferred) or needs a decision. If the check already finished as "ok"
        during the boot phase there is nothing left to show and the app simply
        proceeds.
        """
        fn = self._pending_panel
        self._pending_panel = None
        if fn is not None:
            self._update_phase = True
            fn()
        elif self._update_state == "checking":
            self._update_phase = True
            self._held = True
            self.update()
        # else: "ok" — no separate screen needed

    def update_ok(self):
        """No update (or user skipped): mark done and continue into the app."""
        self._update_state = "ok"
        self._held = False
        self._ok_hold_until = _monotonic_ms() + 650.0
        self._panel.hide()
        self.update()

    def update_available(self, current: str, new: str, notes: str = ""):
        """A newer build exists — show the inline install card and wait."""
        self._update_state = "available"
        if self._update_phase:
            self._panel.show_info(current, new, notes)
            self._show_panel()
        else:
            # Still in the boot phase: hold and reveal the card on its own
            # screen once the spec detection finishes.
            self._held = True
            self._pending_panel = lambda: (
                self._panel.show_info(current, new, notes), self._show_panel())

    def update_progress(self, frac: float):
        """Download progress, 0..1."""
        self._update_state = "downloading"
        self._download_frac = _clamp01(frac)
        self._panel.show_download(self._download_frac)
        self._show_panel()
        self.update()

    def set_installing(self):
        """The staged exe is being swapped in; hold until relaunch."""
        self._update_state = "installing"
        self._download_frac = 1.0
        self._panel.show_installing()
        self._show_panel()
        self.update()

    def update_error(self, message: str):
        """Update check/download failed — show retry on the splash."""
        self._update_state = "error"
        if self._update_phase:
            self._panel.show_error(message)
            self._show_panel()
        else:
            self._held = True
            self._pending_panel = lambda: (
                self._panel.show_error(message), self._show_panel())
        self.update()

    def _show_panel(self):
        self._panel.show()
        self._panel.raise_()
        self._position_panel()
        self.update()

    def _position_panel(self):
        pw = 430
        self._panel.adjustSize()
        ph = max(self._panel.sizeHint().height(), 128)
        x = (self.width() - pw) // 2
        y = max(24, int(self.height() * 0.58) - ph // 2)
        self._panel.setGeometry(x, y, pw, ph)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._panel is not None and self._panel.isVisible():
            self._position_panel()

    def fade_out(self, duration_ms: int = 700, on_done=None):
        """Cross-fade the splash away; the window below shows through."""
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(duration_ms)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _finish():
            self.hide()
            self._timer.stop()
            if on_done:
                on_done()
        anim.finished.connect(_finish)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # ---------------- animation driver ----------------

    def _tick(self):
        import time as _time
        now = _time.monotonic() * 1000.0
        if self._t0 is None or now - self._t0 > self._dur_ms * 2:
            start_offset = 0.0 if self._t0 is None else self._dur_ms
            self._t0 = now - start_offset
        t = now - self._t0
        if self._ok_hold_until is not None and now >= self._ok_hold_until:
            self._ok_hold_until = None
        if t >= self._dur_ms and not self._entered_phase:
            self._entered_phase = True
            self._enter_update_phase()
        if t >= self._dur_ms and not self._done_emitted \
                and not self._held and self._ok_hold_until is None:
            self._done_emitted = True
            self.finished.emit()
        if t >= self._dur_ms * 0.80 and not self._build_emitted:
            self._build_emitted = True
            self.build_now.emit()
        self.update()

    # ---------------- painting ----------------

    def paintEvent(self, _event):
        import time as _time
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        w, h = self.width(), self.height()
        now = _time.monotonic() * 1000.0
        t0 = self._t0 if self._t0 is not None else now
        t = 0.0 if not self._started else now - t0
        t = min(t, self._dur_ms)
        u = _clamp01(t / self._dur_ms)
        pct = int(round(_ease_out_cubic(u) * 100))

        # Update flow overrides the natural progress, but only on the dedicated
        # update screen; the boot bar runs its own 0-100% cycle.
        if self._update_phase:
            if self._update_state == "downloading":
                pct = int(round(self._download_frac * 100))
            elif self._update_state == "installing":
                pct = 100
            elif self._held:
                pct = max(pct, HOLD_PCT)

        self._draw_stage(p, w, h, t)
        self._draw_aurora(p, w, h, t)
        self._draw_scanline(p, w, h, t)
        self._draw_corners(p, w, h, t)
        if self._update_phase:
            self._draw_update_screen(p, w, h, t)
        else:
            self._draw_symbol(p, w, h, t)
            self._draw_wordmark(p, w, h, t)
            self._draw_toasts(p, w, h, t)
        self._draw_progress(p, w, h, t, pct)
        self._draw_footer(p, w, h)
        p.end()

    # ---- background ----

    def _draw_stage(self, p: QPainter, w: int, h: int, t: float):
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, BG_TOP)
        grad.setColorAt(1.0, BG_BOTTOM)
        p.fillRect(0, 0, w, h, grad)

    def _draw_aurora(self, p: QPainter, w: int, h: int, t: float):
        cx, cy = w / 2, h * 0.42
        # two soft drifting glows, very low alpha
        for i, (dx, dy, hue, r, sp) in enumerate((
                (-0.28, -0.12, (0, 90, 120), 0.50, 0.00011),
                (0.30, 0.10, (10, 60, 90), 0.42, -0.00007))):
            ox = dx + 0.05 * math.sin(t * sp + i * 2.1)
            oy = dy + 0.05 * math.cos(t * sp * 1.3)
            x = cx + ox * w
            y = cy + oy * h
            radius = max(w, h) * r
            glow = QRadialGradient(x, y, radius)
            glow.setColorAt(0.0, QColor(*hue, 26))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.fillRect(0, 0, w, h, glow)

    def _draw_scanline(self, p: QPainter, w: int, h: int, t: float):
        # one very faint horizontal band drifting down — texture, not drama
        sy = ((t * 0.05) % (h + 140)) - 70
        line = QLinearGradient(0, sy - 26, 0, sy + 26)
        line.setColorAt(0.0, QColor(139, 92, 246, 0))
        line.setColorAt(0.5, QColor(139, 92, 246, 14))
        line.setColorAt(1.0, QColor(139, 92, 246, 0))
        p.setBrush(line)
        p.setPen(Qt.NoPen)
        p.drawRect(0, sy - 26, w, 52)

    def _draw_corners(self, p: QPainter, w: int, h: int, t: float):
        a = _clamp01((t - 250) / 900.0)
        if a <= 0:
            return
        inset = 26
        length = 30
        pen = QPen(QColor(139, 92, 246, int(70 * a)), 1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for x, y, sx, syx in ((inset, inset, 1, 1), (w - inset, inset, -1, 1),
                              (inset, h - inset, 1, -1), (w - inset, h - inset, -1, -1)):
            p.drawLine(QPointF(x, y + syx * length), QPointF(x, y))
            p.drawLine(QPointF(x, y), QPointF(x + sx * length, y))

    # ---- center composition ----

    def _draw_symbol(self, p: QPainter, w: int, h: int, t: float):
        cx, cy = w / 2, h * 0.42
        a = _clamp01((t - 150) / 450.0)
        if a <= 0:
            return

        # soft halo behind the mark
        halo = QRadialGradient(cx, cy, 96)
        halo.setColorAt(0.0, QColor(139, 92, 246, int(46 * a)))
        halo.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(cx, cy), 96, 96)

        # compact bolt tile that scales in (replaces the old self-drawing ring)
        scale = 0.72 + 0.28 * _ease_out_cubic(a)
        size = 52 * scale
        rect = QRectF(cx - size / 2, cy - size / 2, size, size)
        p.setBrush(QColor(9, 18, 26, int(232 * a)))
        p.setPen(QPen(QColor(139, 92, 246, int(150 * a)), 1))
        p.drawRoundedRect(rect, size * 0.26, size * 0.26)

        s = size * 0.34
        bolt = QColor(139, 92, 246, int(255 * a))
        p.setBrush(bolt)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([
            QPointF(cx + s * 0.25, cy - s * 0.95),
            QPointF(cx - s * 0.45, cy + s * 0.05),
            QPointF(cx - s * 0.05, cy + s * 0.05),
            QPointF(cx - s * 0.25, cy + s * 0.95),
            QPointF(cx + s * 0.45, cy - s * 0.05),
            QPointF(cx + s * 0.05, cy - s * 0.05),
        ]))

    def _draw_wordmark(self, p: QPainter, w: int, h: int, t: float):
        cx = w / 2
        cy = h * 0.42 + 108
        k = _clamp01((t - 650) / 750.0)
        if k <= 0:
            return
        ease = _ease_out_cubic(k)
        alpha = int(255 * ease)
        spread = int(8 * ease)

        f1 = QFont(self.font())
        f1.setPixelSize(40)
        f1.setBold(True)
        f1.setLetterSpacing(QFont.AbsoluteSpacing, spread)
        p.setFont(f1)
        m1 = p.fontMetrics()
        w1 = m1.horizontalAdvance("MAXIMUM")

        f2 = QFont(self.font())
        f2.setPixelSize(40)
        f2.setBold(True)
        f2.setLetterSpacing(QFont.AbsoluteSpacing, spread)
        p.setFont(f2)
        m2 = p.fontMetrics()
        w2 = m2.horizontalAdvance("TWEAKS")

        gap = 34
        total = w1 + gap + w2
        x1 = cx - total / 2

        c1 = QColor(TEXT)
        c1.setAlpha(alpha)
        p.setPen(c1)
        p.setFont(f1)
        p.drawText(QRectF(x1, cy - 24, w1, 40), Qt.AlignCenter, "MAXIMUM")

        c2 = QColor(ACCENT)
        c2.setAlpha(alpha)
        p.setPen(c2)
        p.setFont(f2)
        p.drawText(QRectF(x1 + w1 + gap, cy - 24, w2, 40), Qt.AlignCenter, "TWEAKS")

        # hairline draws from the centre outwards
        hk = _clamp01((t - 1250) / 650.0)
        if hk > 0:
            he = _ease_in_out(hk)
            half = 110 * he
            grad = QLinearGradient(x1 - half, 0, x1 + half, 0)
            grad.setColorAt(0.0, QColor(139, 92, 246, 0))
            grad.setColorAt(0.5, QColor(139, 92, 246, int(120 * hk)))
            grad.setColorAt(1.0, QColor(139, 92, 246, 0))
            p.setBrush(grad)
            p.setPen(Qt.NoPen)
            p.drawRect(x1 - half, cy + 34, half * 2, 1)

    def _draw_toasts(self, p: QPainter, w: int, h: int, t: float):
        """Rapid sequential hardware/system toasts, near-center, fade out fast."""
        if self._update_phase:
            return
        if self._panel is not None and self._panel.isVisible():
            return
        if t < 2200:
            return
        cx = w / 2
        base_y = h * 0.42 + 170
        slot_h = 34
        show = []
        # stagger the four toasts quickly; each pops in and fades out fast
        for i, (prefix, text, kind) in enumerate(TOAST_DEFS):
            start = 2200 + i * 780
            fade_in = 220
            fade_out = 320
            hold = 1250
            end = start + fade_in + hold + fade_out
            if t < start or t > end:
                continue
            a_in = _clamp01((t - start) / fade_in)
            a_out = _clamp01((end - t) / fade_out)
            a = min(a_in, a_out)
            if a <= 0:
                continue
            value = self._toast_values.get(kind, "...")
            label = f"{text}: {value}" if value and value != "..." else f"{text}..."
            show.append((start, a, f"{prefix} {label}"))
        if not show:
            return

        font = QFont(self.font())
        font.setPixelSize(11)
        font.setBold(True)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 0.4)
        p.setFont(font)
        fm = p.fontMetrics()

        for start, a, text in show:
            tw = fm.horizontalAdvance(text)
            pad = 14
            bw = tw + pad * 2
            by = base_y + (start - 2200) // 780 * slot_h
            rect = QRectF(cx - bw / 2, by - 14, bw, 28)

            if a < 1:
                slide = (1.0 - a) * 7
                rect = QRectF(rect.x(), rect.y() + slide, rect.width(),
                              rect.height())

            pop = QColor(10, 15, 21, int(225 * a))
            p.setPen(QPen(QColor(139, 92, 246, int(90 * a)), 1))
            p.setBrush(pop)
            p.drawRoundedRect(rect, 14, 14)

            glyph = QColor(139, 92, 246, int(255 * a))
            p.setPen(glyph)
            p.drawText(rect.adjusted(pad, 0, 0, 0),
                       Qt.AlignLeft | Qt.AlignVCenter, text)

    def _draw_update_screen(self, p: QPainter, w: int, h: int, t: float):
        """Dedicated update loading screen (post-boot).

        Shown only when the update check is still pending after the boot /
        spec-detection phase finishes, so update status never overlaps the
        hardware toasts. A spinner ring while checking, a check mark once the
        check reports "ok"; an available / error outcome shows the panel.
        """
        cx = w / 2
        cy = h * 0.44
        r = 30
        # available / downloading / installing / error all use the panel card;
        # only checking (spinner) and ok (check) are drawn here.
        if self._panel.isVisible():
            return
        if self._update_state == "checking":
            p.setPen(QPen(QColor(139, 92, 246, 36), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)
            pen = QPen(QColor(139, 92, 246, 220), 4)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            start_angle = int((-t / 700.0) * 360 * 16)
            p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), start_angle, 100 * 16)
            heading = "CHECKING FOR UPDATES"
            sub = "Verifying the latest build\u2026"
        else:  # "ok"
            pen = QPen(QColor(139, 92, 246, 230), 4)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawLine(QPointF(cx - 14, cy + 2), QPointF(cx - 3, cy + 13))
            p.drawLine(QPointF(cx - 3, cy + 13), QPointF(cx + 15, cy - 11))
            heading = "UPDATES OK"
            sub = "You are running the latest build"

        f = QFont(self.font())
        f.setPixelSize(13)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 2.5)
        p.setFont(f)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(heading)
        col = QColor(139, 92, 246) if self._update_state == "ok" \
            else QColor(230, 238, 244)
        col.setAlpha(235)
        p.setPen(col)
        p.drawText(QRectF(cx - tw / 2, cy + r + 46, tw, 18), Qt.AlignCenter,
                   heading)

        f2 = QFont(self.font())
        f2.setPixelSize(11)
        f2.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        p.setFont(f2)
        fm2 = p.fontMetrics()
        sw = fm2.horizontalAdvance(sub)
        p.setPen(QColor(124, 147, 166))
        p.drawText(QRectF(cx - sw / 2, cy + r + 70, sw, 16), Qt.AlignCenter,
                   sub)

    def _draw_progress(self, p: QPainter, w: int, h: int, t: float, pct: int):
        if t < 900:
            return
        # The update screen and the inline update panel each own their progress
        # display; the bottom boot bar only belongs to the boot phase.
        if self._update_phase or self._panel.isVisible():
            return
        cx = w / 2
        y = h - 74
        bar_w = 340
        x0 = cx - bar_w / 2

        p.setBrush(QColor(22, 30, 38))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(x0, y, bar_w, 2), 1, 1)

        fill_w = bar_w * pct / 100.0
        gr = QLinearGradient(x0, 0, x0 + bar_w, 0)
        gr.setColorAt(0.0, QColor(124, 58, 237))
        gr.setColorAt(1.0, ACCENT)
        p.setBrush(gr)
        if fill_w > 2:
            p.drawRoundedRect(QRectF(x0, y, fill_w, 2), 1, 1)
            glow = QRadialGradient(x0 + fill_w, y + 1, 9)
            glow.setColorAt(0.0, QColor(139, 92, 246, 150))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(glow)
            p.drawEllipse(QPointF(x0 + fill_w, y + 1), 9, 9)

        # percent
        f = QFont(self.font())
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor(139, 92, 246, 200))
        p.drawText(QRectF(cx + bar_w / 2 + 14, y - 10, 42, 20),
                   Qt.AlignLeft | Qt.AlignVCenter, f"{pct}%")

        # status line above the bar: fixed while the update flow drives it,
        # otherwise cycling through the boot sequence
        cy = y - 26
        fa = QFont(self.font())
        fa.setPixelSize(11)
        fa.setBold(True)
        fa.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(fa)
        fm = p.fontMetrics()

        st = self._update_state
        if self._update_phase and st in ("checking", "ok", "downloading",
                                         "installing", "error"):
            shown = {
                "checking": "CHECKING FOR UPDATES",
                "ok": "UPDATES OK",
                "downloading": "DOWNLOADING UPDATE",
                "installing": "INSTALLING UPDATE",
                "error": "UPDATE ERROR",
            }[st]
            if st == "error":
                col = QColor(255, 118, 118)
            elif st == "checking":
                col = QColor(130, 155, 172)
            else:
                col = QColor(139, 92, 246)
            col.setAlpha(235)
            tw = fm.horizontalAdvance(shown)
            p.setPen(col)
            p.drawText(QRectF(cx - tw / 2, cy - 8, tw, 16), Qt.AlignCenter,
                       shown)
            return

        hold = (self._dur_ms - 1450) / len(STATUS_SEQ)
        idx = int((t - 1450) / hold)
        idx = max(0, min(len(STATUS_SEQ) - 1, idx))
        shown = STATUS_SEQ[idx]
        tw = fm.horizontalAdvance(shown)
        stage = ((t - 1450) / hold) % 1.0
        fad = 0.35 + 0.65 * _clamp01(stage)
        if idx == len(STATUS_SEQ) - 1:
            col = QColor(139, 92, 246)
        else:
            col = QColor(130, 155, 172)
        col.setAlpha(int(235 * fad))
        p.setPen(col)
        p.drawText(QRectF(cx - tw / 2, cy - 8, tw, 16), Qt.AlignCenter, shown)

    def _draw_footer(self, p: QPainter, w: int, h: int):
        f = QFont(self.font())
        f.setPixelSize(10)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(f)
        p.setPen(FAINT)
        p.drawText(QRectF(40, h - 36, 300, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   f"MAXIMUM ENGINE \u00b7 v{APP_VERSION}")
        p.drawText(QRectF(w - 340, h - 36, 300, 16),
                   Qt.AlignRight | Qt.AlignVCenter, "SECURE BOOT \u00b7 LOW LATENCY")