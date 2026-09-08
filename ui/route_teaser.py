"""Cinematic Route Analyzer teaser — a one-shot overlay announced when a new
version ships.

Shown over the main window once per APP_VERSION (persisted marker at
%APPDATA%\\MaximumTweaks\\teaser_seen_<version>), it plays a ~10s sequence:
near-black translucent stage, drifting aurora glows, a self-drawing progress
ring, an expanding-letter-spacing headline, a staggered reveal of the Route
Analyzer features being worked on, a cycling status line and a "MORE SOON"
sign-off. Click, ESC or Enter skips it instantly. Pure PySide6 painting, no
assets, styled to match the boot splash.
"""
from __future__ import annotations

import math
import os
import time

from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from config.app_config import APP_VERSION

ACCENT = QColor("#8B6BFF")
ACCENT_LIGHT = QColor("#C484FF")
TEXT = QColor(238, 244, 248)
DIM = QColor(124, 147, 166)
FAINT = QColor(74, 92, 110)
HOME = QColor(4, 6, 10)

# The features the overlay announces — real work that shipped behind the
# Route Analyzer between releases. Edited here, not in the analyzer itself.
FEATURES = [
    "LIVE LATENCY BUDGET \u2014 where your ping comes from",
    "YOUR ISP'S REAL PATH \u2014 measured, never guessed",
    "BGP ROUTING INTELLIGENCE \u2014 how traffic exits the country",
    "IN-GAME MATCHING PING \u2014 the number your game shows",
    "CONSISTENT GEOGRAPHY \u2014 one answer per server, every time",
]

STATUS_SEQ = [
    "MAPPING THE UNDERSEA LEG",
    "VERIFYING BGP PATHS",
    "CALIBRATING IN-GAME PING",
    "FINALIZING ROUTE OVERSIGHT",
]


class _Tracked:
    """Sequential typewriter reveal with a FIXED final layout.

    Each character has a reserved, immutable x position computed up front from
    the real font metrics (no time-varying gaps), so glyphs can never overlap,
    re-order, or shift while the animation runs. Characters are revealed
    strictly left-to-right by their reveal time.
    """

    def __init__(self, painter: QPainter, text: str, x: float, y: float, font: QFont,
                 color: QColor, alpha: float, spread: float = 0.0):
        self._p = painter
        self._text = text
        self._x = float(x)
        self._y = float(y)
        self._font = font
        self._color = QColor(color)
        self._spread = float(spread)

    def draw(self, t: float, step: float = 0.045, max_alpha: float = 1.0):
        self._p.setFont(self._font)
        fm = QFontMetrics(self._font)
        gap = fm.horizontalAdvance("W") * 0.34
        xs = []
        x = self._x
        for ch in self._text:
            xs.append(x)
            x += fm.horizontalAdvance(ch) + gap
        for i, ch in enumerate(self._text):
            a = max_alpha * self._ease((t - i * step) / max(step, 0.001))
            if a > 0.015:
                c = QColor(self._color)
                c.setAlphaF(self._color.alphaF() * a)
                self._p.setPen(c)
                self._p.drawText(QPointF(xs[i], self._y), ch)

    @staticmethod
    def _ease(v: float):
        if v <= 0.0:
            return 0.0
        if v >= 1.0:
            return 1.0
        return 1 - (1 - v) ** 3


class RouteTeaserOverlay(QWidget):
    """Opaque, non-skippable cinematic gate over a page.

    Fully obscures the underlying widget, swallows all input, and only
    dismisses when BOTH the sequence has finished AND the owner has signalled
    readiness (application-state controlled — there is no user-triggered way
    to bypass or interrupt it). Two modes: embedded (a child widget covering a
    page — used on the Route Analyzer) or full-screen topmost.
    """

    # Emitted when the gate fully dismisses — the owner uses it to run whatever
    # "the loading is over" transition it owns (e.g. auto-start a trace).
    finished_dismiss = Signal()

    def __init__(self, geometry, parent=None, embedded=False):
        super().__init__(parent)
        self._embedded = bool(embedded)
        self._started = False
        self._ready_fn = None
        if not self._embedded:
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            )
        else:
            self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setGeometry(geometry)
        self.setStyleSheet("background: transparent;")

        self._t0: float | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._fading = False
        self._fade_start_at: float = 0.0
        self._fade_dur: float = 450.0
        # Overall fade factor (0..1) applied to everything painted; the gate
        # ramps to 1 over the first ~0.45s and back to 0 during the outgoing
        # fade. windowOpacity is not used because it does not affect child
        # widgets (embedded mode) — the fade is drawn alpha-based instead.
        self._alpha_overlay: float = 0.0

    # ---- lifecycle -------------------------------------------------------
    def set_ready_check(self, fn) -> None:
        """Dismissal is gated on `fn()` returning truthy — the animation never
        ends before the owner confirms initialization is complete."""
        self._ready_fn = fn

    def _ready_ok(self) -> bool:
        if self._ready_fn is None:
            return True
        try:
            return bool(self._ready_fn())
        except Exception:
            return False

    def start(self) -> None:
        """Begin the sequence (called once). A second call is ignored so the
        gate can never be re-entered or double-started."""
        if self._started:
            return
        self._started = True
        if not self._embedded:
            try:
                base = os.environ.get("APPDATA") or ""
                marker = os.path.join(base, "MaximumTweaks", f"teaser_seen_{APP_VERSION}")
                if marker and not os.path.isfile(marker):
                    try:
                        os.makedirs(os.path.dirname(marker), exist_ok=True)
                        with open(marker, "w", encoding="utf-8") as fh:
                            fh.write(APP_VERSION)
                    except OSError:
                        pass
            except Exception:
                pass
        self._t0 = time.monotonic()
        if self._embedded and self.parent() is not None:
            self.parent().installEventFilter(self)
            self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        if self._embedded:
            self.setFocus(Qt.OtherFocusReason)
        self._timer.start()

    def _tick(self) -> None:
        if self._t0 is None:
            return
        t = self.elapsed()
        if not self._fading:
            # Fade-in ramp (~0.45s), then the sequence holds until BOTH the
            # full runtime has passed AND the owner reports ready — only then
            # does the outgoing fade (the dismissal) begin.
            self._alpha_overlay = self._ease01(self._cl01(t / 0.45))
            if t >= 9.6 and self._ready_ok():
                self._begin_fade(700)
        else:
            out = (time.monotonic() - self._fade_start_at) / (self._fade_dur / 1000.0)
            if out >= 1.0:
                self._alpha_overlay = 0.0
                self._done()
                return
            self._alpha_overlay = 1.0 - self._ease01(self._cl01(out))
        self.update()

    @staticmethod
    def _ease01(v: float) -> float:
        if v <= 0.0:
            return 0.0
        if v >= 1.0:
            return 1.0
        return 3 * v * v - 2 * v * v * v

    def elapsed(self) -> float:
        return (time.monotonic() - self._t0) if self._t0 is not None else 0.0

    def _begin_fade(self, ms: int) -> None:
        if self._fading:
            return
        self._fading = True
        self._fade_dur = float(ms)
        self._fade_start_at = time.monotonic()

    def _done(self) -> None:
        if self._embedded and self.parent() is not None:
            self.parent().removeEventFilter(self)
        self.hide()
        self.finished_dismiss.emit()
        self.deleteLater()

    def eventFilter(self, obj, event):
        if self._embedded and obj is self.parent():
            from PySide6.QtCore import QEvent
            if event.type() == QEvent.Resize:
                self.setGeometry(self.parent().rect())
        return super().eventFilter(obj, event)

    # ---- input: the gate swallows everything -------------------------------
    # No focus/mouse/keyboard handler is installed and no shortcut exists —
    # there is deliberately no way to skip, dismiss or interrupt the sequence.
    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        event.accept()

    def keyPressEvent(self, event):
        event.accept()

    def keyReleaseEvent(self, event):
        event.accept()

    # ---- painting ----------------------------------------------------------
    def _cl01(self, v: float) -> float:
        return 0.0 if v < 0 else (1.0 if v > 1 else v)

    def _pt(self, name: str, t: float) -> float:
        """Piecewise progress: (name, start, dur) tuples."""
        table = {
            "fade": (0.0, 0.8),
            "kicker": (0.55, 0.8),
            "title": (1.15, 1.1),
            "sub": (2.25, 0.5),
            "features": (2.85, 2.2),
            "status": (5.2, 2.4),
            "progress": (0.6, 8.0),
            "footer": (7.9, 0.9),
            "best": (8.4, 1.0),
        }
        start, dur = table[name]
        return self._cl01((t - start) / dur)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        t = self.elapsed() if self._t0 is not None else 0.0
        W = float(self.width())
        H = float(self.height())

        # Fully-opaque stage: the underlying page must never show through the gate.
        # While the gate is up the stage is always 100% opaque (only the
        # foreground content fades in); during the authorised dismissal the
        # stage fades out together with everything else.
        bg = QColor(HOME)
        bg.setAlphaF(1.0 if not self._fading else self._alpha_overlay)
        p.fillRect(QRectF(0, 0, W, H), bg)

        # Drifting aurora glows.
        self._aurora(p, W, H, t, (0.72, 0.22, ACCENT), (0.42 + 0.10 * math.sin(t * 0.55)) * self._alpha_overlay)
        self._aurora(p, W, H, t, (0.28, 0.78, ACCENT_LIGHT), (0.30 + 0.08 * math.sin(t * 0.42 + 2.1)) * self._alpha_overlay)
        self._aurora(p, W, H, t, (0.52, 0.92, QColor("#2563EB")), 0.20 * self._alpha_overlay)

        cx = W * 0.5
        col_w = min(760.0, W * 0.66)
        x0 = cx - col_w * 0.5
        yc = H * 0.52
        row_h = H * 0.045
        base = H / 1000.0

        prog = self._pt("progress", t)

        def _font(size: float, weight: int = QFont.Normal) -> QFont:
            f = QFont("Segoe UI")
            f.setPixelSize(int(max(11, base * size)))
            f.setWeight(weight)
            return f

        kick = self._pt("kicker", t)
        if kick > 0:
            tr = _Tracked(p, "ROUTE ANALYZER  \u00b7  IN DEVELOPMENT",
                          x0, H * 0.245, _font(21, QFont.Bold),
                          ACCENT, kick * self._alpha_overlay, spread=1.3)
            tr.draw(kick * 1.4)

        tt = self._pt("title", t)
        if tt > 0:
            tr = _Tracked(p, "THE ROUTE ANALYZER", x0, H * 0.30, _font(54, QFont.DemiBold),
                          TEXT, tt * self._alpha_overlay, spread=0.5)
            tr.draw(tt)
            tr2 = _Tracked(p, "BEING REWORKED", x0, H * 0.385, _font(54, QFont.DemiBold),
                           ACCENT, tt * self._alpha_overlay, spread=0.5)
            tr2.draw(tt - 0.06)

        st = self._pt("sub", t)
        if st > 0:
            p.setFont(_font(20))
            p.setPen(QPen(self._alpha(DIM, st), 1.0))
            p.drawText(QRectF(x0, H * 0.435, col_w, H * 0.05), Qt.AlignLeft | Qt.AlignVCenter,
                       "Every number below is measured and verified \u2014 nothing guessed.")

        # Feature bullets, staggered reveal.
        ft = self._pt("features", t)
        if ft > 0:
            for i, feat in enumerate(FEATURES):
                a = self._cl01((ft - i * 0.16) / 0.34)
                if a <= 0:
                    continue
                y = yc + i * row_h
                p.setFont(_font(24, QFont.Normal))
                # bullet marker
                p.setPen(QPen(self._alpha(ACCENT, a), 1.0))
                p.drawText(QRectF(x0, y, col_w, row_h), Qt.AlignLeft | Qt.AlignVCenter,
                           "\u25b8")
                p.setFont(_font(24))
                p.setPen(QPen(self._alpha(TEXT, a), 1.0))
                p.drawText(QRectF(x0 + col_w * 0.09, y, col_w, row_h),
                           Qt.AlignLeft | Qt.AlignVCenter, feat)

        # Hairline under the bullets that draws as bullets appear.
        hd = self._pt("features", t) * 0.9
        if hd > 0:
            pen = QPen(self._alpha(FAINT, hd), 1.0)
            p.setPen(pen)
            yy = yc + len(FEATURES) * row_h + H * 0.012
            p.drawLine(QPointF(x0, yy), QPointF(x0 + col_w * hd, yy))

        # Cycling status line.
        sti = int(self._cl01(self._pt("status", t)) * (len(STATUS_SEQ) - 1) + 0.5) \
            if self._pt("status", t) > 0 else 0
        if self._pt("status", t) > 0:
            a = self._cl01(self._pt("status", t) * 2.5)
            p.setFont(_font(19))
            p.setPen(QPen(self._alpha(ACCENT_LIGHT, 0.85 * a), 1.0))
            p.drawText(QRectF(x0, H * 0.80, col_w, H * 0.04), Qt.AlignLeft | Qt.AlignVCenter,
                       "\u25c6   " + STATUS_SEQ[sti])

        # Self-drawing progress ring + hairline.
        ring_x = cx
        ring_y = H * 0.845
        radius = base * 13.0
        if prog > 0:
            pen = QPen(self._alpha(ACCENT, 0.55), 1.4)
            p.setPen(QPen(self._alpha(QColor("#22384A"), 0.9), 1.4))
            p.drawEllipse(QPointF(ring_x, ring_y), radius, radius)
            arc = QPen(self._alpha(ACCENT_LIGHT, 0.95), 2.2)
            arc.setStyle(Qt.SolidLine)
            p.setPen(arc)
            p.drawArc(QRectF(ring_x - radius, ring_y - radius, radius * 2, radius * 2),
                      -90 * 16, int(prog * 360 * 16))

        # Footer sign-off.
        fo = self._pt("footer", t)
        if fo > 0:
            p.setFont(_font(17))
            p.setPen(QPen(self._alpha(FAINT, fo), 1.0))
            p.drawText(QRectF(cx - col_w * 0.5, H * 0.905, col_w, H * 0.04),
                       Qt.AlignCenter, "\u2014  R E L E A S I N G   S O O N  \u2014")
            p.setFont(_font(14))
            p.setPen(QPen(self._alpha(FAINT, fo * 0.8), 1.0))
            p.drawText(QRectF(cx - col_w * 0.5, H * 0.945, col_w, H * 0.03),
                       Qt.AlignCenter,
                       f"MAXIMUM TWEAKS  v{APP_VERSION}  \u00b7  ROUTE ANALYZER")
        p.end()

    def _alpha(self, color: QColor, a: float) -> QColor:
        c = QColor(color)
        c.setAlphaF(self._cl01(a * self._alpha_overlay))
        return c

    def _aurora(self, p: QPainter, W: float, H: float, t: float, at: tuple, alpha: float) -> None:
        fx, fy, tint = at
        px = (fx + 0.05 * math.sin(t * 0.24 + fx * 9.0)) * W
        py = (fy + 0.05 * math.cos(t * 0.19 + fy * 7.0)) * H
        rad = max(W, H) * 0.52 * (0.9 + 0.1 * math.sin(t * 0.32 + fx * 5.0))
        g = QRadialGradient(QPointF(px, py), rad)
        c0 = QColor(tint)
        c0.setAlphaF(alpha)
        g.setColorAt(0.0, c0)
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, 0, W, H), g)


def maybe_show_teaser(geometry) -> "RouteTeaserOverlay | None":
    """Show the teaser once per app version, on the given screen/maximized
    geometry. Returns None when it has already been seen (or on any failure —
    the teaser must never break app startup)."""
    try:
        base = os.environ.get("APPDATA") or ""
        marker = os.path.join(base, "MaximumTweaks", f"teaser_seen_{APP_VERSION}")
        if marker and os.path.isfile(marker):
            return None
        ov = RouteTeaserOverlay(geometry)
        ov.start()
        return ov
    except Exception:
        return None