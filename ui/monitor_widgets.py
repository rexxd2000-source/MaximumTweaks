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

from ui.widgets import qss_rgba, tint_pixmap

ACCENT = T["accent"]
DANGER = T["danger"]
WARNING = T["warning"]
TEXT = T["text"]
DIM = T["text_dim"]
FAINT = T["text_faint"]
class GlassCard(QFrame):
    """Translucent frosted panel used by every dashboard card."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GlassCard")


class GlassPanel(QFrame):
    """Dashboard glass panel with decorative bracket corners.

    Matches the reference dashboard: translucent gradient surface, 1px glass
    border and two L-shaped corner brackets (top-left + bottom-right). The
    corner color is passed in (violet / cyan per the reference layout).
    """

    def __init__(self, corner="#9C80FF", parent=None):
        super().__init__(parent)
        self.setObjectName("DashPanel")
        self._corner = QColor(corner)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        pen = QPen(self._corner, 1.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        w, h = self.width(), self.height()
        s = 14
        off = 1.5
        # top-left bracket
        tl = QPainterPath()
        tl.moveTo(off, h - off - s)
        tl.lineTo(off, off + 3)
        tl.quadTo(off, off, off + 3, off)
        tl.lineTo(off + s, off)
        p.drawPath(tl)
        # bottom-right bracket (mirror)
        br = QPainterPath()
        br.moveTo(w - off, off + s)
        br.lineTo(w - off, h - off - 3)
        br.quadTo(w - off, h - off, w - off - 3, h - off)
        br.lineTo(w - off - s, h - off)
        p.setPen(QPen(QColor(self._corner.red(), self._corner.green(),
                             self._corner.blue(), 140), 1.2))
        p.drawPath(br)


class RingGauge(QWidget):
    """96px circular utilization gauge with a glowing colored arc.

    The track is a thin full ring; the value is an animated stroke-dashoffset
    style arc (1/4 turn advance toward the target), matching the reference
    dashboard. The center shows the percentage in a mono face.
    """

    def __init__(self, color="#9C80FF", parent=None):
        super().__init__(parent)
        self.setFixedSize(96, 96)
        self._color = QColor(color)
        self._target = 0.0
        self._display = 0.0
        self._anim: QVariantAnimation | None = None

    def set_value(self, pct: float, color: str | None = None):
        if color:
            self._color = QColor(color)
        target = max(0.0, min(100.0, float(pct)))
        self._target = target
        if self._anim is not None:
            self._anim.stop()
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(900)
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
        p.setRenderHint(QPainter.TextAntialiasing)
        side = self.width()
        pen_w = 8
        rect = QRectF(pen_w / 2, pen_w / 2,
                      side - pen_w, side - pen_w)

        # track ring
        track = QPen(QColor(255, 255, 255, 18), pen_w)
        p.setPen(track)
        p.drawArc(rect, 0, 360 * 16)

        span = -int(round(self._display / 100.0 * 360.0)) * 16
        if abs(span) >= 16:
            # soft glow pass
            glow = QPen(QColor(self._color.red(), self._color.green(),
                               self._color.blue(), 46), pen_w + 6)
            p.setPen(glow)
            p.drawArc(rect, 90 * 16, span)
            # value arc
            value = QPen(self._color, pen_w)
            value.setCapStyle(Qt.RoundCap)
            p.setPen(value)
            p.drawArc(rect, 90 * 16, span)

        # center %
        mono = QFont("JetBrains Mono", 11)
        mono.setPixelSize(18)
        mono.setWeight(QFont.Weight.DemiBold)
        p.setFont(mono)
        fm = p.fontMetrics()
        text = f"{round(self._display)}"
        tw = fm.horizontalAdvance(text)
        base = fm.ascent()
        x = (side - tw) / 2.0
        y = side / 2.0 - base / 2.0
        p.setPen(QColor(242, 243, 248))
        p.drawText(QPointF(x, y + base), text)

        small = QFont("JetBrains Mono", 7)
        small.setPixelSize(11)
        p.setFont(small)
        sfm = p.fontMetrics()
        x2 = x + tw + 2
        p.setPen(QColor(91, 97, 120))
        p.drawText(QPointF(x2, y + base - 4), "%")


class PulseDot(QWidget):
    """Small glowing dot with an infinite pulsing opacity loop."""

    def __init__(self, color="#9C80FF", size=6, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setStyleSheet(
            f"background-color: {color}; border-radius: {size // 2}px;"
            f" border: 1px solid {color};")
        self._anim = None
        self._start_pulse()

    def _start_pulse(self):
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(1300)
        self._anim.setLoopCount(-1)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.35)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)
        self._anim.valueChanged.connect(eff.setOpacity)
        self._anim.start()


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
        p.setRenderHint(QPainter.TextAntialiasing)
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
            font = QFont("Segoe UI")
            font.setPixelSize(27)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(139, 92, 246, 70))
            p.drawText(QRectF(6, 6, self.width() - 12, self.height() - 8),
                       Qt.AlignCenter, "R")
            p.setPen(QColor(139, 92, 246))
            p.drawText(QRectF(5, 5, self.width() - 12, self.height() - 8),
                       Qt.AlignCenter, "R")
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
        # Reference dashboard: temperature line is always the gold series.
        return QColor("#FFB454")

    @property
    def _clock_color(self):
        # Reference dashboard: clock line is always the cyan series.
        return QColor("#4BE8D8")

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
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        ml, mt, mr, mb = 40, 12, 52, 24
        plot = QRectF(ml, mt, w - ml - mr, h - mt - mb)
        if plot.width() <= 0 or plot.height() <= 0:
            return

        small = QFont("Segoe UI")
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
        marks = [("60m", 60), ("30m", 30), ("now", 0)]
        for text, sec in marks:
            x = plot.right() - (sec / self.WINDOW) * plot.width()
            p.setPen(QColor(FAINT))
            p.drawText(QRectF(x - 20, plot.bottom() + 4, 40, 14),
                       Qt.AlignHCenter | Qt.AlignTop, text)
            tick = QPen(QColor(255, 255, 255, 14))
            p.setPen(tick)
            p.drawLine(QPointF(x, plot.bottom()), QPointF(x, plot.bottom() + 3))

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
        clock_color = self._clock_color
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
            therm_lbl = "CPU" if self.mode == "cpu" else "GPU"
            lines.append(f"{therm_lbl}  {temp:.0f}\u00b0C" if temp is not None
                         else f"{therm_lbl}  \u2014")
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
            tip = QFont("Segoe UI")
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
        self.setFixedHeight(7)
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
        p.setRenderHint(QPainter.TextAntialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        radius = self.height() / 2.0

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.setClipPath(path)

        # hairline track
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.fillPath(path, QColor(255, 255, 255, 18))

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


# --------------------------------------------------------------------------
# Disk cleanup worker
# --------------------------------------------------------------------------

class CleanupThread(QThread):
    done = Signal(dict)

    def run(self):
        from engine.telemetry import clean_temp_files
        self.done.emit(clean_temp_files())
