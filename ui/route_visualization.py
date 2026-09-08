"""Horizontal node-link route visualization widget (replaces the 3D globe)."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QRadialGradient
from PySide6.QtWidgets import QWidget

from config.app_config import THEME as T


def _s(key, alpha=0xFF):
    from PySide6.QtGui import QColor
    hex_color = T.get(key, "#928AAD").lstrip("#")
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
    is_context: bool = False  # Derived/inferred (outside leg, BGP routing
                              # data) — NOT a directly measured traceroute hop.
                              # Rendered with a dashed ring + dimmed fill so it
                              # can never be mistaken for a live measured hop.


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
        self.setMinimumHeight(150)
        self.setMaximumHeight(220)
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
        self._coming_soon_text = (
            text or "Optimized route unavailable \u2014 no active tunnel detected"
        )
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
        p.setRenderHint(QPainter.TextAntialiasing)
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
                    QRectF(16, h * 0.24, w - 32, h * 0.5),
                    Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextWordWrap,
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

        rf = QFont("JetBrains Mono")
        rf.setPixelSize(8)
        p.setFont(rf)
        p.setPen(_s("text_dim"))
        for i in range(n - 1):
            rtt = self._nodes[i + 1].rtt_ms
            if rtt > 0:
                mx = (xs[i] + xs[i + 1]) / 2.0
                # RTT chip sits ABOVE the path line, clear of node labels below.
                chip = QRectF(mx - 34, line_y - 26, 68, 13)
                p.fillRect(chip, _s("card", alpha=235))
                p.setPen(QColor(*_s("text_dim").getRgb()[:3], 255))
                p.drawText(chip, Qt.AlignCenter, f"{rtt:.0f} ms")

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
            if node.is_context:
                # Inferred/derived context node (outside-leg or BGP routing
                # data): dashed ring + dimmed fill so it stays visually
                # distinct from real, directly-measured traceroute hops.
                dash = QPen(QColor(color.red(), color.green(), color.blue(), 150), 1.0)
                dash.setStyle(Qt.DashLine)
                p.setPen(dash)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(x, line_y), r + 3.0, r + 3.0)
            if node.is_endpoint:
                halo = QPen(QColor(color.red(), color.green(), color.blue(), 90), 1.0)
                p.setPen(halo)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(x, line_y), r + 3.5, r + 3.5)

            # Labels live in a dedicated band BELOW the path line and marker,
            # with their own backing chip so text never collides with the
            # dashed route. The chart keeps a >=40px internal margin; labels
            # that would run into it FLIP their anchor toward the inner side
            # (text-anchor: middle normally, left/right at the edges) instead
            # of spilling off-canvas.
            #
            # Premium emphasis: the CITY/COUNTRY is the primary label for a
            # hop (Johannesburg, South Africa / Doha, Ad Dawhah, QA) with the
            # IP or role as the secondary line — a route that reads as a path
            # through named places. YOU / CLOUD ZONE / SERVER keep their role
            # as the primary so the anchors stay obvious.
            is_zone = node.label == "CLOUD ZONE"
            if node.is_user or is_zone:
                primary, secondary = node.label, (node.location or node.ip)
            elif node.location and node.location != node.ip:
                primary, secondary = (node.location or ""), (node.label or node.ip)
            else:
                primary, secondary = (node.label or node.ip), (node.location or "")

            lf = QFont(self.font())
            lf.setPixelSize(9)
            lf.setBold(True)
            p.setFont(lf)
            label = p.fontMetrics().elidedText(primary, Qt.ElideRight, 156)
            lw = min(max(p.fontMetrics().horizontalAdvance(label) + 10, 30), 180)

            def _box_and_align(x, lw, w):
                centered = x - lw / 2.0
                lx = min(max(centered, 6.0), max(6.0, w - lw - 6.0))
                if centered < 6.0:
                    align = Qt.AlignLeft | Qt.AlignVCenter
                elif centered + lw > w - 6.0:
                    align = Qt.AlignRight | Qt.AlignVCenter
                else:
                    align = Qt.AlignHCenter | Qt.AlignVCenter
                return lx, align

            lx, l_align = _box_and_align(x, lw, w)
            l_box = QRectF(lx, line_y + r + 5, lw, 14)
            p.fillRect(l_box, QColor(0, 0, 0, 90))
            if is_zone:
                zc = QColor("#FFB454")
                p.setPen(zc)
            else:
                p.setPen(_s("text"))
            p.drawText(l_box, l_align, label)

            info = secondary or " · ".join(
                part for part in (node.location, node.asn) if part
            ) or node.ip
            if info:
                inf = QFont(self.font())
                inf.setPixelSize(7)
                p.setFont(inf)
                info = p.fontMetrics().elidedText(info, Qt.ElideRight, 170)
                iw = min(max(p.fontMetrics().horizontalAdvance(info) + 10, 30), 190)
                ix, i_align = _box_and_align(x, iw, w)
                i_box = QRectF(ix, l_box.bottom() + 3, iw, 12)
                p.fillRect(i_box, QColor(0, 0, 0, 90))
                p.setPen(_s("text_faint"))
                p.drawText(i_box, i_align, info)

        p.end()
