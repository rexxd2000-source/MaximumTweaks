"""Interactive world map widget for route visualization."""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QPen, QBrush, QFont,
    QPainterPath, QFontMetrics, QConicalGradient, QRadialGradient,
    QLinearGradient,
)
from PySide6.QtWidgets import QWidget, QToolTip

from config.app_config import DIRS
from engine.netmonitor.types import Hop, HopStatus, Route


class RouteMapWidget(QWidget):
    hop_clicked = Signal(int)
    hop_hovered = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 150)
        self._map_pixmap: Optional[QPixmap] = None
        self._route: Optional[Route] = None
        self._selected_hop: int = -1
        self._hovered_hop: int = -1
        self._hop_positions: dict[int, QPointF] = {}
        self._pan_offset = QPointF(0, 0)
        self._zoom = 1.0
        self._dragging = False
        self._drag_start = QPointF()
        self._anim_phase = 0.0
        self.setMouseTracking(True)
        self._load_map()

    def _load_map(self):
        path = DIRS["assets"] / "world_map.png"
        if path.exists():
            self._map_pixmap = QPixmap(str(path))
        else:
            self._map_pixmap = None

    def set_route(self, route: Optional[Route]):
        self._route = route
        self._compute_positions()
        self.update()

    def select_hop(self, hop_number: int):
        self._selected_hop = hop_number
        self.update()

    def _compute_positions(self):
        self._hop_positions = {}
        if not self._route or not self._route.hops:
            return

        w = self.width()
        h = self.height()

        pc_pos = self._ll2px(28.0, -26.0)
        self._hop_positions[0] = QPointF(w * 0.05, h * 0.5)

        def _has_geo(hop) -> bool:
            # A rejected geolocation (measured latency below the fiber floor,
            # e.g. a geo-DB "Port Elizabeth" for a 4 ms Vodacom router) must
            # never be pinned on the map — that draws a fake route down the
            # coast. Such hops plot in path sequence like any no-geo hop.
            # Sub-15ms hops are the same story at finer granularity: the DB
            # city for a hop 0-700 km away is registered-office noise —
            # unless the ISP itself named the PoP (reverse-DNS / prefix table),
            # which is authoritative even at short latency.
            geo = getattr(hop, "geo", None)
            latency = getattr(hop, "latency", 0.0) or 0.0
            src = (getattr(geo, "city_source", "") or "") if geo else ""
            trusted_near = src in ("hostname", "isp_prefix", "afrinic")
            return bool(
                geo
                and getattr(geo, "verified", True)
                and (not (0 < latency < 15.0) or trusted_near)
                and geo.latitude != 0
                and geo.longitude != 0
            )

        geo_hops = []
        no_geo_hops = []
        for hop in self._route.hops:
            if _has_geo(hop):
                geo_hops.append(hop)
            else:
                no_geo_hops.append(hop)

        if geo_hops:
            x_step = (w * 0.85) / max(len(self._route.hops), 1)
            y_off = 0
            for i, hop in enumerate(self._route.hops):
                if _has_geo(hop):
                    pos = self._ll2px(hop.geo.longitude, hop.geo.latitude)
                    pos.setX(w * 0.1 + i * x_step)
                    self._hop_positions[hop.number] = pos
                else:
                    # No geo for this hop (private/CGNAT/unknown): still plot it
                    # in its exact sequence position — never drop it from the
                    # visual. Alternate a small y-gap so consecutive CGNAT hops
                    # don't stack into one visible dot.
                    prev_x = w * 0.1 + i * x_step
                    y_off = -10 if y_off == 0 else 0
                    pos = QPointF(prev_x, h * 0.5 + y_off)
                    self._hop_positions[hop.number] = pos
        else:
            x_step = (w * 0.85) / max(len(self._route.hops), 1)
            for i, hop in enumerate(self._route.hops):
                x = w * 0.1 + i * x_step
                y = h * 0.5
                self._hop_positions[hop.number] = QPointF(x, y)

        dest_x = w * 0.92
        self._hop_positions[-1] = QPointF(dest_x, h * 0.5)

    def _ll2px(self, lon: float, lat: float) -> QPointF:
        x = (lon + 180) / 360 * self.width()
        y = (90 - lat) / 180 * self.height()
        return QPointF(x, y)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()

        # Everything must stay inside this widget's own rectangle. The map is
        # a stretchy pane above the RTT instrument; without an explicit clip
        # any overflow paints over (or under) the sibling panel below.
        p.setClipRect(0, 0, max(1, w), max(1, h))

        p.fillRect(0, 0, w, h, QColor(10, 13, 24))

        if self._map_pixmap and not self._map_pixmap.isNull():
            scaled = self._map_pixmap.scaled(
                w, h, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x_off = (w - scaled.width()) // 2
            y_off = (h - scaled.height()) // 2
            p.drawPixmap(x_off, y_off, scaled)

        if not self._route or not self._route.hops:
            p.setPen(QColor(100, 120, 160))
            p.setFont(QFont("Segoe UI", 14))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "Enter a destination to trace the route")
            p.end()
            return

        self._draw_route_lines(p)
        self._draw_hops(p)
        self._draw_labels(p)

        p.end()

    def _draw_route_lines(self, p: QPainter):
        if not self._hop_positions:
            return

        sorted_nums = sorted([n for n in self._hop_positions if n >= 0])
        if len(sorted_nums) < 2:
            return

        # Terminate the cable AT the destination knob so the server marker
        # never floats free of the route (before, the -1 endpoint was drawn
        # as a separate red dot with no line reaching it).
        if -1 in self._hop_positions:
            sorted_nums.append(-1)

        pts = [self._hop_positions[n] for n in sorted_nums]
        count = len(pts)

        # Catmull-Rom spline through every hop: all nodes are woven into ONE
        # flowing cable (round corners, no hard polyline kinks), reading like
        # a premium network trace rather than a flat wireframe.
        path = QPainterPath()
        path.moveTo(pts[0])
        for i in range(count - 1):
            a = pts[max(0, i - 1)]
            b = pts[i]
            c = pts[i + 1]
            d = pts[min(count - 1, i + 2)]
            c1 = QPointF(b.x() + (c.x() - a.x()) / 6.0,
                         b.y() + (c.y() - a.y()) / 6.0)
            c2 = QPointF(c.x() - (d.x() - b.x()) / 6.0,
                         c.y() - (d.y() - b.y()) / 6.0)
            path.cubicTo(c1, c2, c)

        cap = Qt.PenCapStyle.RoundCap
        join = Qt.PenJoinStyle.RoundJoin

        # Deep ambience + violet aura hugging the cable for depth.
        glow_deep = QPen(QBrush(QColor(98, 102, 241, 46)), 11, Qt.SolidLine, cap, join)
        glow_close = QPen(QBrush(QColor(139, 92, 246, 90)), 6, Qt.SolidLine, cap, join)

        p.setPen(glow_deep)
        p.drawPath(path)
        p.setPen(glow_close)
        p.drawPath(path)

        # Gradient light-pipe core: sky -> violet -> rose toward the server.
        grad = QLinearGradient(pts[0], pts[-1])
        grad.setColorAt(0.0, QColor(98, 207, 255))
        grad.setColorAt(0.5, QColor(167, 139, 250))
        grad.setColorAt(1.0, QColor(244, 114, 182))
        core = QPen(QBrush(grad), 3, Qt.SolidLine, cap, join)
        p.setPen(core)
        p.drawPath(path)
        tap = QPen(QBrush(QColor(255, 255, 255, 110)), 1.2, Qt.SolidLine, cap, join)
        p.setPen(tap)
        p.drawPath(path)

        # Direction chevrons riding the curve between every pair of hops.
        total_seg = count - 1
        for i in range(total_seg):
            mid = path.pointAtPercent((i + 0.5) / total_seg)
            ang = path.angleAtPercent((i + 0.5) / total_seg)
            p.save()
            p.translate(mid)
            p.rotate(-ang)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(205, 180, 255))
            arrow = QPainterPath()
            arrow.moveTo(0, 0)
            arrow.lineTo(-9, -6)
            arrow.lineTo(-9, 6)
            arrow.closeSubpath()
            p.drawPath(arrow)
            p.restore()

    def _draw_hops(self, p: QPainter):
        for hop_num, pos in self._hop_positions.items():
            if hop_num == 0:
                color = QColor(96, 165, 250)
                radius = 10
            elif hop_num == -1:
                color = QColor(239, 68, 68)
                radius = 10
            else:
                hop = self._get_hop(hop_num)
                if hop:
                    color = self._status_color(hop.status)
                else:
                    color = QColor(148, 163, 184)
                radius = 7

            # Soft halo so every node reads clearly over the glow cable.
            p.setPen(Qt.PenStyle.NoPen)
            halo = QColor(color.red(), color.green(), color.blue())
            halo.setAlpha(42)
            p.setBrush(QBrush(halo))
            p.drawEllipse(pos, radius + 4, radius + 4)

            if hop_num == self._selected_hop:
                glow = QRadialGradient(pos, radius * 3)
                glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 80))
                glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
                p.setBrush(QBrush(glow))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(pos, radius * 3, radius * 3)
                radius += 2
            elif hop_num == self._hovered_hop:
                radius += 2

            p.setPen(QPen(QColor(18, 22, 38), 2))
            p.setBrush(QBrush(color))
            p.drawEllipse(pos, radius, radius)

            if hop_num in (0, -1):
                inner_color = QColor(10, 13, 24)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(inner_color))
                p.drawEllipse(pos, radius - 4, radius - 4)

            # Destination end-cap: a distinct ring so the red server knob
            # reads as the terminus the cable plugs into.
            if hop_num == -1:
                ring = QColor(color.red(), color.green(), color.blue())
                ring.setAlpha(165)
                p.setPen(QPen(QBrush(ring), 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(pos, radius + 3, radius + 3)

    def _draw_labels(self, p: QPainter):
        font = QFont("Segoe UI", 9)
        p.setFont(font)
        fm = QFontMetrics(font)

        for hop_num, pos in self._hop_positions.items():
            if hop_num == 0:
                label = "PC"
                color = QColor(96, 165, 250)
            elif hop_num == -1:
                route = self._route
                label = route.destination if route else "Dest"
                color = QColor(239, 68, 68)
            else:
                hop = self._get_hop(hop_num)
                if hop:
                    if hop.network.is_cgnat:
                        label = f"CGNAT hop {hop.number}"
                    elif hop.network.is_private:
                        label = f"LAN hop {hop.number}"
                    else:
                        label = hop.location_label or hop.display_name
                    if not label or len(label) > 15:
                        label = (hop.location_label or f"hop {hop.number}")[:12] + "..."
                    color = QColor(180, 200, 230)
                else:
                    label = str(hop_num)
                    color = QColor(120, 140, 170)

            if hop_num == self._selected_hop:
                color = QColor(255, 255, 255)
                font.setBold(True)
                p.setFont(font)

            text_w = fm.horizontalAdvance(label)
            text_rect = QRectF(
                pos.x() - text_w / 2,
                pos.y() + 16,
                text_w + 8,
                fm.height() + 4,
            )
            # Keep edge markers' labels (PC left, server right) from spilling
            # off the widget.
            if text_rect.left() < 4:
                text_rect.moveLeft(4)
            if text_rect.right() > self.width() - 4:
                text_rect.moveRight(self.width() - 4)
            # Backing chip so labels stay legible over the dashed route.
            p.fillRect(text_rect, QColor(0, 0, 0, 110))
            p.setPen(color)
            p.drawText(text_rect, Qt.AlignCenter, label)

            if hop_num == self._selected_hop:
                font.setBold(False)
                p.setFont(font)

    def _get_hop(self, num: int) -> Optional[Hop]:
        if not self._route:
            return None
        for h in self._route.hops:
            if h.number == num:
                return h
        return None

    def _status_color(self, status: HopStatus) -> QColor:
        return {
            HopStatus.HEALTHY: QColor(52, 211, 153),
            HopStatus.WARNING: QColor(251, 191, 36),
            HopStatus.CRITICAL: QColor(239, 68, 68),
            HopStatus.TIMEOUT: QColor(107, 114, 128),
            HopStatus.UNKNOWN: QColor(148, 163, 184),
            HopStatus.PRIVATE: QColor(96, 165, 250),
            HopStatus.LOCAL: QColor(96, 165, 250),
        }.get(status, QColor(148, 163, 184))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position()
            for hop_num, hpos in self._hop_positions.items():
                dx = pos.x() - hpos.x()
                dy = pos.y() - hpos.y()
                if dx * dx + dy * dy < 400:
                    self.hop_clicked.emit(hop_num)
                    return
        elif event.button() == Qt.MiddleButton:
            self._dragging = True
            self._drag_start = event.position()

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = event.position() - self._drag_start
            self._pan_offset += QPointF(delta.x(), delta.y())
            self._drag_start = event.position()
            self.update()
            return

        pos = event.position()
        found = -2
        for hop_num, hpos in self._hop_positions.items():
            dx = pos.x() - hpos.x()
            dy = pos.y() - hpos.y()
            if dx * dx + dy * dy < 400:
                found = hop_num
                break
        if found != self._hovered_hop:
            self._hovered_hop = found
            self.update()
            if found >= 0:
                hop = self._get_hop(found)
                if hop:
                    tip = f"Hop {hop.number}: {hop.display_name}"
                    loc = hop.location_label
                    if loc:
                        tip += f" ({loc})"
                    tip += f"\n{hop.latency:.1f} ms | Loss: {hop.packet_loss:.0f}%"
                    QToolTip.showText(self.mapToGlobal(pos.toPoint()), tip, self)
            else:
                QToolTip.hideText()

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        factor = 1.1 if delta > 0 else 0.9
        self._zoom = max(0.5, min(3.0, self._zoom * factor))
        self.update()
