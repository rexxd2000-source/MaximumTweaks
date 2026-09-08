"""Original custom-painted widgets for the Maximum Tweaks Engine Dashboard.

Every dashboard visual is painted directly with QPainter so the widgets stay
crisp at any DPI and keep the signature neon-cyan identity. Includes the
animated neon stat bars, the dual-axis thermal/clock stability chart, the
Rex logo mark, the pulsing live status badge, the segmented disk bar and the
Official Discord community card. QSS only supplies the card surface.
"""
from __future__ import annotations

from collections import deque
import math

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    Qt,
    QThread,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config.app_config import DISCORD_INVITE_URL, DIRS, THEME as T

from ui.widgets import qss_rgba

ACCENT = T["accent"]
DANGER = T["danger"]
WARNING = T["warning"]
TEXT = T["text"]
DIM = T["text_dim"]
FAINT = T["text_faint"]


def threshold_color(pct: float) -> str:
    """Red/Cyan/Amber accent for high-usage thresholds."""
    if pct >= 85:
        return DANGER
    if pct >= 60:
        return WARNING
    return ACCENT


class GlassCard(QFrame):
    """Translucent frosted panel used by every dashboard card."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GlassCard")


class LinkLabel(QLabel):
    """Text link (accent, hover-underline) that emits `clicked`."""

    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


# --------------------------------------------------------------------------
# Maximum logo mark — the official dashboard brand tile
# --------------------------------------------------------------------------

class RexLogo(QWidget):
    """Brand mark: the Maximum app artwork on a frosted cyan-edged tile.

    Renders the official ``assets/rex_logo.png`` artwork cover-fitted into the
    tile; falls back to the glowing 'R' monogram painter if that file is
    missing.
    """

    def __init__(self, size: int = 58, image_path=None, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._image_path = image_path or str(
            (DIRS["assets"] / "rex_logo.png").resolve())
        self._pixmap = QPixmap(self._image_path)
        if self._pixmap.isNull():
            self._pixmap = QPixmap()  # fall back to the painted 'R'

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(2, 2, self.width() - 4, self.height() - 4)
        radius = 15.0
        tile = QPainterPath()
        tile.addRoundedRect(r, radius, radius)

        if not self._pixmap.isNull():
            # cover-fit the artwork into the rounded tile
            p.save()
            p.setClipPath(tile)
            src = self._pixmap
            if src.width() != src.height():
                side = min(src.width(), src.height())
                src = src.copy(
                    (src.width() - side) // 2, (src.height() - side) // 2,
                    side, side)
            p.drawPixmap(r, src, QRectF(src.rect()))
            p.restore()
        else:
            fill = QLinearGradient(0, 0, self.width(), self.height())
            fill.setColorAt(0.0, QColor(20, 27, 38))
            fill.setColorAt(1.0, QColor(9, 12, 18))
            p.fillPath(tile, fill)

        # cyan frame with a soft outer glow
        for width, alpha in ((7, 22), (3, 90)):
            glow = QPen(QColor(139, 92, 246, alpha))
            glow.setWidthF(width)
            p.setPen(glow)
            p.drawRoundedRect(r, radius, radius)
        frame = QPen(QColor(139, 92, 246, 150), 1.4)
        p.setPen(frame)
        p.drawRoundedRect(r, radius, radius)

        if self._pixmap.isNull():
            # inner accent tick at the bottom-left corner
            accent = QPen(QColor(139, 92, 246, 210), 3)
            accent.setCapStyle(Qt.RoundCap)
            p.setPen(accent)
            p.drawLine(QPointF(r.left() + 11, r.bottom() - 9),
                       QPointF(r.left() + 11, r.bottom() - 3))
            p.drawLine(QPointF(r.left() + 11, r.bottom() - 9),
                       QPointF(r.left() + 17, r.bottom() - 9))

            # glowing 'R'
            font = QFont("Segoe UI Variable Display")
            font.setPixelSize(27)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(139, 92, 246, 70))
            p.drawText(QRectF(6, 6, self.width() - 12, self.height() - 8),
                       Qt.AlignCenter, "R")
            p.setPen(QColor(139, 92, 246))
            p.drawText(QRectF(5, 5, self.width() - 12, self.height() - 8),
                       Qt.AlignCenter, "R")


# --------------------------------------------------------------------------
# Pulsing live status badge (ADMIN MODE ACTIVE / SYS OPTIMIZED)
# --------------------------------------------------------------------------

class LiveBadge(QWidget):
    """Pill with an animated pulsing dot + status text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = "LIVE"
        self._color = QColor(ACCENT)
        self._phase = 0.0
        self.setFixedHeight(30)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_status(self, text: str, color: str):
        self._text = text
        self._color = QColor(color)
        self.updateGeometry()
        self.update()

    def _tick(self):
        self._phase += 0.24
        self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self._text) + 54, 30)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        r = QRectF(0, 0, self.width() - 1, h - 1)
        radius = h / 2.0
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.fillPath(path, QColor(13, 17, 23))
        p.setPen(QPen(QColor(self._color.red(), self._color.green(),
                             self._color.blue(), 90), 1))
        p.drawRoundedRect(r, radius, radius)

        cx, cy = 24.0, h / 2.0
        pulse = (math.sin(self._phase) + 1.0) / 2.0  # 0..1
        halo = QColor(self._color)
        halo.setAlpha(int(14 + 120 * pulse))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(cx, cy), 8.5, 8.5)
        core = QColor(self._color)
        core.setAlpha(255)
        p.setBrush(core)
        p.drawEllipse(QPointF(cx, cy), 3.6, 3.6)

        font = QFont("Segoe UI Variable Display")
        font.setPixelSize(11)
        font.setBold(True)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        p.setFont(font)
        p.setPen(QColor(self._color))
        p.drawText(QRectF(40, 0, self.width() - 46, h),
                   Qt.AlignLeft | Qt.AlignVCenter, self._text)


# --------------------------------------------------------------------------
# Prominent backend-connection status block (header)
# --------------------------------------------------------------------------

class BackendStatusBlock(QWidget):
    """Prominent single-line backend-connection block (header)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main = "CONNECTED TO BACKEND"
        self._color = QColor(ACCENT)
        self._phase = 0.0
        self.setFixedHeight(50)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_status(self, text: str, color: str | None = None):
        self._main = text
        if color:
            self._color = QColor(color)
        self.updateGeometry()
        self.update()

    def _tick(self):
        self._phase += 0.24
        self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self._main) + 70, 50)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(0, 0, w - 1, h - 1)
        radius = 14.0
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.fillPath(path, QColor(12, 16, 22))
        p.setPen(QPen(QColor(self._color.red(), self._color.green(),
                             self._color.blue(), 110), 1))
        p.drawRoundedRect(r, radius, radius)

        cx, cy = 30.0, h / 2.0
        pulse = (math.sin(self._phase) + 1.0) / 2.0
        halo = QColor(self._color)
        halo.setAlpha(int(12 + 120 * pulse))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(cx, cy), 9.0, 9.0)
        core = QColor(self._color)
        core.setAlpha(255)
        p.setBrush(core)
        p.drawEllipse(QPointF(cx, cy), 3.8, 3.8)

        f = QFont("Segoe UI Variable Display")
        f.setPixelSize(12)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
        p.setFont(f)
        p.setPen(QColor(self._color))
        p.drawText(QRectF(52, 0, w - 60, h),
                   Qt.AlignLeft | Qt.AlignVCenter, self._main)


# --------------------------------------------------------------------------
# Neon stat bar (CPU / GPU / RAM utilization)
# --------------------------------------------------------------------------

class NeonBar(QWidget):
    """Animated horizontal bar with a neon fill and soft outer glow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._display = 0.0
        self._color = QColor(ACCENT)
        self._anim: QVariantAnimation | None = None
        self.setFixedHeight(14)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: float, color: str | None = None):
        if color:
            self._color = QColor(color)
        target = max(0.0, min(100.0, float(value)))
        if self._anim is not None:
            self._anim.stop()
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(550)
        self._anim.setStartValue(self._display)
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self._anim.start()

    def _on_anim(self, value):
        self._display = float(value)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        radius = h / 2.0

        track = QPainterPath()
        track.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        p.fillPath(track, QColor(19, 24, 32))

        frac = max(0.0, min(1.0, self._display / 100.0))
        fill_w = max(0.0, frac * w)

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        p.setClipPath(path)

        # outer glow pass behind the fill
        glow = QColor(self._color)
        glow.setAlpha(32)
        p.fillRect(QRectF(0, -2, fill_w, h + 4), glow)
        glow2 = QColor(self._color)
        glow2.setAlpha(60)
        p.fillRect(QRectF(0, -1, fill_w, h + 2), glow2)

        # core fill with a brighter top edge
        core = QColor(self._color)
        core.setAlpha(235)
        p.fillRect(QRectF(0, 0, fill_w, h), core)
        top = QColor(255, 255, 255, 90)
        p.fillRect(QRectF(0, 1, fill_w, 2), top)

        p.setClipping(False)

        outline = QPen(QColor(35, 42, 52), 1)
        p.setPen(outline)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), radius, radius)

        # end-cap dot at the fill head
        if frac > 0.04:
            head = QColor(255, 255, 255, 235)
            p.setPen(Qt.NoPen)
            p.setBrush(head)
            p.drawEllipse(QPointF(min(fill_w, w - radius), h / 2.0), 3.0, 3.0)


# --------------------------------------------------------------------------
# Dual-axis telemetry chart: thermals (°C) + CPU clock stability (MHz)
# --------------------------------------------------------------------------

class LatencyChart(QWidget):
    """Continuous 60-second strip of a thermal line and the CPU clock line.

    Left axis is temperature (°C), right axis is clock speed (MHz). Hovering
    shows a crosshair with the exact values of both series at that sample.
    """

    WINDOW = 60  # 1 sample / second == 60 seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thermal_cpu: deque = deque(maxlen=self.WINDOW)
        self._thermal_gpu: deque = deque(maxlen=self.WINDOW)
        self._clock: deque = deque(maxlen=self.WINDOW)
        self.mode = "cpu"
        self._hover: int | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(180)

    # ---- data ----

    def add(self, cpu_temp, gpu_temp, clock_mhz):
        self._thermal_cpu.append(cpu_temp)
        self._thermal_gpu.append(gpu_temp)
        self._clock.append(clock_mhz)
        self.update()

    def set_mode(self, mode: str):
        self.mode = mode
        self._hover = None
        self.update()

    def _thermal(self) -> deque:
        return self._thermal_cpu if self.mode == "cpu" else self._thermal_gpu

    def _thermal_color(self) -> QColor:
        s = self._thermal()
        hot = s and s[-1] is not None and s[-1] >= 80
        if hot:
            return QColor(DANGER)
        return QColor(ACCENT if self.mode == "cpu" else WARNING)

    # ---- hover ----

    def mouseMoveEvent(self, event):
        ml, mt, mr, mb = 40, 12, 52, 24
        w = self.width() - ml - mr
        n = len(self._thermal())
        offset = self.WINDOW - n
        self._hover = None
        if w > 0 and n:
            idx = int(round((event.position().x() - ml) / w
                            * (self.WINDOW - 1))) - offset
            if 0 <= idx < n:
                self._hover = idx
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover = None
        self.update()
        super().leaveEvent(event)

    # ---- painting ----

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        ml, mt, mr, mb = 40, 12, 52, 24
        plot = QRectF(ml, mt, w - ml - mr, h - mt - mb)
        if plot.width() <= 0 or plot.height() <= 0:
            return

        small = QFont("Segoe UI Variable Text")
        small.setPixelSize(9)
        p.setFont(small)

        # ---- thermal grid (left axis, 0..100 °C) ----
        for v in (0, 25, 50, 75, 100):
            y = plot.bottom() - (v / 100.0) * plot.height()
            line = QPen(QColor(255, 255, 255, 14))
            line.setWidthF(1)
            p.setPen(line)
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(0, y - 7, ml - 6, 14),
                       Qt.AlignRight | Qt.AlignVCenter, f"{v}\u00b0")

        # ---- clock axis range (right) ----
        clocks = [c for c in self._clock if c]
        if clocks:
            lo, hi = min(clocks), max(clocks)
            pad = max(200.0, (hi - lo) * 0.25)
            lo, hi = lo - pad, hi + pad
        else:
            lo, hi = 0.0, 1000.0
        span = max(1.0, hi - lo)

        def clock_y(mhz: float) -> float:
            return plot.bottom() - ((mhz - lo) / span) * plot.height()

        for i, frac in enumerate((0.0, 0.5, 1.0)):
            y = plot.bottom() - frac * plot.height()
            mhz = lo + frac * span
            tick = QPen(QColor(255, 255, 255, 40))
            p.setPen(tick)
            p.drawLine(QPointF(plot.right(), y), QPointF(plot.right() + 4, y))
            p.setPen(QColor(DIM))
            if mhz >= 1000:
                label = f"{mhz / 1000.0:.1f}G"
            else:
                label = f"{mhz:.0f}M"
            p.drawText(QRectF(plot.right() + 7, y - 7, mr - 10, 14),
                       Qt.AlignLeft | Qt.AlignVCenter, label)

        # ---- timeline (bottom) ----
        marks = [("now", 0), ("15", 15), ("30", 30), ("45", 45), ("60", 60)]
        for text, sec in marks:
            x = plot.right() - (sec / self.WINDOW) * plot.width()
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(x - 20, plot.bottom() + 4, 40, 14),
                       Qt.AlignHCenter | Qt.AlignTop, text)
            tick = QPen(QColor(255, 255, 255, 14))
            p.setPen(tick)
            p.drawLine(QPointF(x, plot.bottom()), QPointF(x, plot.bottom() + 3))

        # ---- legend chips ----
        mode_lbl = self.mode.upper()
        self._chip(p, 4, 2, f"\u25cf THERMAL ({mode_lbl})", self._thermal_color())
        self._chip(p, 4 + 126, 2, "\u25cf CLOCK", QColor(WARNING))

        thermal = self._thermal()
        n = len(thermal)
        if n == 0:
            p.setPen(QColor(DIM))
            p.drawText(plot, Qt.AlignCenter, "Waiting for live data\u2026")
            return

        offset = self.WINDOW - n
        t_pts: list = [None] * n
        for i, temp in enumerate(thermal):
            if temp is None:
                continue
            x = plot.left() + ((i + offset) / (self.WINDOW - 1)) * plot.width()
            y = plot.bottom() - max(0.0, min(100.0, float(temp))) / 100.0 * plot.height()
            t_pts[i] = (x, y)
        c_pts: list = [None] * n
        for i, mhz in enumerate(self._clock):
            if mhz is None:
                continue
            x = plot.left() + ((i + offset) / (self.WINDOW - 1)) * plot.width()
            c_pts[i] = (x, clock_y(float(mhz)))

        if not any(t_pts) and not any(c_pts):
            p.setPen(QColor(DIM))
            p.drawText(plot, Qt.AlignCenter, "No telemetry available")
            return

        # ---- thermal line + gradient fill ----
        thermal_color = self._thermal_color()
        t_run = [(i, t_pts[i]) for i in range(n) if t_pts[i]]
        if len(t_run) >= 2:
            path = QPainterPath()
            path.moveTo(*t_run[0][1])
            for _, pt in t_run[1:]:
                path.lineTo(*pt)
            for width, alpha in ((7, 14), (4, 40)):
                glow = QPen(thermal_color)
                glow.setWidthF(width)
                glow.setCapStyle(Qt.RoundCap)
                glow.setJoinStyle(Qt.RoundJoin)
                glow.setColor(QColor(thermal_color.red(), thermal_color.green(),
                                     thermal_color.blue(), alpha))
                p.setPen(glow)
                p.drawPath(path)
            line = QPen(thermal_color)
            line.setWidthF(2.0)
            line.setCapStyle(Qt.RoundCap)
            p.setPen(line)
            p.drawPath(path)

            poly = QPolygonF()
            poly.append(QPointF(t_run[0][1][0], plot.bottom()))
            for _, pt in t_run:
                poly.append(QPointF(*pt))
            poly.append(QPointF(t_run[-1][1][0], plot.bottom()))
            gradient = QLinearGradient(0, plot.top(), 0, plot.bottom())
            gradient.setColorAt(0.0, QColor(thermal_color.red(),
                                            thermal_color.green(),
                                            thermal_color.blue(), 60))
            gradient.setColorAt(1.0, QColor(thermal_color.red(),
                                            thermal_color.green(),
                                            thermal_color.blue(), 0))
            p.setPen(Qt.NoPen)
            p.setBrush(gradient)
            p.drawPolygon(poly)

        # ---- clock line ----
        clock_color = QColor(WARNING)
        c_run = [(i, c_pts[i]) for i in range(n) if c_pts[i]]
        if len(c_run) >= 2:
            path = QPainterPath()
            path.moveTo(*c_run[0][1])
            for _, pt in c_run[1:]:
                path.lineTo(*pt)
            for width, alpha in ((6, 12), (3, 36)):
                glow = QPen(clock_color)
                glow.setWidthF(width)
                glow.setCapStyle(Qt.RoundCap)
                glow.setColor(QColor(clock_color.red(), clock_color.green(),
                                     clock_color.blue(), alpha))
                p.setPen(glow)
                p.drawPath(path)
            line = QPen(clock_color)
            line.setWidthF(1.8)
            line.setCapStyle(Qt.RoundCap)
            p.setPen(line)
            p.drawPath(path)

        # ---- hover crosshair + tooltip ----
        if self._hover is not None and 0 <= self._hover < n:
            xi = self._hover
            guide = QPen(QColor(255, 255, 255, 60), 1, Qt.DashLine)
            p.setPen(guide)
            p.drawLine(QPointF(t_pts[xi][0] if t_pts[xi] else c_pts[xi][0],
                               plot.top()),
                       QPointF(t_pts[xi][0] if t_pts[xi] else c_pts[xi][0],
                               plot.bottom()))

            temp = thermal[xi]
            mhz = self._clock[xi]
            if temp is not None:
                x, y = t_pts[xi]
                p.setPen(Qt.NoPen)
                p.setBrush(thermal_color)
                p.drawEllipse(QPointF(x, y), 3.5, 3.5)
            if mhz is not None:
                x, y = c_pts[xi]
                p.setPen(Qt.NoPen)
                p.setBrush(clock_color)
                p.drawEllipse(QPointF(x, y), 3.0, 3.0)

            ago = (self.WINDOW - 1) - xi
            ago_txt = "now" if ago <= 0 else f"{ago}s ago"
            lines = [ago_txt]
            lines.append(f"{mode_lbl}  {temp:.0f}\u00b0C" if temp is not None
                         else f"{mode_lbl}  \u2014")
            lines.append(f"CLOCK  {mhz:.0f} MHz" if mhz else "CLOCK  \u2014")
            tw, th = 170, 50
            tx = x + 12 if t_pts[xi] else c_pts[xi][0] + 12
            ty = max(plot.top() + 2, y - th / 2 if t_pts[xi] else 0)
            if tx + tw > self.width() - 6:
                tx = x - tw - 12 if t_pts[xi] else c_pts[xi][0] - tw - 12
            tx = max(6, tx)
            ty = max(plot.top() - 2, min(ty, plot.bottom() - th))
            p.setPen(QPen(QColor(60, 66, 79), 1))
            p.setBrush(QColor(21, 27, 36))
            p.drawRoundedRect(QRectF(tx, ty, tw, th), 7, 7)
            tip = QFont("Segoe UI Variable Text")
            tip.setPixelSize(9.5)
            tip.setBold(True)
            p.setFont(tip)
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(tx + 10, ty + 5, tw - 16, 13),
                       Qt.AlignLeft | Qt.AlignVCenter, lines[0])
            p.setPen(QColor(thermal_color))
            p.drawText(QRectF(tx + 10, ty + 18, tw - 16, 13),
                       Qt.AlignLeft | Qt.AlignVCenter, lines[1])
            p.setPen(QColor(clock_color))
            p.drawText(QRectF(tx + 10, ty + 32, tw - 16, 13),
                       Qt.AlignLeft | Qt.AlignVCenter, lines[2])

    def _chip(self, p: QPainter, x: float, y: float, text: str,
              color: QColor):
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text)
        rect = QRectF(x, y, tw + 18, 16)
        p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 60), 1))
        p.setBrush(QColor(14, 18, 25))
        p.drawRoundedRect(rect, 8, 8)
        p.setFont(self.font())
        small = QFont("Segoe UI Variable Text")
        small.setPixelSize(8.5)
        small.setBold(True)
        p.setFont(small)
        p.setPen(QColor(color))
        p.drawText(rect, Qt.AlignCenter, text)


# --------------------------------------------------------------------------
# Official Discord community card artwork
# --------------------------------------------------------------------------

class _CommunityArt(QWidget):
    """Hub artwork: the server's Discord logo as a full-bleed banner."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(96)
        self._logo = QPixmap(str(DIRS["assets"] / "discord_logo.png"))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        r = QRectF(0, 0, w - 1, h - 1)
        radius = 13.0

        # rounded clip so the image respects the panel corners
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        p.setClipPath(clip)

        if not self._logo.isNull():
            # cover-fit: scale to fill width, crop top/bottom overflow so the
            # square logo stretches across the whole banner
            iw, ih = self._logo.width(), self._logo.height()
            scale = max(w / iw, h / ih)
            dw, dh = iw * scale, ih * scale
            p.drawPixmap(
                int((w - dw) / 2.0), int((h - dh) / 2.0),
                int(dw), int(dh), self._logo)
            # soft dark gradient at the edges so the banner melts into the card
            veil = QLinearGradient(0, 0, 0, h)
            veil.setColorAt(0.0, QColor(8, 12, 18, 60))
            veil.setColorAt(0.35, QColor(8, 12, 18, 0))
            veil.setColorAt(0.7, QColor(8, 12, 18, 0))
            veil.setColorAt(1.0, QColor(8, 12, 18, 175))
            p.setBrush(veil)
            p.setPen(Qt.NoPen)
            p.drawRect(QRectF(0, 0, w, h))
        else:
            # fallback: dark panel with a controller glyph
            fill = QLinearGradient(0, 0, w, h)
            fill.setColorAt(0.0, QColor(13, 21, 34))
            fill.setColorAt(1.0, QColor(8, 12, 18))
            p.setBrush(fill)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r, radius, radius)
            self._controller(p, w / 2.0, h / 2.0 + 1)

        p.setClipping(False)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(139, 92, 246, 55), 1))
        p.drawRoundedRect(r, radius, radius)

    def _controller(self, p: QPainter, cx: float, cy: float):
        color = QColor(139, 92, 246, 230)
        pen = QPen(color, 2.2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(QColor(139, 92, 246, 26))
        # body
        p.drawRoundedRect(QRectF(cx - 30, cy - 11, 60, 22), 11, 11)
        # grips
        p.drawRoundedRect(QRectF(cx - 43, cy - 8, 13, 16), 6, 6)
        p.drawRoundedRect(QRectF(cx + 30, cy - 8, 13, 16), 6, 6)
        # d-pad
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(cx - 18, cy), QPointF(cx - 9, cy))
        p.drawLine(QPointF(cx - 13.5, cy - 4.5), QPointF(cx - 13.5, cy + 4.5))
        # face buttons
        for dx, dy in ((13, -6), (13, 6), (19, 0)):
            p.setBrush(color)
            p.drawEllipse(QPointF(cx + dx, cy + dy), 2.2, 2.2)
        p.setBrush(Qt.NoBrush)


class DiscordCommunityCard(GlassCard):
    """Official community hub card — artwork, status pill, join button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("Official Discord Community")
        title.setObjectName("GlassCardTitle")
        title.setWordWrap(True)
        head.addWidget(title, 1)
        lay.addLayout(head)

        badge_row = QHBoxLayout()
        has_invite = bool(DISCORD_INVITE_URL)
        coming = QLabel("\u25cf LIVE" if has_invite else "\u25cf COMING SOON")
        badge_color = ACCENT if has_invite else WARNING
        coming.setStyleSheet(
            f"background-color: {qss_rgba(badge_color, 0x26)};"
            f" color: {badge_color};"
            f" border: 1px solid {qss_rgba(badge_color, 0x88)};"
            " border-radius: 9px; padding: 3px 10px; font-size: 10px;"
            " font-weight: 800; letter-spacing: 0.7px;")
        badge_row.addWidget(coming)
        badge_row.addStretch()
        lay.addLayout(badge_row)

        art = _CommunityArt()
        lay.addWidget(art)

        body = QLabel(
            "Join the Maximum Tweaks community for exclusive beta builds, custom "
            "Fortnite game profiles, and live support.")
        body.setObjectName("CardDetail")
        body.setWordWrap(True)
        lay.addWidget(body)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.join_btn = QPushButton("\U0001F513  Join Discord")
        self.join_btn.setObjectName("Secondary")
        if has_invite:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            self.join_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(DISCORD_INVITE_URL)))
        else:
            self.join_btn.setDisabled(True)
            self.join_btn.setToolTip(
                "The official Discord is coming soon \u2014 stay tuned.")
        row.addStretch()
        row.addWidget(self.join_btn)
        row.addStretch()
        lay.addLayout(row)


# --------------------------------------------------------------------------
# GPU/CPU toggle pill
# --------------------------------------------------------------------------

class TogglePill(QWidget):
    """Segmented pill toggle (e.g. GPU / CPU thermal source)."""

    changed = Signal(str)

    def __init__(self, labels: list[str], default: int = 0, parent=None):
        super().__init__(parent)
        self.setObjectName("TogglePill")
        self._labels = labels
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._group = QButtonGroup(self)
        self._buttons: list[QPushButton] = []
        for i, label in enumerate(labels):
            btn = QPushButton(label)
            btn.setObjectName("SegToggle")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            self._group.addButton(btn, i)
            lay.addWidget(btn)
            self._buttons.append(btn)
        self._group.buttonClicked.connect(self._on_clicked)
        self._set_active(default)

    def _set_active(self, index: int):
        self._buttons[index].setChecked(True)
        self._refresh()

    def _on_clicked(self, btn):
        self._refresh()
        self.changed.emit(self._labels[self._group.id(btn)])

    def _refresh(self):
        from ui.styles import repolish
        for i, btn in enumerate(self._buttons):
            active = btn.isChecked()
            if btn.property("active") != active:
                btn.setProperty("active", "true" if active else "false")
                repolish(btn)


# --------------------------------------------------------------------------
# Multi-segmented disk bar
# --------------------------------------------------------------------------

class DiskBar(QWidget):
    """Rounded segmented progress bar (OS / Games / Free)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setMinimumWidth(220)
        self._segments: list = []
        self._total = 1

    def set_segments(self, segments: list[tuple[str, float, str]], total: float):
        self._segments = segments
        self._total = max(1.0, float(total))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        radius = self.height() / 2.0

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.setClipPath(path)

        x = 0.0
        n = len(self._segments)
        for i, (_, size, color) in enumerate(self._segments):
            frac = max(0.0, float(size)) / self._total
            seg_w = frac * self.width()
            if seg_w <= 0:
                continue
            col = QColor(color)
            if n > 1 and i < n - 1:
                col.setAlpha(230)
            p.fillRect(QRectF(x, 0, seg_w, self.height()), col)
            x += seg_w
        p.setClipping(False)

        outline = QPen(QColor(29, 34, 42), 1)
        p.setPen(outline)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


# --------------------------------------------------------------------------
# Disk cleanup worker
# --------------------------------------------------------------------------

class CleanupThread(QThread):
    done = Signal(dict)

    def run(self):
        from engine.telemetry import clean_temp_files
        self.done.emit(clean_temp_files())


# --------------------------------------------------------------------------
# Dialogs — System Info and What's New
# --------------------------------------------------------------------------

class InfoDialog(QDialog):
    """OS / hardware details popup (System Info)."""

    def __init__(self, rows: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("System Info")
        self.resize(500, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)

        title = QLabel("System Info")
        title.setStyleSheet(f"font-size: 22px; font-weight: 900; color: {TEXT};")
        lay.addWidget(title)
        sub = QLabel("Your system at a glance.")
        sub.setObjectName("PageSub")
        lay.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 6, 6, 6)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        for row, (label, value) in enumerate(rows):
            l = QLabel(label.upper())
            l.setStyleSheet(f"color: {FAINT}; font-size: 10px; font-weight: 800;"
                            "letter-spacing: 1.2px;")
            v = QLabel(value)
            v.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 600;")
            v.setWordWrap(True)
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(l, row, 0)
            grid.addWidget(v, row, 1)
        grid.setColumnStretch(1, 1)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)

        close = QPushButton("Done")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)


class ChangelogDialog(QDialog):
    """What's New modal — recent version highlights."""

    def __init__(self, entries: list[tuple[str, str, list[str]]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("What's New")
        self.resize(540, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)

        title = QLabel("What's New")
        title.setStyleSheet(f"font-size: 22px; font-weight: 900; color: {TEXT};")
        lay.addWidget(title)
        sub = QLabel("The latest changes and improvements.")
        sub.setObjectName("PageSub")
        lay.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 6, 6, 6)
        v.setSpacing(14)
        for version, date, bullets in entries:
            head = QHBoxLayout()
            v_lbl = QLabel(version)
            v_lbl.setStyleSheet(
                f"color: {ACCENT}; font-size: 14px; font-weight: 900;")
            d_lbl = QLabel(date)
            d_lbl.setStyleSheet(f"color: {FAINT}; font-size: 11px;")
            head.addWidget(v_lbl)
            head.addStretch()
            head.addWidget(d_lbl)
            v.addLayout(head)
            for bullet in bullets:
                row = QHBoxLayout()
                row.setSpacing(8)
                dot = QLabel("\u25cf")
                dot.setStyleSheet(f"color: {DIM}; font-size: 9px;")
                b = QLabel(bullet)
                b.setStyleSheet(f"color: {DIM}; font-size: 12.5px;")
                b.setWordWrap(True)
                row.addWidget(dot, 0, Qt.AlignTop)
                row.addWidget(b, 1)
                v.addLayout(row)
        v.addStretch()
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)

        close = QPushButton("Done")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)
