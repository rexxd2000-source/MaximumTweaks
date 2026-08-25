"""3D network globe — professional NOC-style visualization with undersea cables, IXPs, and detailed routing."""
from __future__ import annotations

import math
import time
from typing import Optional
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QTimer
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QPainterPath, QFontMetrics,
    QRadialGradient, QLinearGradient,
)
from PySide6.QtWidgets import QWidget

from config.app_config import THEME as T


def _s(key, alpha=0xFF):
    hex_color = T.get(key, "#94a3b8").lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return QColor(r, g, b, alpha)


# ── Continent outlines (lat/lon polylines) ─────────────────────────────────

CONTINENTS = {
    "Africa": [
        (37, -10), (37, 10), (33, 33), (30, 33), (22, 36), (12, 44),
        (5, 42), (0, 42), (-5, 40), (-11, 40), (-15, 40), (-26, 33),
        (-34, 26), (-34, 18), (-29, 16), (-18, 12), (-6, 12), (0, 10),
        (5, 1), (5, -4), (7, -15), (15, -17), (21, -17), (28, -13),
        (32, -8), (37, -10),
    ],
    "Europe": [
        (37, -10), (43, -10), (48, -5), (51, 2), (54, 8), (55, 12),
        (58, 16), (63, 10), (65, 14), (70, 20), (71, 28), (69, 32),
        (63, 40), (58, 42), (54, 38), (50, 40), (47, 36), (44, 34),
        (42, 30), (40, 26), (38, 24), (36, 22), (36, 15), (38, 10),
        (42, 5), (44, 0), (43, -5), (40, -8), (37, -10),
    ],
    "Asia": [
        (70, 28), (72, 40), (73, 55), (74, 70), (73, 85), (71, 100),
        (72, 130), (68, 170), (65, 175), (60, 165), (55, 162),
        (50, 143), (45, 140), (40, 130), (35, 130), (30, 122),
        (22, 114), (10, 106), (1, 104), (-8, 115), (-8, 140),
        (5, 120), (18, 108), (22, 108), (25, 97), (20, 93),
        (10, 77), (8, 77), (6, 80), (8, 98), (10, 106),
        (22, 90), (22, 88), (23, 86), (20, 73), (24, 68),
        (30, 62), (25, 57), (23, 58), (13, 45), (12, 44),
        (22, 36), (30, 33), (33, 35), (36, 36), (38, 40),
        (42, 42), (45, 40), (48, 38), (50, 40), (54, 38),
        (58, 42), (63, 40), (69, 32), (70, 28),
    ],
    "NorthAmerica": [
        (7, -77), (10, -84), (18, -88), (21, -87), (21, -90),
        (25, -90), (30, -85), (25, -80), (27, -77), (30, -82),
        (29, -90), (27, -97), (26, -98), (28, -97), (32, -105),
        (37, -105), (42, -104), (49, -105), (49, -125), (42, -124),
        (35, -120), (32, -117), (28, -115), (23, -110), (20, -105),
        (15, -92), (10, -84), (7, -77),
    ],
    "SouthAmerica": [
        (12, -70), (10, -62), (7, -55), (2, -50), (-5, -35),
        (-12, -37), (-18, -40), (-23, -42), (-33, -52), (-40, -62),
        (-55, -68), (-55, -65), (-52, -70), (-46, -76), (-40, -73),
        (-33, -72), (-18, -70), (-5, -81), (2, -78), (10, -72),
        (12, -70),
    ],
    "Australia": [
        (-12, 131), (-12, 136), (-14, 136), (-17, 146),
        (-28, 153), (-37, 150), (-38, 145), (-35, 137),
        (-32, 133), (-32, 127), (-34, 116), (-35, 117),
        (-33, 115), (-22, 114), (-14, 126), (-12, 131),
    ],
    "Greenland": [
        (60, -44), (65, -55), (72, -56), (78, -72), (82, -52),
        (84, -30), (82, -22), (76, -18), (70, -22), (65, -38),
        (60, -44),
    ],
    "Japan": [
        (31, 131), (33, 131), (34, 133), (35, 135), (36, 137),
        (37, 140), (39, 140), (41, 140), (43, 145), (45, 142),
        (43, 141), (41, 140), (39, 139), (36, 136), (34, 132),
        (33, 130), (31, 131),
    ],
    "UK": [
        (50, -5), (51, 1), (53, 0), (55, -2), (58, -5),
        (58, -3), (56, -3), (54, -1), (52, 1), (51, 1),
        (50, -5),
    ],
    "NewZealand": [
        (-35, 174), [-37, 175], [-39, 177], [-46, 168],
        [-47, 167], [-46, 166], [-44, 168], [-42, 172],
        [-38, 178], [-37, 176], [-35, 174],
    ],
}


# ── Major submarine cable systems (simplified landing points) ───────────────

SUBSEA_CABLES = {
    "WACS": {
        "color": QColor(0, 180, 255, 100),
        "path": [
            (-33.9, 18.4), (-6.0, 12.5), (5.3, -4.0), (51.5, -0.1),
        ],
        "capacity": "14.5 Tbps",
        "landing": "Cape Town → Angola → Lagos → London",
    },
    "SEACOM": {
        "color": QColor(255, 160, 0, 100),
        "path": [
            (-33.9, 18.4), (-29.9, 31.0), (-1.3, 36.8), (-4.0, 39.7),
            (11.6, 43.1), (19.1, 72.9), (1.3, 103.8),
        ],
        "capacity": "1.5 Tbps",
        "landing": "Cape Town → Durban → Mombasa → Djibouti → Mumbai → Singapore",
    },
    "EASSy": {
        "color": QColor(100, 255, 100, 100),
        "path": [
            (-33.9, 18.4), (-29.9, 31.0), (-1.3, 36.8), (-4.0, 39.7),
            (11.6, 43.1), (12.5, 44.5), (23.6, 58.5), (19.1, 72.9),
        ],
        "capacity": "20+ Tbps",
        "landing": "Cape Town → Durban → Mombasa → Djibouti → Muscat → Mumbai",
    },
    "GLO-1": {
        "color": QColor(255, 100, 100, 100),
        "path": [
            (-33.9, 18.4), (-6.0, 12.5), (5.3, -4.0), (51.5, -0.1),
        ],
        "capacity": "2.5 Tbps",
        "landing": "Cape Town → Lagos → London",
    },
    "SAT-3": {
        "color": QColor(255, 255, 100, 100),
        "path": [
            (-33.9, 18.4), (5.3, -4.0), (51.5, -0.1), (38.7, -9.1),
        ],
        "capacity": "3.84 Tbps",
        "landing": "Cape Town → Lagos → Lisbon",
    },
    "ACE": {
        "color": QColor(180, 100, 255, 100),
        "path": [
            (-33.9, 18.4), (-25.9, 32.6), (-1.3, 36.8), (5.3, -4.0),
            (51.5, -0.1),
        ],
        "capacity": "20+ Tbps",
        "landing": "Cape Town → Maputo → Mombasa → Lagos → London",
    },
    "2Africa": {
        "color": QColor(255, 120, 200, 100),
        "path": [
            (-33.9, 18.4), (-25.9, 32.6), (-1.3, 36.8), (30.0, 31.2),
            (41.0, 29.0), (51.5, -0.1), (52.4, 4.9), (50.1, 8.7),
        ],
        "capacity": "180+ Tbps",
        "landing": "Cape Town → Maputo → Mombasa → Cairo → Istanbul → London → Amsterdam → Frankfurt",
    },
    "TAT-14": {
        "color": QColor(0, 200, 200, 100),
        "path": [
            (40.7, -74.0), (51.5, -0.1), (52.4, 4.9), (50.1, 8.7),
        ],
        "capacity": "5.12 Tbps",
        "landing": "New York → London → Amsterdam → Frankfurt",
    },
    "Dunant": {
        "color": QColor(255, 200, 0, 100),
        "path": [
            (40.7, -74.0), (51.5, -0.1),
        ],
        "capacity": "250 Tbps",
        "landing": "New York → London",
    },
    "FASTER": {
        "color": QColor(100, 200, 255, 100),
        "path": [
            (35.7, 139.7), (37.8, -122.4), (34.1, -118.2),
        ],
        "capacity": "60 Tbps",
        "landing": "Tokyo → Oregon → Los Angeles",
    },
    "Asia-Africa-Europe-1": {
        "color": QColor(200, 100, 255, 100),
        "path": [
            (1.3, 103.8), (19.1, 72.9), (11.6, 43.1), (-1.3, 36.8),
            (30.0, 31.2), (41.0, 29.0), (51.5, -0.1),
        ],
        "capacity": "40+ Tbps",
        "landing": "Singapore → Mumbai → Djibouti → Mombasa → Cairo → Istanbul → London",
    },
}


# ── Internet Exchange Points ────────────────────────────────────────────────

IXPS = {
    "JINX (Johannesburg)": (-26.2, 28.0),
    "CINX (Cape Town)": (-33.9, 18.4),
    "Nairobi IXP": (-1.3, 36.8),
    "Lagos IXP": (6.5, 3.4),
    "Cairo IXP": (30.0, 31.2),
    "DE-CIX Frankfurt": (50.1, 8.7),
    "AMS-IX Amsterdam": (52.4, 4.9),
    "LINX London": (51.5, -0.1),
    "France-IX Paris": (48.9, 2.4),
    "MSK-IX Moscow": (55.8, 37.6),
    "JPNAP Tokyo": (35.7, 139.7),
    "HKIX Hong Kong": (22.3, 114.2),
    "SGIX Singapore": (1.3, 103.8),
    "INX Mumbai": (19.1, 72.9),
    "Equinix IX Sydney": (-33.9, 151.2),
    "IX.br Sao Paulo": (-23.5, -46.6),
    "NYIIX New York": (40.7, -74.0),
    "LINX Los Angeles": (34.1, -118.2),
    "MIX Seoul": (37.6, 127.0),
    "TWIX Taipei": (25.0, 121.5),
}


# ── Major routing cities ────────────────────────────────────────────────────

MAJOR_CITIES = {
    "Johannesburg": (-26.2, 28.0), "Cape Town": (-33.9, 18.4),
    "Nairobi": (-1.3, 36.8), "Lagos": (6.5, 3.4),
    "Cairo": (30.0, 31.2), "Dubai": (25.2, 55.3),
    "London": (51.5, -0.1), "Frankfurt": (50.1, 8.7),
    "Amsterdam": (52.4, 4.9), "Paris": (48.9, 2.4),
    "Marseille": (43.3, 5.4), "Stockholm": (59.3, 18.1),
    "Warsaw": (52.2, 21.0), "Istanbul": (41.0, 29.0),
    "Mumbai": (19.1, 72.9), "Singapore": (1.3, 103.8),
    "Tokyo": (35.7, 139.7), "Hong Kong": (22.3, 114.2),
    "Los Angeles": (34.1, -118.2), "New York": (40.7, -74.0),
    "Miami": (25.8, -80.2), "Sao Paulo": (-23.5, -46.6),
    "Buenos Aires": (-34.6, -58.4), "Sydney": (-33.9, 151.2),
    "Seoul": (37.6, 127.0), "Taipei": (25.0, 121.5),
    "Djibouti": (11.6, 43.1), "Mombasa": (-4.0, 39.7),
    "Dar es Salaam": (-6.8, 39.3), "Luanda": (-8.8, 13.2),
    "Kigali": (-1.9, 30.1), "Addis Ababa": (9.0, 38.7),
    "Chennai": (13.1, 80.3), "Colombo": (6.9, 79.9),
    "Muscat": (23.6, 58.5), "Doha": (25.3, 51.2),
    "Jeddah": (21.5, 39.2), "Tel Aviv": (32.1, 34.8),
    "Athens": (37.9, 23.7), "Rome": (41.9, 12.5),
    "Madrid": (40.4, -3.7), "Lisbon": (38.7, -9.1),
    "Dublin": (53.3, -6.3), "Copenhagen": (55.7, 12.6),
    "Helsinki": (60.2, 24.9), "Moscow": (55.8, 37.6),
    "Bogota": (4.7, -74.1), "Lima": (-12.0, -77.0),
    "Santiago": (-33.4, -70.7), "Mexico City": (19.4, -99.1),
    "Dallas": (32.8, -96.8), "Chicago": (41.9, -87.6),
    "San Francisco": (37.8, -122.4), "Seattle": (47.6, -122.3),
    "Toronto": (43.7, -79.4), "Auckland": (-36.8, 174.8),
    "Reykjavik": (64.1, -21.9), "Casablanca": (33.6, -7.6),
    "Accra": (5.6, -0.2), "Dakar": (14.7, -17.5),
    "Maputo": (-25.9, 32.6), "Durban": (-29.9, 31.0),
    "Pretoria": (-25.7, 28.2), "Windhoek": (-22.6, 17.1),
    "Port Louis": (-20.2, 57.5),
}


@dataclass
class NetworkNode:
    id: str = ""
    label: str = ""
    lat: float = 0.0
    lon: float = 0.0
    node_type: str = "unknown"
    asn: int = 0
    asn_name: str = ""
    ip: str = ""
    city: str = ""
    region: str = ""
    country: str = ""
    confidence: str = "unknown"
    detail: str = ""
    color: str = "#8b9cc0"
    hop_number: int = 0
    latency: float = 0.0
    cable_used: str = ""

    @property
    def role_label(self) -> str:
        return {
            "user": "YOUR NETWORK",
            "gateway": "HOME ROUTER",
            "isp": "ISP",
            "transit": "TRANSIT",
            "peering": "PEERING",
            "ixp": "IXP",
            "cdn": "CDN",
            "destination": "DESTINATION",
            "unknown": "NETWORK",
        }.get(self.node_type, "NETWORK")


@dataclass
class NetworkRoute:
    source: str = ""
    destination: str = ""
    nodes: list[NetworkNode] = field(default_factory=list)
    total_latency: float = 0.0
    total_hops: int = 0
    packet_loss: float = 0.0
    jitter: float = 0.0
    as_path: list[int] = field(default_factory=list)
    as_path_names: dict[int, str] = field(default_factory=dict)
    bgp_confidence: str = ""
    measured_confidence: str = ""
    explanation: str = ""
    cables_used: list[str] = field(default_factory=list)


class GlobeWidget(QWidget):
    hop_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(500, 340)
        self._route: Optional[NetworkRoute] = None
        self._selected_node: str = ""
        self._hovered_node: str = ""
        self._rot_y: float = 15.0
        self._rot_x: float = -20.0
        self._target_rot_y: float = 15.0
        self._target_rot_x: float = -20.0
        self._dragging = False
        self._drag_start = QPointF()
        self._anim: float = 0.0
        self._cx: float = 0
        self._cy: float = 0
        self._radius: float = 0
        self._node_screen: dict[str, QPointF] = {}
        self._node_depth: dict[str, float] = {}
        self._auto_rotate = True
        self._route_arcs: list[list[QPointF]] = []
        self._cable_arcs: list[tuple[list[QPointF], QColor, str]] = []
        self.setMouseTracking(True)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_route(self, route: Optional[NetworkRoute]):
        self._route = route
        self._route_arcs = []
        self._cable_arcs = []
        if route and route.nodes:
            self._focus_on_route(route)
            self._build_arcs(route)
            self._build_cable_arcs(route)
        self.update()

    def clear(self):
        self._route = None
        self._node_screen.clear()
        self._node_depth.clear()
        self._route_arcs = []
        self._cable_arcs = []
        self.update()

    def _focus_on_route(self, route: NetworkRoute):
        if not route.nodes:
            return
        lats = [n.lat for n in route.nodes if abs(n.lat) > 0.01]
        lons = [n.lon for n in route.nodes if abs(n.lon) > 0.01]
        if lats and lons:
            avg_lat = sum(lats) / len(lats)
            avg_lon = sum(lons) / len(lons)
            self._target_rot_y = -avg_lon * 0.4
            self._target_rot_x = avg_lat * 0.25

    def _build_arcs(self, route: NetworkRoute):
        self._route_arcs = []
        nodes = route.nodes
        for i in range(len(nodes) - 1):
            a, b = nodes[i], nodes[i + 1]
            arc = self._great_circle_arc(a.lat, a.lon, b.lat, b.lon, steps=80)
            self._route_arcs.append(arc)

    def _build_cable_arcs(self, route: NetworkRoute):
        self._cable_arcs = []
        route_coords = [(n.lat, n.lon) for n in route.nodes if abs(n.lat) > 0.01 and abs(n.lon) > 0.01]
        if len(route_coords) < 2:
            return
        for cable_name, cable in SUBSEA_CABLES.items():
            cable_pts = cable["path"]
            if len(cable_pts) < 2:
                continue
            overlap = 0
            for rp in route_coords:
                for cp in cable_pts:
                    dlat = abs(rp[0] - cp[0])
                    dlon = abs(rp[1] - cp[1])
                    if dlat < 8 and dlon < 8:
                        overlap += 1
                        break
            if overlap >= 2:
                arc_pts = []
                for i in range(len(cable_pts) - 1):
                    p1, p2 = cable_pts[i], cable_pts[i + 1]
                    seg = self._great_circle_arc(p1[0], p1[1], p2[0], p2[1], steps=40)
                    arc_pts.extend(seg)
                if arc_pts:
                    self._cable_arcs.append((arc_pts, cable["color"], cable_name))

    def _great_circle_arc(self, lat1, lon1, lat2, lon2, steps=60) -> list[QPointF]:
        r1, lo1 = math.radians(lat1), math.radians(lon1)
        r2, lo2 = math.radians(lat2), math.radians(lon2)
        d = math.acos(
            max(-1, min(1,
                math.sin(r1) * math.sin(r2) +
                math.cos(r1) * math.cos(r2) * math.cos(lo2 - lo1)
            ))
        )
        if d < 0.001:
            p1, _ = self._project(lat1, lon1)
            p2, _ = self._project(lat2, lon2)
            return [p1, p2] if p1 and p2 else []
        pts = []
        for i in range(steps + 1):
            f = i / steps
            a = math.sin((1 - f) * d) / math.sin(d)
            b = math.sin(f * d) / math.sin(d)
            x = a * math.cos(r1) * math.cos(lo1) + b * math.cos(r2) * math.cos(lo2)
            y = a * math.cos(r1) * math.sin(lo1) + b * math.cos(r2) * math.sin(lo2)
            z = a * math.sin(r1) + b * math.sin(r2)
            lat = math.degrees(math.atan2(z, math.sqrt(x * x + y * y)))
            lon = math.degrees(math.atan2(y, x))
            pos, depth = self._project(lat, lon)
            if pos:
                pts.append(pos)
        return pts

    def _tick(self):
        self._anim += 0.04
        if self._auto_rotate and not self._dragging:
            self._target_rot_y += 0.012
        self._rot_y += (self._target_rot_y - self._rot_y) * 0.08
        self._rot_x += (self._target_rot_x - self._rot_x) * 0.08
        self.update()

    def _ll_to_xyz(self, lat, lon):
        lr, lo = math.radians(lat), math.radians(lon)
        return (
            math.cos(lr) * math.sin(lo),
            -math.sin(lr),
            math.cos(lr) * math.cos(lo),
        )

    def _rot(self, x, y, z):
        ry, rx = math.radians(self._rot_y), math.radians(self._rot_x)
        c, s = math.cos(ry), math.sin(ry)
        x1, z1 = x * c + z * s, -x * s + z * c
        c2, s2 = math.cos(rx), math.sin(rx)
        y1, z2 = y * c2 - z1 * s2, y * s2 + z1 * c2
        return x1, y1, z2

    def _project(self, lat, lon):
        x, y, z = self._ll_to_xyz(lat, lon)
        rx, ry, rz = self._rot(x, y, z)
        if rz < -0.05:
            return None, rz
        return QPointF(self._cx + rx * self._radius, self._cy + ry * self._radius), rz

    def _compute_nodes(self):
        self._node_screen = {}
        self._node_depth = {}
        if not self._route:
            return
        for node in self._route.nodes:
            pos, depth = self._project(node.lat, node.lon)
            if pos:
                self._node_screen[node.id] = pos
                self._node_depth[node.id] = depth

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor(4, 6, 12))
        bg.setColorAt(1, QColor(8, 10, 18))
        p.fillRect(0, 0, w, h, bg)

        self._cx = w * 0.5
        self._cy = h * 0.48
        self._radius = min(w, h) * 0.38

        self._draw_atmosphere(p)
        self._draw_globe_solid(p)
        self._draw_grid(p)
        self._draw_continents_solid(p)
        self._draw_ixp_markers(p)
        self._draw_city_dots(p)

        if self._route and self._route.nodes:
            self._compute_nodes()
            self._draw_cable_lines(p)
            self._draw_route_arcs(p)
            self._draw_flow_particles(p)
            self._draw_nodes(p)
            self._draw_node_labels(p)
            self._draw_noc_overlay(p)
        else:
            self._draw_idle(p, w, h)

        self._draw_legend(p)
        p.end()

    def _draw_atmosphere(self, p: QPainter):
        cx, cy, r = self._cx, self._cy, self._radius
        glow = QRadialGradient(cx, cy, r * 1.4)
        glow.setColorAt(0.6, QColor(15, 30, 60, 25))
        glow.setColorAt(0.75, QColor(10, 25, 50, 15))
        glow.setColorAt(0.9, QColor(8, 20, 40, 8))
        glow.setColorAt(1.0, QColor(5, 15, 30, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), r * 1.4, r * 1.4)

    def _draw_globe_solid(self, p: QPainter):
        cx, cy, r = self._cx, self._cy, self._radius
        grad = QRadialGradient(cx - r * 0.15, cy - r * 0.15, r * 1.1)
        grad.setColorAt(0, QColor(18, 28, 50))
        grad.setColorAt(0.3, QColor(14, 22, 42))
        grad.setColorAt(0.6, QColor(10, 16, 32))
        grad.setColorAt(0.85, QColor(7, 12, 24))
        grad.setColorAt(1, QColor(5, 8, 18))
        p.setPen(QPen(QColor(40, 70, 120, 120), 1.5))
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPointF(cx, cy), r, r)

        highlight = QRadialGradient(cx - r * 0.3, cy - r * 0.35, r * 0.6)
        highlight.setColorAt(0, QColor(60, 90, 140, 30))
        highlight.setColorAt(0.5, QColor(40, 70, 120, 10))
        highlight.setColorAt(1, QColor(20, 40, 80, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(highlight))
        p.drawEllipse(QPointF(cx, cy), r * 0.95, r * 0.95)

    def _draw_grid(self, p: QPainter):
        for lat_deg in range(-75, 76, 15):
            pts = []
            for lon_deg in range(0, 361, 2):
                pos, _ = self._project(lat_deg, lon_deg)
                if pos:
                    pts.append(pos)
            if len(pts) >= 3:
                path = QPainterPath()
                path.moveTo(pts[0])
                for pt in pts[1:]:
                    path.lineTo(pt)
                p.setPen(QPen(QColor(30, 50, 80, 25), 0.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)

        for lon_deg in range(0, 360, 15):
            pts = []
            for lat_deg in range(-85, 86, 2):
                pos, _ = self._project(lat_deg, lon_deg)
                if pos:
                    pts.append(pos)
            if len(pts) >= 3:
                path = QPainterPath()
                path.moveTo(pts[0])
                for pt in pts[1:]:
                    path.lineTo(pt)
                p.setPen(QPen(QColor(30, 50, 80, 25), 0.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)

        p.setPen(Qt.PenStyle.NoPen)
        for lat_deg in range(-60, 61, 30):
            for lon_deg in range(0, 360, 30):
                pos, depth = self._project(lat_deg, lon_deg)
                if pos and depth > 0:
                    alpha = int(35 * depth)
                    p.setBrush(QBrush(QColor(50, 75, 110, alpha)))
                    p.drawEllipse(pos, 1.2, 1.2)

    def _draw_continents_solid(self, p: QPainter):
        for name, outline in CONTINENTS.items():
            pts = []
            for lat, lon in outline:
                if isinstance(lat, str):
                    continue
                pos, depth = self._project(lat, lon)
                if pos and depth > -0.05:
                    pts.append((pos, depth))
            if len(pts) >= 3:
                path = QPainterPath()
                path.moveTo(pts[0][0])
                for pt, _ in pts[1:]:
                    path.lineTo(pt)
                path.closeSubpath()
                land_fill = QBrush(QColor(22, 40, 70, 180))
                p.setPen(QPen(QColor(50, 80, 120, 80), 1.0))
                p.setBrush(land_fill)
                p.drawPath(path)

        p.setPen(QPen(QColor(60, 95, 140, 50), 0.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for name, outline in CONTINENTS.items():
            pts = []
            for lat, lon in outline:
                if isinstance(lat, str):
                    continue
                pos, depth = self._project(lat, lon)
                if pos and depth > -0.05:
                    pts.append(pos)
            if len(pts) >= 3:
                path = QPainterPath()
                path.moveTo(pts[0])
                for pt in pts[1:]:
                    path.lineTo(pt)
                path.closeSubpath()
                p.drawPath(path)

    def _draw_ixp_markers(self, p: QPainter):
        p.setPen(Qt.PenStyle.NoPen)
        for name, (lat, lon) in IXPS.items():
            pos, depth = self._project(lat, lon)
            if pos and depth > 0.08:
                alpha = int(70 * depth)
                sz = 2.5 * depth
                glow = QRadialGradient(pos, sz * 2.5)
                glow.setColorAt(0, QColor(255, 200, 50, int(alpha * 0.4)))
                glow.setColorAt(1, QColor(255, 200, 50, 0))
                p.setBrush(QBrush(glow))
                p.drawEllipse(pos, sz * 2.5, sz * 2.5)
                p.setBrush(QBrush(QColor(255, 200, 50, alpha)))
                diamond = QPainterPath()
                diamond.moveTo(pos.x(), pos.y() - sz)
                diamond.lineTo(pos.x() + sz * 0.7, pos.y())
                diamond.lineTo(pos.x(), pos.y() + sz)
                diamond.lineTo(pos.x() - sz * 0.7, pos.y())
                diamond.closeSubpath()
                p.drawPath(diamond)

    def _draw_city_dots(self, p: QPainter):
        p.setPen(Qt.PenStyle.NoPen)
        for city, (lat, lon) in MAJOR_CITIES.items():
            pos, depth = self._project(lat, lon)
            if pos and depth > 0.06:
                alpha = int(50 * depth)
                sz = 1.0 + depth * 0.8
                p.setBrush(QBrush(QColor(70, 110, 160, alpha)))
                p.drawEllipse(pos, sz, sz)

    def _draw_cable_lines(self, p: QPainter):
        for arc_pts, color, cable_name in self._cable_arcs:
            if len(arc_pts) < 2:
                continue
            path = QPainterPath()
            path.moveTo(arc_pts[0])
            for pt in arc_pts[1:]:
                path.lineTo(pt)
            p.setPen(QPen(color, 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            c = QColor(color)
            glow_pen = QPen(QColor(c.red(), c.green(), c.blue(), 30), 6)
            p.setPen(glow_pen)
            p.drawPath(path)

    def _draw_route_arcs(self, p: QPainter):
        for arc_pts in self._route_arcs:
            if len(arc_pts) < 2:
                continue
            path = QPainterPath()
            path.moveTo(arc_pts[0])
            for pt in arc_pts[1:]:
                path.lineTo(pt)

            p.setPen(QPen(QColor(100, 80, 200, 10), 14))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setPen(QPen(QColor(120, 100, 220, 30), 6))
            p.drawPath(path)
            p.setPen(QPen(QColor(160, 140, 255, 60), 2.5))
            p.drawPath(path)
            p.setPen(QPen(QColor(200, 180, 255, 120), 1.5))
            p.drawPath(path)

    def _draw_flow_particles(self, p: QPainter):
        all_pts = []
        for arc in self._route_arcs:
            all_pts.extend(arc)
        if len(all_pts) < 3:
            return

        total_len = 0
        for i in range(len(all_pts) - 1):
            dx = all_pts[i + 1].x() - all_pts[i].x()
            dy = all_pts[i + 1].y() - all_pts[i].y()
            total_len += math.sqrt(dx * dx + dy * dy)

        num_particles = min(16, max(5, int(total_len / 50)))
        for d in range(num_particles):
            phase = ((self._anim * 0.6 + d * 0.08) % 1.0)
            target_dist = phase * total_len
            accum = 0
            px, py = all_pts[0].x(), all_pts[0].y()
            for i in range(len(all_pts) - 1):
                dx = all_pts[i + 1].x() - all_pts[i].x()
                dy = all_pts[i + 1].y() - all_pts[i].y()
                seg_len = math.sqrt(dx * dx + dy * dy)
                if accum + seg_len >= target_dist:
                    frac = (target_dist - accum) / max(seg_len, 0.001)
                    px = all_pts[i].x() + dx * frac
                    py = all_pts[i].y() + dy * frac
                    break
                accum += seg_len
            dp = QPointF(px, py)
            gr = 4 + 2 * math.sin(self._anim * 0.5 + d * 0.9)
            glow_g = QRadialGradient(dp, gr)
            glow_g.setColorAt(0, QColor(220, 210, 255, 180))
            glow_g.setColorAt(0.3, QColor(160, 140, 255, 60))
            glow_g.setColorAt(1, QColor(139, 92, 246, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(glow_g))
            p.drawEllipse(dp, gr, gr)
            p.setBrush(QBrush(QColor(240, 235, 255)))
            p.drawEllipse(dp, 2, 2)

    def _draw_nodes(self, p: QPainter):
        if not self._route:
            return
        sorted_nodes = sorted(
            self._route.nodes,
            key=lambda n: self._node_depth.get(n.id, 0),
        )
        for node in sorted_nodes:
            if node.id not in self._node_screen:
                continue
            pos = self._node_screen[node.id]
            depth = self._node_depth.get(node.id, 0)
            if depth < -0.05:
                continue

            is_sel = node.id == self._selected_node
            is_hov = node.id == self._hovered_node
            color = QColor(node.color)

            if node.node_type == "user":
                r = 10
            elif node.node_type == "destination":
                r = 9
            elif node.node_type == "isp":
                r = 8
            elif node.node_type == "gateway":
                r = 7
            else:
                r = 6

            if is_sel:
                r += 3
                glow = QRadialGradient(pos, r * 5)
                glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 100))
                glow.setColorAt(0.5, QColor(color.red(), color.green(), color.blue(), 30))
                glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(glow))
                p.drawEllipse(pos, r * 5, r * 5)
            elif is_hov:
                r += 2
                glow = QRadialGradient(pos, r * 3)
                glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 60))
                glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(glow))
                p.drawEllipse(pos, r * 3, r * 3)

            if node.node_type == "user":
                pulse = 0.4 + 0.4 * math.sin(self._anim * 0.7)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), int(pulse * 60))))
                p.drawEllipse(pos, r + 6, r + 6)

            p.setPen(QPen(QColor(4, 6, 12), 2.5))
            p.setBrush(QBrush(color))
            p.drawEllipse(pos, r, r)

            inner = QRadialGradient(pos.x() - r * 0.3, pos.y() - r * 0.3, r)
            inner.setColorAt(0, QColor(255, 255, 255, 70))
            inner.setColorAt(0.5, QColor(255, 255, 255, 20))
            inner.setColorAt(1, QColor(255, 255, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(inner))
            p.drawEllipse(pos, r - 1, r - 1)

            if node.node_type == "user":
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(4, 6, 12)))
                p.drawEllipse(pos, r - 4, r - 4)
                p.setBrush(QBrush(color))
                p.drawEllipse(pos, r - 6, r - 6)

            if node.node_type in ("isp", "destination", "gateway", "transit"):
                ring = 0.4 + 0.3 * math.sin(self._anim * 1.0 + hash(node.id) % 10)
                p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), int(ring * 100)), 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(pos, r + 4, r + 4)

    def _draw_node_labels(self, p: QPainter):
        if not self._route:
            return
        font = QFont("Segoe UI", 9)
        fm = QFontMetrics(font)

        for node in self._route.nodes:
            if node.id not in self._node_screen:
                continue
            depth = self._node_depth.get(node.id, 0)
            if depth < 0.05:
                continue

            pos = self._node_screen[node.id]
            is_sel = node.id == self._selected_node
            label = node.label
            if not label:
                continue
            if len(label) > 28:
                label = label[:25] + "..."

            font.setBold(is_sel)
            p.setFont(font)
            tw = fm.horizontalAdvance(label)
            lx = pos.x() - tw / 2
            ly = pos.y() + 18

            tr = QRectF(lx - 5, ly - 3, tw + 10, fm.height() + 6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(4, 6, 12, 230)))
            p.drawRoundedRect(tr, 4, 4)
            p.setPen(QPen(QColor(50, 75, 110, 120), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(tr, 4, 4)

            if is_sel:
                p.setPen(QColor(255, 255, 255))
            elif node.node_type == "user":
                p.setPen(QColor(96, 165, 250))
            elif node.node_type == "isp":
                p.setPen(QColor(96, 165, 250))
            elif node.node_type == "destination":
                p.setPen(QColor(52, 211, 153))
            elif node.node_type == "gateway":
                p.setPen(QColor(251, 191, 36))
            else:
                p.setPen(QColor(170, 190, 220))
            p.setFont(font)
            p.drawText(tr, Qt.AlignCenter, label)

            sub_parts = []
            if node.city:
                sub_parts.append(node.city)
            if node.country:
                sub_parts.append(node.country)
            if node.asn:
                sub_parts.append(f"AS{node.asn}")
            if node.latency > 0:
                sub_parts.append(f"{node.latency:.0f}ms")

            if sub_parts:
                sub_label = " \u00b7 ".join(sub_parts)
                sfont = QFont("Consolas", 7)
                stw = QFontMetrics(sfont).horizontalAdvance(sub_label)
                p.setFont(sfont)
                sy = ly + fm.height() + 1
                sr = QRectF(pos.x() - stw / 2 - 4, sy, stw + 8, fm.height() + 3)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(4, 6, 12, 200)))
                p.drawRoundedRect(sr, 3, 3)
                p.setPen(QColor(150, 130, 220, 180))
                p.drawText(sr, Qt.AlignCenter, sub_label)

            if is_sel:
                font.setBold(False)
                p.setFont(font)

    def _draw_noc_overlay(self, p: QPainter):
        if not self._route:
            return
        route = self._route
        w, h = self.width(), self.height()

        panel_x = 12
        panel_y = 12
        line_h = 15
        font_mono = QFont("Consolas", 8)
        fm = QFontMetrics(font_mono)

        lines = []
        lines.append(("header", "NETWORK INTELLIGENCE"))
        lines.append(("sep", "─" * 36))
        lines.append(("label", f"Source: {route.source or 'your_network'}"))
        lines.append(("label", f"Destination: {route.destination}"))
        lines.append(("sep", ""))

        if route.total_latency > 0:
            lines.append(("metric", f"RTT        {route.total_latency:>8.1f} ms"))
        if route.jitter > 0:
            lines.append(("metric", f"Jitter     {route.jitter:>8.1f} ms"))
        if route.packet_loss > 0:
            lines.append(("metric", f"Loss       {route.packet_loss:>7.0f}  %"))
        if route.total_hops > 0:
            lines.append(("metric", f"Hops       {route.total_hops:>8d}    "))
        if route.as_path:
            as_str = " -> ".join(str(a) for a in route.as_path[:6])
            if len(route.as_path) > 6:
                as_str += " -> ..."
            lines.append(("metric", f"AS Path    {as_str}"))

        if route.cables_used:
            lines.append(("sep", ""))
            lines.append(("header", "SUBMARINE CABLES"))
            for cable in route.cables_used[:3]:
                lines.append(("cable", f"  {cable}"))

        if route.explanation:
            lines.append(("sep", ""))
            lines.append(("header", "BGP EXPLANATION"))
            words = route.explanation.split()
            cur = ""
            for w_ in words:
                test = cur + " " + w_ if cur else w_
                if fm.horizontalAdvance(test) > 280:
                    lines.append(("note", f"  {cur}"))
                    cur = w_
                else:
                    cur = test
            if cur:
                lines.append(("note", f"  {cur}"))

        total_h = len(lines) * line_h + 12
        max_w = 310

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(4, 6, 12, 220)))
        p.drawRoundedRect(QRectF(panel_x, panel_y, max_w, total_h), 6, 6)
        p.setPen(QPen(QColor(40, 65, 100, 100), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(panel_x, panel_y, max_w, total_h), 6, 6)

        for i, (kind, text) in enumerate(lines):
            y = panel_y + 6 + i * line_h
            if kind == "header":
                p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
                p.setPen(QColor(100, 180, 255))
            elif kind == "sep":
                p.setFont(font_mono)
                p.setPen(QColor(40, 65, 100, 60))
            elif kind == "label":
                p.setFont(font_mono)
                p.setPen(QColor(140, 160, 190))
            elif kind == "metric":
                p.setFont(font_mono)
                p.setPen(QColor(200, 200, 220))
            elif kind == "cable":
                p.setFont(font_mono)
                p.setPen(QColor(0, 200, 255))
            elif kind == "note":
                p.setFont(QFont("Consolas", 7))
                p.setPen(QColor(120, 140, 170))
            else:
                p.setFont(font_mono)
                p.setPen(QColor(140, 160, 190))
            p.drawText(QRectF(panel_x + 8, y, max_w - 16, line_h), Qt.AlignLeft | Qt.AlignVCenter, text)

    def _draw_legend(self, p: QPainter):
        w, h = self.width(), self.height()
        items = [
            (QColor(96, 165, 250), "Your Network"),
            (QColor(96, 165, 250), "ISP"),
            (QColor(167, 139, 250), "Transit"),
            (QColor(255, 200, 50), "IXP"),
            (QColor(0, 180, 255), "Subsea Cable"),
            (QColor(52, 211, 153), "Destination"),
        ]
        font = QFont("Segoe UI", 7)
        fm = QFontMetrics(font)
        p.setFont(font)

        lx = w - 140
        ly = h - len(items) * 14 - 8
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(4, 6, 12, 200)))
        p.drawRoundedRect(QRectF(lx - 6, ly - 4, 145, len(items) * 14 + 8), 4, 4)

        for i, (color, label) in enumerate(items):
            y = ly + i * 14
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(lx + 4, y + 5), 3, 3)
            p.setPen(QColor(160, 180, 210))
            p.drawText(QRectF(lx + 14, y, 120, 14), Qt.AlignVCenter, label)

    def _draw_idle(self, p: QPainter, w: int, h: int):
        font = QFont("Segoe UI", 11)
        p.setFont(font)
        p.setPen(QColor(45, 60, 90))
        p.drawText(
            QRectF(0, self._cy + self._radius + 20, w, 30),
            Qt.AlignCenter,
            "Discovering your network topology...",
        )
        cx, cy, r = self._cx, self._cy, self._radius * 0.4
        for i in range(4):
            a = self._anim * 0.05 + i * 1.57
            x = cx + r * math.cos(a)
            y = cy + r * math.sin(a) * 0.35
            gr = 8
            glow = QRadialGradient(QPointF(x, y), gr)
            glow.setColorAt(0, QColor(139, 92, 246, 60))
            glow.setColorAt(1, QColor(139, 92, 246, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(glow))
            p.drawEllipse(QPointF(x, y), gr, gr)
            p.setBrush(QBrush(QColor(139, 92, 246, 150)))
            p.drawEllipse(QPointF(x, y), 2, 2)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position()
            for nid, npos in self._node_screen.items():
                if self._node_depth.get(nid, 0) < -0.05:
                    continue
                dx, dy = pos.x() - npos.x(), pos.y() - npos.y()
                if dx * dx + dy * dy < 600:
                    self._selected_node = nid
                    self._auto_rotate = False
                    self.hop_clicked.emit(nid)
                    self.update()
                    return
        elif event.button() == Qt.MiddleButton:
            self._dragging = True
            self._drag_start = event.position()
            self._auto_rotate = False

    def mouseMoveEvent(self, event):
        if self._dragging:
            d = event.position() - self._drag_start
            self._target_rot_y += d.x() * 0.3
            self._target_rot_x = max(-80, min(80, self._target_rot_x + d.y() * 0.3))
            self._drag_start = event.position()
            self.update()
            return
        pos = event.position()
        found = ""
        for nid, npos in self._node_screen.items():
            if self._node_depth.get(nid, 0) < -0.05:
                continue
            dx, dy = pos.x() - npos.x(), pos.y() - npos.y()
            if dx * dx + dy * dy < 600:
                found = nid
                break
        if found != self._hovered_node:
            self._hovered_node = found
            self.update()

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def wheelEvent(self, event):
        pass
