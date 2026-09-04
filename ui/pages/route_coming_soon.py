"""Route Analyzer — 'coming soon' screen, ported from the reference
route-analyzer-realistic-globe.html into our PySide6 stack.

Two-column layout: a rotating dotted-Earth globe (real land mask, arcs between
example cities, city labels) on the left, and a sidebar of cards on the right.
All numbers/locations on the globe are illustrative, never a live trace.
The globe rotates to keep the page feeling alive; every other element is
static — no progress indicator, no navigation to a finished product.
"""
from __future__ import annotations

import base64
import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

# ---- color tokens (reference stylesheet) -----------------------------------
BG_VOID = QColor("#08050f")
BG_DEEP = QColor("#120a26")
VIOLET_500 = QColor("#7c5cff")
VIOLET_300 = QColor("#b6a3ff")
INK_100 = QColor("#f4f2fb")
INK_400 = QColor("#8d84ab")
INK_600 = QColor("#4f4870")
SIGNAL = QColor("#43e6d6")
LINE = QColor(140, 120, 220, 46)          # rgba(140,120,220,0.18)
LINE_BORDER = "rgba(140, 120, 220, 46)"
PANEL = "rgba(255, 255, 255, 7)"          # rgba(255,255,255,0.025)
SIGNAL_BORDER = "rgba(67, 230, 214, 64)"  # rgba(67,230,214,0.25)

LAND_B64 = (
    "//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AA///////////////////////////////////////////////////////AAAf///////////////////////////////////////////////////////4AAAA///////////////8H/////////////////////////////////////gAAAAAH//////////////AAHh//////////////////////////////////wAAAAAAA/////////////IAAAAH////////////////////////////////+AAAAAAAAf///////////gAAAH+AAf//////////////////////////////+AAAAABgP///////////4AcAAD+AP////////////////////////////////gAAAAAD////////////8OAAAA8Af////////////////////////////////4AAAAAAAx///////////wAAAAAAB////////////////////////////////gAAAAAAAD/////////////AAAAAAD///////////////////////////////gAAAAAAAAAf///4AH/////wAAAAAAA//////////////////////////////gAAAAAAAAAAAbEAA//////+AAAAAAAD/////////////////////////////8AAAAAAAAAAAAAABUBwBED/AAAAAAAB//////////////////////////////wAAAAAAAAAAAAAA5AAAGM8AAAAAAAAP////////////7////////////////4AAAAAAAAAAAAAAAAAAAd+AAAAAAAABgP///3//////8////////////////AAAAAAAAAAAAAAAAAAAEb8AAAAAAAAAAAACAAH/////4f/////////////+AAAAAAAAAAAAAAAAAAAAAw4AAAAAAAAAAAAAAAED////8A/////////////AAAAAAAAAAAAAAAAAAAAAABgAAAAAAAAAAAAAAAAAP///8AH//////////4AAAAAAAAAAAAAAAAAAAAAAADwAAAAAAAAAAAAAAAAAAX4AAAAH////wPz//AAAAAAAAAAAAAAAAAAAAAAAAAdAAAAAAAAAAAAAAAAAADwAAAAAAA4DAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAGAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAC4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAOAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAuAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH8AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD+AAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAF/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAAAAAAAAAAAAAAAAH+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB4AAAAAAAAAAAAAAAAAAB/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA8AAAAAAAAAAAAAAAAAAB/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAcAAAAAAAAAAAAAAAAAAC/wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMAAAHAAAAAAAAAAAAAAAAAAC/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAOAAADgAAAAAAAAAAAAAAAAAB/sAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWAAAB4AAAAAAAAAAAAAAAAAB/8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAiAAAAIAAAAAAAAAAAAAAAAAB/8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAcAAAAAAAAAAAAAAAAAB//4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHsAAAAeAAAAAAAAAAAAAAAAAB//8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/AAAAQAAAAAAAAAAAAAAAAAA//4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABP/gAAAgAAAAAAAAAAAAAAAAAA//4AAAAAAAAAAAAAAAAAAAAAAAAAAAAGAABf/gAAAAAAAAAAAAAAAAAAAAAAf//gAAAAAAAAAAAfgAAAAAAAAAAAAAAfAAC//wAAAAAAAAAAAAAAAAAAAAAAf//wAAAAAAAAAAA/8AAAAAAAAAAAAAAP+AH//wAAAAAAAAAAAAAAAAAAAAAAf//4AAAAAAAAAAAf/AAAAAAAAAAAAAAP/4f//4AAAAAAAAAAAAAAAAAAAAAAf//4AAAAAAAAAAA//gAAAAAAAAAAAAAP/////8AAAAAAAAAAAAAAAAAAAAAAf//8AAAAAAAAAAA//gAAAAAAAAAAAAAf/////8AAAAAAAAAAAAAAAAAAAAAAf//+AAAAAAAAAAB//wAAAAAAAAAAAAAf/////8AAAAAAAAAAAAAAAAAAAAAAf///AAAAAAAAAAD//4AAAAAAAAAAAAAf/////8AAAAAAAAAAAAAAAAAAAAAAP///AAAAAAAAAAD//4AAAAAAAAAAAAA//////8AAAAAAAAAAAAAAAAAAAAAAP///AAAAAAAAAAH//4AAAAAAAAAAAAAf/////8AAAAAAAAAAAAAAAAAAAAAAP///gAAAAAAAAAH//+AHAAAAAAAAAAA//////4AAAAAAAAAAAAAAAAAAAAAAP///wAAAAAAAAAH///APAAAAAAAAAAA//////wAAAAAAAAAAAAAAAAAAAAAAP///8gAAAAAAAAH///APAAAAAAAAAAA//////gAAAAAAAAAAAAAAAAAAAAAAP////wAAAAAAAAH///APgAAAAAAAAAA//////AAAAAAAAAAAAAAAAAAAAAAAP////wAAAAAAAAP///APgAAAAAAAAAAH/////AAEAAAAAAAAAAAAAAAAAAAAP////wAAAAAAAAP//+AHgAAAAAAAAAAA////+AAAAAAAAAAAAAAAAAAAAAAAP////4AAAAAAAAf///AHwAAAAAAAAAAAP///4AAAAAAAAAAAAAAAAAAAAAAAP////4AAAAAAAA////wHwAAAAAAAAAAAH///4AAAACAAAAAAAAAAAAAAAAAA/////4AAAAAAAA////8HwAAAAAAAAAAAH//3wAAAAAAAAAAAAAAAAAAAAAAD/////8AAAAAAAA////+DwAAAAAAAAAAAB//DwAAAAAAAAAAAAAAAAAAAAAAH/////4AAAAAAAAf///+A4AAAAAAAAAAAA/8DwAABAAAAAAAAAAAAAAAAAAAP/////8AAAAAAAAf///+A4AAAAAAAAAAAAT8DAAAAAAAAAAAAAAAAAAAAAAAP/////8AAAAAAAAf///+AQAAAAAAAAAAAAB+DAAAAAAAAAAAAAAAAAAAAAAAf/////+AAAAAAAAP///+AAAAAAAAAAAAAAAYDAAAAAAAAAAAAAAAAAAAAAAAf/////+AAAAAAAAP///+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA///////AAAAAAAAP///8AAAAAAAAAAAAAiAAADQAAAAAAAAAAAAAAAAAAAAA///////gAAAAAAAP///8AAAAAAAAAAAAEBgAHGABAAAAAAAAAAAAAAAAAAAB///////wAAAAAAAP///8AAAAAAAAAAAHgAAA/MAUAAAAAAAAAAAAAAAAAAAB///////wAAAAAAAf///8AAAAAAAAAAB/gAAAf4AQAAAAAAAAAAAAAAAAAAAH///////gAAAAAAAf///4AAAAAAAAAADAAAAAf9xAAAAAAAAAAAAAAAAAAAAH///////AAAAAAAA////8AAAAAAAAAAMAAgAA/wAAAAAAAAAAAAAAAAAAAAAH//////8AAAAAAAA////8AAAAAAAAAAcAQsAX/gAAAAAAAAAAAAAAAAAAAAAB//////4AAAAAAAB////+AAAAAAAAAA+n5oGb+AAAAAAAAAAAAAAAAAAAAAAD/////8AAAAAAAAD/////AAAAAAAAAB6H4wC4wEAAAAAAAAAAAAAAAAAAAAAD/////wAAAAAAAAH/////gAAAAAAAAB4P8oB6AAAAAAAAAAAAAAAAAAAAAAAD////6AAAAAAAAAD/////gAAAAAAAADwP8gAAAAAAAAAAAAAAAAAAAAAAAAAB////+AAAAAAAAAD/////wAAAAAAAAH4f+YIAAAAAAAAAAAAAAAAAAAAAAAAA////8AAAAAAAAAD/////8AAAAAAAAHYD8AAAAAAAAAAAAAAAAAAAAAAAAAAAf///8AAAAAAAAAD/////+AAAAAAAAMwB8AAAAAAAAAAAAAAAAAAAAAAAAAAAf///4AAAAAAAAAD//////AAAAAAAAZwg8AAAAAAAAAAAAAAAAAAAAAAAAAAAf///wAAAAAAHiA///////gAAAAAAAxwAegAAAAAAAAAAAAAAAAAAAAAAAAAAf//4AAAAAAAP/x///////gAAAAAAABgAGRAAAAAAAAAAAAAAAAAAAAAAAAAAf//wAAAAAAAf/////////wAAAAMAACAAALgAAAAAAAAAAAAAAAAAAAAAAAAE///gAAAAAAA//////////wAAAAMAAGAAEHgAAAAAAAAAAAAAAAAAAAAAAAATv//AAAAAAAB//////////4AAABgAAEEACAgAAAAAAAAAAAAAAAAAAAAAAAAgHf8AAAAAAAD//////////4AAABwAAECABEAAAAAAAAAAAAAAAAAAAAAAAABgD8IAAAAAAAH/////////w8AAADwAAEPgADAAAAAAAAAAAAAAAAAAAAAAAADgAoAAAAAAAAP/////////wAAAADwAEEfwAjAAAAAAAAAAAAAAAAAAAAAAAAHgAAAAAAAAAAP/////////sAAAAH4AAH/wAWAAAAAAAAAAAAAAAAAAAAAAAB/gAABAAAAAAAP/////////PAAAAH4AAH/wAUAAAAAAAAAAAAAAAAAAAAAAAD/gAAAAAAAAAAf////////+f4AAAH4AAP/gAYAAAAAAAAAAAAAAAAAAAAAABvwAAAAAAAAAAAP////////+f+AAAP8ABP/gAwAAAAAAAAAAAAAAAAAAAAAAP/wAAAAAAAAAAAP////////8f/gAAP+ABv/AAYAAAAAAAAAAAAAAAAAAAAAA//wAQBgAAAAAAAP////////4//4AAP/AB/+AAYAAAAAAAAAAAAAAAAAAAAAD/h4AA8AAAAAAAAP////////w//8AAP/gB/8YAAAAAAAAAAAAAAAAAAAAAAAH/A4AcAAAAAAAAAP////////x//8AAf/4D/+AAAAAAAAAAAAAAAAAAAAAAAAH+A8A4AAAAAAAAAP////////z//+ABf/4H//IAAAAAAAAAAAAAAAAAAAAAAAH+AAjAAAAAAAAAAP////////j///AD///v///AAAAAAAAAAAAAAAAAAAAAACP+AAeAAAAAAAAAAP////////H///AH///////4QAAAAAAAAAAAAAAAAAAAACf+AAAAAAAAAAAAAH////////H/98AP///////8QAAAAAAAAAAAAAAAAAAAAM/+AAAgAAAAAAAAAD///////+P/8IAf///////+AAAAAAAAAAAAAAAAAAAAAJ/+AAEAAAAAAAAAAD///////+f/4D//////////AAAAAAAAAAAAAAAAAAAAAx/+AAMAAAAAAAAAAB///////8//w3//////////gAAAAAAAAAAAAAAAAAAAA3/+AAMAAAAAAAAAAA///////+//j///////////gAAAAAAAAAAAAAAAAAAAAv//gAMAAAAAAAAAAAP//////7//n///////////wAAAAAAAAAAAAAAAAAAABP///hYAAAAAAAAAAAH/////////n///////////wAAAAAAAAAAAAAAAAAAADf////4AAAAAAAAAAAH////H+///////////////wAAAAAAAAAAAAAAAAAAAD/////8AAAAAAAAAAAH///8PgB//////////////wBAAAAAAAAAAAAAAAAAAH/////+AAAAAAAAAAAD///AAAA//////////////gDQAAAAAAAAAAAAAAAAAP//////gAAAAAAAAAAA//+AAAA//////////////gA6AAAAAAAAAAAAAAAAA///////wAAAAAAAAAAA//+AAQG//////////////AYfwAAAAAAAAAAAAAAAB///////wAAAAAAAAAAAAf+AAAA//////////////gcD4AAAAAAAAAAAAAAAD///////wAAAAAAAAAAC+AHEBF///////////////4cB4AAAAAAAAAAAAAAAH///////4AAAAAAAAAAD/AAeDj///////////////A4AIAAAAAAAAAAAAAAAH///////4AAAAAAAAAAH/AEBDH//////////////8AwAMAAAAAAAAAAAAAAAP///////8AAAAAAAAAAD/iECOn///////////////P4AMAAAAAAAAAAAAAAAP///////+AAAAAAAAAAD/gEPP8/1//////////////8AAAAAAAAAAAAAAAAAP////////wAAAAAAAAAD/8E4P+BA//////////////8AAAAAAAAAAAAAAAAAP////////wAAAAAAAAAH/8Bw/8AB///////////////YHwAAAAAAAAAAAAAAP////////4wAAAAAAAAAB/5j/+AD///////////////8DwAAAAAAAAAAAAAAP/////////cAAAAAAAAAB//v//DP///////////////+CAAAAAAAAAAAAAAAH/////////xgAAAAAAAAB/////iP////////////////CAgAAAAAAAAAAAAAP/////////4AwAAAAAAAD//////z////////////////hAAAAAAAAAAAAAAAP/////////AfwAAAAAAAP///////////////////////wAAAAAAAAAAAAAAAb////////8wPgAAAAAAAB///////////////////////4AAAAAAAAAAAAAABv/////////AEAAAAAAAAAP//////////////////////5AAAAAAAAAAAAAAB///////////yAAAAAAAAPn//////////////////////5AAAAAAAAAAAAAAD///////8///+AAAAAAAOfx///////////////////////AAYAAAAAAAAAAAn///////8///8AAAAAAAHPg//////////////////////7AAYAAAAAAAAAABv///////w///4AAAAAAAPDAG3///////////////////+YAA8AAAAAAAAAAB3///////w///wAAAAAAAD+AEkD//////////////////9gAA/AAAAAAMAAAB///////4BP/+AAAAAAAAAYAG4D///////////////////AAA/gAAAAADAAAE///////gAP/+AAAAAAAAAcAGeD///////////////////gAAfgAAAAABkAAN//////8AAf/8AAAAAAAABYAA+Af//////////////////4AAHgAAAAAf4AAv//////wAA/8YAAAAAAAAAAAe/A///////////////////+AID4AAAAb/9wH///////wAAfwQAAAAAAAAAAA//gAf///////////////////+A0AAAAH/+T////////wAAf4AAA/AAAAAAAB//D//////////////////////jP+AAAH///////////4AC/AAAB/AAAAABAB//D///////////////////////3/wAAD////////////AAAewAD/gAAAAAAAH/j//////////////////////////AAAP///////////z4g/wAH/wAAPwAAAB/4//n//////////////////////+BwP////////////7g//AAP/gAAf+AAAA/8P+R///////////////////////v8P////////////9gD+OAH/9gAL8AAAAf//+B////////////////////////wAf////////f///4A/4Af//wAAAAAAAH////E////P/////////////////8AH///////+BeDfxwa+wAf//8AAAAAAAT///8GPf//3/////////////////AAB////n//4fnvvR5P+AAH///+AAAAAAA///gAQAfng///////////////3/AAA//+wALAH//w+A5/6AAz////wAAAAAAR/AAAABgPv/////////////8AEAwAABwAAAAAP/8A8X//wAAD///+4AAAAAAA6AAAB4Afve///////+///54AABAAAAAAAAAfP/cPQd+8AAB////3wAAAAAAAAAAADwAHkZ///////8AP/AAAAAAAAAAAAAAP7Q4ved/wAAA////+wAAAAAAAAAAAA4AAAX///9//j8AAAAAAAAAAAAAAAAAP8AACcgAAAAD/////wAAAAAAAAAAAAeAAAAn///gAAACEAAAAAAAAAAAAAAAABPwM7/8AAAH/////8AAAAAAAAAAAAPgAAAD///+AAAA/DgAAAAAAAAAAAAAAr5pWDgAABA//////8AAAAAAAAAAAAAfgAAAH///AAAAWAAAAAAAAAAAAAAAA+AAAgP+Af///////3AAAAABAAAAAAAAAAAAAA/AAAAAAAAAAAAAAAAAAAAAAAOAJgB/4////////5AAAAAPjAAAAAAAAAAAACAAAAAAAAAAAAAAAAAAAAAAAAADgP2/wD///////+AAAAAfwAAAAAAAAAAAA84AAAAAAAAAAAAAAAAAAAAAAAAAM/7//wH//////9gAAAACf8AAAEBAAAAAP0AAAAAAAAAAAAAAAAAAAAAAAAAAAeL+//P///////8AAAAAAAAAAAcRAAAADgAAAAAAAAAAAAAAAAAAAAAAAAAAAAK///8f5z/+PZgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf8AAAP35/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
)


# ---- lucide icons (ISC, lucide-static) ------------------------------------
# Inline so the bundled app needs no external assets. Rendered as mono-stroke
# glyphs tinted via "currentColor" replacement.
_LUCIDE = {
    "route": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/></svg>""",
    "gauge": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/></svg>""",
    "package": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><path d="m3.3 7 7.703 4.734a2 2 0 0 0 1.994 0L20.7 7"/><path d="m7.5 4.27 9 5.15"/></svg>""",
    "activity": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/></svg>""",
    "triangle-alert": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>""",
    "network": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/></svg>""",
    "server": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/></svg>""",
    "search": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>""",
    "arrow-up-right": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 7h10v10"/><path d="M7 17 17 7"/></svg>""",
}


def _svg_pixmap(svg_text: str, color: QColor, size: int) -> QPixmap:
    """Render an inline SVG glyph to a crisp logical-size pixmap."""
    svg = svg_text.replace("currentColor", color.name())
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer = QSvgRenderer()
    renderer.load(svg.encode("utf-8"))
    renderer.render(p, QRectF(0, 0, pm.width() - 1, pm.height() - 1))
    p.end()
    pm.setDevicePixelRatio(2.0)
    return pm


def _pick_family(*names: str) -> str:
    fams = set(QFontDatabase.families())
    for name in names:
        if name in fams:
            return name
    return names[-1]


def _reduced_motion() -> bool:
    """Windows 'Show animations' toggle (HKCU Accessibility Visual Effects)."""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\Accessibility\Visual Effects",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "User preference")
            return str(value).strip().lower() == "no animation"
    except Exception:
        return False


class _Backdrop(QWidget):
    """Reference .bg + .grid-noise: deep vertical gradient, violet glow top-left,
    faint teal glow bottom-right, 56px grid masked toward the edges."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._grid: QPixmap | None = None

    def _ensure_grid(self):
        w, h = self.width(), self.height()
        if self._grid is not None and self._grid.size() == self.size():
            return
        pm = QPixmap(max(1, w), max(1, h))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setPen(QPen(QColor(140, 120, 220, 18), 1))
        step = 56
        x = step
        while x < w:
            p.drawLine(x, 0, x, h)
            x += step
        y = step
        while y < h:
            p.drawLine(0, y, w, y)
            y += step
        p.end()
        m = QPainter(pm)
        m.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        g = QRadialGradient(QPointF(w / 2.0, h * 0.25), max(w, h) * 0.65)
        g.setColorAt(0.0, QColor(0, 0, 0, 255))
        g.setColorAt(0.65, QColor(0, 0, 0, 120))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        m.fillRect(0, 0, w, h, g)
        m.end()
        self._grid = pm

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        base = QLinearGradient(0, 0, 0, h)
        base.setColorAt(0.0, BG_DEEP)
        base.setColorAt(0.6, BG_VOID)
        base.setColorAt(1.0, BG_VOID)
        p.fillRect(QRectF(0, 0, w, h), base)
        # violet glow, top-left
        g1 = QRadialGradient(QPointF(w * 0.25, h * 0.10), max(w, h) * 0.55)
        c1 = QColor(VIOLET_500)
        c1.setAlphaF(0.22)
        g1.setColorAt(0.0, c1)
        g1.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, 0, w, h), g1)
        # faint teal glow, bottom-right
        g2 = QRadialGradient(QPointF(w * 0.90, h * 0.85), max(w, h) * 0.42)
        c2 = QColor(SIGNAL)
        c2.setAlphaF(0.06)
        g2.setColorAt(0.0, c2)
        g2.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, 0, w, h), g2)
        # grid texture
        self._ensure_grid()
        if self._grid is not None:
            p.drawPixmap(0, 0, self._grid)


class _PulseDot(QWidget):
    """CSS-style pulsing live dot (box-shadow ring, ~2.2s)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)
        self._t0 = None

    def start(self):
        if self._t0 is None:
            self._t0 = time.monotonic()
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        c = QPointF(self.width() / 2.0, self.height() / 2.0)
        if self._t0 is not None:
            ph = ((time.monotonic() - self._t0) % 2.2) / 2.2
            ring = 0.5 + 0.5 * math.sin(ph * 2 * math.pi)
        else:
            ring = 0.0
        c_ring = QColor(SIGNAL)
        c_ring.setAlphaF(int(110 * (1.0 - ring)) / 255.0)
        p.setPen(QPen(c_ring, 1.4))
        p.drawEllipse(c, 3.2 + 4.2 * ring, 3.2 + 4.2 * ring)
        p.setPen(Qt.NoPen)
        p.setBrush(SIGNAL)
        p.drawEllipse(c, 2.6, 2.6)


class _GlobeView(QWidget):
    """Rotating dotted-Earth globe: land-masked point sphere, example arcs
    between cities, labelled city markers. Illustrative only."""

    TILT = 18 * math.pi / 180.0

    def __init__(self, parent, reduced: bool = False):
        super().__init__(parent)
        self._reduced = reduced
        self._rotation = 0.0
        self._tilt = self.TILT
        self._drag = False
        self._last: QPointF | None = None
        self.setCursor(Qt.OpenHandCursor)
        self._dots: list[tuple[float, float, float]] | None = None
        self._arcs: list[list[tuple[float, float, float]]] = []
        self._cities = [
            ("Cape Town", -33.9, 18.4),
            ("Johannesburg", -26.2, 28.0),
            ("London", 51.5, -0.1),
            ("Frankfurt", 50.1, 8.7),
            ("Dubai", 25.2, 55.3),
            ("Singapore", 1.35, 103.8),
            ("Sydney", -33.9, 151.2),
            ("New York", 40.7, -74.0),
        ]
        self._city_pts = []
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)
        self._ensure_geo()

    # ---- geometry -----------------------------------------------------------
    def _ensure_geo(self):
        if self._dots is not None:
            return
        try:
            land = base64.b64decode(LAND_B64)
        except Exception:
            land = b""

        def is_land(lat_deg: float, lon_deg: float) -> bool:
            if not land:
                return True
            la = max(-90, min(90, int(round(lat_deg))))
            lo = ((int(round(lon_deg)) + 180) % 360 + 360) % 360 - 180
            idx = (la + 90) * 360 + (lo + 180)
            byte_idx = idx >> 3
            if byte_idx >= len(land):
                return True
            return ((land[byte_idx] >> (7 - (idx & 7))) & 1) == 1

        n = 5200
        dots = []
        for i in range(n):
            y = 1.0 - (i / (n - 1)) * 2.0
            radius = math.sqrt(max(0.0, 1.0 - y * y))
            theta = math.pi * (3 - math.sqrt(5)) * i
            x = math.sin(theta) * radius
            z = math.cos(theta) * radius
            lat = math.asin(y) * 180.0 / math.pi
            lon = math.atan2(x, z) * 180.0 / math.pi
            if is_land(lat, lon) and random.random() < 0.95:
                dots.append((x, y, z))
        self._dots = dots

        def to_vec(lat_deg: float, lon_deg: float):
            lat = lat_deg * math.pi / 180.0
            lon = lon_deg * math.pi / 180.0
            return (math.cos(lat) * math.sin(lon), math.sin(lat),
                    math.cos(lat) * math.cos(lon))

        self._city_pts = [to_vec(lat, lon) for _, lat, lon in self._cities]

        pairs = [(0, 2), (0, 4), (1, 5), (4, 6), (2, 7), (3, 5)]
        self._arcs = []
        for a, b in pairs:
            pta, ptb = self._city_pts[a], self._city_pts[b]
            dot = pta[0] * ptb[0] + pta[1] * ptb[1] + pta[2] * ptb[2]
            omega = math.acos(max(-1.0, min(1.0, dot)))
            pts = []
            for t in range(41):
                f = t / 40.0
                if omega < 0.0001:
                    pts.append(pta)
                    continue
                w1 = math.sin((1 - f) * omega) / math.sin(omega)
                w2 = math.sin(f * omega) / math.sin(omega)
                pts.append((pta[0] * w1 + ptb[0] * w2,
                            pta[1] * w1 + ptb[1] * w2,
                            pta[2] * w1 + ptb[2] * w2))
            self._arcs.append(pts)

    # ---- lifecycle ----------------------------------------------------------
    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _advance(self):
        if not self._reduced and not self._drag:
            self._rotation += 0.0022
        self.update()

    # ---- interaction (drag to spin / tilt) ----------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = True
            self._last = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag and self._last is not None:
            pos = event.position()
            self._rotation += (pos.x() - self._last.x()) * 0.008
            self._tilt += (pos.y() - self._last.y()) * 0.003
            self._tilt = max(-math.radians(60), min(math.radians(30), self._tilt))
            self._last = pos
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = False
            self._last = None
            self.setCursor(Qt.OpenHandCursor)
            super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self.setCursor(Qt.OpenHandCursor if not self._drag else Qt.ClosedHandCursor)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._drag:
            self.unsetCursor()
        super().leaveEvent(event)

    # ---- projection / painting ----------------------------------------------
    def _rot_y(self, v, r):
        c = math.cos(r)
        s = math.sin(r)
        return (v[0] * c - v[2] * s, v[1], v[0] * s + v[2] * c)

    def _tilt_x(self, v):
        c = math.cos(self._tilt)
        s = math.sin(self._tilt)
        return (v[0], v[1] * c - v[2] * s, v[1] * s + v[2] * c)

    def _project(self, v, cx, cy, r):
        r1 = self._rot_y(v, self._rotation)
        r2 = self._tilt_x(r1)
        return (cx + r2[0] * r, cy - r2[1] * r, r2[2])

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        cx = w / 2.0
        cy = h / 2.0
        r = min(w, h) * 0.44

        # sphere base
        grad = QRadialGradient(QPointF(cx - r * 0.35, cy - r * 0.4), r * 1.05)
        grad.setColorAt(0.0, QColor(124, 92, 255, 51))
        grad.setColorAt(0.55, QColor(20, 12, 42, 230))
        grad.setColorAt(1.0, QColor(6, 4, 12, 250))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(140, 120, 220, 89), 1))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(QPen(QColor(140, 120, 220, 38), 1))
        p.drawEllipse(QPointF(cx, cy), r * 1.045, r * 1.045)

        # land dots
        projected = [self._project(d, cx, cy, r) for d in self._dots]
        for px, py, pz in projected:
            if pz <= 0.02:
                continue
            depth = pz
            rad = 1.1 + depth * 0.7
            p.setPen(Qt.NoPen)
            c = QColor(VIOLET_300)
            c.setAlphaF(min(1.0, 0.18 + depth * 0.55))
            p.setBrush(c)
            p.drawEllipse(QPointF(px, py), rad, rad)

        # arcs between example cities
        for idx, arc in enumerate(self._arcs):
            path = QPainterPath()
            started = False
            for v in arc:
                lifted = (v[0] * 1.06, v[1] * 1.06, v[2] * 1.06)
                px, py, pz = self._project(lifted, cx, cy, r)
                if pz <= 0:
                    started = False
                    continue
                if not started:
                    path.moveTo(px, py)
                    started = True
                else:
                    path.lineTo(px, py)
            if not path.isEmpty():
                p.setPen(QPen(QColor(VIOLET_300 if idx % 2 == 0 else SIGNAL),
                              1.1, Qt.SolidLine))
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)

        # city markers + labels
        label_font = QFont(_pick_family("JetBrains Mono", "Cascadia Mono",
                                        "JetBrains Mono", "Courier New"))
        label_font.setPixelSize(10)
        p.setFont(label_font)
        fm = p.fontMetrics()
        for idx, (name, _lat, _lon) in enumerate(self._cities):
            px, py, pz = self._project(self._city_pts[idx], cx, cy, r)
            fade = max(0.0, min(1.0, 0.3 + pz * 1.2))
            if pz <= 0.05 or fade <= 0.001:
                continue
            # glow under marker (shadowBlur equivalent)
            glow_color = QColor(SIGNAL if idx == 0 else INK_100)
            glow_color.setAlphaF(0.35 * fade)
            p.setPen(Qt.NoPen)
            p.setBrush(glow_color)
            p.drawEllipse(QPointF(px, py), 6.0, 6.0)
            # marker
            mcolor = QColor(SIGNAL if idx == 0 else INK_100)
            mcolor.setAlphaF(fade)
            p.setBrush(mcolor)
            p.drawEllipse(QPointF(px, py), 2.6, 2.6)
            # label panel above marker
            tw = fm.horizontalAdvance(name)
            lw = tw + 14
            lh = fm.height() + 4
            lx = px - lw / 2.0
            ly = py - lh - 6
            p.setPen(QPen(QColor(140, 120, 220, int(46 * fade)), 1))
            p.setBrush(QColor(20, 12, 42, int(0.75 * 255 * fade)))
            p.drawRoundedRect(QRectF(lx, ly, lw, lh), 5, 5)
            text_color = QColor(INK_100)
            text_color.setAlphaF(fade)
            p.setPen(text_color)
            p.drawText(QRectF(lx, ly, lw, lh),
                       Qt.AlignCenter, name)


class RouteComingSoonPage(QWidget):
    """'Coming soon' Route Analyzer page (reference globe design)."""

    def __init__(self, ctx=None, navigate=None, parent=None, reduced_motion=None):
        super().__init__(parent)
        self.ctx = ctx
        self.navigate = navigate
        self._reduced = _reduced_motion() if reduced_motion is None else bool(reduced_motion)
        self._wide = True

        self._display_family = _pick_family(
            "Segoe UI")
        self._body_family = _pick_family("Segoe UI", "Arial")
        self._mono_family = _pick_family(
            "JetBrains Mono", "Cascadia Mono", "JetBrains Mono", "Courier New")

        self._backdrop = _Backdrop(self)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._scroll.viewport().setAutoFillBackground(False)

        inner = QWidget()
        inner.setObjectName("ComingSoonContent")
        inner.setStyleSheet("QWidget#ComingSoonContent { background: transparent; }")
        self._root_lay = QVBoxLayout(inner)
        self._root_lay.setContentsMargins(0, 0, 0, 0)
        self._col = self._build_column()
        self._root_lay.addWidget(self._col, 1)
        self._scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll, 1)

    # ---- construction -------------------------------------------------------
    def _build_column(self) -> QWidget:
        col = QWidget(self)
        lay = QVBoxLayout(col)
        lay.setContentsMargins(28, 40, 28, 36)
        lay.setSpacing(0)
        self._col_lay = lay

        # ---- top header (centered, capped 660) ----
        top = QWidget(col)
        top.setFixedWidth(680)
        tlay = QVBoxLayout(top)
        tlay.setContentsMargins(0, 0, 0, 0)
        tlay.setSpacing(0)

        brand = QLabel("MAXIMUM TWEAKS")
        brand.setFont(self._font(self._mono_family, 18, 700, 2.2))
        brand.setStyleSheet(f"color: {INK_400.name()}; background: transparent;")
        brand.setAlignment(Qt.AlignHCenter)
        tlay.addWidget(brand)
        tlay.addSpacing(14)

        eyebrow = QHBoxLayout()
        eyebrow.setSpacing(8)
        eyebrow.setAlignment(Qt.AlignHCenter)
        self._dot = _PulseDot()
        eyebrow.addWidget(self._dot, 0, Qt.AlignVCenter)
        eyebrow_label = QLabel("ROUTE ANALYZER \u00b7 COMING SOON")
        eyebrow_label.setFont(self._font(self._mono_family, 14, 600, 1.5))
        eyebrow_label.setStyleSheet(f"color: {VIOLET_300.name()}; background: transparent;")
        eyebrow.addWidget(eyebrow_label, 0, Qt.AlignVCenter)
        tlay.addLayout(eyebrow)
        tlay.addSpacing(18)

        self._h1 = QLabel(
            "Your ping is a symptom. "
            "<span style=\"color:#b6a3ff;font-weight:700;\">Route Analyzer "
            "finds the cause.</span>")
        self._h1.setWordWrap(True)
        self._h1.setAlignment(Qt.AlignHCenter)
        self._h1.setTextInteractionFlags(Qt.NoTextInteraction)
        self._h1.setFont(self._font(self._display_family, 34, 600))
        self._h1.setStyleSheet(f"color: {INK_100.name()}; background: transparent;")
        tlay.addWidget(self._h1)
        tlay.addSpacing(15)

        lede = QLabel(
            "It traces the real network path your connection takes to a server "
            "\u2014 every hop between your PC, your ISP, and the destination "
            "\u2014 so you can see why your ping is high, not just what it is.")
        lede.setWordWrap(True)
        lede.setAlignment(Qt.AlignHCenter)
        lede.setFont(self._font(self._body_family, 15))
        lede.setStyleSheet(f"color: {INK_400.name()}; background: transparent;")
        tlay.addWidget(lede)

        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.addStretch(1)
        h.addWidget(top, 100)
        h.addStretch(1)
        lay.addLayout(h)
        lay.addSpacing(30)

        # ---- content grid ----
        self._grid_host = QWidget(col)
        self._globe_host = self._build_globe_host()
        self._side = self._build_side()
        self._band_lay = QBoxLayout(QBoxLayout.LeftToRight, self._grid_host)
        self._band_lay.setContentsMargins(0, 0, 0, 0)
        self._band_lay.addWidget(self._globe_host, 1)
        self._band_lay.addWidget(self._side, 0)
        self._set_band(self._wide)
        lay.addWidget(self._grid_host, 1)

        return col

    def _card_frame(self, corners: int = 14) -> QFrame:
        f = QFrame()
        f.setObjectName("Card")
        f.setStyleSheet(
            f"#Card {{ background-color: {PANEL}; border: 1px solid {LINE_BORDER};"
            f" border-radius: {corners}px; }}")
        return f

    def _font(self, family: str, px: int, weight: int = 400, spacing: float = 0.0) -> QFont:
        f = QFont(family)
        f.setPixelSize(px)
        f.setWeight(QFont.Weight(weight))
        if spacing:
            f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
        return f

    def _build_globe_host(self) -> QWidget:
        host = QWidget()
        host.setMinimumHeight(480)
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._globe = _GlobeView(host, reduced=self._reduced)
        lay.addWidget(self._globe, 1)
        return host

    def _build_side(self) -> QWidget:
        side = QWidget()
        side.setMaximumWidth(360)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        # ---- what it checks ----
        checks = self._card_frame()
        c_lay = QVBoxLayout(checks)
        c_lay.setContentsMargins(20, 18, 20, 20)
        c_lay.setSpacing(10)
        head = self._mono_head("WHAT IT CHECKS")
        c_lay.addWidget(head)
        rows = [
            ("Where your route is going", "route"),
            ("Latency at each hop", "gauge"),
            ("Packet loss", "package"),
            ("Sudden latency spikes", "activity"),
            ("Unusual or inefficient routing", "triangle-alert"),
            ("ISP routing paths", "network"),
            ("Hops that may be adding latency", "server"),
        ]
        for text, icon_key in rows:
            row = QHBoxLayout()
            row.setSpacing(10)
            mark = self._icon_label(icon_key, VIOLET_500, 16)
            row.addWidget(mark, 0, Qt.AlignTop)
            lab = QLabel(text)
            lab.setFont(self._font(self._body_family, 13))
            lab.setWordWrap(True)
            lab.setStyleSheet(f"color: {INK_100.name()}; background: transparent;")
            row.addWidget(lab, 1)
            c_lay.addLayout(row)
        lay.addWidget(checks)

        # ---- important ----
        important = self._card_frame()
        important.setStyleSheet(
            f"#Card {{ background-color: {PANEL}; border: 1px solid {SIGNAL_BORDER};"
            " border-radius: 14px; }}")
        i_lay = QVBoxLayout(important)
        i_lay.setContentsMargins(20, 18, 20, 20)
        i_lay.setSpacing(8)
        i_head = self._mono_head("IMPORTANT")
        i_head.setStyleSheet(f"color: {SIGNAL.name()}; background: transparent;")
        i_lay.addWidget(i_head)
        i_text = QLabel(
            "Route Analyzer doesn't lower your ping. It diagnoses the route so "
            "you know where the latency is coming from \u2014 whether that's your "
            "PC, local network, ISP, upstream routing, or the path to the server. "
            "Understanding the problem is the first step to fixing it.")
        i_text.setWordWrap(True)
        i_text.setFont(self._font(self._body_family, 13))
        i_text.setStyleSheet(f"color: {INK_400.name()}; background: transparent;")
        i_lay.addWidget(i_text)
        lay.addWidget(important)

        # ---- search ----
        search = self._card_frame(12)
        search.setStyleSheet(
            f"#Card {{ background-color: {PANEL}; border: 1px solid {LINE_BORDER};"
            " border-radius: 12px; }}")
        s_lay = QHBoxLayout(search)
        s_lay.setContentsMargins(16, 12, 16, 12)
        s_lay.setSpacing(10)
        icon = self._icon_label("search", INK_600, 16)
        s_lay.addWidget(icon, 0, Qt.AlignVCenter)
        field = QLineEdit()
        field.setReadOnly(True)
        field.setText("Route lookup \u2014 not available yet")
        field.setFont(self._font(self._body_family, 13))
        field.setStyleSheet(
            f"color: {INK_600.name()}; background: transparent; border: none;")
        s_lay.addWidget(field, 1)
        arrow = QLabel()
        arrow.setFixedSize(26, 26)
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setPixmap(_svg_pixmap(_LUCIDE["arrow-up-right"], INK_600, 15))
        arrow.setStyleSheet(
            f"background: transparent; border: 1px solid {LINE_BORDER};"
            " border-radius: 13px;")
        s_lay.addWidget(arrow, 0)
        lay.addWidget(search)

        note = QLabel("This box lights up once Route Analyzer goes live.")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignHCenter)
        note.setFont(self._font(self._mono_family, 11))
        note.setStyleSheet(f"color: {INK_600.name()}; background: transparent;")
        lay.addWidget(note)

        return side

    def _icon_label(self, name: str, color: QColor, size: int) -> QLabel:
        lab = QLabel()
        lab.setFixedSize(size, size)
        lab.setPixmap(_svg_pixmap(_LUCIDE[name], color, size))
        lab.setStyleSheet("background: transparent;")
        return lab

    def _mono_head(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setFont(self._font(self._mono_family, 11, 600, 1.1))
        lab.setStyleSheet(f"color: {INK_400.name()}; background: transparent;")
        return lab

    def _set_band(self, wide: bool):
        if wide:
            self._band_lay.setDirection(QBoxLayout.LeftToRight)
            self._band_lay.setSpacing(26)
            self._side.setMaximumWidth(360)
            self._globe_host.setMinimumHeight(480)
        else:
            self._band_lay.setDirection(QBoxLayout.TopToBottom)
            self._band_lay.setSpacing(18)
            self._side.setMaximumWidth(16777215)
            self._globe_host.setMinimumHeight(400)

    # ---- lifecycle ----------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        self._backdrop.setGeometry(self.rect())
        cap = 1180
        extra = max(0, (self.width() - cap) // 2)
        self._root_lay.setContentsMargins(extra, 0, extra, 0)
        self._dot.start()
        self._globe.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._dot.stop()
        self._globe.stop()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._backdrop.setGeometry(self.rect())
        self._backdrop.update()
        wide = self.width() >= 960
        if wide != self._wide:
            self._wide = wide
            self._set_band(wide)
        px = 31 if self.width() >= 640 else 25
        self._h1.setFont(self._font(self._display_family, px, 600))
        cap = 1180
        extra = max(0, (self.width() - cap) // 2)
        self._root_lay.setContentsMargins(extra, 0, extra, 0)