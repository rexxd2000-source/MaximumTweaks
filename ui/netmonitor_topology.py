"""Network topology view — node graph showing network relationships.

Displays AS-level relationships, peering, transit, and IXP connections.
"""
from __future__ import annotations

import math
from typing import Optional
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QTimer
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QPainterPath, QFontMetrics,
    QRadialGradient, QLinearGradient,
)
from PySide6.QtWidgets import QWidget, QScrollArea

from config.app_config import THEME as T


def _s(key, alpha=0xFF):
    hex_color = T.get(key, "#94a3b8").lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return QColor(r, g, b, alpha)


@dataclass
class TopoNode:
    id: str = ""
    label: str = ""
    sublabel: str = ""
    node_type: str = "unknown"
    asn: int = 0
    confidence: str = "unknown"
    color: str = "#8b9cc0"
    x: float = 0.0
    y: float = 0.0


@dataclass
class TopoEdge:
    from_id: str = ""
    to_id: str = ""
    edge_type: str = "measured"
    label: str = ""
    confidence: str = "measured"
    latency: float = 0.0


class TopologyWidget(QWidget):
    node_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self._nodes: list[TopoNode] = []
        self._edges: list[TopoEdge] = []
        self._selected: str = ""
        self._hovered: str = ""
        self._anim: float = 0.0
        self._node_rects: dict[str, QRectF] = {}
        self.setMouseTracking(True)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def set_topology(self, nodes: list[TopoNode], edges: list[TopoEdge]):
        self._nodes = nodes
        self._edges = edges
        self._layout_nodes()
        self.update()

    def clear(self):
        self._nodes = []
        self._edges = []
        self._node_rects.clear()
        self.update()

    def _layout_nodes(self):
        if not self._nodes:
            return
        w = self.width()
        h = self.height()
        n = len(self._nodes)

        type_order = {
            "user": 0, "gateway": 1, "isp": 2, "transit": 3,
            "peering": 4, "ixp": 5, "cdn": 6, "cloud": 7,
            "destination": 8, "unknown": 9,
        }

        sorted_nodes = sorted(self._nodes, key=lambda nd: type_order.get(nd.node_type, 9))

        levels: dict[int, list[TopoNode]] = {}
        for nd in sorted_nodes:
            level = type_order.get(nd.node_type, 9)
            if level not in levels:
                levels[level] = []
            levels[level].append(nd)

        margin = 60
        usable_w = w - margin * 2
        usable_h = h - margin * 2

        sorted_levels = sorted(levels.keys())
        num_levels = len(sorted_levels)

        for li, level in enumerate(sorted_levels):
            nodes_at_level = levels[level]
            y = margin + (li / max(num_levels - 1, 1)) * usable_h
            for ni, nd in enumerate(nodes_at_level):
                x = margin + ((ni + 0.5) / len(nodes_at_level)) * usable_w
                nd.x = x
                nd.y = y

    def _tick(self):
        self._anim += 0.04
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor(4, 6, 12))
        bg.setColorAt(1, QColor(8, 10, 18))
        p.fillRect(0, 0, w, h, bg)

        self._node_rects.clear()

        self._draw_edges(p)
        self._draw_nodes(p)

        p.end()

    def _draw_edges(self, p: QPainter):
        node_map = {n.id: n for n in self._nodes}
        for edge in self._edges:
            n_from = node_map.get(edge.from_id)
            n_to = node_map.get(edge.to_id)
            if not n_from or not n_to:
                continue

            p1 = QPointF(n_from.x, n_from.y)
            p2 = QPointF(n_to.x, n_to.y)

            if edge.edge_type == "measured":
                color = QColor(96, 165, 250, 180)
                pen = QPen(color, 2.5)
                style = Qt.PenStyle.SolidLine
            elif edge.edge_type == "bgp_observed":
                color = QColor(167, 139, 250, 150)
                pen = QPen(color, 2.0)
                style = Qt.PenStyle.DashLine
            elif edge.edge_type == "inferred":
                color = QColor(140, 160, 190, 100)
                pen = QPen(color, 1.5)
                style = Qt.PenStyle.DotLine
            else:
                color = QColor(100, 130, 170, 120)
                pen = QPen(color, 1.5)
                style = Qt.PenStyle.SolidLine

            pen.setStyle(style)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)

            mid_x = (p1.x() + p2.x()) / 2
            mid_y = (p1.y() + p2.y()) / 2 - 15
            ctrl = QPointF(mid_x, mid_y)
            path = QPainterPath()
            path.moveTo(p1)
            path.quadTo(ctrl, p2)
            p.drawPath(path)

            if edge.latency > 0:
                font = QFont("Consolas", 7)
                p.setFont(font)
                p.setPen(QColor(200, 200, 220, 180))
                p.drawText(QRectF(mid_x - 25, mid_y - 8, 50, 16),
                           Qt.AlignCenter, f"{edge.latency:.0f} ms")

            if edge.label:
                font = QFont("Consolas", 6)
                p.setFont(font)
                p.setPen(QColor(140, 160, 190, 120))
                label_pos = QPointF(mid_x + 30, mid_y - 3)
                p.drawText(label_pos, edge.label)

    def _draw_nodes(self, p: QPainter):
        type_colors = {
            "user": "#60a5fa", "gateway": "#fbbf24", "isp": "#60a5fa",
            "transit": "#a78bfa", "peering": "#f472b6", "ixp": "#fbbf24",
            "cdn": "#34d399", "cloud": "#34d399", "hosting": "#34d399",
            "destination": "#34d399", "unknown": "#8b9cc0",
        }
        type_sizes = {
            "user": 22, "gateway": 18, "isp": 18, "transit": 15,
            "peering": 14, "ixp": 14, "cdn": 14, "cloud": 14,
            "destination": 18, "unknown": 12,
        }

        for node in self._nodes:
            color_hex = type_colors.get(node.node_type, node.color)
            color = QColor(color_hex)
            is_sel = node.id == self._selected
            is_hov = node.id == self._hovered

            r = type_sizes.get(node.node_type, 12)
            if is_sel:
                r += 4

            cx, cy = node.x, node.y
            node_rect = QRectF(cx - 45, cy - r - 20, 90, r * 2 + 40)
            self._node_rects[node.id] = node_rect

            if is_sel:
                glow = QRadialGradient(QPointF(cx, cy), r * 3)
                glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 60))
                glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(glow))
                p.drawEllipse(QPointF(cx, cy), r * 3, r * 3)
            elif is_hov:
                glow = QRadialGradient(QPointF(cx, cy), r * 2)
                glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 40))
                glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(glow))
                p.drawEllipse(QPointF(cx, cy), r * 2, r * 2)

            if node.node_type == "user":
                pulse = 0.5 + 0.3 * math.sin(self._anim * 1.2)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), int(pulse * 40))))
                p.drawEllipse(QPointF(cx, cy), r + 5, r + 5)

            p.setPen(QPen(QColor(4, 6, 12), 2))
            p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(cx, cy), r, r)

            inner = QRadialGradient(cx - r * 0.2, cy - r * 0.2, r)
            inner.setColorAt(0, QColor(255, 255, 255, 50))
            inner.setColorAt(1, QColor(255, 255, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(inner))
            p.drawEllipse(QPointF(cx, cy), r - 1, r - 1)

            font = QFont("Segoe UI", 8)
            font.setBold(is_sel)
            p.setFont(font)
            fm = QFontMetrics(font)

            label = node.label
            if len(label) > 20:
                label = label[:17] + "..."
            tw = fm.horizontalAdvance(label)
            lx = cx - tw / 2
            ly = cy + r + 6

            tr = QRectF(lx - 4, ly - 2, tw + 8, fm.height() + 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(4, 6, 12, 220)))
            p.drawRoundedRect(tr, 3, 3)

            p.setFont(font)
            p.setPen(QColor(200, 210, 230) if is_sel else QColor(160, 180, 210))
            p.drawText(tr, Qt.AlignCenter, label)

            if node.sublabel:
                sfont = QFont("Consolas", 7)
                stw = QFontMetrics(sfont).horizontalAdvance(node.sublabel)
                p.setFont(sfont)
                sy = ly + fm.height()
                sr = QRectF(cx - stw / 2 - 3, sy, stw + 6, fm.height() + 2)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(4, 6, 12, 180)))
                p.drawRoundedRect(sr, 2, 2)
                p.setPen(QColor(150, 130, 220, 180))
                p.drawText(sr, Qt.AlignCenter, node.sublabel)

            if node.node_type in ("ixp", "peering"):
                ring = 0.4 + 0.3 * math.sin(self._anim * 1.5 + hash(node.id) % 100)
                p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), int(ring * 80)), 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), r + 4, r + 4)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            for nid, rect in self._node_rects.items():
                if rect.contains(pos):
                    self._selected = nid
                    self.node_clicked.emit(nid)
                    self.update()
                    return

    def mouseMoveEvent(self, event):
        pos = event.position()
        found = ""
        for nid, rect in self._node_rects.items():
            if rect.contains(pos):
                found = nid
                break
        if found != self._hovered:
            self._hovered = found
            self.setCursor(Qt.CursorShape.PointingHandCursor if found else Qt.CursorShape.ArrowCursor)
            self.update()
