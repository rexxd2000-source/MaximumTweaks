"""Horizontal node-link route visualization widget (replaces the 3D globe)."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QRadialGradient
from PySide6.QtWidgets import QWidget

from config.app_config import THEME as T


def _s(key, alpha=0xFF):
    from PySide6.QtGui import QColor
    hex_color = T.get(key, "#94a3b8").lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return QColor(r, g, b, alpha)


@dataclass
class RouteNode:
    label: str = ""         # "YOU", "ISP", "JOHANNESBURG", etc.
    ip: str = ""
    location: str = ""      # "City, Country"
    asn: str = ""           # "AS12345"
    network: str = ""       # "Network Name"
    rtt_ms: float = 0.0     # RTT to this node
    is_endpoint: bool = False  # Is this the game endpoint?
    is_user: bool = False   # Is this the user?
    color: str = "#60a5fa"


class RouteVisualizationWidget(QWidget):
    """2D horizontal node-link diagram of network hops."""

    MARGIN = 40.0
    ANIM_INTERVAL_MS = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes: list[RouteNode] = []
        self._title: str = ""
        self._subtitle: str = ""
        self._route_color: str = "#60a5fa"
        self._anim_offset: float = 0
        self._coming_soon: bool = False
        self._coming_soon_text: str = ""
        self.setMinimumHeight(120)
        self.setMaximumHeight(200)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), _s("card"))
        self.setPalette(pal)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(self.ANIM_INTERVAL_MS)
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._sync_timer()

    # ------------------------------------------------------------------ API
    def set_title(self, title: str, subtitle: str = ""):
        self._title = title
        self._subtitle = subtitle
        self.update()

    def set_nodes(self, nodes: list[RouteNode]):
        self._nodes = list(nodes)
        self._coming_soon = False
        self.update()
        self._sync_timer()

    def set_route_color(self, color: str):
        self._route_color = color
        self.update()

    def clear(self):
        self._nodes = []
        self._coming_soon = False
        self.update()
        self._sync_timer()

    def set_coming_soon(self, text: str = ""):
        self._coming_soon = True
        self._coming_soon_text = text or "Hop-by-hop route analysis coming soon"
        self._nodes = []
        self.update()

    # ------------------------------------------------------------ animation
    def _on_anim_tick(self):
        self._anim_offset += 0.5
        self.update()

    def _sync_timer(self):
        if self._nodes and self.isVisible():
            self._anim_timer.start()
        else:
            self._anim_timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event):
        self._anim_timer.stop()
        super().hideEvent(event)

    # ------------------------------------------------------------- painting
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        p.fillRect(self.rect(), _s("card"))

        top = 0.0
        if self._title:
            tf = QFont(self.font())
            tf.setPixelSize(9)
            tf.setBold(True)
            tf.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
            p.setFont(tf)
            p.setPen(_s("accent"))
            p.drawText(QRectF(12, 6, w - 24, 14),
                       Qt.AlignLeft | Qt.AlignVCenter, self._title.upper())
            top = 18.0
            if self._subtitle:
                sf = QFont(self.font())
                sf.setPixelSize(8)
                p.setFont(sf)
                p.setPen(_s("text_faint"))
                p.drawText(QRectF(12, top, w - 24, 12),
                           Qt.AlignLeft | Qt.AlignVCenter, self._subtitle)
                top += 13.0

        if not self._nodes:
            if self._coming_soon:
                cs_font = QFont(self.font())
                cs_font.setPixelSize(11)
                cs_font.setBold(True)
                p.setFont(cs_font)
                p.setPen(_s("text_faint"))
                p.drawText(
                    QRectF(0, h * 0.35, w, 20),
                    Qt.AlignHCenter | Qt.AlignVCenter,
                    self._coming_soon_text.upper())
            p.end()
            return

        n = len(self._nodes)
        line_y = top + (h - top) * 0.42
        if n == 1:
            xs = [w / 2.0]
        else:
            step = (w - 2 * self.MARGIN) / (n - 1)
            xs = [self.MARGIN + i * step for i in range(n)]

        pen = QPen(QColor(self._route_color))
        pen.setWidthF(1.5)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([4.0, 5.0])
        pen.setDashOffset(self._anim_offset)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for i in range(n - 1):
            p.drawLine(QPointF(xs[i], line_y), QPointF(xs[i + 1], line_y))

        rf = QFont("Consolas")
        rf.setPixelSize(8)
        p.setFont(rf)
        p.setPen(_s("text_dim"))
        for i in range(n - 1):
            rtt = self._nodes[i + 1].rtt_ms
            if rtt > 0:
                mx = (xs[i] + xs[i + 1]) / 2.0
                p.drawText(QRectF(mx - 35, line_y - 19, 70, 12),
                           Qt.AlignCenter, f"{rtt:.0f} ms")

        for i, node in enumerate(self._nodes):
            x = xs[i]
            r = 8.0 if node.is_endpoint else 6.0
            color = QColor(node.color or self._route_color)
            grad = QRadialGradient(x - r * 0.3, line_y - r * 0.3, r * 2.2)
            grad.setColorAt(0.0, color.lighter(140))
            grad.setColorAt(1.0, color.darker(130))
            p.setPen(QPen(color.darker(150), 1.0))
            p.setBrush(QBrush(grad))
            p.drawEllipse(QPointF(x, line_y), r, r)
            if node.is_endpoint:
                halo = QPen(QColor(color.red(), color.green(), color.blue(), 90), 1.0)
                p.setPen(halo)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(x, line_y), r + 3.5, r + 3.5)

            lf = QFont(self.font())
            lf.setPixelSize(9)
            lf.setBold(True)
            p.setFont(lf)
            p.setPen(_s("text"))
            label = p.fontMetrics().elidedText(node.label, Qt.ElideRight, 120)
            p.drawText(QRectF(x - 65, line_y + r + 4, 130, 12),
                       Qt.AlignHCenter | Qt.AlignTop, label)

            info = " · ".join(part for part in (node.location, node.asn) if part) or node.ip
            if info:
                inf = QFont(self.font())
                inf.setPixelSize(7)
                p.setFont(inf)
                p.setPen(_s("text_faint"))
                info = p.fontMetrics().elidedText(info, Qt.ElideRight, 140)
                p.drawText(QRectF(x - 75, line_y + r + 15, 150, 10),
                           Qt.AlignHCenter | Qt.AlignTop, info)

        p.end()
