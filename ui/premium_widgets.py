"""Premium visual widgets for Maximum Tweaks — scan overlay, custom painted
cards, glass dropdowns, preset bar, changes preview, and micro-interaction
components.

All rendering uses QPainter for pixel-perfect control. Animations use
QPropertyAnimation for 60fps smoothness.
"""
from __future__ import annotations

import math
import time
from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
    Property,
    QRectF,
    QPointF,
)
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QRadialGradient,
    QPen,
    QFont,
    QBrush,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QListView,
    QItemDelegate,
)

from config.app_config import THEME as T


# ──────────────────────────────────────────────────────────────
# Game icon data — local fallback art for all 12 games
# ──────────────────────────────────────────────────────────────

GAME_ICONS: dict[str, dict] = {
    "gp-001": {"initials": "FN", "color": "#818cf8", "shape": "shield",
               "platform": "EPIC GAMES", "platform_color": "#818cf8"},
    "gp-002": {"initials": "VA", "color": "#f87171", "shape": "crosshair",
               "platform": "RIOT", "platform_color": "#f87171"},
    "gp-003": {"initials": "CS", "color": "#fbbf24", "shape": "target",
               "platform": "STEAM", "platform_color": "#60a5fa"},
    "gp-004": {"initials": "CD", "color": "#8b5cf6", "shape": "bolt",
               "platform": "BATTLE.NET", "platform_color": "#60a5fa"},
    "gp-005": {"initials": "AP", "color": "#f472b6", "shape": "diamond",
               "platform": "STEAM", "platform_color": "#60a5fa"},
    "gp-006": {"initials": "OW", "color": "#fb923c", "shape": "circle",
               "platform": "BATTLE.NET", "platform_color": "#60a5fa"},
    "gp-007": {"initials": "MC", "color": "#d946ef", "shape": "cube",
               "platform": "MICROSOFT", "platform_color": "#38bdf8"},
    "gp-008": {"initials": "RL", "color": "#38bdf8", "shape": "ring",
               "platform": "EPIC GAMES", "platform_color": "#818cf8"},
    "gp-009": {"initials": "LO", "color": "#c084fc", "shape": "star",
               "platform": "RIOT", "platform_color": "#f87171"},
    "gp-010": {"initials": "RS", "color": "#94a3b8", "shape": "skull",
               "platform": "STEAM", "platform_color": "#60a5fa"},
    "gp-011": {"initials": "EF", "color": "#fb7185", "shape": "exclamation",
               "platform": "BATTLE.NET", "platform_color": "#60a5fa"},
    "gp-012": {"initials": "WZ", "color": "#a78bfa", "shape": "wave",
               "platform": "BATTLE.NET", "platform_color": "#60a5fa"},
}


def _draw_game_icon(painter: QPainter, rect: QRectF, game_id: str,
                    size: float = 40):
    """Draw a stylized game icon using QPainter paths."""
    icon = GAME_ICONS.get(game_id, {"initials": "?", "color": "#94a3b8", "shape": "circle"})
    cx, cy = rect.center().x(), rect.center().y()
    r = size / 2 - 2

    # Glow behind icon.
    glow = QRadialGradient(cx, cy, r * 1.8)
    c = QColor(icon["color"])
    glow.setColorAt(0, QColor(c.red(), c.green(), c.blue(), 40))
    glow.setColorAt(1, QColor(c.red(), c.green(), c.blue(), 0))
    painter.setBrush(QBrush(glow))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(cx, cy), r * 1.8, r * 1.8)

    # Dark circle background.
    painter.setBrush(QBrush(QColor(icon["color"])))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(cx, cy), r, r)

    # Draw shape inside.
    painter.setPen(QPen(QColor(255, 255, 255, 200), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    shape = icon["shape"]
    sr = r * 0.5
    if shape == "shield":
        path = QPainterPath()
        path.moveTo(cx, cy - sr)
        path.lineTo(cx + sr * 0.8, cy - sr * 0.3)
        path.lineTo(cx + sr * 0.6, cy + sr * 0.7)
        path.lineTo(cx, cy + sr)
        path.lineTo(cx - sr * 0.6, cy + sr * 0.7)
        path.lineTo(cx - sr * 0.8, cy - sr * 0.3)
        path.closeSubpath()
        painter.drawPath(path)
    elif shape == "crosshair":
        painter.drawEllipse(QPointF(cx, cy), sr * 0.6, sr * 0.6)
        painter.drawLine(QPointF(cx - sr, cy), QPointF(cx + sr, cy))
        painter.drawLine(QPointF(cx, cy - sr), QPointF(cx, cy + sr))
    elif shape == "target":
        painter.drawEllipse(QPointF(cx, cy), sr, sr)
        painter.drawEllipse(QPointF(cx, cy), sr * 0.5, sr * 0.5)
        painter.drawEllipse(QPointF(cx, cy), sr * 0.15, sr * 0.15)
    elif shape == "bolt":
        path = QPainterPath()
        path.moveTo(cx + sr * 0.2, cy - sr)
        path.lineTo(cx - sr * 0.5, cy + sr * 0.1)
        path.lineTo(cx + sr * 0.1, cy + sr * 0.1)
        path.lineTo(cx - sr * 0.2, cy + sr)
        path.lineTo(cx + sr * 0.5, cy - sr * 0.1)
        path.lineTo(cx - sr * 0.1, cy - sr * 0.1)
        path.closeSubpath()
        painter.drawPath(path)
    elif shape == "diamond":
        path = QPainterPath()
        path.moveTo(cx, cy - sr)
        path.lineTo(cx + sr * 0.7, cy)
        path.lineTo(cx, cy + sr)
        path.lineTo(cx - sr * 0.7, cy)
        path.closeSubpath()
        painter.drawPath(path)
    elif shape == "circle":
        painter.drawEllipse(QPointF(cx, cy), sr * 0.7, sr * 0.7)
        painter.drawEllipse(QPointF(cx, cy), sr * 0.3, sr * 0.3)
    elif shape == "cube":
        path = QPainterPath()
        path.moveTo(cx - sr * 0.6, cy - sr * 0.3)
        path.lineTo(cx, cy - sr * 0.8)
        path.lineTo(cx + sr * 0.6, cy - sr * 0.3)
        path.lineTo(cx + sr * 0.6, cy + sr * 0.5)
        path.lineTo(cx, cy + sr)
        path.lineTo(cx - sr * 0.6, cy + sr * 0.5)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(cx, cy - sr * 0.3), QPointF(cx, cy + sr * 0.2))
    elif shape == "ring":
        painter.drawEllipse(QPointF(cx, cy), sr, sr)
        painter.drawEllipse(QPointF(cx, cy), sr * 0.5, sr * 0.5)
    elif shape == "star":
        path = QPainterPath()
        for i in range(5):
            angle = math.radians(-90 + i * 72)
            x = cx + sr * math.cos(angle)
            y = cy + sr * math.sin(angle)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
            angle2 = math.radians(-90 + i * 72 + 36)
            x2 = cx + sr * 0.4 * math.cos(angle2)
            y2 = cy + sr * 0.4 * math.sin(angle2)
            path.lineTo(x2, y2)
        path.closeSubpath()
        painter.drawPath(path)
    elif shape == "skull":
        painter.drawEllipse(QPointF(cx, cy - sr * 0.15), sr * 0.7, sr * 0.65)
        painter.drawEllipse(QPointF(cx - sr * 0.25, cy - sr * 0.25), sr * 0.15, sr * 0.15)
        painter.drawEllipse(QPointF(cx + sr * 0.25, cy - sr * 0.25), sr * 0.15, sr * 0.15)
    elif shape == "exclamation":
        painter.setFont(QFont("Segoe UI", int(sr * 1.4), QFont.Bold))
        painter.drawText(rect, Qt.AlignCenter, "!")
    elif shape == "wave":
        path = QPainterPath()
        for i in range(40):
            t = i / 39
            x = cx - sr + t * sr * 2
            y = cy + sr * 0.3 * math.sin(t * math.pi * 3)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.drawPath(path)
    else:
        painter.drawEllipse(QPointF(cx, cy), sr * 0.6, sr * 0.6)

    # Initials overlay.
    painter.setPen(QColor(255, 255, 255, 220))
    painter.setFont(QFont("Segoe UI", int(size * 0.28), QFont.Bold))
    painter.drawText(rect, Qt.AlignCenter, icon["initials"])


# ──────────────────────────────────────────────────────────────
# ScanOverlay — animated glassmorphic scanning overlay
# ──────────────────────────────────────────────────────────────

class ScanOverlay(QWidget):
    """Full-screen glassmorphic overlay with 3-phase scan animation."""

    scan_complete = Signal()

    PHASE_1_DURATION = 1200
    PHASE_2_DURATION = 800
    PHASE_3_DURATION = 400

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0
        self._progress = 0.0
        self._opacity = 0.0
        self._radar_angle = 0.0
        self._scan_y = 0.0
        self.setVisible(False)

        # Animations.
        self._opacity_anim = QPropertyAnimation(self, b"overlayOpacity")
        self._opacity_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._radar_anim = QPropertyAnimation(self, b"radarAngle")
        self._radar_anim.setDuration(2000)
        self._radar_anim.setLoopCount(-1)
        self._radar_anim.setStartValue(0.0)
        self._radar_anim.setEndValue(360.0)

        self._scan_anim = QPropertyAnimation(self, b"scanY")
        self._scan_anim.setEasingCurve(QEasingCurve.InOutSine)

        self._phase_timer = QTimer(self)
        self._phase_timer.setSingleShot(True)
        self._phase_timer.timeout.connect(self._next_phase)

    def start_scan(self):
        """Start the 3-phase scanning sequence."""
        self._phase = 1
        self._progress = 0.0
        self.setVisible(True)
        self.raise_()
        self.setFocus()

        # Fade in.
        self._opacity_anim.stop()
        self._opacity_anim.setDuration(300)
        self._opacity_anim.setStartValue(0.0)
        self._opacity_anim.setEndValue(1.0)
        self._opacity_anim.start()

        # Start radar.
        self._radar_anim.start()

        # Start scan line.
        self._scan_anim.stop()
        self._scan_anim.setDuration(self.PHASE_1_DURATION)
        self._scan_anim.setStartValue(0.0)
        self._scan_anim.setEndValue(1.0)
        self._scan_anim.start()

        # Phase timer.
        self._phase_timer.start(self.PHASE_1_DURATION)
        self.update()

    def _next_phase(self):
        if self._phase == 1:
            self._phase = 2
            self._scan_anim.stop()
            self._scan_anim.setDuration(self.PHASE_2_DURATION)
            self._scan_anim.setStartValue(0.0)
            self._scan_anim.setEndValue(1.0)
            self._scan_anim.start()
            self._phase_timer.start(self.PHASE_2_DURATION)
            self.update()
        elif self._phase == 2:
            self._phase = 3
            self._radar_anim.stop()
            # Fade out.
            self._opacity_anim.stop()
            self._opacity_anim.setDuration(self.PHASE_3_DURATION)
            self._opacity_anim.setStartValue(1.0)
            self._opacity_anim.setEndValue(0.0)
            self._opacity_anim.finished.connect(self._on_scan_done)
            self._opacity_anim.start()

    def _on_scan_done(self):
        self.setVisible(False)
        self._opacity_anim.finished.disconnect(self._on_scan_done)
        self.scan_complete.emit()

    # Properties for animation.
    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, val):
        self._opacity = val
        self.update()

    def _get_radar_angle(self):
        return self._radar_angle

    def _set_radar_angle(self, val):
        self._radar_angle = val
        self.update()

    def _get_scan_y(self):
        return self._scan_y

    def _set_scan_y(self, val):
        self._scan_y = val
        self.update()

    overlayOpacity = Property(float, _get_opacity, _set_opacity)
    radarAngle = Property(float, _get_radar_angle, _set_radar_angle)
    scanY = Property(float, _get_scan_y, _set_scan_y)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._opacity)
        w, h = self.width(), self.height()

        # Dark glass background.
        p.setBrush(QBrush(QColor(9, 11, 14, 230)))
        p.setPen(Qt.NoPen)
        p.drawRect(0, 0, w, h)

        cx, cy = w / 2, h / 2

        # Radar rings.
        if self._phase in (1, 2):
            for i in range(4):
                r = 40 + i * 35
                alpha = max(0, 60 - i * 15)
                p.setPen(QPen(QColor(139, 92, 246, alpha), 1))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(cx, cy - 30), r, r)

            # Radar sweep line.
            angle = math.radians(self._radar_angle)
            line_len = 180
            ex = cx + line_len * math.cos(angle)
            ey = (cy - 30) + line_len * math.sin(angle)
            sweep = QLinearGradient(cx, cy - 30, ex, ey)
            sweep.setColorAt(0, QColor(139, 92, 246, 120))
            sweep.setColorAt(1, QColor(139, 92, 246, 0))
            p.setPen(QPen(QBrush(sweep), 2))
            p.drawLine(QPointF(cx, cy - 30), QPointF(ex, ey))

            # Sweep cone.
            cone = QPainterPath()
            cone.moveTo(cx, cy - 30)
            for a_off in range(30):
                a2 = angle - math.radians(a_off)
                cone.lineTo(cx + line_len * math.cos(a2),
                            (cy - 30) + line_len * math.sin(a2))
            cone.closeSubpath()
            cone_fill = QColor(139, 92, 246, 15)
            p.setBrush(QBrush(cone_fill))
            p.setPen(Qt.NoPen)
            p.drawPath(cone)

        # Scan line (horizontal sweep).
        if self._phase in (1, 2):
            scan_y_pos = 80 + self._scan_y * (h - 160)
            scan_pen = QPen(QColor(139, 92, 246, 180), 2)
            p.setPen(scan_pen)
            p.drawLine(QPointF(cx - 200, scan_y_pos), QPointF(cx + 200, scan_y_pos))
            # Glow around scan line.
            scan_glow = QLinearGradient(cx - 200, scan_y_pos - 15, cx - 200, scan_y_pos + 15)
            scan_glow.setColorAt(0, QColor(139, 92, 246, 0))
            scan_glow.setColorAt(0.5, QColor(139, 92, 246, 25))
            scan_glow.setColorAt(1, QColor(139, 92, 246, 0))
            p.setBrush(QBrush(scan_glow))
            p.setPen(Qt.NoPen)
            p.drawRect(QRectF(cx - 200, scan_y_pos - 15, 400, 30))

        # Status text.
        if self._phase == 1:
            status = "Detecting System Info & Executing Hardware Audit..."
            sub = "Scanning registry, active display drivers, and game directory manifests..."
        elif self._phase == 2:
            status = "Launching Competitive Game Profiles..."
            sub = "Initializing NvAPI DRS connection and loading game catalog..."
        else:
            status = "Ready"
            sub = ""

        p.setPen(QColor(T["text"]))
        p.setFont(QFont("Segoe UI", 14, QFont.Bold))
        p.drawText(QRectF(cx - 250, cy + 60, 500, 30), Qt.AlignCenter, status)
        p.setPen(QColor(T["text_dim"]))
        p.setFont(QFont("Segoe UI", 11))
        p.drawText(QRectF(cx - 280, cy + 95, 560, 30), Qt.AlignCenter, sub)

        # Progress dots.
        dot_y = cy + 140
        for i in range(3):
            dot_x = cx - 30 + i * 30
            if self._phase > i + 1 or (self._phase == i + 1 and self._scan_y > 0.5):
                p.setBrush(QBrush(QColor(T["accent"])))
            else:
                p.setBrush(QBrush(QColor(T["border"])))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(dot_x, dot_y), 4, 4)

        p.end()


# ──────────────────────────────────────────────────────────────
# LoadingCard — glassmorphic centered loading overlay
# ──────────────────────────────────────────────────────────────

class LoadingCard(QWidget):
    """Full-area glassmorphic loading card with spinner and 10-second timer."""

    loading_complete = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacity = 0.0
        self._spinner_angle = 0.0
        self._elapsed = 0.0
        self._duration = 10.0
        self.setVisible(False)

        self._fade_in = QPropertyAnimation(self, b"cardOpacity")
        self._fade_in.setDuration(400)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)

        self._spinner_anim = QPropertyAnimation(self, b"spinnerAngle")
        self._spinner_anim.setDuration(1200)
        self._spinner_anim.setLoopCount(-1)
        self._spinner_anim.setStartValue(0.0)
        self._spinner_anim.setEndValue(360.0)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(50)
        self._tick_timer.timeout.connect(self._tick)

        self._fade_out = QPropertyAnimation(self, b"cardOpacity")
        self._fade_out.setDuration(500)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.finished.connect(self._on_done)

    def start(self):
        self._elapsed = 0.0
        self._opacity = 0.0
        self.setVisible(True)
        self.raise_()
        self.setFocus()
        self._fade_in.stop()
        self._fade_in.start()
        self._spinner_anim.start()
        self._tick_timer.start()

    def _tick(self):
        self._elapsed += 0.05
        if self._elapsed >= self._duration:
            self._tick_timer.stop()
            self._spinner_anim.stop()
            self._fade_out.start()

    def _on_done(self):
        self.setVisible(False)
        self.loading_complete.emit()

    # Animated properties.
    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, val):
        self._opacity = val
        self.update()

    def _get_spinner_angle(self):
        return self._spinner_angle

    def _set_spinner_angle(self, val):
        self._spinner_angle = val
        self.update()

    cardOpacity = Property(float, _get_opacity, _set_opacity)
    spinnerAngle = Property(float, _get_spinner_angle, _set_spinner_angle)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._opacity)
        w, h = self.width(), self.height()

        # Full dark background.
        p.setBrush(QBrush(QColor(9, 11, 14, 210)))
        p.setPen(Qt.NoPen)
        p.drawRect(0, 0, w, h)

        # Centered glassmorphic card.
        card_w, card_h = 420, 260
        cx = (w - card_w) / 2
        cy = (h - card_h) / 2

        # Card shadow.
        p.setBrush(QBrush(QColor(0, 0, 0, 60)))
        p.drawRoundedRect(QRectF(cx + 4, cy + 6, card_w, card_h), 18, 18)

        # Card body.
        p.setBrush(QBrush(QColor(18, 23, 32, 220)))
        p.setPen(QPen(QColor(139, 92, 246, 40), 1))
        p.drawRoundedRect(QRectF(cx, cy, card_w, card_h), 16, 16)

        # Header.
        p.setPen(QColor(T["text"]))
        p.setFont(QFont("Segoe UI", 18, QFont.Bold))
        p.drawText(QRectF(cx, cy + 30, card_w, 30), Qt.AlignCenter, "Game Profiles")

        # Status text.
        p.setPen(QColor(T["text_dim"]))
        p.setFont(QFont("Segoe UI", 12))
        p.drawText(QRectF(cx, cy + 70, card_w, 24), Qt.AlignCenter,
                   "detecting system info ... launching")

        # Spinner arc.
        spinner_cx = w / 2
        spinner_cy = cy + 140
        spinner_r = 22
        pen = QPen(QColor(139, 92, 246, 180), 3)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(QRectF(spinner_cx - spinner_r, spinner_cy - spinner_r,
                         spinner_r * 2, spinner_r * 2),
                  int(self._spinner_angle * 16), 90 * 16)

        # Elapsed bar.
        bar_w = card_w - 80
        bar_h = 4
        bar_x = cx + 40
        bar_y = cy + card_h - 50
        frac = min(self._elapsed / self._duration, 1.0)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(T["border"])))
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)
        if frac > 0:
            p.setBrush(QBrush(QColor(T["accent"])))
            p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w * frac, bar_h), 2, 2)

        p.end()


# ──────────────────────────────────────────────────────────────
# GameListItem — premium compact card for master list
# ──────────────────────────────────────────────────────────────

class GameListItem(QFrame):
    """Premium game card with custom-painted gradient border, glow, icon,
    platform tag, and status badge."""

    clicked = Signal(str)

    def __init__(self, game_id: str, parent=None):
        super().__init__(parent)
        self.game_id = game_id
        self._selected = False
        self._hover_progress = 0.0
        self._select_progress = 0.0
        self._installed = False
        self._applied = False
        self.setObjectName("GameListItem")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(76)
        self.setMinimumWidth(200)

        self._hover_anim = QPropertyAnimation(self, b"hoverProgress")
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._select_anim = QPropertyAnimation(self, b"selectProgress")
        self._select_anim.setDuration(250)
        self._select_anim.setEasingCurve(QEasingCurve.OutCubic)

    def _get_hover_progress(self):
        return self._hover_progress

    def _set_hover_progress(self, val):
        self._hover_progress = val
        self.update()

    def _get_select_progress(self):
        return self._select_progress

    def _set_select_progress(self, val):
        self._select_progress = val
        self.update()

    hoverProgress = Property(float, _get_hover_progress, _set_hover_progress)
    selectProgress = Property(float, _get_select_progress, _set_select_progress)

    def set_selected(self, selected: bool):
        if self._selected == selected:
            return
        self._selected = selected
        self._select_anim.stop()
        self._select_anim.setStartValue(self._select_progress)
        self._select_anim.setEndValue(1.0 if selected else 0.0)
        self._select_anim.start()

    def set_installed(self, installed: bool):
        self._installed = installed
        self.update()

    def set_applied(self, applied: bool):
        self._applied = applied
        self.update()

    def enterEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.game_id)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = 12
        hover = self._hover_progress
        sel = self._select_progress

        # Background.
        bg = QColor(T["card_alt"] if sel > 0.5 else T["card"])
        p.setBrush(QBrush(bg))
        p.setPen(Qt.NoPen)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), r, r)
        p.drawPath(path)

        # Gradient border.
        if sel > 0.01:
            border_a = int(40 + sel * 80)
            grad = QLinearGradient(0, 0, w, h)
            grad.setColorAt(0, QColor(139, 92, 246, border_a))
            grad.setColorAt(0.5, QColor(255, 255, 255, int(5 + sel * 15)))
            grad.setColorAt(1, QColor(139, 92, 246, int(border_a * 0.4)))
            p.setPen(QPen(QBrush(grad), 1.5))
        elif hover > 0.01:
            border_a = int(20 + hover * 30)
            grad = QLinearGradient(0, 0, w, h)
            grad.setColorAt(0, QColor(139, 92, 246, border_a))
            grad.setColorAt(1, QColor(139, 92, 246, int(border_a * 0.3)))
            p.setPen(QPen(QBrush(grad), 1.0))
        else:
            p.setPen(QPen(QColor(T["border"]), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)

        # Selection glow.
        if sel > 0.01:
            glow = QLinearGradient(0, 0, 0, h * 0.4)
            glow.setColorAt(0, QColor(139, 92, 246, int(20 * sel)))
            glow.setColorAt(1, QColor(139, 92, 246, 0))
            p.setBrush(QBrush(glow))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(1, 1, w - 2, h * 0.4), r, r)

        # Game icon.
        icon_rect = QRectF(12, (h - 44) / 2, 44, 44)
        _draw_game_icon(p, icon_rect, self.game_id, 44)

        # Game name.
        from engine import nvprofiles
        meta = nvprofiles.GAMES.get(self.game_id, {})
        name = meta.get("name", self.game_id)
        p.setPen(QColor(T["text"]))
        p.setFont(QFont("Segoe UI", 13, QFont.Bold))
        p.drawText(QRectF(64, h * 0.14, w - 160, h * 0.32),
                   Qt.AlignVCenter | Qt.AlignLeft, name)

        # Platform tag.
        icon_data = GAME_ICONS.get(self.game_id, {})
        platform = icon_data.get("platform", "")
        plat_color = icon_data.get("platform_color", T["text_faint"])
        p.setPen(QColor(plat_color))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRectF(64, h * 0.48, 100, h * 0.25),
                   Qt.AlignVCenter | Qt.AlignLeft, platform)

        # Status badge (right side).
        if self._applied:
            badge_text = "OPTIMIZED"
            badge_bg = QColor(T["accent"])
            badge_fg = QColor(T["accent_dark"])
        elif self._installed:
            badge_text = "DETECTED"
            badge_bg = QColor(T["border"])
            badge_fg = QColor(T["text_dim"])
        else:
            badge_text = "NOT FOUND"
            badge_bg = QColor(T["border"])
            badge_fg = QColor(T["text_faint"])

        badge_x = w - 92
        badge_y = (h - 22) / 2
        badge_w = 78
        badge_h = 22
        p.setBrush(QBrush(badge_bg))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), 11, 11)
        p.setPen(QColor(badge_fg))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(QRectF(badge_x, badge_y, badge_w, badge_h),
                   Qt.AlignCenter, badge_text)

        p.end()


# ──────────────────────────────────────────────────────────────
# GlassComboBox — premium custom dropdown
# ──────────────────────────────────────────────────────────────

class GlassComboBox(QComboBox):
    """Custom styled dropdown with glassmorphism appearance."""

    def __init__(self, options: list[str] = None, parent=None):
        super().__init__(parent)
        if options:
            self.addItems(options)
        self.setFixedHeight(36)
        self.setView(QListView(self))
        self.setItemDelegate(QItemDelegate(self))
        self.setStyleSheet(f"""
            QComboBox {{
                background-color: {T['bg_alt']};
                border: 1px solid {T['border']};
                border-radius: 8px;
                padding: 6px 28px 6px 12px;
                color: {T['text']};
                font-size: 12px;
                font-weight: 600;
            }}
            QComboBox:hover {{
                border-color: rgba(139, 92, 246, 0.35);
            }}
            QComboBox:focus {{
                border-color: rgba(139, 92, 246, 0.55);
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
                subcontrol-position: center right;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {T['text_dim']};
                margin-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {T['bg_alt']};
                border: 1px solid {T['border']};
                border-radius: 8px;
                padding: 4px;
                selection-background-color: rgba(139, 92, 246, 0.12);
                selection-color: {T['accent']};
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{
                padding: 6px 12px;
                border-radius: 4px;
                min-height: 24px;
            }}
        """)


# ──────────────────────────────────────────────────────────────
# GlassCheckbox — premium checkbox with animated indicator
# ──────────────────────────────────────────────────────────────

class GlassCheckbox(QWidget):
    """Premium checkbox with animated toggle indicator."""

    toggled = Signal(bool)

    def __init__(self, label: str = "", checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._label = label
        self._check_progress = 1.0 if checked else 0.0
        self._hover = False
        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"checkProgress")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def isChecked(self):
        return self._checked

    def setChecked(self, val: bool):
        if self._checked == val:
            return
        self._checked = val
        self._anim.stop()
        self._anim.setStartValue(self._check_progress)
        self._anim.setEndValue(1.0 if val else 0.0)
        self._anim.start()
        self.toggled.emit(val)

    def _get_check_progress(self):
        return self._check_progress

    def _set_check_progress(self, val):
        self._check_progress = val
        self.update()

    checkProgress = Property(float, _get_check_progress, _set_check_progress)

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        box_size = 16
        box_y = (h - box_size) / 2

        if self._check_progress > 0.5:
            p.setBrush(QBrush(QColor(T["accent"])))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(0, box_y, box_size, box_size), 4, 4)
            p.setPen(QPen(QColor(T["accent_dark"]), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawLine(QPointF(4, box_y + box_size / 2), QPointF(7, box_y + box_size - 4))
            p.drawLine(QPointF(7, box_y + box_size - 4), QPointF(12, box_y + 3))
        else:
            bc = QColor(T["accent"]) if self._hover else QColor(T["border"])
            p.setBrush(QBrush(QColor(T["bg_alt"])))
            p.setPen(QPen(bc, 1))
            p.drawRoundedRect(QRectF(0, box_y, box_size, box_size), 4, 4)

        p.setPen(QColor(T["text"]))
        p.setFont(QFont("Segoe UI", 12))
        p.drawText(QRectF(box_size + 8, 0, w - box_size - 8, h),
                   Qt.AlignVCenter | Qt.AlignLeft, self._label)
        p.end()


# ──────────────────────────────────────────────────────────────
# ProfilePresetBar — quick one-click mode switcher
# ──────────────────────────────────────────────────────────────

class ProfilePresetBar(QWidget):
    """Horizontal bar with 3 preset buttons: Max Perf, Balanced, Custom."""

    preset_changed = Signal(str)

    PRESETS = [
        ("max_perf", "\u26a1 MAX PERFORMANCE", "1080p stretch, Max Reflex, Ultra Low-Latency"),
        ("balanced", "\U0001f3af BALANCED COMPETITIVE", "1080p Native, High Reflex, DX12"),
        ("custom", "\U0001f6e0\ufe0f CUSTOM TUNING", "Unlock manual edits"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = "custom"
        self._hover_idx = -1
        self.setFixedHeight(52)

        self._btns: list[QRectF] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._buttons: list[QPushButton] = []
        for key, label, desc in self.PRESETS:
            btn = QPushButton(label)
            btn.setObjectName("PresetBtn")
            btn.setProperty("preset", key)
            btn.setToolTip(desc)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._on_click(k))
            lay.addWidget(btn)
            self._buttons.append(btn)

        self._update_styles()

    def _on_click(self, key: str):
        self._active = key
        self._update_styles()
        self.preset_changed.emit(key)

    def _update_styles(self):
        for btn in self._buttons:
            k = btn.property("preset")
            if k == self._active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: rgba(139, 92, 246, 0.12);
                        border: 1px solid rgba(139, 92, 246, 0.55);
                        border-radius: 8px;
                        padding: 8px 16px;
                        color: {T['accent']};
                        font-size: 11px;
                        font-weight: 700;
                        letter-spacing: 0.5px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        border: 1px solid {T['border']};
                        border-radius: 8px;
                        padding: 8px 16px;
                        color: {T['text_dim']};
                        font-size: 11px;
                        font-weight: 600;
                    }}
                    QPushButton:hover {{
                        border-color: #2A313C;
                        color: {T['text']};
                    }}
                """)

    def active_preset(self) -> str:
        return self._active


# ──────────────────────────────────────────────────────────────
# ResolutionPicker — inline W x H with aspect ratio presets
# ──────────────────────────────────────────────────────────────

class ResolutionPicker(QWidget):
    """Inline resolution picker with W x H inputs and preset buttons."""

    changed = Signal(str, str)

    RESOLUTIONS = [
        ("16:9 1080p", "1920", "1080"),
        ("16:9 1440p", "2560", "1440"),
        ("16:9 4K", "3840", "2160"),
        ("16:10 1080p", "1920", "1200"),
        ("4:3 1024", "1024", "768"),
        ("Stretch 1650", "1680", "1050"),
    ]

    def __init__(self, current_w: str = "1920", current_h: str = "1080",
                 parent=None):
        super().__init__(parent)
        self._w = current_w
        self._h = current_h

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        w_lbl = QLabel("W")
        w_lbl.setStyleSheet(f"color: {T['text_faint']}; font-size: 10px; font-weight: 700; background: transparent;")
        lay.addWidget(w_lbl)

        self._w_combo = GlassComboBox([f"{r[0]}  ({r[1]})" for r in self.RESOLUTIONS])
        self._w_combo.setFixedWidth(120)
        self._w_combo.currentIndexChanged.connect(self._on_preset)
        lay.addWidget(self._w_combo)

        x_lbl = QLabel("\u00d7")
        x_lbl.setStyleSheet(f"color: {T['text_faint']}; font-size: 14px; font-weight: 700; background: transparent;")
        lay.addWidget(x_lbl)

        h_lbl = QLabel("H")
        h_lbl.setStyleSheet(f"color: {T['text_faint']}; font-size: 10px; font-weight: 700; background: transparent;")
        lay.addWidget(h_lbl)

        self._h_combo = GlassComboBox([f"{r[0]}  ({r[2]})" for r in self.RESOLUTIONS])
        self._h_combo.setFixedWidth(120)
        self._h_combo.currentIndexChanged.connect(self._on_preset)
        lay.addWidget(self._h_combo)

        # Aspect ratio tag.
        self._ar_tag = QLabel("16:9 Native")
        self._ar_tag.setStyleSheet(
            f"color: {T['accent']}; font-size: 10px; font-weight: 700;"
            f"background-color: rgba(139, 92, 246, 0.08);"
            f"border: 1px solid rgba(139, 92, 246, 0.25);"
            f"border-radius: 6px; padding: 3px 8px;")
        lay.addWidget(self._ar_tag)

        lay.addStretch()

    def _on_preset(self, idx):
        if 0 <= idx < len(self.RESOLUTIONS):
            _, w, h = self.RESOLUTIONS[idx]
            self._w = w
            self._h = h
            self._update_ar_tag()
            self.changed.emit(w, h)

    def _update_ar_tag(self):
        try:
            w, h = int(self._w), int(self._h)
            from math import gcd
            g = gcd(w, h)
            rw, rh = w // g, h // g
            common = {(16, 9): "16:9 Native", (16, 10): "16:10", (4, 3): "4:3",
                      (21, 9): "21:9 Ultrawide", (32, 9): "32:9 Super"}
            tag = common.get((rw, rh), f"{rw}:{rh}")
            self._ar_tag.setText(tag)
        except (ValueError, ZeroDivisionError):
            self._ar_tag.setText("Custom")

    def get_values(self) -> tuple[str, str]:
        return self._w, self._h


# ──────────────────────────────────────────────────────────────
# SystemInfoBadge — GPU/driver info pill
# ──────────────────────────────────────────────────────────────

class SystemInfoBadge(QFrame):
    """Displays GPU name, driver version, and NvAPI status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedHeight(36)
        self.setStyleSheet(f"""
            #Card {{
                background-color: rgba(139, 92, 246, 0.04);
                border: 1px solid rgba(139, 92, 246, 0.12);
                border-radius: 8px;
            }}
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(8)

        self._gpu_lbl = QLabel("")
        self._gpu_lbl.setStyleSheet(f"color: {T['accent']}; font-size: 11px; font-weight: 700; background: transparent; border: none;")
        lay.addWidget(self._gpu_lbl)

        for text in ["\u00b7", "", "\u00b7"]:
            if text:
                sep = QLabel(text)
                sep.setStyleSheet(f"color: {T['text_faint']}; background: transparent; border: none;")
                lay.addWidget(sep)
            else:
                self._driver_lbl = QLabel("")
                self._driver_lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 10px; background: transparent; border: none;")
                lay.addWidget(self._driver_lbl)

        self._nvapi_lbl = QLabel("NvAPI Ready")
        self._nvapi_lbl.setStyleSheet(f"color: {T['success']}; font-size: 10px; font-weight: 700; background: transparent; border: none;")
        lay.addWidget(self._nvapi_lbl)
        lay.addStretch()

    def set_info(self, gpu_name: str = "", driver_version: str = "",
                 nvapi_ready: bool = True):
        self._gpu_lbl.setText(gpu_name or "No GPU detected")
        self._driver_lbl.setText(f"Driver {driver_version}" if driver_version else "")
        color = T["success"] if nvapi_ready else T["text_faint"]
        text = "NvAPI Ready" if nvapi_ready else "NvAPI Unavailable"
        self._nvapi_lbl.setText(text)
        self._nvapi_lbl.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: 700; background: transparent; border: none;")


# ──────────────────────────────────────────────────────────────
# NvapiFlagsAccordion — expandable key-value grid
# ──────────────────────────────────────────────────────────────

class NvapiFlagsAccordion(QWidget):
    """Expandable accordion showing NvAPI driver flags in a 2-column grid."""

    FLAGS = [
        ("OGL_THREAD_CONTROL", "ENABLED"),
        ("SET_POWER_THROTTLE_FOR_PCI_E_GPU", "OFF"),
        ("SLI_PRE_RENDER_LIMIT", "1"),
        ("Power management mode", "Prefer maximum performance"),
        ("Threaded optimization", "Auto (On)"),
        ("Vertical Sync", "Force Off"),
        ("Shader Cache", "Enabled"),
        ("Texture filtering - Quality", "High Performance"),
        ("Ambient Occlusion", "Off"),
        ("FXAA", "Off"),
        ("Antialiasing - Mode", "Off"),
        ("Maximum pre-rendered frames", "1"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)

        self._header = QPushButton("\u25b6  Advanced NvAPI Flags")
        self._header.setObjectName("Ghost")
        self._header.setStyleSheet(f"""
            QPushButton {{ text-align: left; padding: 8px 12px; font-size: 11px;
                font-weight: 700; color: {T['text_dim']}; letter-spacing: 0.5px;
                border: 1px solid {T['border']}; border-radius: 8px;
                background-color: transparent; }}
            QPushButton:hover {{ color: {T['text']}; background-color: {T['bg_alt']}; }}
        """)
        self._header.clicked.connect(self._toggle)
        self._lay.addWidget(self._header)

        self._content = QWidget()
        self._content.setVisible(False)
        self._content.setStyleSheet("background: transparent;")
        grid = QVBoxLayout(self._content)
        grid.setContentsMargins(4, 8, 4, 8)
        grid.setSpacing(2)

        for key, value in self.FLAGS:
            row = QHBoxLayout()
            row.setSpacing(8)
            k_lbl = QLabel(key)
            k_lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 11px; font-family: 'Consolas', monospace; background: transparent; border: none;")
            k_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(k_lbl, 1)
            arrow = QLabel("\u279c")
            arrow.setStyleSheet(f"color: {T['text_faint']}; background: transparent; border: none;")
            row.addWidget(arrow)
            v_lbl = QLabel(value)
            v_lbl.setStyleSheet(f"color: {T['accent']}; font-size: 11px; font-weight: 600; font-family: 'Consolas', monospace; background: transparent; border: none;")
            v_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(v_lbl, 1)
            grid.addLayout(row)

        self._lay.addWidget(self._content)

    def _toggle(self):
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        arrow = "\u25bc" if self._expanded else "\u25b6"
        self._header.setText(f"{arrow}  Advanced NvAPI Flags")


# ──────────────────────────────────────────────────────────────
# ChangesPreviewDialog — code-editor overlay showing changes
# ──────────────────────────────────────────────────────────────

class ChangesPreviewDialog(QDialog):
    """Sleek code-editor overlay showing exact NvAPI + config changes."""

    def __init__(self, game_id: str, config_values: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("View Driver & File Edits")
        self.setMinimumSize(620, 520)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {T['bg']};
                border: 1px solid {T['border']};
                border-radius: 12px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(14)

        # Title.
        title = QLabel("Pending System Changes")
        title.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {T['text']};")
        lay.addWidget(title)

        sub = QLabel("The following driver and file modifications will be applied:")
        sub.setStyleSheet(f"font-size: 12px; color: {T['text_dim']};")
        lay.addWidget(sub)

        # Code preview.
        code = QTextEdit()
        code.setReadOnly(True)
        code.setFont(QFont("Consolas", 11))
        code.setStyleSheet(f"""
            QTextEdit {{
                background-color: {T['bg_alt']};
                border: 1px solid {T['border']};
                border-radius: 8px;
                color: {T['text']};
                padding: 12px;
                selection-background-color: {T['accent']};
            }}
        """)
        code.setPlainText(self._build_preview(game_id, config_values))
        lay.addWidget(code, 1)

        # Close button.
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("Ghost")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

    def _build_preview(self, game_id: str, config_values: dict) -> str:
        from engine import nvprofiles
        from engine import game_config
        import os

        lines = []
        lines.append("; ============================================")
        lines.append("; NVIDIA NvAPI Driver Overrides")
        lines.append("; ============================================")
        lines.append("")

        for key, entry in nvprofiles.SETTINGS.items():
            name = entry["name"]
            default = entry["default"]
            if isinstance(default, int):
                lines.append(f"; {name} = 0x{default:X} ({default})")
            else:
                lines.append(f"; {name} = {default}")

        lines.append("")
        lines.append("; ============================================")

        game_cfg = game_config.get_config(game_id)
        if game_cfg:
            cfg_path = game_cfg.find_config()
            if cfg_path:
                lines.append(f"; {cfg_path}")
                lines.append("; ============================================")
                lines.append("")
                for key, val in config_values.items():
                    if key in ("resolution_w", "resolution_h", "fps_limit",
                               "rendering_mode", "audio_quality", "reflex"):
                        lines.append(f"{key} = {val}")
                lines.append("")
                if game_id == "gp-001":
                    lines.append("; Additional Fortnite flags:")
                    lines.append("bDisableMouseAcceleration = True")
                    lines.append("bDisableFullscreen = 0")
            else:
                lines.append("; Config file not found on this system.")
        else:
            lines.append("; No local config support for this game.")
            lines.append("; Driver-only profile will be applied.")

        lines.append("")
        lines.append("; ============================================")
        lines.append("; Ready to apply.")
        lines.append("; ============================================")

        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# AnimatedToast — premium notification
# ──────────────────────────────────────────────────────────────

class AnimatedToast(QWidget):
    """Premium toast notification with slide-in animation and auto-dismiss."""

    def __init__(self, message: str, style: str = "success",
                 duration: int = 3000, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self.setMinimumWidth(320)
        self.setMaximumWidth(500)
        self._message = message
        self._style = style
        self._opacity = 0.0
        self._progress = 0.0

        colors = {"success": T["success"], "error": T["danger"],
                  "warning": T["warning"], "info": T["accent"]}
        self._accent = colors.get(style, T["accent"])

        self._fade_anim = QPropertyAnimation(self, b"toastOpacity")
        self._fade_anim.setDuration(300)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._progress_anim = QPropertyAnimation(self, b"progress")
        self._progress_anim.setDuration(duration)
        self._progress_anim.setEasingCurve(QEasingCurve.Linear)
        self._progress_anim.finished.connect(self._dismiss)

    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, val):
        self._opacity = val
        self.setWindowOpacity(val)
        self.update()

    def _get_progress(self):
        return self._progress

    def _set_progress(self, val):
        self._progress = val
        self.update()

    toastOpacity = Property(float, _get_opacity, _set_opacity)
    progress = Property(float, _get_progress, _set_progress)

    def show_toast(self, parent_widget: QWidget):
        if parent_widget is None:
            return
        pw = parent_widget.width()
        self.setFixedWidth(min(460, pw - 40))
        x = (pw - self.width()) // 2
        self.setParent(parent_widget)
        self.setGeometry(x, 20, self.width(), 56)
        self.show()
        self.raise_()
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()
        self._progress = 0.0
        self._progress_anim.setStartValue(0.0)
        self._progress_anim.setEndValue(1.0)
        self._progress_anim.start()

    def _dismiss(self):
        fade_out = QPropertyAnimation(self, b"toastOpacity")
        fade_out.setDuration(250)
        fade_out.setEasingCurve(QEasingCurve.InCubic)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.finished.connect(self.deleteLater)
        fade_out.start()
        self._fade_out = fade_out

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        p.setBrush(QBrush(QColor(21, 27, 36)))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(0, 0, w, h), 12, 12)

        p.setBrush(QBrush(QColor(self._accent)))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(0, 4, 3, h - 8), 1.5, 1.5)

        p.setPen(QPen(QColor(T["border"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 12, 12)

        icons = {"success": "\u2713", "error": "\u2717", "warning": "\u26a0", "info": "\u2139"}
        p.setPen(QColor(self._accent))
        p.setFont(QFont("Segoe UI", 16, QFont.Bold))
        p.drawText(QRectF(14, 0, 30, h), Qt.AlignCenter, icons.get(self._style, "\u2713"))

        p.setPen(QColor(T["text"]))
        p.setFont(QFont("Segoe UI", 12))
        p.drawText(QRectF(50, 0, w - 66, h), Qt.AlignVCenter | Qt.AlignLeft, self._message)

        bar_h = 2
        p.setBrush(QBrush(QColor(T["bg_alt"])))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(0, h - bar_h, w, bar_h))
        p.setBrush(QBrush(QColor(self._accent)))
        p.drawRoundedRect(QRectF(0, h - bar_h, w * (1.0 - self._progress), bar_h), 1, 1)
        p.end()


# Re-export toast helper for convenience.
def toast(message: str, style: str = "success", parent: QWidget = None):
    t = AnimatedToast(message, style, 3500, parent)
    t.show_toast(parent)
    return t


# ──────────────────────────────────────────────────────────────
# ComingSoonPage — blurry locked placeholder
# ──────────────────────────────────────────────────────────────

class ComingSoonPage(QWidget):
    """Blurry locked placeholder for features coming soon."""

    def __init__(self, title: str = "Game Profiles", parent=None):
        super().__init__(parent)
        self._title = title
        self._pulse = 0.0
        self._lock_bob = 0.0

        self._pulse_anim = QPropertyAnimation(self, b"pulseVal")
        self._pulse_anim.setDuration(2000)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)

        self._lock_anim = QPropertyAnimation(self, b"lockBob")
        self._lock_anim.setDuration(1800)
        self._lock_anim.setLoopCount(-1)
        self._lock_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._lock_anim.setStartValue(0.0)
        self._lock_anim.setEndValue(8.0)
        self._lock_anim.setDirection(QPropertyAnimation.Forward)
        self._lock_anim.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._pulse_anim.start()

    def _get_pulse(self):
        return self._pulse

    def _set_pulse(self, val):
        self._pulse = val
        self.update()

    def _get_lock_bob(self):
        return self._lock_bob

    def _set_lock_bob(self, val):
        self._lock_bob = val
        self.update()

    pulseVal = Property(float, _get_pulse, _set_pulse)
    lockBob = Property(float, _get_lock_bob, _set_lock_bob)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Blurry background — layered translucent dark panels.
        import random
        random.seed(42)
        for _ in range(12):
            rx = random.randint(0, w)
            ry = random.randint(0, h)
            rw = random.randint(80, 220)
            rh = random.randint(40, 100)
            alpha = random.randint(8, 18)
            p.setBrush(QBrush(QColor(18, 23, 32, alpha)))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(rx, ry, rw, rh), 10, 10)

        # Overall blur tint.
        p.setBrush(QBrush(QColor(9, 11, 14, 160)))
        p.setPen(Qt.NoPen)
        p.drawRect(0, 0, w, h)

        # Horizontal scan lines for blurry effect.
        for y in range(0, h, 4):
            alpha = 6 + int(4 * math.sin(y * 0.05 + self._pulse * 6.28))
            p.setPen(QPen(QColor(255, 255, 255, alpha), 1))
            p.drawLine(QPointF(0, y), QPointF(w, y))

        cx, cy = w / 2, h / 2

        # Glassmorphic card.
        card_w, card_h = 380, 300
        card_x = cx - card_w / 2
        card_y = cy - card_h / 2

        # Card shadow.
        p.setBrush(QBrush(QColor(0, 0, 0, 50)))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(card_x + 3, card_y + 5, card_w, card_h), 20, 20)

        # Card body.
        pulse_alpha = int(35 + 15 * math.sin(self._pulse * 6.28))
        p.setBrush(QBrush(QColor(18, 23, 32, 200)))
        p.setPen(QPen(QColor(139, 92, 246, pulse_alpha), 1))
        p.drawRoundedRect(QRectF(card_x, card_y, card_w, card_h), 18, 18)

        # Lock icon (drawn with paths).
        lock_cx = cx
        lock_cy = card_y + 80 + self._lock_bob
        # Lock body.
        p.setBrush(QBrush(QColor(139, 92, 246, 140)))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(lock_cx - 18, lock_cy, 36, 28), 4, 4)
        # Lock shackle.
        shackle_pen = QPen(QColor(139, 92, 246, 140), 4)
        shackle_pen.setCapStyle(Qt.RoundCap)
        p.setPen(shackle_pen)
        p.setBrush(Qt.NoBrush)
        shackle_rect = QRectF(lock_cx - 10, lock_cy - 14, 20, 18)
        p.drawArc(shackle_rect, 0, 180 * 16)
        # Keyhole.
        p.setBrush(QBrush(QColor(9, 11, 14, 200)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(lock_cx, lock_cy + 10), 4, 4)
        p.drawRect(QRectF(lock_cx - 1.5, lock_cy + 12, 3, 8))

        # Title.
        p.setPen(QColor(T["text"]))
        p.setFont(QFont("Segoe UI", 20, QFont.Bold))
        p.drawText(QRectF(card_x, card_y + 130, card_w, 30), Qt.AlignCenter, self._title)

        # "Coming Soon" text.
        p.setPen(QColor(T["accent"]))
        p.setFont(QFont("Segoe UI", 14, QFont.Bold))
        p.drawText(QRectF(card_x, card_y + 170, card_w, 26), Qt.AlignCenter, "COMING SOON")

        # Subtitle.
        p.setPen(QColor(T["text_dim"]))
        p.setFont(QFont("Segoe UI", 11))
        p.drawText(QRectF(card_x + 20, card_y + 210, card_w - 40, 50), Qt.AlignCenter,
                   "This feature is under development\nand will be available in a future update.")

        # Pulsing dots.
        dot_y = card_y + card_h - 40
        for i in range(3):
            dot_x = cx - 30 + i * 30
            phase = (self._pulse * 3 + i * 0.3) % 1.0
            alpha = int(80 + 175 * math.sin(phase * 3.14))
            p.setBrush(QBrush(QColor(139, 92, 246, alpha)))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(dot_x, dot_y), 4, 4)

        p.end()


class AssistantComingSoon(QWidget):
    """Coming-soon placeholder for the AI Assistant.

    Deliberately distinct from ``ComingSoonPage``: instead of the blurry
    lock, it previews a mock chat with a glowing sparkle icon, a
    purple/magenta gradient card, twinkling stars, and shimmering reply
    bars — so it reads as an "AI / chat" surface, not a locked tool.
    """

    def __init__(self, title: str = "AI Assistant", parent=None):
        super().__init__(parent)
        self._title = title
        self._pulse = 0.0

        self._pulse_anim = QPropertyAnimation(self, b"pulseVal")
        self._pulse_anim.setDuration(2200)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)

        # Fixed twinkle field (seeded so it is stable, but unlike the lock page).
        import random
        random.seed(7)
        self._stars = [
            (random.uniform(0.03, 0.97), random.uniform(0.05, 0.95),
             random.uniform(1.0, 2.6), random.uniform(0.0, 6.28))
            for _ in range(42)
        ]

    def showEvent(self, event):
        super().showEvent(event)
        self._pulse_anim.start()

    def _get_pulse(self):
        return self._pulse

    def _set_pulse(self, val):
        self._pulse = val
        self.update()

    pulseVal = Property(float, _get_pulse, _set_pulse)

    @staticmethod
    def _sparkle_path(cx: float, cy: float, r: float) -> QPainterPath:
        """Four-point star used as the assistant's glowing icon."""
        pts = []
        for i in range(8):
            ang = i * math.pi / 4.0
            rr = r if i % 2 == 0 else r * 0.26
            pts.append(QPointF(cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
        path = QPainterPath()
        path.moveTo(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        path.closeSubpath()
        return path

    def _draw_bars(self, p, x, y, available, fractions, phase, right=False):
        """Shimmering mock reply bars inside a chat bubble."""
        bar_h, gap = 9, 7
        for i, frac in enumerate(fractions):
            width = max(10.0, available * frac)
            bx = x + (available - width) if right else x
            by = y + i * (bar_h + gap)
            p.setBrush(QBrush(QColor(255, 255, 255, 26)))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(bx, by, width, bar_h), 4, 4)
            # Sweeping highlight.
            sweep = (phase + i * 0.16) % 1.0
            hl_w = 30.0
            hl_x = bx - hl_w + sweep * (width + hl_w * 2)
            p.setBrush(QBrush(QColor(255, 255, 255, 85)))
            p.drawRoundedRect(QRectF(hl_x, by, hl_w, bar_h), 4, 4)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        t = self._pulse * math.tau

        # Base.
        p.fillRect(0, 0, w, h, QColor(11, 13, 18))

        # Drifting purple/magenta glow orbs.
        orbs = [
            (0.22, 0.20, 240, (120, 76, 255)),
            (0.80, 0.30, 200, (201, 76, 255)),
            (0.65, 0.80, 260, (84, 64, 255)),
            (0.15, 0.75, 180, (255, 76, 205)),
        ]
        for i, (ox, oy, rad, rgb) in enumerate(orbs):
            gx = ox * w + math.sin(t * 0.5 + i * 1.7) * 14
            gy = oy * h + math.cos(t * 0.4 + i * 2.1) * 10
            grad = QRadialGradient(QPointF(gx, gy), rad)
            grad.setColorAt(0.0, QColor(*rgb, 42))
            grad.setColorAt(1.0, QColor(*rgb, 0))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(gx - rad, gy - rad, rad * 2, rad * 2))

        # Twinkling stars.
        for sx, sy, sr, ph in self._stars:
            a = int(18 + 42 * (0.5 + 0.5 * math.sin(t * 0.8 + ph)))
            p.setBrush(QBrush(QColor(210, 190, 255, a)))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(sx * w, sy * h), sr, sr)

        cx, cy = w / 2, h / 2
        card_w, card_h = 460, 400
        card_x, card_y = cx - card_w / 2, cy - card_h / 2

        # Card shadow.
        p.setBrush(QBrush(QColor(0, 0, 0, 90)))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(card_x + 4, card_y + 6, card_w, card_h), 22, 22)

        # Gradient border + body.
        glow = int(55 + 25 * math.sin(t))
        border = QLinearGradient(card_x, card_y, card_x + card_w, card_y + card_h)
        border.setColorAt(0.0, QColor(139, 92, 246, 200))
        border.setColorAt(0.5, QColor(217, 70, 239, glow))
        border.setColorAt(1.0, QColor(99, 102, 241, 200))
        body = QLinearGradient(card_x, card_y, card_x, card_y + card_h)
        body.setColorAt(0.0, QColor(24, 25, 40, 235))
        body.setColorAt(1.0, QColor(16, 17, 28, 235))
        p.setBrush(QBrush(body))
        p.setPen(QPen(border, 1.5))
        p.drawRoundedRect(QRectF(card_x, card_y, card_w, card_h), 22, 22)

        # Glowing sparkle icon.
        spark = self._sparkle_path(cx, card_y + 70, 20 + 3 * math.sin(t * 1.5))
        p.setBrush(QBrush(QColor(196, 132, 255, 235)))
        p.setPen(QPen(QColor(236, 217, 255, 200), 1))
        p.drawPath(spark)

        # Title.
        p.setPen(QColor(T["text"]))
        p.setFont(QFont("Segoe UI", 24, QFont.Bold))
        p.drawText(QRectF(card_x, card_y + 100, card_w, 34), Qt.AlignCenter, self._title)

        # "COMING SOON" pill badge.
        pill_w, pill_h, pill_y = 168, 28, card_y + 146
        pill_x = cx - pill_w / 2
        pill_grad = QLinearGradient(pill_x, pill_y, pill_x + pill_w, pill_y + pill_h)
        pill_grad.setColorAt(0.0, QColor(139, 92, 246, 45))
        pill_grad.setColorAt(1.0, QColor(217, 70, 239, 45))
        p.setBrush(QBrush(pill_grad))
        p.setPen(QPen(QColor(196, 132, 255, 170), 1))
        p.drawRoundedRect(QRectF(pill_x, pill_y, pill_w, pill_h), pill_h / 2, pill_h / 2)
        p.setPen(QColor(216, 180, 254))
        p.setFont(QFont("Segoe UI", 11, QFont.Bold))
        p.drawText(QRectF(pill_x, pill_y, pill_w, pill_h), Qt.AlignCenter, "COMING SOON")

        # Subtitle.
        p.setPen(QColor(T["text_dim"]))
        p.setFont(QFont("Segoe UI", 11))
        p.drawText(QRectF(card_x + 24, card_y + 182, card_w - 48, 46), Qt.AlignCenter,
                   "A real chat assistant is being trained to\n"
                   "answer questions about your PC.")

        # Mock conversation: user bubble (right) + assistant bubble (left).
        bubble_h, bubble_w = 52, 250
        pad = 26
        user_y = card_y + 238
        user_x = card_x + card_w - pad - bubble_w

        p.setPen(QColor(196, 132, 255))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(QRectF(user_x, user_y, bubble_w, 16), Qt.AlignRight, "YOU")
        u_grad = QLinearGradient(user_x, user_y, user_x + bubble_w, user_y + bubble_h)
        u_grad.setColorAt(0.0, QColor(109, 40, 217, 175))
        u_grad.setColorAt(1.0, QColor(162, 28, 175, 175))
        p.setBrush(QBrush(u_grad))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(user_x, user_y + 18, bubble_w, bubble_h - 18), 12, 12)
        self._draw_bars(p, user_x + 18, user_y + 26, bubble_w - 36,
                        [0.92, 0.92, 0.58], self._pulse, right=True)

        asst_y = card_y + 298
        asst_x = card_x + pad
        p.setPen(QColor(167, 139, 250))
        p.drawText(QRectF(asst_x, asst_y, bubble_w, 16), Qt.AlignLeft, "MAXIMUM")
        p.setBrush(QBrush(QColor(255, 255, 255, 9)))
        p.setPen(QPen(QColor(139, 92, 246, 150), 1))
        p.drawRoundedRect(QRectF(asst_x, asst_y + 18, bubble_w, bubble_h - 18), 12, 12)
        self._draw_bars(p, asst_x + 18, asst_y + 26, bubble_w - 36,
                        [1.0, 0.72, 0.5], self._pulse + 0.5, right=False)

        # Pulsing dots.
        dot_y = card_y + card_h - 34
        for i in range(3):
            phase = (self._pulse * 3 + i * 0.32) % 1.0
            alpha = int(90 + 165 * math.sin(phase * 3.14))
            p.setBrush(QBrush(QColor(196, 132, 255, alpha)))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx - 26 + i * 26, dot_y), 4, 4)

        p.end()
