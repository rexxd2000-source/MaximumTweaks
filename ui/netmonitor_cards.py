"""Destination cards, route quality, intelligence, and hop timeline widgets."""
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
from engine.netmonitor.types import Hop, HopStatus, Route


def _s(key, alpha=0xFF):
    hex_color = T.get(key, "#94a3b8").lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return QColor(r, g, b, alpha)


class DestinationCard(QWidget):
    clicked = Signal(str)

    def __init__(self, name="", category="", latency=0.0, loss=0.0,
                 jitter=0.0, hops=0, region="", status="pending",
                 installed=False, parent=None):
        super().__init__(parent)
        self._name = name
        self._category = category
        self._latency = latency
        self._loss = loss
        self._jitter = jitter
        self._hops = hops
        self._region = region
        self._status = status
        self._installed = installed
        self._selected = False
        self.setFixedHeight(64)
        self.setMinimumWidth(180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def update_data(self, latency=0.0, loss=0.0, jitter=0.0, hops=0,
                    region="", status="pending"):
        self._latency = latency
        self._loss = loss
        self._jitter = jitter
        self._hops = hops
        if region:
            self._region = region
        self._status = status
        self.update()

    def set_selected(self, s: bool):
        self._selected = s
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if self._selected:
            bg = QColor(22, 18, 42)
            border_c = QColor(139, 92, 246, 180)
        else:
            bg = QColor(18, 21, 32)
            border_c = QColor(35, 30, 55, 180)
        p.setPen(QPen(border_c, 1))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)

        cat_colors = {"gaming": QColor(139, 92, 246), "services": QColor(96, 165, 250), "cdn": QColor(52, 211, 153)}
        cc = cat_colors.get(self._category, QColor(120, 135, 165))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(cc))
        p.drawRoundedRect(QRectF(8, 10, 3, h - 20), 1, 1)

        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.setPen(QColor(235, 240, 250))
        nm = self._name if len(self._name) <= 18 else self._name[:15] + "..."
        p.drawText(QRectF(18, 6, 140, 18), Qt.AlignVCenter | Qt.AlignLeft, nm)

        if self._region:
            p.setFont(QFont("Segoe UI", 8))
            p.setPen(QColor(85, 100, 130))
            p.drawText(QRectF(18, 24, 140, 14), Qt.AlignVCenter | Qt.AlignLeft, self._region)

        if self._installed:
            p.setFont(QFont("Segoe UI", 7))
            p.setPen(QColor(52, 211, 153))
            p.drawText(QRectF(18, 38, 60, 12), Qt.AlignVCenter | Qt.AlignLeft, "INSTALLED")

        if self._latency > 0:
            p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            lc = QColor(52, 211, 153) if self._latency < 100 else (QColor(251, 191, 36) if self._latency < 200 else QColor(239, 68, 68))
            p.setPen(lc)
            p.drawText(QRectF(w - 88, 6, 80, 20), Qt.AlignVCenter | Qt.AlignRight, f"{self._latency:.0f} ms")

            p.setFont(QFont("Segoe UI", 8))
            p.setPen(QColor(100, 115, 145))
            p.drawText(QRectF(w - 88, 26, 80, 14), Qt.AlignVCenter | Qt.AlignRight,
                       f"{self._hops} hops \u00b7 {self._loss:.0f}% loss")

            sc = {"healthy": QColor(52, 211, 153), "degraded": QColor(251, 191, 36),
                  "critical": QColor(239, 68, 68)}.get(self._status, QColor(80, 95, 120))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(sc))
            p.drawEllipse(QPointF(w - 12, h / 2), 4, 4)
        else:
            p.setFont(QFont("Segoe UI", 9))
            p.setPen(QColor(60, 75, 100))
            p.drawText(QRectF(w - 88, 6, 80, 20), Qt.AlignVCenter | Qt.AlignRight, "\u2014")

        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._name)


class DestinationCardBar(QWidget):
    destination_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80)
        self._cards: list[DestinationCard] = []
        self._selected = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                                   "QScrollArea>QWidget{background:transparent;}")
        outer.addWidget(self._scroll)

        self._container = QWidget()
        self._flow = QHBoxLayout(self._container)
        self._flow.setContentsMargins(0, 8, 0, 8)
        self._flow.setSpacing(8)
        self._scroll.setWidget(self._container)

    def set_destinations(self, dests: list[dict]):
        for c in self._cards:
            c.setParent(None)
            c.deleteLater()
        self._cards.clear()
        for d in dests:
            card = DestinationCard(
                name=d.get("name", ""), category=d.get("category", ""),
                latency=d.get("latency", 0), loss=d.get("loss", 0),
                jitter=d.get("jitter", 0), hops=d.get("hops", 0),
                region=d.get("region", ""), status=d.get("status", "pending"),
                installed=d.get("installed", False),
            )
            card.clicked.connect(self._on_click)
            self._cards.append(card)
            self._flow.addWidget(card)
        self._flow.addStretch()

    def _on_click(self, name: str):
        self._selected = name
        for c in self._cards:
            c.set_selected(c._name == name)
        self.destination_selected.emit(name)

    def update_card(self, name: str, latency=0.0, loss=0.0, jitter=0.0,
                    hops=0, region="", status="pending"):
        for c in self._cards:
            if c._name == name:
                c.update_data(latency=latency, loss=loss, jitter=jitter,
                              hops=hops, region=region, status=status)
                break


class RouteQualityWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._score = 0
        self._health = "unknown"
        self._factors: dict = {}
        self._explanation = ""
        self.setFixedHeight(160)

    def set_quality(self, score=0, health="unknown", factors=None, explanation=""):
        self._score = score
        self._health = health
        self._factors = factors or {}
        self._explanation = explanation
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(QPen(QColor(35, 30, 55), 1))
        p.setBrush(QBrush(QColor(14, 17, 28)))
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.setPen(QColor(145, 160, 195))
        p.drawText(QRectF(14, 8, 200, 18), Qt.AlignVCenter | Qt.AlignLeft, "ROUTE QUALITY")

        if self._score <= 0:
            p.setPen(QColor(60, 75, 100))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(14, 30, w - 28, h - 36), Qt.AlignCenter, "Awaiting route data...")
            p.end()
            return

        cx, cy, r = w - 65, 48, 32

        bg_pen = QPen(QColor(30, 38, 55), 5)
        p.setPen(bg_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        hc = {"good": QColor(52, 211, 153), "degraded": QColor(251, 191, 36),
              "critical": QColor(239, 68, 68)}.get(self._health, QColor(120, 135, 165))
        score_pen = QPen(hc, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(score_pen)
        span = int(self._score / 100 * 360 * 16)
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 90 * 16, -span)

        p.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        p.setPen(hc)
        p.drawText(QRectF(cx - r, cy - 12, r * 2, 24), Qt.AlignCenter, str(self._score))

        factor_order = [("latency", "Latency"), ("jitter", "Stability"),
                        ("packet_loss", "Packet Loss"), ("timeouts", "Timeouts"),
                        ("hop_count", "Hop Count")]
        y = 32
        bar_w = 70
        for key, label in factor_order:
            if key not in self._factors:
                continue
            fs = self._factors[key].get("score", 50)

            p.setFont(QFont("Segoe UI", 8))
            p.setPen(QColor(90, 105, 135))
            p.drawText(QRectF(14, y, 80, 14), Qt.AlignVCenter | Qt.AlignLeft, label)

            bx = 98
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(22, 28, 42)))
            p.drawRoundedRect(QRectF(bx, y + 2, bar_w, 8), 3, 3)

            bc = QColor(52, 211, 153) if fs >= 75 else (QColor(251, 191, 36) if fs >= 45 else QColor(239, 68, 68))
            p.setBrush(QBrush(bc))
            p.drawRoundedRect(QRectF(bx, y + 2, max(2, bar_w * fs / 100), 8), 3, 3)

            p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            p.setPen(bc)
            p.drawText(QRectF(bx + bar_w + 4, y, 24, 12), Qt.AlignVCenter, f"{fs}")
            y += 17

        if self._explanation:
            p.setFont(QFont("Segoe UI", 7))
            p.setPen(QColor(100, 115, 145))
            exp = self._explanation[:110] + "..." if len(self._explanation) > 110 else self._explanation
            p.drawText(QRectF(14, h - 18, w - 28, 14), Qt.AlignVCenter, exp)

        p.end()


class RouteIntelligenceWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._spikes: list[dict] = []
        self._loss_analysis: dict = {}
        self._summary = ""
        self._latency = 0.0
        self.setFixedHeight(140)

    def set_intelligence(self, spikes=None, loss_analysis=None, route_summary="",
                         latency=0.0, **_kw):
        self._spikes = spikes or []
        self._loss_analysis = loss_analysis or {}
        self._summary = route_summary
        self._latency = latency
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(QPen(QColor(35, 30, 55), 1))
        p.setBrush(QBrush(QColor(14, 17, 28)))
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.setPen(QColor(145, 160, 195))
        p.drawText(QRectF(14, 8, 200, 18), Qt.AlignVCenter | Qt.AlignLeft, "ROUTE INTELLIGENCE")

        if self._latency <= 0:
            p.setPen(QColor(60, 75, 100))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(14, 30, w - 28, h - 36), Qt.AlignCenter, "Analyzing route...")
            p.end()
            return

        y = 30

        if self._spikes:
            worst = max(self._spikes, key=lambda s: s.get("jump", 0))
            jump = worst.get("jump", 0)
            hop = worst.get("hop", 0)
            sev = worst.get("severity", "moderate")

            p.setPen(QPen(QColor(251, 191, 36, 120), 1))
            p.setBrush(QBrush(QColor(251, 191, 36, 12)))
            p.drawRoundedRect(QRectF(10, y, w - 20, 32), 5, 5)

            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            p.setPen(QColor(251, 191, 36))
            p.drawText(QRectF(18, y + 1, w - 36, 15), Qt.AlignVCenter,
                       f"+{jump:.0f} ms added at Hop {hop}")

            p.setFont(QFont("Segoe UI", 8))
            p.setPen(QColor(170, 160, 120))
            lbl = "Significant" if sev == "high" else "Moderate"
            p.drawText(QRectF(18, y + 16, w - 36, 13), Qt.AlignVCenter,
                       f"{lbl} latency increase \u2014 likely international transit")
            y += 38
        else:
            p.setPen(QPen(QColor(52, 211, 153, 100), 1))
            p.setBrush(QBrush(QColor(52, 211, 153, 10)))
            p.drawRoundedRect(QRectF(10, y, w - 20, 24), 5, 5)
            p.setFont(QFont("Segoe UI", 9))
            p.setPen(QColor(52, 211, 153))
            p.drawText(QRectF(18, y + 1, w - 36, 22), Qt.AlignVCenter,
                       "No significant latency spikes detected")
            y += 30

        diag = self._loss_analysis.get("diagnosis", "")
        if diag and diag != "no_loss":
            if diag == "rate_limiting":
                txt = "Intermediate hops show loss but dest does not \u2014 likely ICMP rate-limiting, not real loss."
            elif diag == "real_loss":
                start = self._loss_analysis.get("start_hop", "?")
                txt = f"Real packet loss begins at Hop {start} and persists to destination."
            else:
                txt = "Intermittent loss \u2014 may be congestion or ICMP deprioritization."

            p.setPen(QPen(QColor(139, 92, 246, 100), 1))
            p.setBrush(QBrush(QColor(139, 92, 246, 10)))
            p.drawRoundedRect(QRectF(10, y, w - 20, 32), 5, 5)
            p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            p.setPen(QColor(139, 92, 246))
            p.drawText(QRectF(18, y + 1, w - 36, 13), Qt.AlignVCenter, "PACKET LOSS ANALYSIS")
            p.setFont(QFont("Segoe UI", 8))
            p.setPen(QColor(140, 130, 180))
            if len(txt) > 80:
                txt = txt[:77] + "..."
            p.drawText(QRectF(18, y + 15, w - 36, 13), Qt.AlignVCenter, txt)
            y += 38

        if self._summary:
            p.setFont(QFont("Segoe UI", 7))
            p.setPen(QColor(70, 85, 110))
            s = self._summary[:100] + "..." if len(self._summary) > 100 else self._summary
            p.drawText(QRectF(14, h - 16, w - 28, 12), Qt.AlignVCenter, s)

        p.end()


class HopTimelineWidget(QWidget):
    hop_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._route: Optional[Route] = None
        self._selected: int = -1
        self._hops: list[Hop] = []
        self.setMinimumHeight(160)

    def set_route(self, route: Optional[Route]):
        self._route = route
        self._hops = route.hops if route else []
        self.update()

    def select_hop(self, n: int):
        self._selected = n
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(QPen(QColor(35, 30, 55), 1))
        p.setBrush(QBrush(QColor(14, 17, 28)))
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.setPen(QColor(145, 160, 195))
        p.drawText(QRectF(14, 6, 200, 18), Qt.AlignVCenter | Qt.AlignLeft, "HOP TIMELINE")

        if not self._hops:
            p.setPen(QColor(60, 75, 100))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(14, 28, w - 28, h - 32), Qt.AlignCenter, "No route data")
            p.end()
            return

        y0 = 26
        rh = 22
        lx = 24
        max_vis = max(1, (h - y0) // rh)
        vis = self._hops[:max_vis]

        for i, hop in enumerate(vis):
            y = y0 + i * rh
            is_sel = hop.number == self._selected

            if is_sel:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(139, 92, 246, 20)))
                p.drawRoundedRect(QRectF(4, y, w - 8, rh), 3, 3)

            if i < len(vis) - 1:
                p.setPen(QPen(QColor(30, 40, 60), 1))
                p.drawLine(lx, y + 7, lx, y + rh - 3)

            sc = self._color(hop.status)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(sc))
            p.drawEllipse(QPointF(lx, y + 7), 3, 3)

            p.setFont(QFont("Consolas", 8))
            p.setPen(QColor(60, 75, 100))
            p.drawText(QRectF(6, y, 14, rh), Qt.AlignVCenter | Qt.AlignRight, f"{hop.number:02d}")

            nm = hop.geo.city or hop.display_name or hop.ip or "*"
            if len(nm) > 20:
                nm = nm[:17] + "..."
            p.setFont(QFont("Segoe UI", 8))
            p.setPen(QColor(210, 220, 240) if is_sel else QColor(150, 170, 200))
            p.drawText(QRectF(34, y, w - 110, rh), Qt.AlignVCenter, nm)

            lt = f"{hop.latency:.0f}ms" if hop.status == HopStatus.HEALTHY else "T/O"
            p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            p.setPen(sc)
            p.drawText(QRectF(w - 72, y, 64, rh), Qt.AlignVCenter | Qt.AlignRight, lt)

            if i > 0 and vis[i - 1].status == HopStatus.HEALTHY and hop.status == HopStatus.HEALTHY:
                diff = hop.latency - vis[i - 1].latency
                if diff > 25:
                    p.setFont(QFont("Consolas", 7))
                    p.setPen(QColor(251, 191, 36))
                    p.drawText(QRectF(w - 72, y, 56, rh),
                               Qt.AlignVCenter | Qt.AlignRight, f"+{diff:.0f}")

        p.end()

    def _color(self, s: HopStatus) -> QColor:
        return {
            HopStatus.HEALTHY: QColor(52, 211, 153),
            HopStatus.WARNING: QColor(251, 191, 36),
            HopStatus.CRITICAL: QColor(239, 68, 68),
            HopStatus.TIMEOUT: QColor(80, 95, 120),
            HopStatus.UNKNOWN: QColor(120, 135, 165),
            HopStatus.PRIVATE: QColor(96, 165, 250),
            HopStatus.LOCAL: QColor(96, 165, 250),
        }.get(s, QColor(120, 135, 165))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            idx = (int(event.position().y()) - 26) // 22
            if 0 <= idx < len(self._hops):
                self.hop_clicked.emit(self._hops[idx].number)


class LatencyGraphWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._samples: list[tuple[float, float]] = []
        self._max_lat = 100.0
        self._min_lat = 0.0
        self._label = "Route Latency"
        self.setMinimumHeight(120)
        self.setMaximumHeight(170)

    def set_samples(self, samples, label=""):
        self._samples = samples
        if label:
            self._label = label
        if samples:
            valid = [s[1] for s in samples if s[1] >= 0]
            if valid:
                self._max_lat = max(valid) * 1.2
                self._min_lat = min(0, min(valid) - 5)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(QPen(QColor(35, 30, 55), 1))
        p.setBrush(QBrush(QColor(14, 17, 28)))
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        ml, mr, mt, mb = 40, 10, 24, 20
        gw, gh = w - ml - mr, h - mt - mb

        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        p.setPen(QColor(145, 160, 195))
        p.drawText(QRectF(14, 3, 200, 18), Qt.AlignVCenter | Qt.AlignLeft, self._label)

        font = QFont("Segoe UI", 7)
        p.setFont(font)
        for i in range(5):
            y = mt + int(gh * i / 4)
            p.setPen(QColor(28, 36, 52))
            p.drawLine(ml, y, w - mr, y)
            val = self._max_lat - (self._max_lat - self._min_lat) * i / 4
            p.setPen(QColor(55, 70, 95))
            p.drawText(QRectF(0, y - 6, ml - 4, 12), Qt.AlignVCenter | Qt.AlignRight, f"{val:.0f}")

        if not self._samples or gw <= 0 or gh <= 0:
            p.setPen(QColor(50, 65, 90))
            p.drawText(QRectF(ml, mt, gw, gh), Qt.AlignCenter, "Awaiting data...")
            p.end()
            return

        valid = [s for s in self._samples if s[1] >= 0]
        if not valid:
            p.end()
            return

        t_min, t_max = valid[0][0], valid[-1][0]
        t_range = max(t_max - t_min, 1)

        pts = []
        for ts, lat in self._samples:
            if lat < 0:
                continue
            x = ml + (ts - t_min) / t_range * gw
            y = mt + gh - (lat - self._min_lat) / max(self._max_lat - self._min_lat, 1) * gh
            pts.append(QPointF(x, y))

        if len(pts) >= 2:
            path = QPainterPath()
            path.moveTo(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)

            p.setPen(QPen(QColor(139, 92, 246, 25), 4))
            p.drawPath(path)
            p.setPen(QPen(QColor(139, 92, 246, 180), 1.5))
            p.drawPath(path)

            fill = QPainterPath(path)
            fill.lineTo(pts[-1].x(), mt + gh)
            fill.lineTo(pts[0].x(), mt + gh)
            fill.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(139, 92, 246, 15)))
            p.drawPath(fill)

        if pts:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(139, 92, 246)))
            p.drawEllipse(pts[-1], 3, 3)

        if valid:
            latest = valid[-1][1]
            avg = sum(s[1] for s in valid) / len(valid)
            p.setFont(QFont("Segoe UI", 7))
            p.setPen(QColor(80, 95, 125))
            p.drawText(QRectF(ml, h - mb + 2, gw, mb - 2), Qt.AlignLeft,
                       f"Now: {latest:.0f} ms  Avg: {avg:.0f} ms  ({len(valid)} samples)")

        p.end()
