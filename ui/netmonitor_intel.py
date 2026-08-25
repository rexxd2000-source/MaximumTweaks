"""Network intelligence panels — AS topology, BGP info, connections."""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QPainterPath, QFontMetrics,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
)

from config.app_config import THEME as T
from engine.netmonitor.bgp import NetworkIntel, BgpPath, AsnRelationship
from engine.netmonitor.connections import ActiveConnection
from ui.netmonitor_globe import NetworkNode, NetworkRoute


def _s(key, alpha=0xFF):
    hex_color = T.get(key, "#94a3b8").lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return QColor(r, g, b, alpha)


class NetworkPathWidget(QWidget):
    node_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._route: Optional[NetworkRoute] = None
        self._selected: str = ""
        self.setMinimumHeight(200)

    def set_route(self, route: Optional[NetworkRoute]):
        self._route = route
        self.update()

    def select_node(self, node_id: str):
        self._selected = node_id
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(QPen(QColor(30, 38, 55), 1))
        p.setBrush(QBrush(QColor(12, 15, 26)))
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.setPen(QColor(140, 155, 190))
        p.drawText(QRectF(14, 6, 200, 18), Qt.AlignVCenter | Qt.AlignLeft, "NETWORK PATH")

        if not self._route or not self._route.nodes:
            p.setPen(QColor(50, 65, 90))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(14, 28, w - 28, h - 32), Qt.AlignCenter,
                       "Select a connection to visualize its path")
            p.end()
            return

        y = 28
        lx = 28
        nodes = self._route.nodes

        for i, node in enumerate(nodes):
            is_sel = node.id == self._selected

            if is_sel:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(139, 92, 246, 18)))
                p.drawRoundedRect(QRectF(6, y, w - 12, 38), 4, 4)

            color = QColor(node.color)

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(lx, y + 16), 5, 5)

            if node.node_type == "user":
                p.setPen(QPen(QColor(8, 10, 18), 1))
                p.setBrush(QBrush(QColor(12, 15, 26)))
                p.drawEllipse(QPointF(lx, y + 16), 2, 2)

            if i < len(nodes) - 1:
                p.setPen(QPen(QColor(35, 48, 72), 1))
                p.drawLine(lx, y + 22, lx, y + 38)

            p.setFont(QFont("Segoe UI", 7))
            p.setPen(QColor(100, 115, 145))
            p.drawText(QRectF(lx + 12, y, 80, 14), Qt.AlignVCenter | Qt.AlignLeft,
                       node.role_label)

            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold if is_sel else QFont.Weight.Normal))
            p.setPen(QColor(240, 245, 255) if is_sel else QColor(200, 215, 240))
            label = node.label or node.ip or "Unknown"
            if len(label) > 28:
                label = label[:25] + "..."
            p.drawText(QRectF(lx + 12, y + 14, w - lx - 80, 18), Qt.AlignVCenter | Qt.AlignLeft, label)

            if node.asn:
                p.setFont(QFont("Consolas", 7))
                p.setPen(QColor(139, 92, 246))
                p.drawText(QRectF(lx + 12, y + 28, w - lx - 80, 10), Qt.AlignVCenter | Qt.AlignLeft,
                           f"AS{node.asn} \u00b7 {node.confidence}")

            conf_colors = {
                "measured": QColor(52, 211, 153),
                "observed": QColor(139, 92, 246),
                "approximate": QColor(251, 191, 36),
                "unknown": QColor(100, 115, 145),
            }
            cc = conf_colors.get(node.confidence, QColor(100, 115, 145))
            p.setFont(QFont("Segoe UI", 7))
            p.setPen(cc)
            p.drawText(QRectF(w - 72, y + 14, 62, 14), Qt.AlignVCenter | Qt.AlignRight,
                       node.confidence.upper())

            y += 42

        if self._route.explanation:
            p.setFont(QFont("Segoe UI", 8))
            p.setPen(QColor(100, 120, 155))
            exp = self._route.explanation[:100]
            p.drawText(QRectF(14, h - 18, w - 28, 14), Qt.AlignVCenter, exp)

        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._route:
            y = 28
            for node in self._route.nodes:
                if y <= int(event.position().y()) <= y + 38:
                    self.node_clicked.emit(node.id)
                    return
                y += 42


class BgpInfoWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._intel: Optional[NetworkIntel] = None
        self.setFixedHeight(200)

    def set_intel(self, intel: Optional[NetworkIntel]):
        self._intel = intel
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(QPen(QColor(30, 38, 55), 1))
        p.setBrush(QBrush(QColor(12, 15, 26)))
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.setPen(QColor(140, 155, 190))
        p.drawText(QRectF(14, 6, 200, 18), Qt.AlignVCenter | Qt.AlignLeft, "BGP & ASN INFORMATION")

        if not self._intel or not self._intel.asn.asn:
            p.setPen(QColor(50, 65, 90))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(14, 28, w - 28, h - 32), Qt.AlignCenter,
                       "Select a destination to view BGP data")
            p.end()
            return

        intel = self._intel
        y = 28

        def field(label, value, yy):
            p.setFont(QFont("Segoe UI", 8))
            p.setPen(QColor(100, 115, 145))
            p.drawText(QRectF(14, yy, 100, 13), Qt.AlignVCenter | Qt.AlignLeft, label)
            p.setFont(QFont("Segoe UI", 9))
            p.setPen(QColor(210, 225, 245))
            val = str(value) if value else "Unknown"
            if len(val) > 40:
                val = val[:37] + "..."
            p.drawText(QRectF(118, yy, w - 132, 13), Qt.AlignVCenter | Qt.AlignLeft, val)
            return yy + 16

        y = field("IP ADDRESS", intel.ip, y)
        if intel.hostname:
            y = field("HOSTNAME", intel.hostname, y)
        y = field("ASN", f"AS{intel.asn.asn}" if intel.asn.asn else "Unknown", y)
        y = field("NETWORK", intel.asn.name or "Unknown", y)
        if intel.asn.isp:
            y = field("ISP", intel.asn.isp, y)
        y = field("COUNTRY", intel.geo_country or intel.asn.country or "Unknown", y)

        if intel.asn.asn:
            p.setPen(QColor(35, 48, 72))
            p.drawLine(14, y, w - 14, y)
            y += 6

            y = field("PREFIXES V4", str(intel.asn.prefixes_v4) if intel.asn.prefixes_v4 else "Unknown", y)
            y = field("PREFIXES V6", str(intel.asn.prefixes_v6) if intel.asn.prefixes_v6 else "Unknown", y)

            if intel.upstreams:
                y = field("UPSTREAMS", f"{len(intel.upstreams)} observed", y)
                for u in intel.upstreams[:3]:
                    y = field("", f"  AS{u.asn} \u2014 {u.name}", y)

            if intel.bgp_path.as_path:
                p.setPen(QColor(35, 48, 72))
                p.drawLine(14, y, w - 14, y)
                y += 6
                p.setFont(QFont("Segoe UI", 8))
                p.setPen(QColor(139, 92, 246))
                p.drawText(QRectF(14, y, 100, 13), Qt.AlignVCenter | Qt.AlignLeft, "AS PATH")
                path_str = intel.bgp_path.as_path_str
                if len(path_str) > 50:
                    path_str = path_str[:47] + "..."
                p.setFont(QFont("Consolas", 8))
                p.setPen(QColor(200, 190, 240))
                p.drawText(QRectF(118, y, w - 132, 13), Qt.AlignVCenter | Qt.AlignLeft, path_str)
                y += 14

                p.setFont(QFont("Segoe UI", 7))
                p.setPen(QColor(100, 115, 145))
                p.drawText(QRectF(118, y, w - 132, 13), Qt.AlignVCenter | Qt.AlignLeft,
                           "BGP observed path \u2014 not exact packet route")
                y += 14

        if intel.data_sources:
            p.setFont(QFont("Segoe UI", 7))
            p.setPen(QColor(60, 75, 100))
            srcs = ", ".join(intel.data_sources[:4])
            p.drawText(QRectF(14, h - 14, w - 28, 12), Qt.AlignVCenter,
                       f"Sources: {srcs}")

        p.end()


class ConnectionListWidget(QWidget):
    connection_selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connections: list[ActiveConnection] = []
        self._selected_ip: str = ""
        self._scroll_y: float = 0
        self.setMinimumHeight(200)

    def set_connections(self, connections: list[ActiveConnection]):
        self._connections = connections
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(QPen(QColor(30, 38, 55), 1))
        p.setBrush(QBrush(QColor(12, 15, 26)))
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.setPen(QColor(140, 155, 190))
        p.drawText(QRectF(14, 6, 200, 18), Qt.AlignVCenter | Qt.AlignLeft, "ACTIVE CONNECTIONS")

        count_label = f"{len(self._connections)} detected"
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QColor(80, 95, 125))
        p.drawText(QRectF(w - 100, 6, 90, 18), Qt.AlignVCenter | Qt.AlignRight, count_label)

        if not self._connections:
            p.setPen(QColor(50, 65, 90))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(14, 28, w - 28, h - 32), Qt.AlignCenter,
                       "Scanning connections...")
            p.end()
            return

        y = 26
        rh = 32

        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QColor(80, 95, 125))
        p.drawText(QRectF(14, y, 80, 12), Qt.AlignVCenter, "SERVICE")
        p.drawText(QRectF(100, y, 100, 12), Qt.AlignVCenter, "NETWORK")
        p.drawText(QRectF(w - 140, y, 60, 12), Qt.AlignVCenter | Qt.AlignRight, "ASN")
        p.drawText(QRectF(w - 70, y, 60, 12), Qt.AlignVCenter | Qt.AlignRight, "COUNTRY")
        y += 14

        max_rows = max(1, (h - y) // rh)
        visible = self._connections[:max_rows]

        for i, conn in enumerate(visible):
            is_sel = conn.remote_ip == self._selected_ip

            if is_sel:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(139, 92, 246, 15)))
                p.drawRoundedRect(QRectF(6, y, w - 12, rh), 3, 3)

            cat_colors = {
                "gaming": QColor(139, 92, 246),
                "communication": QColor(96, 165, 250),
                "browser": QColor(52, 211, 153),
                "streaming": QColor(251, 191, 36),
                "development": QColor(239, 68, 68),
                "other": QColor(100, 115, 145),
            }
            cc = cat_colors.get(conn.app_category, QColor(100, 115, 145))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(cc))
            p.drawEllipse(QPointF(20, y + rh / 2), 3, 3)

            p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold if is_sel else QFont.Weight.Normal))
            p.setPen(QColor(230, 240, 255) if is_sel else QColor(190, 210, 240))
            svc = conn.display_name
            if len(svc) > 14:
                svc = svc[:11] + "..."
            p.drawText(QRectF(30, y + 2, 70, rh - 4), Qt.AlignVCenter, svc)

            if conn.intel and conn.intel.asn.asn:
                net_name = conn.intel.asn.name
                if len(net_name) > 16:
                    net_name = net_name[:13] + "..."
                p.setFont(QFont("Segoe UI", 8))
                p.setPen(QColor(170, 190, 220))
                p.drawText(QRectF(100, y + 2, 100, rh - 4), Qt.AlignVCenter, net_name)

                p.setFont(QFont("Consolas", 8))
                p.setPen(QColor(139, 92, 246))
                p.drawText(QRectF(w - 140, y + 2, 60, rh - 4), Qt.AlignVCenter | Qt.AlignRight,
                           f"AS{conn.intel.asn.asn}")

                p.setFont(QFont("Segoe UI", 8))
                p.setPen(QColor(150, 170, 200))
                country = conn.intel.geo_country or conn.intel.asn.country or "?"
                p.drawText(QRectF(w - 70, y + 2, 60, rh - 4), Qt.AlignVCenter | Qt.AlignRight, country)
            else:
                p.setFont(QFont("Segoe UI", 8))
                p.setPen(QColor(80, 95, 125))
                p.drawText(QRectF(100, y + 2, 100, rh - 4), Qt.AlignVCenter, "resolving...")

            p.setPen(QColor(30, 38, 55))
            p.drawLine(14, y + rh, w - 14, y + rh)

            y += rh

        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            y = 40
            rh = 32
            for conn in self._connections:
                if y <= int(event.position().y()) <= y + rh:
                    self._selected_ip = conn.remote_ip
                    self.connection_selected.emit(conn)
                    self.update()
                    return
                y += rh
                if y > self.height():
                    break


class RouteMetricsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._latency = 0.0
        self._jitter = 0.0
        self._loss = 0.0
        self._hops = 0
        self._as_hops = 0
        self._confidence = ""
        self._data_source = ""
        self.setFixedHeight(130)

    def set_metrics(self, latency=0.0, jitter=0.0, loss=0.0, hops=0,
                    as_hops=0, confidence="", data_source=""):
        self._latency = latency
        self._jitter = jitter
        self._loss = loss
        self._hops = hops
        self._as_hops = as_hops
        self._confidence = confidence
        self._data_source = data_source
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(QPen(QColor(30, 38, 55), 1))
        p.setBrush(QBrush(QColor(12, 15, 26)))
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.setPen(QColor(140, 155, 190))
        p.drawText(QRectF(14, 6, 200, 18), Qt.AlignVCenter | Qt.AlignLeft, "ROUTE METRICS")

        if self._latency <= 0:
            p.setPen(QColor(50, 65, 90))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(14, 28, w - 28, h - 32), Qt.AlignCenter, "No metrics available")
            p.end()
            return

        y = 28
        col_w = w // 3

        def metric_box(label, value, color, x, yy):
            p.setFont(QFont("Segoe UI", 8))
            p.setPen(QColor(100, 115, 145))
            p.drawText(QRectF(x, yy, col_w - 10, 13), Qt.AlignVCenter, label)
            p.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
            p.setPen(color)
            p.drawText(QRectF(x, yy + 14, col_w - 10, 20), Qt.AlignVCenter, value)
            return yy

        lc = QColor(52, 211, 153) if self._latency < 100 else (QColor(251, 191, 36) if self._latency < 200 else QColor(239, 68, 68))
        metric_box("LATENCY", f"{self._latency:.0f} ms", lc, 14, y)
        metric_box("JITTER", f"{self._jitter:.1f} ms", QColor(160, 180, 220), 14 + col_w, y)
        metric_box("LOSS", f"{self._loss:.0f}%", QColor(52, 211, 153) if self._loss == 0 else QColor(239, 68, 68), 14 + col_w * 2, y)

        y += 40
        metric_box("HOPS", str(self._hops), QColor(160, 180, 220), 14, y)
        metric_box("AS HOPS", str(self._as_hops), QColor(139, 92, 246), 14 + col_w, y)

        conf = self._confidence or "unknown"
        conf_colors = {
            "measured": QColor(52, 211, 153),
            "observed": QColor(139, 92, 246),
            "approximate": QColor(251, 191, 36),
            "unknown": QColor(100, 115, 145),
        }
        metric_box("CONFIDENCE", conf.upper(), conf_colors.get(conf, QColor(100, 115, 145)), 14 + col_w * 2, y)

        if self._data_source:
            p.setFont(QFont("Segoe UI", 7))
            p.setPen(QColor(60, 75, 100))
            p.drawText(QRectF(14, h - 14, w - 28, 12), Qt.AlignVCenter,
                       f"Data source: {self._data_source}")

        p.end()
