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

Update flow (full-screen, ported from updater-flow.html — no card, no popup):
    splash.arm_update_check()                     # check runs behind the boot
    the boot sequence plays normally first; at its mid milestone either the
    resolved result reveals directly or the "Checking for updates" view takes
    over. splash.update_check_result(info, error) delivers the result.
    while downloading: update_progress(frac); then update_downloaded()
    on failure: update_error(msg)
    buttons: Install (install_clicked), Skip (skip_clicked), Retry
    (retry_clicked), and the ready view's green Restart (restart_clicked).
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


_FLOW_QSS = """
#FlowGhost {
    background: rgba(255, 255, 255, 0.03);
    color: #F6F4FC;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 11px;
    padding: 12px 26px;
    font-family: "Inter";
    font-size: 13.5px;
    font-weight: 600;
}
#FlowGhost:hover { background: rgba(255, 255, 255, 0.07); }
#FlowGhost:pressed { background: rgba(255, 255, 255, 0.10); }
#FlowGhost:disabled { color: #514A70; border-color: rgba(255, 255, 255, 0.05); }

#FlowPrimary {
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                stop: 0 #8B6BFF, stop: 1 #6D4FE0);
    color: #FFFFFF;
    border: none;
    border-radius: 11px;
    padding: 12px 26px;
    font-family: "Inter";
    font-size: 13.5px;
    font-weight: 600;
}
#FlowPrimary:hover { background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                stop: 0 #9D80FF, stop: 1 #7A5CF2); }
#FlowPrimary:pressed { background: #6D4FE0; }
#FlowPrimary:disabled { background: #2A2440; color: #5C5A6B; }

#FlowGreen {
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                stop: 0 #3DDC97, stop: 1 #1F8F63);
    color: #07140F;
    border: none;
    border-radius: 11px;
    padding: 12px 26px;
    font-family: "Inter";
    font-size: 13.5px;
    font-weight: 600;
}
#FlowGreen:hover { background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                stop: 0 #57E6A8, stop: 1 #26A16F); }
#FlowGreen:pressed { background: #1F8F63; }
#FlowGreen:disabled { background: #14362A; color: #5C8A77; }
"""


class _RingSpinner(QWidget):
    """64px rotating ring (updater-flow.html .spin-ring): a faint violet track
    with a bright sweeping leading edge, one 0.9s revolution."""

    def __init__(self, parent=None, size: int = 64):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._rot = 0.0
        self._t = QTimer(self)
        self._t.setInterval(16)
        self._t.timeout.connect(self._tick)

    def start(self):
        if not self._t.isActive():
            self._t.start()
            self.show()
            self.raise_()

    def stop(self):
        self._t.stop()
        self.hide()

    def _tick(self):
        self._rot = (self._rot + 360.0 / 900.0) % 360.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2.0, self.height() / 2.0)
        r = self.width() / 2.0 - 2.0
        track = QPen(QColor(150, 130, 235, 46), 2)
        track.setCapStyle(Qt.RoundCap)
        p.setPen(track)
        p.drawArc(QRectF(c.x() - r, c.y() - r, r * 2, r * 2), 0, 360 * 16)
        sweep = QPen(QColor("#C9C0FF"), 2)
        sweep.setCapStyle(Qt.RoundCap)
        p.setPen(sweep)
        p.drawArc(QRectF(c.x() - r, c.y() - r, r * 2, r * 2),
                  int(-(90.0 + self._rot) * 16), int(250 * 16))
        p.end()


# ---------------------------------------------------------------------------
# Full-screen update flow — pixel-accurate port of updater-flow.html.
# The boot canvas keeps painting the background/blobs/dots/topbar/bottombar;
# the hero area swaps between the flow's views (checking, update available,
# downloading, installing, ready, error). Action buttons are real widgets so
# they stay clickable on top of the painted scene.
# ---------------------------------------------------------------------------
_HEAD_FONT = 22
_SUB_WIDTH = 420
_ACTIONS_Y = 0.685          # vertical centre of the action-button row
_ACTIONS_H = 44


def _flow_font(family: str, pixel: int, weight: QFont.Weight,
               spacing: float = 0.0) -> QFont:
    f = QFont(family, 1)
    f.setPixelSize(pixel)
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


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
    retry_clicked, restart_clicked; methods start(), update_checking(),
    update_ok(), update_available(cur,new,notes), update_progress(frac),
    update_downloaded(), set_download_bytes(total), update_error(msg),
    fade_out(ms, on_done).
    """

    build_now = Signal()
    finished = Signal()
    install_clicked = Signal()
    skip_clicked = Signal()
    retry_clicked = Signal()
    restart_clicked = Signal()

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
        self._update_state = "idle"
        self._check_armed = False
        self._check_parked: dict | None = None
        self._held = False
        self._ok_hold_until: float | None = None
        self._download_frac = 0.0
        self._dl_total_bytes = 0
        self._dl_probe_at: float | None = None
        self._dl_probe_frac = 0.0
        self._dl_speed = "0.0 MB/s"
        self._dl_speed_raw = -1.0
        self._dl_start_pct = 58.0
        self._flow_cur = APP_VERSION.lstrip("v")
        self._flow_new = ""
        self._flow_items: list[str] = []
        self._flow_error = ""

        # Full-screen update-flow chrome: spinner + the action buttons.
        self._spinner = _RingSpinner(self)
        self._spinner.raise_()

        self._btn_skip = QPushButton("Skip", self)
        self._btn_skip.setObjectName("FlowGhost")
        self._btn_skip.setStyleSheet(_FLOW_QSS)
        self._btn_skip.setCursor(Qt.PointingHandCursor)
        self._btn_skip.hide()

        self._btn_primary = QPushButton("Install update", self)
        self._btn_primary.setObjectName("FlowPrimary")
        self._btn_primary.setStyleSheet(_FLOW_QSS)
        self._btn_primary.setCursor(Qt.PointingHandCursor)
        self._btn_primary.hide()

        self._btn_restart = QPushButton("Restart now", self)
        self._btn_restart.setObjectName("FlowGreen")
        self._btn_restart.setStyleSheet(_FLOW_QSS)
        self._btn_restart.setCursor(Qt.PointingHandCursor)
        self._btn_restart.hide()

        self._btn_skip.clicked.connect(self.skip_clicked)
        self._btn_primary.clicked.connect(self._on_flow_primary)
        self._btn_restart.clicked.connect(self.restart_clicked)
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

    # ---------------- full-screen update flow ----------------

    def update_checking(self):
        self._update_state = "checking"
        self._held = True
        self._ok_hold_until = None
        self._set_actions(None)
        self._spinner.start()
        self.update()

    def arm_update_check(self):
        """Run the update check in the background: the boot sequence plays
        normally first and the check view only takes over at the mid
        milestone (never as the first thing on the loading screen)."""
        self._check_parked = None
        self._check_armed = True

    def update_check_result(self, info: dict | None, error: str | None):
        """Consume a finished background check. If the boot is still playing
        its opening sequence, park the result until the mid milestone;
        otherwise reveal it immediately."""
        if self._check_armed:
            self._check_parked = {"info": info, "error": error}
            return
        self._did_resolve_check(info, error)

    def _did_resolve_check(self, info, error):
        if error:
            self.update_error(error)
        elif info is None:
            self.update_ok()
        else:
            self.update_available(
                APP_VERSION, str(info.get("version") or ""),
                info.get("notes") or "")

    def update_ok(self):
        self._update_state = "ok"
        self._held = False
        self._ok_hold_until = _monotonic_ms() + 650.0
        self._set_actions(None)
        self._spinner.stop()
        self.update()

    def update_available(self, current: str, new: str, notes: str = ""):
        self._update_state = "available"
        self._flow_cur = str(current or "").lstrip("v")
        self._flow_new = str(new or "").lstrip("v")
        self._flow_items = self._parse_flow_notes(notes)[:3]
        self._held = True
        self._ok_hold_until = None
        self._spinner.stop()
        self._set_actions(("skip", "install"))
        self.update()

    def set_download_bytes(self, total: int):
        self._dl_total_bytes = int(total or 0)

    def update_progress(self, frac: float):
        if self._update_state != "downloading":
            self._dl_start_pct = self._current_pct()
        self._update_state = "downloading"
        self._download_frac = _clamp01(frac)
        self._track_download_speed()
        self._held = True
        self._set_actions(None)
        self._spinner.stop()
        self.update()

    def update_downloaded(self):
        """Download finished — play the installing beat, then the ready view
        with the green Restart action (ported from updater-flow.html)."""
        self._update_state = "installing"
        self._download_frac = 1.0
        self._held = True
        self._set_actions(None)
        self._spinner.start()
        self.update()
        QTimer.singleShot(1400, self._ready_view)

    def _ready_view(self):
        if self._update_state == "installing":
            self._update_state = "ready"
            self._held = True
            self._spinner.stop()
            self._set_actions(("restart",))
            self.update()

    def update_error(self, message: str):
        self._update_state = "error"
        self._flow_error = str(message or "Couldn\u2019t check for updates.")
        self._held = True
        self._ok_hold_until = None
        self._spinner.stop()
        self._set_actions(("skip", "retry"))
        self.update()

    def _parse_flow_notes(self, notes: str) -> list[str]:
        lines = [ln.strip() for ln in (notes or "").replace("\r", "").splitlines()
                 if ln.strip()]
        out: list[str] = []
        for ln in lines:
            ln = ln.lstrip("-*+#>\u26a1").strip()
            if not ln:
                continue
            out.append(ln)
        return out

    @staticmethod
    def _wrap_text(fm, text: str, max_w: float) -> list[str]:
        words = text.split(" ")
        if not words:
            return []
        lines: list[str] = []
        cur = ""
        for word in words:
            trial = word if not cur else cur + " " + word
            if fm.horizontalAdvance(trial) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def _track_download_speed(self):
        now = _monotonic_ms()
        if self._dl_probe_at is not None and self._dl_total_bytes > 0:
            dt = (now - self._dl_probe_at) / 1000.0
            df = max(0.0, self._download_frac - self._dl_probe_frac)
            if dt > 0.05:
                mb = df * self._dl_total_bytes / 1048576.0
                raw = mb / dt
                if self._dl_speed_raw < 0:
                    self._dl_speed_raw = raw
                else:
                    self._dl_speed_raw = self._dl_speed_raw * 0.7 + raw * 0.3
                self._dl_speed = f"{self._dl_speed_raw:.1f} MB/s"
        self._dl_probe_at = now
        self._dl_probe_frac = self._download_frac

    def _on_flow_primary(self):
        if self._update_state == "available":
            self.install_clicked.emit()
        elif self._update_state == "error":
            self.retry_clicked.emit()

    def _set_actions(self, spec):
        """spec: None | ('skip','install') | ('skip','retry') | ('restart',)."""
        skip, primary, restart = self._btn_skip, self._btn_primary, self._btn_restart
        if spec == ("skip", "install"):
            skip.setText("Skip")
            skip.show()
            primary.setText("Install update")
            primary.show()
            restart.hide()
        elif spec == ("skip", "retry"):
            skip.setText("Skip")
            skip.show()
            primary.setText("Retry")
            primary.show()
            restart.hide()
        elif spec == ("restart",):
            restart.setText("Restart now")
            restart.show()
            skip.hide()
            primary.hide()
        else:
            skip.hide()
            primary.hide()
            restart.hide()
        self._layout_actions()

    def _layout_actions(self):
        vis = [b for b in (self._btn_skip, self._btn_primary, self._btn_restart)
               if b.isVisible()]
        if not vis:
            return
        widths = [max(b.sizeHint().width(), 0) for b in vis]
        gap = 12
        total = sum(widths) + gap * (len(vis) - 1)
        x = (self.width() - total) / 2.0
        y = self.height() * _ACTIONS_Y - _ACTIONS_H / 2.0
        for b, wd in zip(vis, widths):
            b.setGeometry(round(x), round(y), wd, _ACTIONS_H)
            x += wd + gap

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._bg = None
        self._layout_actions()
        if getattr(self, "_spinner", None) is not None:
            self.update()

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
        if (t >= self._dur_ms and not self._done_emitted
                and not self._held and self._ok_hold_until is None):
            self._done_emitted = True
            self.finished.emit()
        pct = self._current_pct(t)
        # The update check runs behind the boot sequence; it only takes over
        # the screen once the loading reaches the mid milestone (or at the end
        # of the boot if it somehow never crossed it).
        if self._check_armed and (pct >= float(self.HOLD_PCT)
                                  or self._entered_phase):
            self._check_armed = False
            parked = self._check_parked
            self._check_parked = None
            if parked is not None:
                self._did_resolve_check(parked.get("info"),
                                        parked.get("error"))
            else:
                self.update_checking()
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
            start = max(self._dl_start_pct, 58.0)
            range_top = max(start + self._download_frac * (100.0 - start),
                           start)
            pct = min(range_top, 100.0)
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
            f = _flow_font("Space Grotesk", 13, QFont.Weight.Bold)
            p.setFont(f)
            p.setPen(QColor("#C9C0FF"))
            p.drawText(rect, Qt.AlignCenter, "M")
        fb = _flow_font("Space Grotesk", 14, QFont.Weight.DemiBold)
        p.setFont(fb)
        p.setPen(QColor("#F6F4FC"))
        p.drawText(QRectF(81, 28, 320, 30),
                   Qt.AlignVCenter | Qt.AlignLeft, "Maximum Tweaks")
        # step tracker (update flow) or elapsed clock
        _step = {"checking": 1, "available": 1, "downloading": 2,
                 "installing": 3, "ready": 4}.get(self._update_state, 0)
        if _step:
            fc = QFont("JetBrains Mono", 10.5)
            fc.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
            p.setFont(fc)
            s1, s2 = "Step ", " of 4"
            sn = str(_step)
            w1 = p.fontMetrics().horizontalAdvance(s1)
            wn = p.fontMetrics().horizontalAdvance(sn)
            x = w - 40 - (w1 + wn + p.fontMetrics().horizontalAdvance(s2))
            p.setPen(QColor("#514A70"))
            p.drawText(QRectF(x, 28, w1 + wn, 30),
                       Qt.AlignVCenter | Qt.AlignLeft, s1)
            p.setPen(QColor("#C9C0FF"))
            p.drawText(QRectF(x + w1, 28, wn, 30),
                       Qt.AlignVCenter | Qt.AlignLeft, sn)
            p.setPen(QColor("#514A70"))
            p.drawText(QRectF(x + w1 + wn, 28, 240, 30),
                       Qt.AlignVCenter | Qt.AlignLeft, s2)
        else:
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
        if self._update_state in ("checking", "available", "downloading",
                                  "installing", "ready", "error"):
            self._draw_flow(p, w, h)
            return
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

    # ---------------- update-flow painting ----------------

    def _draw_flow(self, p: QPainter, w: int, h: int):
        st = self._update_state
        stage = {"checking": "Updater", "available": "Update available",
                 "downloading": "Downloading update",
                 "installing": "Installing"}.get(st)
        if stage:
            self._draw_stage(p, w, h, stage.upper())
        if st == "checking":
            self._spinner.move(w // 2 - 32, int(h * 0.32))
            self._spinner.start()
            self._draw_state(p, w, int(h * 0.32) + 64 + 34,
                             "Checking for updates",
                             "Comparing your installed version against the "
                             "latest release.")
        elif st == "available":
            self._spinner.stop()
            self._draw_available(p, w, h)
        elif st == "downloading":
            self._spinner.stop()
            self._draw_downloading(p, w, h)
        elif st == "installing":
            self._spinner.move(w // 2 - 32, int(h * 0.32))
            self._spinner.start()
            self._draw_state(p, w, int(h * 0.32) + 64 + 34,
                             "Applying update",
                             "Replacing app files and verifying integrity \u2014 "
                             "this only takes a moment.")
        elif st == "ready":
            self._spinner.stop()
            self._draw_ready(p, w, h)
        elif st == "error":
            self._spinner.stop()
            self._draw_state(p, w, int(h * 0.36),
                             "Couldn\u2019t check for updates", self._flow_error)

    def _draw_stage(self, p: QPainter, w: int, h: int, text: str):
        p.setFont(_flow_font("JetBrains Mono", 12, QFont.Weight.Medium, 2.6))
        p.setPen(QColor("#C9C0FF"))
        p.drawText(QRectF(0, int(h * 0.185), w, 20), Qt.AlignCenter, text)

    def _draw_state(self, p: QPainter, w: int, top: int, title: str,
                    sub: str):
        p.setFont(_flow_font("Space Grotesk", _HEAD_FONT, QFont.Weight.DemiBold))
        p.setPen(QColor("#F6F4FC"))
        p.drawText(QRectF(0, top, w, 34), Qt.AlignCenter, title)
        p.setFont(_flow_font("Inter", 13, QFont.Weight.Normal))
        p.setPen(QColor("#928AAD"))
        p.drawText(QRectF((w - _SUB_WIDTH) / 2.0, top + 44, _SUB_WIDTH, 64),
                   Qt.TextWordWrap | Qt.AlignHCenter, sub)

    def _draw_available(self, p: QPainter, w: int, h: int):
        cur = "v" + (self._flow_cur or "")
        new = "v" + (self._flow_new or "")
        fs = _flow_font("Space Grotesk", 30, QFont.Weight.Bold)
        p.setFont(fs)
        fm = p.fontMetrics()
        wcur, wnew = fm.horizontalAdvance(cur), fm.horizontalAdvance(new)
        arrow_w = 44
        total = wcur + arrow_w + wnew
        x = (w - total) / 2.0
        cy = int(h * 0.30)
        p.setPen(QColor("#928AAD"))
        p.drawText(QRectF(x, cy, wcur, 38), Qt.AlignCenter, cur)
        p.setFont(_flow_font("Inter", 22, QFont.Weight.Medium))
        p.setPen(QColor("#514A70"))
        p.drawText(QRectF(x + wcur, cy, arrow_w, 38), Qt.AlignCenter, "\u2192")
        p.setFont(fs)
        p.setPen(QColor("#C9C0FF"))
        p.drawText(QRectF(x + wcur + arrow_w, cy, wnew, 38),
                   Qt.AlignCenter, new)
        lab = _flow_font("Inter", 10, QFont.Weight.Normal, 0.6)
        p.setFont(lab)
        p.setPen(QColor("#514A70"))
        ly = cy + 44
        p.drawText(QRectF(x, ly, wcur, 16), Qt.AlignCenter, "INSTALLED")
        p.drawText(QRectF(x + wcur + arrow_w, ly, wnew, 16),
                   Qt.AlignCenter, "NEW")

        cw = 340
        clx = (w - cw) / 2.0
        cy2 = ly + 46
        p.setFont(_flow_font("JetBrains Mono", 10, QFont.Weight.Medium, 1.1))
        p.setPen(QColor("#514A70"))
        p.drawText(QRectF(clx, cy2, cw, 16),
                   Qt.AlignVCenter | Qt.AlignLeft, "WHAT\u2019S NEW")
        if self._flow_items:
            iy = cy2 + 30
            note_font = _flow_font("Inter", 12.5, QFont.Weight.Normal)
            p.setFont(note_font)
            nfm = p.fontMetrics()
            dash = "\u2014"
            dw = nfm.horizontalAdvance(dash)
            lx = clx + dw + 9
            lw = cw - dw - 9
            yy = iy
            drawn = 0
            for item in self._flow_items[:3]:
                first = True
                for ln in self._wrap_text(nfm, item, lw):
                    if drawn >= 7 or yy + 16 > int(h * 0.66):
                        break
                    p.setFont(note_font)
                    if first:
                        p.setPen(QColor("#C9C0FF"))
                        p.drawText(QRectF(clx, yy, dw, 16),
                                   Qt.AlignVCenter | Qt.AlignLeft, dash)
                    p.setPen(QColor("#928AAD"))
                    p.drawText(QRectF(lx, yy, lw, 16),
                               Qt.AlignVCenter | Qt.AlignLeft, ln)
                    first = False
                    yy += 18
                    drawn += 1

    def _draw_downloading(self, p: QPainter, w: int, h: int):
        frac = _clamp01(self._download_frac)
        label = f"{int(round(frac * 100))}%"
        size = int(round(max(90, min(190, w * 0.13))))
        f = _flow_font("Space Grotesk", size, QFont.Weight.Bold,
                       -0.02 * size)
        p.setFont(f)
        fm = p.fontMetrics()
        max_w = fm.horizontalAdvance("100%")
        cx = w / 2.0
        tw = fm.horizontalAdvance(label)
        rect = QRectF(cx - max_w / 2.0, h * 0.36 - fm.height() * 0.5,
                      max_w, fm.height() * 1.1)
        text_rect = QRectF(cx - tw / 2.0, rect.top(), tw, rect.height())
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
        p.setFont(f)
        tpen = QPen()
        tpen.setBrush(QBrush(g2))
        p.setPen(tpen)
        p.drawText(text_rect, Qt.AlignCenter, label)

        bw = min(560.0, w * 0.56)
        bx = (w - bw) / 2.0
        by = rect.bottom() + 40
        track = QRectF(bx, by, bw, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 15))
        p.drawRoundedRect(track, 3, 3)
        fill = bw * frac
        if fill > 1:
            bg = QLinearGradient(track.topLeft(), track.topRight())
            bg.setColorAt(0.0, QColor("#8B6BFF"))
            bg.setColorAt(1.0, QColor("#4BE8D8"))
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(bx, by, fill, 6), 3, 3)
        p.setFont(_flow_font("JetBrains Mono", 11, QFont.Weight.Medium, 0.5))
        p.setPen(QColor("#514A70"))
        p.drawText(QRectF(bx, by + 16, bw, 18),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   "Downloading the new build\u2026")
        p.drawText(QRectF(bx, by + 16, bw, 18),
                   Qt.AlignVCenter | Qt.AlignRight, self._dl_speed)

    def _draw_ready(self, p: QPainter, w: int, h: int):
        cx, cy = w // 2, int(h * 0.36)
        glow = QRadialGradient(QPointF(cx, cy), 60)
        glow.setColorAt(0.0, QColor(61, 220, 151, 54))
        glow.setColorAt(1.0, QColor(61, 220, 151, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), 58, 58)
        p.setPen(QPen(QColor(61, 220, 151, 102), 1))
        p.setBrush(QColor(61, 220, 151, 26))
        p.drawEllipse(QPointF(cx, cy), 32, 32)
        cpen = QPen(QColor("#3DDC97"), 3)
        cpen.setCapStyle(Qt.RoundCap)
        cpen.setJoinStyle(Qt.RoundJoin)
        p.setPen(cpen)
        p.drawPolyline([QPointF(cx - 9, cy + 1), QPointF(cx - 3, cy + 7),
                        QPointF(cx + 10, cy - 6)])
        self._draw_state(
            p, w, cy + 62,
            "Update installed",
            f"Maximum Tweaks v{self._flow_new} is ready. Restart to finish.")

    def _draw_bottombar(self, p: QPainter, w: int, h: int, pct: float):
        top = h - 66
        p.setPen(QPen(QColor(255, 255, 255, 15), 1))
        p.drawLine(QPointF(40, top), QPointF(w - 40, top))
        fv = QFont("JetBrains Mono", 10)
        fv.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
        p.setFont(fv)
        p.setPen(QColor("#514A70"))
        v_old = self._flow_cur
        v_new = self._flow_new
        if self._update_state in ("available", "downloading", "installing",
                                  "ready"):
            foot = f"MAXIMUM ENGINE \u00b7 v{v_old} \u2192 v{v_new}"
        else:
            foot = "MAXIMUM ENGINE \u00b7 v" + APP_VERSION
        p.drawText(QRectF(40, top + 10, 480, 20),
                   Qt.AlignVCenter | Qt.AlignLeft, foot)
        if self._update_state in ("checking", "available", "downloading",
                                  "installing", "ready", "error"):
            return
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
