"""Isometric gaming PC visualization with animated component fly-out.

Pure QPainter — no OpenGL.  Renders a mid-tower gaming case with a
tempered-glass side panel showing internal components.  Components
fly out during scanning.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPolygonF,
    QPen, QFont, QFontMetrics, QBrush, QRadialGradient,
)
from PySide6.QtWidgets import QWidget, QSizePolicy

from config.app_config import THEME as T


def _qc(h: str, a: int = 255) -> QColor:
    h = h.lstrip("#")
    return QColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


# ── Component model ─────────────────────────────────────────────────

@dataclass
class Comp:
    label: str
    ox: float = 0.0
    oy: float = 0.0
    cx: float = 0.0
    cy: float = 0.0
    fly: float = 0.0
    status: str = "pending"
    pulse: float = 0.0
    w: float = 40.0
    h: float = 30.0
    color: str = "#8B5CF6"

    def reset(self):
        self.cx, self.cy = self.ox, self.oy
        self.fly = 0.0
        self.status = "pending"
        self.pulse = 0.0


_DEFAULTS: Dict[str, dict] = {
    "cpu":         {"label": "CPU",     "w": 48, "h": 40, "ox": 0,   "oy": -50},
    "gpu":         {"label": "GPU",     "w": 78, "h": 28, "ox": 0,   "oy": 10},
    "ram":         {"label": "RAM",     "w": 16, "h": 56, "ox": -56, "oy": -8},
    "storage":     {"label": "SSD",     "w": 56, "h": 20, "ox": 0,   "oy": 58},
    "motherboard": {"label": "MB",      "w": 92, "h": 72, "ox": 0,   "oy": 0},
    "network":     {"label": "NIC",     "w": 30, "h": 18, "ox": 56,  "oy": -30},
    "input":       {"label": "INPUT",   "w": 26, "h": 18, "ox": 56,  "oy": 18},
    "display":     {"label": "DISPLAY", "w": 26, "h": 18, "ox": -56, "oy": 38},
}

_FLY_X, _FLY_Y = -150, -120
_ANIM_MS, _TICK_MS = 460, 16

# Colours
_COL_CASE   = "#1A1D2E"
_CASE_EDGE  = "#252840"
_CASE_DARK  = "#12141F"
_GLASS_TINT = "#8B5CF6"
_FRAME      = "#2A2D42"
_LED_ON     = "#4ADE80"


class PCVisualization(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(380, 380)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._label = ""
        self._tick = 0
        self._scan_y = 0.0
        self._comps: Dict[str, Comp] = {}
        self._aprog: Dict[str, float] = {}
        self._adir: Dict[str, int] = {}
        self._init_comps()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(_TICK_MS)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

    # ── Public API ──────────────────────────────────────────────────

    def fly_out(self, cid: str):
        c = self._comps.get(cid)
        if not c:
            return
        c.fly = 0.0
        self._aprog[cid] = 0.0
        self._adir[cid] = 1

    def fly_in(self, cid: str):
        c = self._comps.get(cid)
        if not c:
            return
        self._aprog[cid] = 1.0
        self._adir[cid] = -1

    def set_scan_phase(self, cid: str, status: str):
        c = self._comps.get(cid)
        if c:
            c.status = status

    def set_label(self, text: str):
        self._label = text
        self.update()

    def reset(self):
        self._init_comps()
        self._aprog.clear()
        self._adir.clear()
        self._label = ""
        self.update()

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(380, 380)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(420, 420)

    # ── Init ────────────────────────────────────────────────────────

    def _init_comps(self):
        self._comps.clear()
        for cid, d in _DEFAULTS.items():
            self._comps[cid] = Comp(
                label=d["label"], ox=d["ox"], oy=d["oy"],
                cx=d["ox"], cy=d["oy"],
                w=d["w"], h=d["h"],
                color=T["accent"],
            )

    # ── Timer ───────────────────────────────────────────────────────

    def _on_tick(self):
        self._tick += 1
        dt = _TICK_MS / _ANIM_MS
        dirty = False

        for cid in list(self._aprog):
            prog = min(1.0, self._aprog[cid] + dt)
            d = self._adir[cid]
            c = self._comps[cid]
            e = _ease_in_out(prog)

            if d == 1:
                c.cx = _lerp(c.ox, c.ox + _FLY_X, e)
                c.cy = _lerp(c.oy, c.oy + _FLY_Y, e)
                c.fly = e
            else:
                c.cx = _lerp(c.ox + _FLY_X, c.ox, e)
                c.cy = _lerp(c.oy + _FLY_Y, c.oy, e)
                c.fly = 1.0 - e

            self._aprog[cid] = prog
            if prog >= 1.0:
                if d == 1:
                    c.fly = 1.0
                else:
                    c.fly = 0.0
                    c.cx, c.cy = c.ox, c.oy
                del self._aprog[cid]
                del self._adir[cid]
            dirty = True

        has_scan = any(c.status == "scanning" for c in self._comps.values())
        for c in self._comps.values():
            if c.status == "scanning":
                c.pulse = 0.5 + 0.5 * math.sin(self._tick * 0.16)
                dirty = True

        if has_scan:
            self._scan_y = (self._scan_y + 2.2) % 340
            dirty = True

        if dirty or self._label:
            self.update()

    # ── Paint ───────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        w, h = self.width(), self.height()
        cx = w * 0.52
        cy = h * 0.46
        cw = min(w, h) * 0.34
        ch = cw * 1.38
        d = cw * 0.24

        self._paint_case(p, cx, cy, cw, ch, d)
        self._paint_glass(p, cx, cy, cw, ch)
        self._paint_scan_line(p, cx, cy, cw, ch)
        self._paint_comps(p, cx, cy)
        self._paint_label(p, cx, cy + ch * 0.5 + d + 32)

        p.end()

    # ── Case: isometric box with glass front panel ──────────────────

    def _paint_case(self, p, cx, cy, cw, ch, d):
        hw, hh = cw / 2, ch / 2

        front = QPolygonF([
            QPointF(cx - hw, cy - hh),
            QPointF(cx + hw, cy - hh),
            QPointF(cx + hw, cy + hh),
            QPointF(cx - hw, cy + hh),
        ])
        top = QPolygonF([
            QPointF(cx - hw, cy - hh),
            QPointF(cx - hw + d, cy - hh - d),
            QPointF(cx + hw + d, cy - hh - d),
            QPointF(cx + hw, cy - hh),
        ])
        right = QPolygonF([
            QPointF(cx + hw, cy - hh),
            QPointF(cx + hw + d, cy - hh - d),
            QPointF(cx + hw + d, cy + hh - d),
            QPointF(cx + hw, cy + hh),
        ])

        # Front face — dark metal
        gf = QLinearGradient(cx - hw, cy - hh, cx + hw, cy + hh)
        gf.setColorAt(0, _qc(_COL_CASE))
        gf.setColorAt(1, _qc(_CASE_DARK))
        p.setPen(QPen(_qc(_CASE_EDGE), 1.5))
        p.setBrush(QBrush(gf))
        p.drawPolygon(front)

        # Top face
        gt = QLinearGradient(cx - hw, cy - hh - d, cx + hw, cy - hh)
        gt.setColorAt(0, _qc(_CASE_EDGE))
        gt.setColorAt(1, _qc(_COL_CASE))
        p.setPen(QPen(_qc(_CASE_EDGE), 1.0))
        p.setBrush(QBrush(gt))
        p.drawPolygon(top)

        # Right face — vented mesh
        gr = QLinearGradient(cx + hw, cy - hh, cx + hw + d, cy + hh)
        gr.setColorAt(0, _qc(_CASE_EDGE))
        gr.setColorAt(1, _qc(_CASE_DARK))
        p.setPen(QPen(_qc(_CASE_EDGE), 1.0))
        p.setBrush(QBrush(gr))
        p.drawPolygon(right)

        # Vent holes on right side
        p.setPen(QPen(_qc(_CASE_DARK, 160), 0.6))
        for i in range(8):
            vy = cy - hh + ch * 0.10 + i * (ch * 0.09)
            p.drawLine(QPointF(cx + hw + 2, vy), QPointF(cx + hw + d - 2, vy))

        # Power LED (bottom-left front)
        lx, ly = cx - hw + 12, cy + hh - 16
        pulse = 0.5 + 0.5 * math.sin(self._tick * 0.07)
        led_g = QRadialGradient(lx, ly, 8)
        led_g.setColorAt(0, QColor(74, 222, 128, int(140 * pulse)))
        led_g.setColorAt(0.5, QColor(74, 222, 128, int(30 * pulse)))
        led_g.setColorAt(1, QColor(74, 222, 128, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(led_g))
        p.drawEllipse(QPointF(lx, ly), 8, 8)
        p.setBrush(QBrush(QColor(74, 222, 128)))
        p.drawEllipse(QPointF(lx, ly), 2.5, 2.5)

        # Top fans (spinning)
        for fx in [cx + hw * 0.35 + d * 0.5, cx - hw * 0.1 + d * 0.5]:
            self._paint_fan(p, fx, cy - hh - d * 0.5, d * 0.5)

    def _paint_fan(self, p, fx, fy, r):
        p.setPen(QPen(_qc(_CASE_EDGE, 120), 0.8))
        p.setBrush(QBrush(_qc(_CASE_DARK, 180)))
        p.drawEllipse(QPointF(fx, fy), r, r * 0.5)
        angle = (self._tick * 3) % 360
        p.setPen(QPen(_qc(_CASE_EDGE, 70), 0.4))
        for blade in range(5):
            a = math.radians(angle + blade * 72)
            bx = fx + math.cos(a) * r * 0.7
            by = fy + math.sin(a) * r * 0.35
            p.drawLine(QPointF(fx, fy), QPointF(bx, by))

    # ── Glass panel overlay ─────────────────────────────────────────

    def _paint_glass(self, p, cx, cy, cw, ch):
        hw, hh = cw / 2, ch / 2
        pad = 7

        glass = QPolygonF([
            QPointF(cx - hw + pad, cy - hh + pad),
            QPointF(cx + hw - pad, cy - hh + pad),
            QPointF(cx + hw - pad, cy + hh - pad),
            QPointF(cx - hw + pad, cy + hh - pad),
        ])

        # Subtle glass tint
        gg = QLinearGradient(cx, cy - hh, cx, cy + hh)
        gg.setColorAt(0, QColor(139, 92, 246, 6))
        gg.setColorAt(0.5, QColor(139, 92, 246, 2))
        gg.setColorAt(1, QColor(139, 92, 246, 8))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(gg))
        p.drawPolygon(glass)

        # Glass edge highlight (top edge)
        p.setPen(QPen(QColor(255, 255, 255, 18), 0.8))
        p.setBrush(Qt.NoBrush)
        p.drawLine(
            QPointF(cx - hw + pad + 4, cy - hh + pad),
            QPointF(cx + hw - pad - 4, cy - hh + pad),
        )

    # ── Scan line ───────────────────────────────────────────────────

    def _paint_scan_line(self, p, cx, cy, cw, ch):
        if not any(c.status == "scanning" for c in self._comps.values()):
            return
        hw, hh = cw / 2, ch / 2
        y = cy - hh + self._scan_y % ch

        grad = QLinearGradient(cx - hw, y - 12, cx - hw, y + 12)
        grad.setColorAt(0, QColor(139, 92, 246, 0))
        grad.setColorAt(0.5, QColor(139, 92, 246, 25))
        grad.setColorAt(1, QColor(139, 92, 246, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRect(QRectF(cx - hw, y - 12, cw * 1.25, 24))

        p.setPen(QPen(QColor(139, 92, 246, 80), 0.8))
        p.drawLine(QPointF(cx - hw, y), QPointF(cx + hw + cw * 0.25, y))

    # ── Components ──────────────────────────────────────────────────

    def _paint_comps(self, p, cx, cy):
        order = ["motherboard", "storage", "ram", "gpu", "network",
                 "input", "display", "cpu"]
        for cid in order:
            c = self._comps.get(cid)
            if c:
                self._paint_comp(p, cx, cy, cid, c)

    def _paint_comp(self, p, cx, cy, cid, c):
        x = cx + c.cx
        y = cy + c.cy
        hw, hh = c.w / 2, c.h / 2
        rect = QRectF(x - hw, y - hh, c.w, c.h)

        # Status-based colour
        if c.status == "complete":
            border = _qc(T["green"])
            fill_alpha = 80
        elif c.status == "issue":
            border = _qc(T["amber"])
            fill_alpha = 80
        elif c.status == "scanning":
            border = _qc(T["accent"])
            fill_alpha = int(60 + c.pulse * 30)
        else:
            border = _qc(c.color, 100 + int(c.fly * 120))
            fill_alpha = 30 + int(c.fly * 50)

        # Scanning pulse indicator (small ring)
        if c.status == "scanning":
            ring_r = max(c.w, c.h) * 0.45
            ring = QRadialGradient(x, y, ring_r)
            gc = _qc(T["accent"])
            ring.setColorAt(0, QColor(gc.red(), gc.green(), gc.blue(),
                                     int(25 * c.pulse)))
            ring.setColorAt(0.8, QColor(gc.red(), gc.green(), gc.blue(), 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(ring))
            p.drawEllipse(QPointF(x, y), ring_r, ring_r)

        if cid == "motherboard":
            self._draw_mb(p, x, y, hw, hh, fill_alpha, border)
        elif cid == "cpu":
            self._draw_cpu(p, x, y, hw, hh, fill_alpha, border)
        elif cid == "gpu":
            self._draw_gpu(p, x, y, hw, hh, fill_alpha, border)
        elif cid == "ram":
            self._draw_ram(p, x, y, hw, hh, fill_alpha, border)
        elif cid == "storage":
            self._draw_ssd(p, x, y, hw, hh, fill_alpha, border)
        else:
            self._draw_card(p, x, y, hw, hh, fill_alpha, border)

        self._draw_status_dot(p, x + hw - 3, y - hh + 3, c)
        self._draw_label(p, x, y + hh + 11, c)

    # ── Motherboard ─────────────────────────────────────────────────

    def _draw_mb(self, p, x, y, hw, hh, alpha, border):
        rect = QRectF(x - hw, y - hh, hw * 2, hh * 2)
        g = QLinearGradient(x - hw, y - hh, x + hw, y + hh)
        g.setColorAt(0, QColor(34, 40, 54, alpha + 20))
        g.setColorAt(1, QColor(20, 23, 36, alpha + 12))
        p.setPen(QPen(border, 1.0))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(rect, 5, 5)

        # PCB traces
        p.setPen(QPen(_qc(_CASE_EDGE, 50), 0.5))
        for i in range(5):
            tx = x - hw + 10 + i * (hw * 2 - 20) / 4
            p.drawLine(QPointF(tx, y - hh + 8), QPointF(tx, y + hh - 8))
        for i in range(4):
            ty = y - hh + 10 + i * (hh * 2 - 20) / 3
            p.drawLine(QPointF(x - hw + 8, ty), QPointF(x + hw - 8, ty))

        # Chipset
        cs = min(hw, hh) * 0.22
        p.setPen(QPen(_qc(_CASE_EDGE, 60), 0.6))
        p.setBrush(QBrush(_qc(_CASE_DARK, 40)))
        p.drawRoundedRect(QRectF(x - cs, y - cs, cs * 2, cs * 2), 2, 2)

    # ── CPU ─────────────────────────────────────────────────────────

    def _draw_cpu(self, p, x, y, hw, hh, alpha, border):
        rect = QRectF(x - hw, y - hh, hw * 2, hh * 2)
        g = QLinearGradient(x, y - hh, x, y + hh)
        g.setColorAt(0, QColor(40, 32, 65, alpha + 30))
        g.setColorAt(1, QColor(22, 18, 40, alpha + 20))
        p.setPen(QPen(border, 1.2))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(rect, 4, 4)

        # IHS (heat spreader)
        ihs = QRectF(x - hw + 4, y - hh + 4, hw * 2 - 8, hh * 2 - 8)
        p.setPen(QPen(_qc(_CASE_EDGE, 60), 0.5))
        p.setBrush(QBrush(_qc(_CASE_DARK, 30)))
        p.drawRoundedRect(ihs, 2, 2)

        # Die
        ds = min(hw, hh) * 0.45
        die = QRectF(x - ds, y - ds, ds * 2, ds * 2)
        p.setPen(QPen(border, 0.8))
        p.setBrush(QBrush(_qc(_CASE_DARK, 20)))
        p.drawRoundedRect(die, 1, 1)

        # Die grid
        p.setPen(QPen(border, 30))
        for i in range(3):
            lx = x - ds + 3 + i * (ds * 2 - 6) / 2
            p.drawLine(QPointF(lx, y - ds + 2), QPointF(lx, y + ds - 2))
        for i in range(3):
            ly = y - ds + 3 + i * (ds * 2 - 6) / 2
            p.drawLine(QPointF(x - ds + 2, ly), QPointF(x + ds - 2, ly))

    # ── GPU ─────────────────────────────────────────────────────────

    def _draw_gpu(self, p, x, y, hw, hh, alpha, border):
        rect = QRectF(x - hw, y - hh, hw * 2, hh * 2)
        g = QLinearGradient(x - hw, y, x + hw, y)
        g.setColorAt(0, QColor(30, 26, 56, alpha + 30))
        g.setColorAt(0.5, QColor(42, 36, 72, alpha + 35))
        g.setColorAt(1, QColor(30, 26, 56, alpha + 30))
        p.setPen(QPen(border, 1.2))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(rect, 4, 4)

        # Dual fans
        fan_r = hh * 0.55
        for fx_off in [-hw * 0.35, hw * 0.35]:
            fcx = x + fx_off
            p.setPen(QPen(_qc(_CASE_EDGE, 40), 0.5))
            p.setBrush(QBrush(_qc(_CASE_DARK, 100)))
            p.drawEllipse(QPointF(fcx, y), fan_r, fan_r)
            angle = (self._tick * 4) % 360
            for blade in range(5):
                a = math.radians(angle + blade * 72)
                bx = fcx + math.cos(a) * fan_r * 0.75
                by = y + math.sin(a) * fan_r * 0.75
                p.setPen(QPen(_qc(_CASE_EDGE, 35), 0.3))
                p.drawLine(QPointF(fcx, y), QPointF(bx, by))
            # Hub
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(_qc(_CASE_EDGE, 30)))
            p.drawEllipse(QPointF(fcx, y), fan_r * 0.15, fan_r * 0.15)

    # ── RAM ─────────────────────────────────────────────────────────

    def _draw_ram(self, p, x, y, hw, hh, alpha, border):
        gap = 4
        sw = hw - gap / 2
        for side in [-1, 1]:
            sx = x + side * (sw / 2 + gap / 2)
            rect = QRectF(sx - sw / 2, y - hh, sw, hh * 2)
            g = QLinearGradient(sx, y - hh, sx, y + hh)
            g.setColorAt(0, QColor(50, 38, 100, alpha + 30))
            g.setColorAt(1, QColor(28, 20, 60, alpha + 20))
            p.setPen(QPen(border, 0.9))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(rect, 2, 2)

            # Heatspreader lines
            p.setPen(QPen(border, 20))
            for i in range(5):
                ly = y - hh + 4 + i * (hh * 2 - 8) / 4
                p.drawLine(QPointF(sx - sw / 2 + 2, ly),
                           QPointF(sx + sw / 2 - 2, ly))

    # ── SSD ─────────────────────────────────────────────────────────

    def _draw_ssd(self, p, x, y, hw, hh, alpha, border):
        rect = QRectF(x - hw, y - hh, hw * 2, hh * 2)
        g = QLinearGradient(x - hw, y - hh, x + hw, y + hh)
        g.setColorAt(0, QColor(36, 32, 52, alpha + 25))
        g.setColorAt(1, QColor(22, 20, 36, alpha + 18))
        p.setPen(QPen(border, 0.9))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(rect, 3, 3)

        # Label badge
        lr = QRectF(x - hw + 4, y - hh + 3, hw * 0.8, hh * 0.6)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(_qc(_CASE_DARK, 25)))
        p.drawRoundedRect(lr, 2, 2)

        # Activity LED
        pulse = 0.3 + 0.7 * math.sin(self._tick * 0.1)
        p.setBrush(QBrush(QColor(74, 222, 128, int(100 * pulse))))
        p.drawEllipse(QPointF(x + hw - 7, y), 1.8, 1.8)

    # ── Generic card ────────────────────────────────────────────────

    def _draw_card(self, p, x, y, hw, hh, alpha, border):
        rect = QRectF(x - hw, y - hh, hw * 2, hh * 2)
        g = QLinearGradient(x, y - hh, x, y + hh)
        g.setColorAt(0, QColor(35, 30, 55, alpha + 25))
        g.setColorAt(1, QColor(20, 18, 32, alpha + 18))
        p.setPen(QPen(border, 0.8))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(rect, 3, 3)

    # ── Status dot ──────────────────────────────────────────────────

    def _draw_status_dot(self, p, x, y, c):
        if c.status == "pending":
            return
        r = 5

        if c.status == "scanning":
            gc = _qc(T["accent"])
            g = QRadialGradient(x, y, r * 2.5)
            g.setColorAt(0, QColor(gc.red(), gc.green(), gc.blue(),
                                  int(60 * c.pulse)))
            g.setColorAt(1, QColor(gc.red(), gc.green(), gc.blue(), 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(x, y), r * 2.5, r * 2.5)
            p.setBrush(QBrush(_qc(T["accent"])))
            p.drawEllipse(QPointF(x, y), r, r)

        elif c.status == "complete":
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(_qc(T["green"], 200)))
            p.drawEllipse(QPointF(x, y), r, r)
            p.setPen(QPen(QColor(11, 13, 18), 1.4))
            p.drawLine(QPointF(x - 2, y), QPointF(x - 0.5, y + 2))
            p.drawLine(QPointF(x - 0.5, y + 2), QPointF(x + 3, y - 2))

        elif c.status == "issue":
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(_qc(T["amber"], 200)))
            tri = QPolygonF([
                QPointF(x, y - r - 1),
                QPointF(x - r - 1, y + r),
                QPointF(x + r + 1, y + r),
            ])
            p.drawPolygon(tri)
            p.setPen(QPen(QColor(11, 13, 18), 1.0))
            p.drawLine(QPointF(x, y - r + 2), QPointF(x, y + r - 2))
            p.drawEllipse(QPointF(x, y + r - 3), 0.8, 0.8)

    # ── Label ───────────────────────────────────────────────────────

    def _draw_label(self, p, x, y, c):
        if c.fly < 0.25 and c.status == "pending":
            return
        font = QFont("Segoe UI", 9)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(font)

        if c.status == "complete":
            col = _qc(T["green"])
        elif c.status == "issue":
            col = _qc(T["amber"])
        elif c.status == "scanning":
            col = _qc(T["accent"])
        else:
            col = _qc(T["text_dim"])

        a = min(1.0, c.fly * 3) if c.fly < 0.4 else 1.0
        col.setAlpha(int(210 * a))
        p.setPen(QPen(col))
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(c.label)
        p.drawText(QPointF(x - tw / 2, y + 4), c.label)

    # ── Bottom label ────────────────────────────────────────────────

    def _paint_label(self, p, x, y):
        if not self._label:
            return
        font = QFont("Segoe UI", 13)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        font.setWeight(QFont.DemiBold)
        p.setFont(font)
        p.setPen(QPen(_qc(T["accent"])))
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(self._label)
        p.drawText(QPointF(x - tw / 2, y), self._label)

        # Underline accent
        ul = tw + 10
        grad = QLinearGradient(x - ul / 2, y + 5, x + ul / 2, y + 5)
        grad.setColorAt(0, QColor(139, 92, 246, 0))
        grad.setColorAt(0.5, QColor(139, 92, 246, 80))
        grad.setColorAt(1, QColor(139, 92, 246, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRect(QRectF(x - ul / 2, y + 3, ul, 2))
