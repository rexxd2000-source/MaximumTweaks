"""Deep-space ambient background shared across the whole UI.

Reuses the exact look of the AI Assistant page (AssistantComingSoon):
a dark base, drifting purple/magenta glow orbs, and a field of twinkling
stars. It sits behind the stacked pages so the ambient glow + starfield
show through the transparent page backgrounds.
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

# (relative x, relative y, radius-as-fraction-of-min-dim, rgb)
ORBS = [
    (0.22, 0.20, 0.30, (120, 76, 255)),   # violet
    (0.80, 0.30, 0.26, (201, 76, 255)),   # magenta
    (0.65, 0.80, 0.32, (84, 64, 255)),    # indigo
    (0.15, 0.75, 0.24, (255, 76, 205)),   # pink
]


class SpaceBackground(QWidget):
    """Slowly drifting glow orbs + twinkling stars over a deep-space base."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        rng = random.Random(7)
        self._stars = [
            (rng.uniform(0.02, 0.98), rng.uniform(0.02, 0.98),
             rng.uniform(0.8, 2.4), rng.uniform(0.0, 6.28))
            for _ in range(90)
        ]
        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._timer.isActive():
            self._clock.restart()
            self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def _tick(self):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if w < 2 or h < 2:
            p.end()
            return

        t = (self._clock.elapsed() / 2200.0) * math.tau
        p.fillRect(0, 0, w, h, QColor(11, 13, 18))

        # Drifting purple/magenta glow orbs.
        scale = min(w, h)
        for i, (ox, oy, rad_frac, rgb) in enumerate(ORBS):
            rad = scale * rad_frac
            gx = ox * w + math.sin(t * 0.5 + i * 1.7) * 14
            gy = oy * h + math.cos(t * 0.4 + i * 2.1) * 10
            grad = QRadialGradient(QPointF(gx, gy), rad)
            grad.setColorAt(0.0, QColor(*rgb, 42))
            grad.setColorAt(1.0, QColor(*rgb, 0))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(gx - rad, gy - rad, rad * 2, rad * 2))

        # Twinkling stars.
        for sx, sy, sr, ph in self._stars:
            a = int(18 + 42 * (0.5 + 0.5 * math.sin(t * 0.8 + ph)))
            p.setBrush(QBrush(QColor(210, 190, 255, a)))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(sx * w, sy * h), sr, sr)

        p.end()
