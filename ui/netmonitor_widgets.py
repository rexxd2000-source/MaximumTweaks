"""Interactive world map widget for route visualization."""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QPen, QBrush, QFont,
    QPainterPath, QFontMetrics, QConicalGradient, QRadialGradient,
)
from PySide6.QtWidgets import QWidget, QToolTip

from config.app_config import DIRS
from engine.netmonitor.types import Hop, HopStatus, Route


class RouteMapWidget(QWidget):
    hop_clicked = Signal(int)
    hop_hovered = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(600, 300)
        self.setMinimumHeight(280)
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

        geo_hops = []
        no_geo_hops = []
        for hop in self._route.hops:
            if hop.geo.latitude != 0 and hop.geo.longitude != 0:
                geo_hops.append(hop)
            else:
                no_geo_hops.append(hop)

        if geo_hops:
            x_step = (w * 0.85) / max(len(self._route.hops), 1)
            for i, hop in enumerate(self._route.hops):
                if hop.geo.latitude != 0 and hop.geo.longitude != 0:
                    pos = self._ll2px(hop.geo.longitude, hop.geo.latitude)
                    pos.setX(w * 0.1 + i * x_step)
                    self._hop_positions[hop.number] = pos
                else:
                    prev_x = w * 0.1 + i * x_step
                    pos = QPointF(prev_x, h * 0.5)
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
        w, h = self.width(), self.height()

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
        if not sorted_nums:
            return

        points = [self._hop_positions[n] for n in sorted_nums]

        glow_pen = QPen(QColor(139, 92, 246, 60), 6)
        p.setPen(glow_pen)
        if len(points) >= 2:
            path = QPainterPath()
            path.moveTo(points[0])
            for pt in points[1:]:
                path.lineTo(pt)
            p.drawPath(path)

        main_pen = QPen(QColor(139, 92, 246), 2)
        p.setPen(main_pen)
        if len(points) >= 2:
            for i in range(len(points) - 1):
                p.drawLine(points[i], points[i + 1])

        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]
            mid = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
            angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
            arrow_size = 8
            ax = mid.x() + arrow_size * math.cos(angle - 0.4)
            ay = mid.y() + arrow_size * math.sin(angle - 0.4)
            bx = mid.x() + arrow_size * math.cos(angle + 0.4)
            by = mid.y() + arrow_size * math.sin(angle + 0.4)
            p.setBrush(QBrush(QColor(139, 92, 246)))
            p.setPen(Qt.PenStyle.NoPen)
            tri = QPainterPath()
            tri.moveTo(mid)
            tri.lineTo(ax, ay)
            tri.lineTo(bx, by)
            tri.closeSubpath()
            p.drawPath(tri)

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

            p.setPen(QPen(QColor(20, 25, 40), 2))
            p.setBrush(QBrush(color))
            p.drawEllipse(pos, radius, radius)

            if hop_num in (0, -1):
                inner_color = QColor(10, 13, 24)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(inner_color))
                p.drawEllipse(pos, radius - 4, radius - 4)

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
                    label = hop.geo.city or hop.display_name or str(hop.number)
                    if len(label) > 15:
                        label = label[:12] + "..."
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
                text_w + 4,
                fm.height() + 2,
            )
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
                    if hop.geo.city:
                        tip += f" ({hop.location_str})"
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
