"""Cinematic boot splash for Rex Tweaks.

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
from PySide6.QtWidgets import QWidget

from config.app_config import APP_VERSION

ACCENT = QColor("#00F2FE")
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

# Rapid hardware/system detection toasts shown near the center of the stage.
# Each entry: (prefix, base text, kind). `kind` lets real detected values fill
# the label once the lightweight probe thread reports back.
TOAST_DEFS = [
    ("[+]", "Detecting GPU", "gpu"),
    ("[+]", "Detecting System Memory & CPU", "cpu"),
    ("[+]", "Verifying Discord Session", "discord"),
    ("[+]", "Loading Tweaks & System Hooks", "tweaks"),
]

_dur = 7000


def _ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def _ease_in_out(t: float) -> float:
    return t * t * (3 - 2 * t)


def _clamp01(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


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
            from engine import discord_auth
            prof = discord_auth.session()
            if prof:
                name = discord_auth.display_name(prof) or "Verified"
                values["discord"] = f"OK \u00b7 {name}" if prof.get("verified") \
                    else f"OK \u00b7 {name}"
            else:
                values["discord"] = "None"
        except Exception:  # noqa: BLE001
            values["discord"] = "..."
        values["tweaks"] = ""
        self.result.emit(values)


class CinematicSplash(QWidget):
    """Frameless boot screen. Emits build_now ~80% in, finished at 100%."""

    build_now = Signal()
    finished = Signal()

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

    # ---------------- lifecycle ----------------

    def start(self, duration_ms: int | None = None):
        if duration_ms is not None:
            self._dur_ms = int(duration_ms)
        self._done_emitted = False
        self._build_emitted = False
        self._started = True
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
        if t >= self._dur_ms and not self._done_emitted:
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

        self._draw_stage(p, w, h, t)
        self._draw_aurora(p, w, h, t)
        self._draw_scanline(p, w, h, t)
        self._draw_corners(p, w, h, t)
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
        line.setColorAt(0.0, QColor(0, 242, 254, 0))
        line.setColorAt(0.5, QColor(0, 242, 254, 14))
        line.setColorAt(1.0, QColor(0, 242, 254, 0))
        p.setBrush(line)
        p.setPen(Qt.NoPen)
        p.drawRect(0, sy - 26, w, 52)

    def _draw_corners(self, p: QPainter, w: int, h: int, t: float):
        a = _clamp01((t - 250) / 900.0)
        if a <= 0:
            return
        inset = 26
        length = 30
        pen = QPen(QColor(0, 242, 254, int(70 * a)), 1)
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
        halo.setColorAt(0.0, QColor(0, 242, 254, int(46 * a)))
        halo.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(cx, cy), 96, 96)

        # compact bolt tile that scales in (replaces the old self-drawing ring)
        scale = 0.72 + 0.28 * _ease_out_cubic(a)
        size = 52 * scale
        rect = QRectF(cx - size / 2, cy - size / 2, size, size)
        p.setBrush(QColor(9, 18, 26, int(232 * a)))
        p.setPen(QPen(QColor(0, 242, 254, int(150 * a)), 1))
        p.drawRoundedRect(rect, size * 0.26, size * 0.26)

        s = size * 0.34
        bolt = QColor(0, 242, 254, int(255 * a))
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
        w1 = m1.horizontalAdvance("REX")

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
        p.drawText(QRectF(x1, cy - 24, w1, 40), Qt.AlignCenter, "REX")

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
            grad.setColorAt(0.0, QColor(0, 242, 254, 0))
            grad.setColorAt(0.5, QColor(0, 242, 254, int(120 * hk)))
            grad.setColorAt(1.0, QColor(0, 242, 254, 0))
            p.setBrush(grad)
            p.setPen(Qt.NoPen)
            p.drawRect(x1 - half, cy + 34, half * 2, 1)

    def _draw_toasts(self, p: QPainter, w: int, h: int, t: float):
        """Rapid sequential hardware/system toasts, near-center, fade out fast."""
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
            p.setPen(QPen(QColor(0, 242, 254, int(90 * a)), 1))
            p.setBrush(pop)
            p.drawRoundedRect(rect, 14, 14)

            glyph = QColor(0, 242, 254, int(255 * a))
            p.setPen(glyph)
            p.drawText(rect.adjusted(pad, 0, 0, 0),
                       Qt.AlignLeft | Qt.AlignVCenter, text)

    def _draw_progress(self, p: QPainter, w: int, h: int, t: float, pct: int):
        if t < 900:
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
        gr.setColorAt(0.0, QColor(0, 190, 235))
        gr.setColorAt(1.0, ACCENT)
        p.setBrush(gr)
        if fill_w > 2:
            p.drawRoundedRect(QRectF(x0, y, fill_w, 2), 1, 1)
            glow = QRadialGradient(x0 + fill_w, y + 1, 9)
            glow.setColorAt(0.0, QColor(0, 242, 254, 150))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(glow)
            p.drawEllipse(QPointF(x0 + fill_w, y + 1), 9, 9)

        # percent
        f = QFont(self.font())
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor(0, 242, 254, 200))
        p.drawText(QRectF(cx + bar_w / 2 + 14, y - 10, 42, 20),
                   Qt.AlignLeft | Qt.AlignVCenter, f"{pct}%")

        # cycling status line above the bar — stretched to fill the full boot
        hold = (self._dur_ms - 1450) / len(STATUS_SEQ)
        idx = int((t - 1450) / hold)
        idx = max(0, min(len(STATUS_SEQ) - 1, idx))
        shown = STATUS_SEQ[idx]
        cy = y - 26
        fa = QFont(self.font())
        fa.setPixelSize(11)
        fa.setBold(True)
        fa.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(fa)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(shown)
        stage = ((t - 1450) / hold) % 1.0
        fad = 0.35 + 0.65 * _clamp01(stage)
        if idx == len(STATUS_SEQ) - 1:
            col = QColor(0, 242, 254)
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
                   f"REX ENGINE \u00b7 v{APP_VERSION}")
        p.drawText(QRectF(w - 340, h - 36, 300, 16),
                   Qt.AlignRight | Qt.AlignVCenter, "SECURE BOOT \u00b7 LOW LATENCY")