"""Hop timeline, latency graph, detail panel, and event log widgets."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QPainterPath, QFontMetrics,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QTextEdit,
)

from config.app_config import THEME as T
from engine.netmonitor.types import Hop, HopStatus, Route, RouteEvent, MonitorState


def _s(key, alpha=0xFF):
    hex_color = T.get(key, "#94a3b8").lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return QColor(r, g, b, alpha)


def _status_color(status: HopStatus) -> QColor:
    return {
        HopStatus.HEALTHY: QColor(52, 211, 153),
        HopStatus.WARNING: QColor(251, 191, 36),
        HopStatus.CRITICAL: QColor(239, 68, 68),
        HopStatus.TIMEOUT: QColor(107, 114, 128),
        HopStatus.UNKNOWN: QColor(148, 163, 184),
        HopStatus.PRIVATE: QColor(96, 165, 250),
        HopStatus.LOCAL: QColor(96, 165, 250),
    }.get(status, QColor(148, 163, 184))


def _status_emoji(status: HopStatus) -> str:
    return {
        HopStatus.HEALTHY: "\U0001f7e2",
        HopStatus.WARNING: "\U0001f7e1",
        HopStatus.CRITICAL: "\U0001f534",
        HopStatus.TIMEOUT: "\u26aa",
        HopStatus.UNKNOWN: "\u26aa",
        HopStatus.PRIVATE: "\U0001f535",
        HopStatus.LOCAL: "\U0001f535",
    }.get(status, "\u26aa")


class HopTimelineWidget(QWidget):
    hop_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._route: Optional[Route] = None
        self._selected: int = -1
        self._hops: list[Hop] = []
        self.setMinimumWidth(260)
        self.setMaximumWidth(340)

    def set_route(self, route: Optional[Route]):
        self._route = route
        self._hops = route.hops if route else []
        self.update()

    def select_hop(self, num: int):
        self._selected = num
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.fillRect(0, 0, w, h, QColor(10, 13, 24))

        if not self._hops:
            p.setPen(QColor(100, 120, 160))
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "No route data")
            p.end()
            return

        font = QFont("Segoe UI", 10)
        p.setFont(font)
        fm = QFontMetrics(font)

        row_h = 32
        x_start = 36
        line_x = 20

        for i, hop in enumerate(self._hops):
            y = 12 + i * row_h
            if y > h:
                break

            is_sel = hop.number == self._selected

            if is_sel:
                p.fillRect(QRectF(0, y - 2, w, row_h), QColor(139, 92, 246, 30))

            if i < len(self._hops) - 1:
                p.setPen(QPen(QColor(50, 60, 80), 1))
                p.drawLine(line_x, y + 10, line_x, y + row_h - 10)
            else:
                p.setPen(QPen(QColor(50, 60, 80), 1))
                p.drawLine(line_x, y + 10, line_x, y + 12)

            sc = _status_color(hop.status)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(sc))
            p.drawEllipse(QPointF(line_x, y + 10), 4, 4)

            num_text = f"{hop.number:02d}"
            p.setPen(QColor(100, 120, 160))
            p.drawText(QRectF(4, y, 30, row_h), Qt.AlignVCenter | Qt.AlignRight, num_text)

            name = hop.geo.city or hop.display_name or hop.ip or "*"
            if len(name) > 22:
                name = name[:19] + "..."

            p.setPen(QColor(220, 230, 245) if is_sel else QColor(180, 200, 230))
            p.drawText(QRectF(x_start, y, w - x_start - 60, row_h),
                       Qt.AlignVCenter, name)

            lat_text = f"{hop.latency:.0f}ms" if hop.status == HopStatus.HEALTHY else "T/O"
            p.setPen(sc)
            p.drawText(QRectF(w - 60, y, 56, row_h),
                       Qt.AlignVCenter | Qt.AlignRight, lat_text)

        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            y = int(event.position().y())
            row_h = 32
            idx = (y - 12) // row_h
            if 0 <= idx < len(self._hops):
                self.hop_clicked.emit(self._hops[idx].number)


class LatencyGraphWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._samples: list[tuple[float, float]] = []
        self._max_latency: float = 100.0
        self._min_latency: float = 0.0
        self._label: str = "Route Latency"
        self.setMinimumHeight(140)
        self.setMaximumHeight(200)

    def set_samples(self, samples: list[tuple[float, float]], label: str = ""):
        self._samples = samples
        if label:
            self._label = label
        if samples:
            valid = [s[1] for s in samples if s[1] >= 0]
            if valid:
                self._max_latency = max(valid) * 1.2
                self._min_latency = min(0, min(valid) - 5)
        self.update()

    def set_label(self, label: str):
        self._label = label
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.fillRect(0, 0, w, h, QColor(10, 13, 24))

        margin_l, margin_r, margin_t, margin_b = 50, 16, 28, 24
        gw = w - margin_l - margin_r
        gh = h - margin_t - margin_b

        font = QFont("Segoe UI", 9)
        p.setFont(font)

        p.setPen(QColor(40, 50, 70))
        for i in range(5):
            y = margin_t + int(gh * i / 4)
            p.drawLine(margin_l, y, w - margin_r, y)
            lat_val = self._max_latency - (self._max_latency - self._min_latency) * i / 4
            p.setPen(QColor(80, 95, 120))
            p.drawText(QRectF(0, y - 8, margin_l - 4, 16),
                       Qt.AlignVCenter | Qt.AlignRight, f"{lat_val:.0f}")
            p.setPen(QColor(40, 50, 70))

        p.setPen(QColor(60, 75, 100))
        p.drawText(QRectF(0, 4, w, 20), Qt.AlignCenter, self._label)

        if not self._samples or gw <= 0 or gh <= 0:
            p.setPen(QColor(80, 100, 130))
            p.drawText(QRectF(margin_l, margin_t, gw, gh),
                       Qt.AlignCenter, "Awaiting data...")
            p.end()
            return

        valid = [s for s in self._samples if s[1] >= 0]
        if not valid:
            p.end()
            return

        t_min = valid[0][0]
        t_max = valid[-1][0]
        t_range = max(t_max - t_min, 1)

        points = []
        for ts, lat in self._samples:
            if lat < 0:
                continue
            x = margin_l + (ts - t_min) / t_range * gw
            y = margin_t + gh - (lat - self._min_latency) / max(
                self._max_latency - self._min_latency, 1
            ) * gh
            points.append(QPointF(x, y))

        if len(points) >= 2:
            glow_pen = QPen(QColor(139, 92, 246, 40), 4)
            p.setPen(glow_pen)
            path = QPainterPath()
            path.moveTo(points[0])
            for pt in points[1:]:
                path.lineTo(pt)
            p.drawPath(path)

            line_pen = QPen(QColor(139, 92, 246), 2)
            p.setPen(line_pen)
            p.drawPath(path)

            fill_path = QPainterPath()
            fill_path.addPath(path)
            fill_path.lineTo(points[-1].x(), margin_t + gh)
            fill_path.lineTo(points[0].x(), margin_t + gh)
            fill_path.closeSubpath()
            grad = QColor(139, 92, 246, 30)
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(fill_path)

        for pt in points[-1:]:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(139, 92, 246)))
            p.drawEllipse(pt, 4, 4)

        if valid:
            latest = valid[-1][1]
            avg = sum(s[1] for s in valid) / len(valid)
            p.setPen(QColor(180, 200, 230))
            info = f"Current: {latest:.0f} ms  |  Avg: {avg:.0f} ms  |  Samples: {len(valid)}"
            p.drawText(QRectF(margin_l, h - margin_b + 4, gw, margin_b),
                       Qt.AlignLeft, info)

        p.end()


class HopDetailWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._hop: Optional[Hop] = None
        self.setMinimumWidth(280)
        self.setMaximumWidth(380)

    def set_hop(self, hop: Optional[Hop]):
        self._hop = hop
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.fillRect(0, 0, w, h, QColor(10, 13, 24))

        if not self._hop:
            p.setPen(QColor(100, 120, 160))
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "Select a hop")
            p.end()
            return

        hop = self._hop
        font_title = QFont("Segoe UI", 13, QFont.Weight.Bold)
        font_label = QFont("Segoe UI", 9)
        font_value = QFont("Segoe UI", 10)
        fm = QFontMetrics(font_value)

        y = 16

        p.setFont(font_title)
        sc = _status_color(hop.status)
        p.setPen(sc)
        emoji = _status_emoji(hop.status)
        title = f"{emoji} Hop {hop.number}"
        p.drawText(QRectF(12, y, w - 24, 24), Qt.AlignLeft, title)
        y += 30

        p.setPen(QColor(50, 60, 80))
        p.drawLine(12, y, w - 12, y)
        y += 10

        def draw_field(label, value, y_pos):
            p.setFont(font_label)
            p.setPen(QColor(100, 120, 160))
            p.drawText(QRectF(12, y_pos, w - 24, 16), Qt.AlignLeft, label)
            y_pos += 16
            p.setFont(font_value)
            p.setPen(QColor(220, 230, 245))
            p.drawText(QRectF(12, y_pos, w - 24, 18), Qt.AlignLeft, str(value))
            return y_pos + 22

        y = draw_field("IP ADDRESS", hop.ip or "Unknown", y)
        if hop.hostname:
            y = draw_field("HOSTNAME", hop.hostname, y)
        if hop.network.asn:
            y = draw_field("ASN / ORG", f"AS{hop.network.asn} — {hop.network.as_org}", y)
        if hop.network.isp:
            y = draw_field("ISP / NETWORK", hop.network.isp, y)
        if hop.location_str:
            y = draw_field("LOCATION", hop.location_str, y)

        p.setPen(QColor(50, 60, 80))
        p.drawLine(12, y, w - 12, y)
        y += 10

        y = draw_field("LATENCY", f"{hop.latency:.1f} ms", y)
        y = draw_field("JITTER", f"{hop.jitter:.1f} ms", y)
        y = draw_field("PACKET LOSS", f"{hop.packet_loss:.0f}%", y)
        y = draw_field("MIN / MAX", f"{hop.probes.min_latency:.0f} / {hop.probes.max_latency:.0f} ms", y)
        y = draw_field("PROBES", f"{hop.probes.sent} sent, {hop.probes.received} received", y)

        p.setPen(QColor(50, 60, 80))
        p.drawLine(12, y, w - 12, y)
        y += 10

        role_labels = {
            "local": "Local Infrastructure",
            "gateway": "Default Gateway",
            "isp_access": "ISP Access Network",
            "isp_core": "ISP Core Network",
            "transit": "Transit / Peering",
            "peering": "Peering Point",
            "cdn": "CDN / Edge Network",
            "edge": "Edge Server",
            "destination": "Destination",
            "unknown": "Unknown",
        }
        y = draw_field("ROLE", role_labels.get(hop.role.value if hasattr(hop.role, 'value') else str(hop.role), "Unknown"), y)

        status_labels = {
            HopStatus.HEALTHY: "Healthy",
            HopStatus.WARNING: "Warning",
            HopStatus.CRITICAL: "Critical",
            HopStatus.TIMEOUT: "No Response",
            HopStatus.UNKNOWN: "Unknown",
            HopStatus.PRIVATE: "Private/Local",
            HopStatus.LOCAL: "Private/Local",
        }
        y = draw_field("STATUS", status_labels.get(hop.status, "Unknown"), y)

        p.end()


class EventLogWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._events: list[RouteEvent] = []
        self.setMinimumHeight(120)
        self.setMaximumHeight(180)

    def set_events(self, events: list[RouteEvent]):
        self._events = events
        self.update()

    def add_event(self, event: RouteEvent):
        self._events.append(event)
        if len(self._events) > 200:
            self._events = self._events[-200:]
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.fillRect(0, 0, w, h, QColor(10, 13, 24))

        p.setPen(QColor(100, 120, 160))
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        p.drawText(QRectF(8, 4, w - 16, 16), Qt.AlignLeft, "EVENT LOG")
        p.setPen(QColor(50, 60, 80))
        p.drawLine(8, 20, w - 8, 20)

        font = QFont("Consolas", 8)
        p.setFont(font)
        fm = QFontMetrics(font)
        row_h = fm.height() + 2
        y_start = 24
        max_rows = max(1, (h - y_start) // row_h)

        visible = self._events[-max_rows:]
        for i, evt in enumerate(visible):
            y = y_start + i * row_h
            ts = datetime.fromtimestamp(evt.timestamp).strftime("%H:%M:%S")

            level_colors = {
                "info": QColor(100, 140, 200),
                "warning": QColor(251, 191, 36),
                "error": QColor(239, 68, 68),
            }
            color = level_colors.get(evt.level, QColor(148, 163, 184))

            p.setPen(QColor(70, 85, 110))
            p.drawText(QRectF(8, y, 70, row_h), Qt.AlignVCenter, ts)

            p.setPen(color)
            msg = evt.message
            if len(msg) > 80:
                msg = msg[:77] + "..."
            p.drawText(QRectF(82, y, w - 90, row_h), Qt.AlignVCenter, msg)

        if not self._events:
            p.setPen(QColor(70, 85, 110))
            p.drawText(QRectF(8, y_start, w - 16, row_h),
                       Qt.AlignVCenter, "No events yet")

        p.end()
