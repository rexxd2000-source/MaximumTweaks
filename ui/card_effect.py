"""Premium 3D card-hover tilt + cursor-following light.

``CardHoverTilt`` is a reusable QGraphicsEffect that you attach to any card
widget via ``widget.setGraphicsEffect(CardHoverTilt(widget))``. It gives every
card the same subtle, premium "the card leans toward the cursor" interaction:

  * The card tilts a few degrees toward the cursor, in real time, with
    perspective foreshortening (corners genuinely recede — not a flat skew).
  * A soft radial highlight follows the cursor so the closest edge reads as
    slightly more illuminated.
  * All motion is frame-rate-independent exponential easing — smooth, never
    jittery — and the card eases back to flat when the cursor leaves.
  * The widget's geometry, layout and children are never touched, so buttons,
    toggles, text and animations keep working exactly as before.

Performance: only the hovered card animates (one QTimer per card, started on
enter and stopped once settled); the source pixmap is cached by Qt, so each
frame is a cheap transformed blit.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QPainter,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import QGraphicsEffect


class CardHoverTilt(QGraphicsEffect):
    """Attach to a card widget for a tilt-toward-cursor hover effect.

    All tuning constants are class attributes so cards can be fine-tuned
    individually without subclasses (e.g. ``effect.MAX_DEG = 5``).
    """

    # Maximum tilt in degrees (±). Big enough to read clearly on screen;
    # 6° was imperceptible (corners moved ~3px on a 280px card).
    MAX_DEG = 12.0
    # Camera distance in px from the card plane. Smaller = stronger
    # perspective. 600 over a ~260px card reads as a clear lean.
    PERSPECTIVE = 600.0
    # Easing rate (1/seconds): higher = snappier, lower = floatier.
    EASE = 22.0
    # When the cursor leaves, rotation is "settled" below this many degrees.
    SETTLE_EPS = 0.04
    # Smoothed cursor delta below which we consider the card flat.
    POS_EPS = 0.004
    # Extra padding (beyond the computed worst-case corner shift) around the
    # source in the effect's backing store, so the projected corners never
    # clip at maximum tilt.
    MARGIN = 8
    # Base alpha of the cursor-following light (0 disables the light).
    HIGHLIGHT_ALPHA = 24
    # QSS ``opacity`` (0..1) to apply for these `state` property values while
    # under a graphics effect (QSS opacity is ignored for effect-rendered
    # widgets, so the effect re-applies the intended dimming itself).
    STATE_OPACITY = {"incompatible": 0.78, "detecting": 0.62}

    def __init__(self, widget, parent=None):
        super().__init__(parent)
        self._w = widget
        # Smoothed normalized cursor position, -1..1 (0 = idle/flat).
        self._nx = 0.0
        self._ny = 0.0
        # Values of the last frame that was actually painted (see _tick).
        self._painted_nx = 0.0
        self._painted_ny = 0.0
        # Target values the easing converges toward.
        self._tgt_nx = 0.0
        self._tgt_ny = 0.0
        self._active = False
        self._last_t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        # Hover events reach a widget even while the cursor is over a child
        # (labels, toggle, chips cover most of a card), which plain Enter/Leave
        # do not. Without this the tilt would rarely start in the real app.
        widget.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        widget.installEventFilter(self)

    # ------------------------------------------------------------------
    # Qt widget-event plumbing (enter/leave/hover/hide)
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self._w:
            etype = event.type()
            if etype == QEvent.Type.HoverEnter:
                self._active = True
                self._start()
            elif etype == QEvent.Type.HoverMove:
                p = event.position()
                w = self._w
                self._tgt_nx = max(-1.0, min(1.0,
                    (p.x() / max(1, w.width())) * 2.0 - 1.0))
                self._tgt_ny = max(-1.0, min(1.0,
                    (p.y() / max(1, w.height())) * 2.0 - 1.0))
                self._active = True
                self._start()
            elif etype in (QEvent.Type.HoverLeave, QEvent.Type.Leave):
                # Cursor may still be over a child widget (the toggle, icon…),
                # so don't stop — the tick re-checks the true cursor position.
                self._active = False
                self._tgt_nx = 0.0
                self._tgt_ny = 0.0
                self._start()
            elif etype == QEvent.Type.Enter:
                self._active = True
                self._start()
            elif etype == QEvent.Type.Hide:
                self._reset()
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Easing loop
    # ------------------------------------------------------------------

    def _start(self):
        if not self._timer.isActive():
            self._last_t = 0.0
            self._timer.start()

    def _reset(self):
        self._active = False
        self._nx = self._ny = 0.0
        self._painted_nx = self._painted_ny = 0.0
        self._tgt_nx = self._tgt_ny = 0.0
        self._timer.stop()
        self._w.update()

    def _tick(self):
        w = self._w
        try:
            if not w.isVisible():
                self._reset()
                return
            local = w.mapFromGlobal(QCursor.pos())
            inside = w.rect().contains(local)
        except RuntimeError:  # widget deleted while the timer was running
            self._reset()
            return

        if inside:
            self._active = True
            self._tgt_nx = max(-1.0, min(1.0,
                (local.x() / max(1, w.width())) * 2.0 - 1.0))
            self._tgt_ny = max(-1.0, min(1.0,
                (local.y() / max(1, w.height())) * 2.0 - 1.0))
        else:
            self._active = False
            self._tgt_nx = 0.0
            self._tgt_ny = 0.0

        now = time.monotonic()
        dt = now - self._last_t
        self._last_t = now
        if dt > 0.05:  # window was unfocused/hidden; avoid a snap
            dt = 0.05
        k = 1.0 - math.exp(-dt * self.EASE) if dt > 0 else 1.0
        self._nx += (self._tgt_nx - self._nx) * k
        self._ny += (self._tgt_ny - self._ny) * k

        # Repaint only when the tilt actually moved since the last painted
        # frame. A parked cursor leaves the card visually identical, so the
        # 60 fps re-render of the whole card becomes a no-op (that re-render
        # through the effect was what made the grid feel laggy under the
        # cursor). The timer itself keeps polling QCursor.pos() so the tilt
        # still follows a cursor that moves over child widgets without events.
        if (abs(self._nx - self._painted_nx) > self.POS_EPS
                or abs(self._ny - self._painted_ny) > self.POS_EPS):
            self._painted_nx = self._nx
            self._painted_ny = self._ny
            w.update()

        if (not self._active
                and abs(self._nx) < self.POS_EPS
                and abs(self._ny) < self.POS_EPS):
            self._nx = self._ny = 0.0
            self._timer.stop()

    # ------------------------------------------------------------------
    # QGraphicsEffect rendering
    # ------------------------------------------------------------------

    def boundingRectFor(self, sourceRect):
        m = self._tilt_margin()
        return sourceRect.adjusted(-m, -m, m, m)

    def _tilt_margin(self) -> int:
        """Padding needed so no projected corner leaves the backing store at
        maximum tilt. Grows with the card size (a wide card recedes further at
        the far corner), so a fixed margin would clip on wide cards."""
        try:
            w = max(1, self._w.width())
            h = max(1, self._w.height())
        except RuntimeError:  # widget already deleted during teardown
            return 16 + self.MARGIN
        cx, cy = w / 2.0, h / 2.0
        t = math.radians(self.MAX_DEG)
        s, c = math.sin(t), math.cos(t)
        d = self.PERSPECTIVE
        worst = 0.0
        for rx_s in (1.0, -1.0):
            for ry_s in (1.0, -1.0):
                m13 = -ry_s * s / d
                m23 = rx_s * s / d
                for x in (0.0, float(w)):
                    for y in (0.0, float(h)):
                        X, Y = x - cx, y - cy
                        wq = 1.0 + m13 * X + m23 * Y
                        if wq <= 0:
                            continue
                        px = X * c / wq
                        py = Y * c / wq
                        worst = max(worst, abs(px - X), abs(py - Y))
        return int(math.ceil(worst)) + self.MARGIN

    def draw(self, painter):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        try:
            w = self._w
            width = max(1, w.width())
            height = max(1, w.height())
        except RuntimeError:  # widget already deleted during teardown
            painter.restore()
            return

        # The backing store is larger than the card (card + tilt margin), and
        # QGraphicsEffect does not always wipe it between frames; clear the
        # whole store so a previous frame's tilted corners never ghost behind
        # the current frame as a "bigger card".
        m = self._tilt_margin()
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(QRectF(-m, -m, width + 2.0 * m, height + 2.0 * m),
                         QColor(0, 0, 0, 0))
        painter.restore()

        # QSS opacity is dropped for effect-rendered widgets; re-apply the
        # intended dimming so `incompatible`/`detecting` cards keep their look.
        state = str(w.property("state") or "")
        opacity = self.STATE_OPACITY.get(state)
        if opacity is not None:
            painter.setOpacity(opacity)

        # Rotation about the card center. ny>0 (cursor near the bottom) tips
        # the bottom edge toward the viewer; nx>0 (cursor right) tips the
        # right edge toward the viewer. The painter origin in effect.draw()
        # is the source's own top-left corner, so no margin offset is needed.
        rx = -self._ny * math.radians(self.MAX_DEG)
        ry = self._nx * math.radians(self.MAX_DEG)

        # drawSource() renders the widget itself (no sourcePixmap() re-capture
        # churn). It must be the LAST thing drawn on this painter state: some
        # Qt builds leave the painter broken after drawSource(), so the cursor
        # light is painted on a separate, restored state.
        painter.save()
        painter.translate(width / 2.0, height / 2.0)
        painter.setTransform(self._tilt_transform(rx, ry), True)
        painter.translate(-width / 2.0, -height / 2.0)
        self.drawSource(painter)
        painter.restore()

        self._paint_light(painter, width, height, QPoint(0, 0))

        painter.restore()

    def _tilt_transform(self, rx: float, ry: float) -> QTransform:
        """Projective rotation about the X and Y axes.

        A point (x, y, z=0) on the card is rotated about the card center, then
        projected from a camera at distance ``PERSPECTIVE`` on the z axis:

            z' = -x*sin(ry) + y*sin(rx)
            X' = d*x*cos(ry) / (d - z')
            Y' = d*y*cos(rx) / (d - z')

        Expressed as a QTransform's perspective (division by w) terms.
        """
        d = float(self.PERSPECTIVE)
        cxs, sxs = math.cos(rx), math.sin(rx)
        cys, sys = math.cos(ry), math.sin(ry)
        m = QTransform()
        m.setMatrix(
            cys, 0.0, -sys / d,
            0.0, cxs, sxs / d,
            0.0, 0.0, 1.0,
        )
        return m

    def _paint_light(self, painter, width: int, height: int, offset: QPoint = None):
        """Very subtle radial light centered under the cursor."""
        alpha = self.HIGHLIGHT_ALPHA
        if alpha <= 0:
            return
        ox = offset.x() if offset is not None else 0.0
        oy = offset.y() if offset is not None else 0.0
        cx = ox + (self._nx + 1.0) / 2.0 * width
        cy = oy + (self._ny + 1.0) / 2.0 * height
        radius = max(width, height) * 1.15
        grad = QRadialGradient(QPointF(cx, cy), radius)
        grad.setColorAt(0.0, QColor(255, 255, 255, alpha))
        grad.setColorAt(0.5, QColor(255, 255, 255, alpha // 2))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawRect(QRectF(ox, oy, width, height))
