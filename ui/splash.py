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
    QBrush,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
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

from config.app_config import APP_VERSION, DIRS

ACCENT = QColor("#8B6BFF")
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
    color: #8B6BFF;
    font-size: 13px;
    font-weight: 700;
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
                                      stop: 0 #7C3AED, stop: 1 #8B6BFF);
    border-radius: 3px;
}
#UpdPrimary {
    background-color: #8B6BFF;
    color: #F6F4FC;
    border: none;
    border-radius: 8px;
    padding: 8px 20px;
    font-size: 12px;
    font-weight: 700;
}
#UpdPrimary:hover {
    background-color: #9C80FF;
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
    """Boot screen — port of loading-screen-fullscreen.html.

    Fullscreen + always-on-top (locked above everything, but still Alt+Tab-
    able). Renders the reference: brand topbar with live clock, tracking
    stage label, a giant % number in a white->violet-soft->cyan gradient,
    MAXIMUM TWEAKS mono wordmark, violet->cyan bar with the real current
    step line, and a bottom bar with three status chips (hardware / tweak
    database / license) that light green as each real check lands. Core +
    corner glow blobs, 38px dot grid and rising particles fill the screen.

    API: signals build_now, finished, install_clicked, skip_clicked,
    retry_clicked; methods start(), update_checking(), update_ok(),
    update_available(cur,new,notes), update_progress(frac), set_installing(),
    update_error(msg), fade_out(ms, on_done).
    """

    build_now = Signal()
    finished = Signal()
    install_clicked = Signal()
    skip_clicked = Signal()
    retry_clicked = Signal()

    STAGES = ((0, "INITIALIZING ENGINE"), (24, "DETECTING HARDWARE"),
              (40, "LOADING TWEAK DATABASE"), (58, "VERIFYING LICENSE"),
              (88, "STARTING ENGINE"), (98, "READY"))
    STEPS = (
        (0, "Detecting GPU — {gpu}"),
        (12, "Detecting CPU — {cpu}"),
        (24, "Reading system memory — {ram}"),
        (40, "Loading tweak database — {db} entries"),
        (58, "Verifying license — {license}"),
        (72, "Restoring last session state"),
        (88, "Starting Maximum Engine"),
        (98, "Ready"),
    )
    HOLD_PCT = 58

    def __init__(self, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint)
        self._t0: float | None = None
        self._dur_ms = _dur
        self._done_emitted = False
        self._build_emitted = False
        self._started = False
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._toast_values: dict = {"gpu": "...", "cpu": "...",
                                    "ram": "...", "db": "...",
                                    "license": "..."}
        self._probe: _ProbeThread | None = None
        import random as _r
        self._particles = [(_r.random(), _r.uniform(8.0, 18.0),
                            _r.uniform(0.0, 10.0), _r.uniform(0.20, 0.70))
                           for _ in range(40)]
        self._update_phase = False
        self._entered_phase = False
        self._pending_panel = None
        self._update_state = "idle"
        self._held = False
        self._ok_hold_until: float | None = None
        self._download_frac = 0.0
        self._panel = _UpdatePanel(self)
        self._panel.hide()
        self._panel.install.connect(self.install_clicked)
        self._panel.skip.connect(self.skip_clicked)
        self._panel.retry.connect(self.retry_clicked)
        self._bg: QPixmap | None = None
        self._load_db()

    def _load_db(self):
        try:
            from database import TWEAKS
            self._toast_values["db"] = str(len(TWEAKS))
        except Exception:  # noqa: BLE001
            self._toast_values["db"] = "..."

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
        if self._probe is not None and self._probe.isRunning():
            return
        self._probe = _ProbeThread(self)
        self._probe.result.connect(self._on_probe_result)
        self._probe.start()

    def _on_probe_result(self, values: dict):
        v = dict(values or {})
        v.setdefault("license", v.get("license", "..."))
        self._toast_values.update(v)
        self.update()

    # ---------------- inline update flow ----------------

    def update_checking(self):
        self._update_state = "checking"
        self._held = True
        self._ok_hold_until = None
        self._panel.hide()
        self.update()

    def _enter_update_phase(self):
        fn = self._pending_panel
        self._pending_panel = None
        if fn is not None:
            self._update_phase = True
            fn()
        elif self._update_state == "checking":
            self._update_phase = True
            self._held = True
            self.update()

    def update_ok(self):
        self._update_state = "ok"
        self._held = False
        self._update_phase = False
        self._ok_hold_until = _monotonic_ms() + 650.0
        self._panel.hide()
        self.update()

    def update_available(self, current: str, new: str, notes: str = ""):
        self._update_state = "available"
        if self._update_phase:
            self._panel.show_info(current, new, notes)
            self._show_panel()
        else:
            self._held = True
            self._pending_panel = lambda: (
                self._panel.show_info(current, new, notes), self._show_panel())

    def update_progress(self, frac: float):
        self._update_state = "downloading"
        self._download_frac = _clamp01(frac)
        self._panel.show_download(self._download_frac)
        self._show_panel()
        self.update()

    def set_installing(self):
        self._update_state = "installing"
        self._download_frac = 1.0
        self._panel.show_installing()
        self._show_panel()
        self.update()

    def update_error(self, message: str):
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
        y = int(self.height() * 0.72) - ph // 2
        self._panel.setGeometry(x, y, pw, ph)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._bg = None
        if self._panel is not None and self._panel.isVisible():
            self._position_panel()

    def fade_out(self, duration_ms: int = 700, on_done=None):
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
        now = _monotonic_ms()
        if self._t0 is None:
            self._t0 = now
        t = now - self._t0
        if self._ok_hold_until is not None and now >= self._ok_hold_until:
            self._ok_hold_until = None
        if t >= self._dur_ms and not self._entered_phase:
            self._entered_phase = True
            self._enter_update_phase()
        if (t >= self._dur_ms and not self._done_emitted
                and not self._held and self._ok_hold_until is None):
            self._done_emitted = True
            self.finished.emit()
        pct = self._current_pct(t)
        if pct >= 88 and not self._build_emitted:
            self._build_emitted = True
            self.build_now.emit()
        self.update()

    def _current_pct(self, t: float | None = None) -> float:
        if t is None:
            t = 0.0 if self._t0 is None else _monotonic_ms() - self._t0
        u = _clamp01(t / self._dur_ms)
        pct = _ease_out_cubic(u) * 100.0
        if self._update_state == "downloading":
            pct = max(pct, 58.0 + self._download_frac * 32.0)
        elif self._update_state == "installing":
            pct = 96.0
        elif self._held:
            pct = min(pct, float(self.HOLD_PCT))
        return min(pct, 100.0)

    # ---------------- painting ----------------

    def paintEvent(self, _event):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        now = _monotonic_ms()
        t = 0.0 if self._t0 is None else now - self._t0
        pct = self._current_pct(t)

        if (self._bg is None or self._bg.width() != w
                or self._bg.height() != h):
            self._bg = self._render_bg(w, h)
        p = QPainter(self)
        p.drawPixmap(0, 0, self._bg)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        self._draw_particles(p, w, h, t)
        self._draw_topbar(p, w, t)
        self._draw_hero(p, w, h, pct, t)
        self._draw_bottombar(p, w, h, pct)
        p.end()

    def _render_bg(self, w: int, h: int) -> QPixmap:
        """#050309 void + three huge soft blobs (violet TL, cyan BR, violet
        core) + 38px dot grid masked to the centre (CSS .blob/.dots)."""
        pm = QPixmap(w, h)
        pm.fill(QColor("#050309"))
        p = QPainter(pm)
        core = QRadialGradient(QPointF(w / 2, h * 0.48), max(w, h) * 0.55)
        core.setColorAt(0.0, QColor(139, 107, 255, 36))
        core.setColorAt(0.6, QColor(139, 107, 255, 0))
        p.fillRect(pm.rect(), core)
        ga = QRadialGradient(QPointF(190, 70), 420)
        ga.setColorAt(0.0, QColor(139, 107, 255, 56))
        ga.setColorAt(0.7, QColor(139, 107, 255, 0))
        p.fillRect(pm.rect(), ga)
        gb = QRadialGradient(QPointF(w - 180, h - 40), 400)
        gb.setColorAt(0.0, QColor(75, 232, 216, 33))
        gb.setColorAt(0.7, QColor(75, 232, 216, 0))
        p.fillRect(pm.rect(), gb)
        cx, cy = 0.50 * w, 0.45 * h
        rx, ry = 0.75 * w, 0.70 * h
        y = 19.0
        while y < h:
            x = 19.0
            while x < w:
                d = (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2) ** 0.5
                if d < 0.92:
                    a = int(43 * (1.0 - d / 0.92))
                    if a > 3:
                        p.setPen(QColor(200, 190, 240, a))
                        p.drawPoint(QPointF(x, y))
                x += 38.0
            y += 38.0
        p.end()
        return pm

    def _draw_particles(self, p: QPainter, w: int, h: int, t: float):
        for fx, dur, delay, op in self._particles:
            lt = (t / 1000.0 - delay) % dur
            if t / 1000.0 < delay:
                continue
            prog = lt / dur
            y = h + 10 - prog * (h + 20)
            a = op * 255
            if prog < 0.1:
                a *= prog / 0.1
            elif prog > 0.9:
                a *= (1.0 - prog) / 0.1
            p.setPen(Qt.NoPen)
            c = QColor(201, 192, 255, int(max(0.0, min(1.0, a / 255)) * 160))
            p.setBrush(c)
            p.drawEllipse(QPointF(fx * w, y), 1.2, 1.2)

    def _load_pfp(self):
        if getattr(self, "_pfp", None) is not None:
            return self._pfp
        pm = QPixmap()
        # 1) the user's own profile picture if one has been set...
        try:
            from engine.state import pfp_path
            path = pfp_path()
            if path:
                pm = QPixmap(path)
        except Exception:  # noqa: BLE001
            pm = QPixmap()
        # 2) otherwise the official Maximum logo so we never show the bare "M".
        if pm is None or pm.isNull():
            try:
                logo = DIRS["assets"] / "rex_logo.png"
                if logo.is_file():
                    pm = QPixmap(str(logo))
            except Exception:  # noqa: BLE001
                pm = QPixmap()
        self._pfp = pm
        return pm

    def _draw_topbar(self, p: QPainter, w: int, t: float):
        # brand mark — the user's profile picture, or the official Maximum
        # logo if no PFP has been set (falling back to the "M" monogram only
        # if even the logo is unavailable).
        rect = QRectF(40, 28, 30, 30)
        pfp = self._load_pfp()
        if pfp is not None and not pfp.isNull():
            pm = pfp.scaled(int(rect.width()), int(rect.height()),
                            Qt.KeepAspectRatio, Qt.SmoothTransformation)
            path = QPainterPath()
            path.addRoundedRect(rect, 9, 9)
            p.save()
            p.setClipPath(path)
            p.drawPixmap(rect, pm, QRectF(pm.rect()))
            p.setClipping(False)
            p.setPen(QPen(QColor(150, 130, 235, 120), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect, 9, 9)
            p.restore()
        else:
            grad = QRadialGradient(QPointF(rect.left() + 0.35 * 30,
                                           rect.top() + 0.30 * 30), 36)
            grad.setColorAt(0.0, QColor(139, 107, 255, 128))
            grad.setColorAt(1.0, QColor(11, 8, 20, 230))
            p.setBrush(grad)
            p.setPen(QPen(QColor(150, 130, 235, 102), 1))
            p.drawRoundedRect(rect, 9, 9)
            f = QFont("Segoe UI", 10)
            f.setWeight(QFont.Weight.Bold)
            p.setFont(f)
            p.setPen(QColor("#C9C0FF"))
            p.drawText(rect, Qt.AlignCenter, "M")
        fb = QFont("Segoe UI", 13)
        fb.setWeight(QFont.Weight.DemiBold)
        p.setFont(fb)
        p.setPen(QColor("#F6F4FC"))
        p.drawText(QRectF(81, 28, 320, 30),
                   Qt.AlignVCenter | Qt.AlignLeft, "Maximum Tweaks")
        # elapsed clock
        secs = int(t / 1000)
        fc = QFont("JetBrains Mono", 11)
        fc.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
        p.setFont(fc)
        p.setPen(QColor("#514A70"))
        p.drawText(QRectF(w - 240, 28, 200, 30),
                   Qt.AlignVCenter | Qt.AlignRight,
                   "%02d:%02d:%02d" % (secs // 3600, (secs // 60) % 60,
                                        secs % 60))

    def _hero_font(self, px, weight):
        f = QFont("Segoe UI", 1)
        f.setPixelSize(px)
        f.setWeight(weight)
        f.setLetterSpacing(QFont.AbsoluteSpacing, -0.02 * px)
        return f

    def _draw_hero(self, p: QPainter, w: int, h: int, pct: float,
                   t: float):
        # stage label
        stage = self.STAGES[0][1]
        for thr, txt in self.STAGES:
            if pct >= thr:
                stage = txt
        if self._update_state in ("checking",):
            stage = "CHECKING FOR UPDATES"
        elif self._update_state == "downloading":
            stage = "DOWNLOADING UPDATE"
        elif self._update_state == "installing":
            stage = "INSTALLING UPDATE"
        elif self._update_state == "error":
            stage = "UPDATE CHECK FAILED"
        fs = QFont("JetBrains Mono", 12)
        fs.setLetterSpacing(QFont.AbsoluteSpacing, 2.6)
        p.setFont(fs)
        p.setPen(QColor("#C9C0FF"))
        p.drawText(QRectF(0, h * 0.20, w, 20), Qt.AlignCenter, stage)

        # giant percentage with gradient fill
        size = int(max(72, min(128, w * 0.062)))
        label = "%d" % int(round(pct)) + "%"
        pf = self._hero_font(size, QFont.Weight.Bold)
        p.setFont(pf)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(label)
        rect = QRectF((w - tw) / 2.0, h * 0.5 - fm.height() * 0.62,
                      tw, fm.height() * 1.25)
        grad = QLinearGradient(rect.topLeft(),
                               rect.bottomRight() * 1.0)
        g2 = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        g2.setColorAt(0.0, QColor("#FFFFFF"))
        g2.setColorAt(0.55, QColor("#C9C0FF"))
        g2.setColorAt(1.0, QColor("#4BE8D8"))
        glow = QRadialGradient(rect.center(), rect.width() * 0.75)
        glow.setColorAt(0.0, QColor(139, 107, 255, 40))
        glow.setColorAt(1.0, QColor(139, 107, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(rect.center(), rect.width() * 0.62,
                      rect.width() * 0.62)
        p.setFont(pf)
        tpen = QPen()
        tpen.setBrush(QBrush(g2))
        p.setPen(tpen)
        p.drawText(rect, Qt.AlignCenter, label)

        # wordmark
        fw = QFont("JetBrains Mono", 12)
        fw.setLetterSpacing(QFont.AbsoluteSpacing, 5.0)
        p.setFont(fw)
        p.setPen(QColor("#514A70"))
        wr = QRectF(0, rect.bottom() + 10, w, 18)
        p.drawText(wr, Qt.AlignCenter, "MAXIMUM TWEAKS")

        # progress bar + step line
        bw = min(640.0, w * 0.60)
        bx = (w - bw) / 2.0
        by = wr.bottom() + 26
        track = QRectF(bx, by, bw, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 15))
        p.drawRoundedRect(track, 3, 3)
        fw2 = bw * pct / 100.0
        if fw2 > 1:
            bg = QLinearGradient(track.topLeft(), track.topRight())
            bg.setColorAt(0.0, QColor("#8B6BFF"))
            bg.setColorAt(1.0, QColor("#4BE8D8"))
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(bx, by, fw2, 6), 3, 3)
        step = self.STEPS[0][1]
        for thr, txt in self.STEPS:
            if pct >= thr:
                step = txt
        for k in ("gpu", "cpu", "ram", "db", "license"):
            token = "{" + k + "}"
            if token in step:
                val = self._toast_values.get(k) or "..."
                step = step.replace(token, str(val))
        fst = QFont("JetBrains Mono", 11)
        p.setFont(fst)
        fm2 = p.fontMetrics()
        line = "[+]  " + step
        lw = fm2.horizontalAdvance(line)
        sr = QRectF((w - lw) / 2.0, by + 16, lw, 18)
        p.setPen(QColor("#C9C0FF"))
        p.drawText(QRectF(sr.left(), sr.top(),
                         fm2.horizontalAdvance("[+]  "), 18),
                   Qt.AlignLeft | Qt.AlignVCenter, "[+]")
        p.setPen(QColor("#514A70"))
        p.drawText(QRectF(sr.left() + fm2.horizontalAdvance("[+]  "),
                         sr.top(), lw, 18),
                   Qt.AlignLeft | Qt.AlignVCenter, step)

    def _draw_bottombar(self, p: QPainter, w: int, h: int, pct: float):
        top = h - 66
        p.setPen(QPen(QColor(255, 255, 255, 15), 1))
        p.drawLine(QPointF(40, top), QPointF(w - 40, top))
        fv = QFont("JetBrains Mono", 10)
        fv.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
        p.setFont(fv)
        p.setPen(QColor("#514A70"))
        p.drawText(QRectF(40, top + 10, 480, 20),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   "MAXIMUM ENGINE \u00b7 v" + APP_VERSION)
        vals = self._toast_values
        chips = (
            ("Hardware detected", bool(vals.get("gpu")) and vals.get("gpu") not in ("...", "GPU")),
            ("Tweak database loaded", vals.get("db") not in ("...", None) and str(vals.get("db", "")).isdigit()),
            ("License verified", str(vals.get("license", "")).startswith("OK")),
        )
        x = float(w - 40)
        for label, on in reversed(chips):
            f2 = QFont("JetBrains Mono", 9)
            f2.setLetterSpacing(QFont.AbsoluteSpacing, 0.55)
            p.setFont(f2)
            fm2 = p.fontMetrics()
            up = label.upper()
            cw = fm2.horizontalAdvance(up) + 30
            crect = QRectF(x - cw, top + 7, cw, 24)
            x -= cw + 9
            if on:
                p.setPen(QPen(QColor(61, 220, 151, 90), 1))
                p.setBrush(QColor(61, 220, 151, 20))
                p.drawRoundedRect(crect, 7, 7)
                p.setPen(QColor("#3DDC97"))
                p.setBrush(QColor("#3DDC97"))
            else:
                p.setPen(QPen(QColor(255, 255, 255, 23), 1))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(crect, 7, 7)
                p.setPen(QColor("#514A70"))
                p.setBrush(QColor("#514A70"))
            p.drawEllipse(QPointF(crect.left() + 12, crect.center().y()),
                          2.5, 2.5)
            p.drawText(crect.adjusted(18, 0, -6, 0),
                       Qt.AlignVCenter | Qt.AlignLeft, up)
