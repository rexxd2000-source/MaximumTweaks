"""Hop timeline, latency graph, detail panel, and event log widgets."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QPainterPath, QFontMetrics,
    QLinearGradient,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QTextEdit,
)

from config.app_config import THEME as T
from engine.netmonitor.types import Hop, HopStatus, Route, RouteEvent, MonitorState


def _s(key, alpha=0xFF):
    hex_color = T.get(key, "#928AAD").lstrip("#")
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


# â”€â”€ Shared "instrument" chrome: bezel frames, header bands, corner
#    brackets, right-aligned header chips, and a drawn scrollbar. â”€â”€

_PANEL_BG = QColor(10, 14, 28)
_PANEL_BG_HI = QColor(14, 20, 40)
_BEZEL = QColor(40, 53, 80)
_CHIP_B = QColor(58, 72, 104)
_CYAN = QColor(125, 211, 252)
_CYAN_HI = QColor(34, 211, 238)
_AMBER = QColor(251, 191, 36)
_AMBER_DIM = QColor(205, 168, 82)
_INK = QColor(159, 179, 216)
_INK_DIM = QColor(125, 143, 180)


def _draw_frame(p: QPainter, w: int, h: int):
    """Bezel border + cyan corner brackets (tactical instrument frame)."""
    p.setPen(QPen(_BEZEL, 1))
    p.drawRect(QRectF(0.5, 0.5, w - 1, h - 1))
    ins, L, tw = 6, 9, 1.6
    pen = QPen(_CYAN_HI, tw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(ins, ins + L), QPointF(ins, ins))
    p.drawLine(QPointF(ins, ins), QPointF(ins + L, ins))
    p.drawLine(QPointF(w - ins - L, ins), QPointF(w - ins, ins))
    p.drawLine(QPointF(w - ins, ins), QPointF(w - ins, ins + L))
    p.drawLine(QPointF(ins, h - ins - L), QPointF(ins, h - ins))
    p.drawLine(QPointF(ins, h - ins), QPointF(ins + L, h - ins))
    p.drawLine(QPointF(w - ins - L, h - ins), QPointF(w - ins, h - ins))
    p.drawLine(QPointF(w - ins, h - ins),
               QPointF(w - ins, h - ins - L))


def _header_band(p: QPainter, h: int):
    """Filled header strip with a bottom rule."""
    p.fillRect(0, 0, p.viewport().width(), h, _PANEL_BG_HI)
    p.fillRect(0, h - 1, p.viewport().width(), 1, _BEZEL)


def _band_title(p: QPainter, text: str, h: int,
                color: QColor = _CYAN, size: int = 8):
    f = QFont("Segoe UI", size, QFont.Weight.Bold)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
    p.setFont(f)
    p.setPen(color)
    p.drawText(QRectF(12, 4, 300, h - 8), Qt.AlignVCenter | Qt.AlignLeft, text)


def _right_chips(p: QPainter, w: int, y: int, items, chip_h: int = 16):
    """Draw right-aligned bordered chips; items = (text, fg QColor)."""
    if not items:
        return
    font = QFont("Segoe UI", 7, QFont.Weight.Bold)
    p.setFont(font)
    fm = QFontMetrics(font)
    x = w - 10
    for text, fg in reversed(items):
        cw = fm.horizontalAdvance(text) + 16
        rect = QRectF(x - cw, y, cw, chip_h)
        p.setBrush(QColor(255, 255, 255, 7))
        p.setPen(QPen(_CHIP_B, 1))
        p.drawRoundedRect(rect, chip_h / 2, chip_h / 2)
        p.setPen(fg)
        p.drawText(rect, Qt.AlignCenter, text)
        x -= cw + 6


def _scrollbar(p: QPainter, w: int, top: float, bottom: float,
               scroll: int, scroll_max: int, content_h: int):
    """Thin cyan thumb scrollbar drawn along the right edge."""
    if scroll_max <= 0 or content_h <= 0 or bottom - top < 40:
        return
    x = w - 5.5
    H = bottom - top
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 10))
    p.drawRoundedRect(QRectF(x, top, 3, H), 1.5, 1.5)
    thumb_h = max(22, H * (H / content_h))
    travel = max(0.0, H - thumb_h)
    ty = top + (scroll / scroll_max) * travel
    p.setBrush(QColor(34, 211, 238, 210))
    p.drawRoundedRect(QRectF(x, ty, 3, thumb_h), 1.5, 1.5)


class HopTimelineWidget(QWidget):
    """HOP ROUTE // TRACE — bezel-framed routing instrument.

    Every hop is a tile inside a machine console panel: numbered badge,
    journey spine with downward flow arrows, identity lines, a big latency
    readout, a status rail, and a progress meter. The panel has a header
    band with live chips, corner brackets, and a drawn cyan scrollbar.
    """

    hop_clicked = Signal(int)

    _HEADER_H = 34
    _TILE_H = 58
    _GAP = 10
    _BODY_T = 40

    def __init__(self, parent=None):
        super().__init__(parent)
        self._route: Optional[Route] = None
        self._selected: int = -1
        self._hops: list[Hop] = []
        self._scroll: int = 0
        self.setMinimumWidth(320)
        self.setMaximumWidth(480)
        self.setMinimumHeight(150)

    @property
    def _stride(self) -> int:
        return self._TILE_H + self._GAP

    def set_route(self, route: Optional[Route]):
        new_hops = route.hops if route else []
        same = (
            len(new_hops) == len(self._hops)
            and all(a.ip == b.ip for a, b in zip(new_hops, self._hops))
        )
        self._route = route
        self._hops = new_hops
        if not same:
            self._scroll = 0
        self.update()

    def select_hop(self, num: int):
        self._selected = num
        self.update()

    def _max_latency(self) -> float:
        vals = [
            h.latency for h in self._hops
            if h.latency > 0 and h.status != HopStatus.TIMEOUT
        ]
        return max(vals) if vals else 0.0

    def _scroll_max(self) -> int:
        content = len(self._hops) * self._stride
        visible = max(0, self.height() - self._BODY_T - 6)
        return max(0, content - visible)

    def _status_short(self, status: HopStatus) -> str:
        return {
            HopStatus.HEALTHY: "OK",
            HopStatus.WARNING: "PARTIAL",
            HopStatus.CRITICAL: "CRITICAL",
            HopStatus.TIMEOUT: "100% LOSS",
            HopStatus.UNKNOWN: "UNKNOWN",
            HopStatus.PRIVATE: "LOCAL",
            HopStatus.LOCAL: "LOCAL",
        }.get(status, "UNKNOWN")

    def _sub_line(self, hop: Hop) -> str:
        nodes = []
        org = (hop.network.as_org or hop.network.network_name or "").strip()
        if org:
            nodes.append(org)
        if hop.hostname and hop.hostname != hop.ip:
            nodes.append(hop.hostname)
        elif hop.ip:
            nodes.append(hop.ip)
        base = "  \u00b7  ".join(nodes)
        if hop.packet_loss > 0 and hop.status != HopStatus.TIMEOUT:
            base = f"{base}  \u00b7  {hop.packet_loss:.0f}% loss"
        if base == hop.ip and hop.location_label == hop.ip:
            base = "local hop"
        return base

    def _latency_text(self, hop: Hop) -> str:
        if hop.status != HopStatus.TIMEOUT and hop.latency > 0:
            if hop.latency >= 100:
                return f"{hop.latency:.0f} ms"
            return f"{hop.latency:.1f} ms"
        if hop.probes.raw_hint:
            return "\u2014"
        return "T/O"

    def _jitter_sub(self, hop: Hop) -> str:
        if hop.status == HopStatus.TIMEOUT:
            return "no reply"
        parts = [f"jitter {hop.jitter:.1f} ms"]
        if hop.packet_loss > 0:
            parts.append(f"{hop.packet_loss:.0f}% loss")
        return " \u00b7 ".join(parts)

    def _geom(self, w: int):
        """tile_x, tile_w, badge_x, text_x, readout_x"""
        tile_w = max(210, w - 30)
        tile_x = 10
        bx = tile_x + 11
        tx = bx + 42
        rx = tile_x + tile_w - 12 - 104
        if rx - tx < 84:
            rx = tx + 84
            tile_w = max(tile_w, rx + 120 - tile_x)
        return tile_x, tile_w, bx, tx, rx

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()

        p.fillRect(0, 0, w, h, _PANEL_BG)

        if not self._hops:
            p.setPen(QColor(100, 120, 160))
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(QRectF(8, 0, w - 16, h), Qt.AlignCenter,
                       "NO ROUTE DATA \u2014 RUN A TRACE")
            _draw_frame(p, w, h)
            p.end()
            return

        # â”€â”€ Chrome: bezel, brackets, header band â”€â”€
        _draw_frame(p, w, h)
        _header_band(p, self._HEADER_H)
        _band_title(p, "> HOP ROUTE // TRACE", self._HEADER_H)

        n = len(self._hops)
        tos = sum(1 for hp in self._hops if hp.status == HopStatus.TIMEOUT)
        floor = self._route.latency_floor_ms if self._route else 0.0
        chips = [(f"{n:02d} HOPS", _INK)]
        # Traceable confidence: answered probes / sent probes across all hops,
        # halved when the scan never resolved the destination. Every number is
        # derivable from the per-hop probe counts shown in the tooltips.
        try:
            _sent = sum(hp.probes.sent for hp in self._hops) or 0
            _rcvd = sum(hp.probes.received for hp in self._hops) or 0
            last = self._hops[-1] if self._hops else None
            _resolved = bool(last and last.role in (HopRole.DESTINATION,))
            conf = round(100 * (_rcvd / _sent)) if _sent else 0
            if not _resolved:
                conf = round(conf * 0.5)
            conf_color = (
                QColor(52, 211, 153) if conf >= 85
                else QColor(251, 191, 36) if conf >= 60
                else QColor(239, 68, 68)
            )
            chips.append((f"CONF {conf}%", conf_color))
        except Exception:
            pass
        if w >= 380:
            chips.append((f"FLOOR ~{floor:.0f}" if floor > 0 else "NO FLOOR",
                          _AMBER_DIM if floor > 0 else QColor(95, 110, 136)))
            chips.append(("LOST %d" % tos if tos else "CLEAN",
                          QColor(239, 68, 68) if tos
                          else QColor(52, 211, 153)))
        _right_chips(p, w, (self._HEADER_H - 16) / 2, chips)

        axis_x = 12
        max_lat = self._max_latency() or 1.0

        tile_x, tile_w, bx, tx, rx = self._geom(w)
        rw_read = tile_x + tile_w - 12 - rx

        name_font = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        sub_font = QFont("Segoe UI", 8)
        big_font = QFont("JetBrains Mono", 15, QFont.Weight.Bold)
        small_font = QFont("JetBrains Mono", 7)
        badge_font = QFont("JetBrains Mono", 12, QFont.Weight.Bold)
        name_fm = QFontMetrics(name_font)
        sub_fm = QFontMetrics(sub_font)
        small_fm = QFontMetrics(small_font)

        # Scrolled tiles must never bleed over the header band or under the
        # footer — clamp all tile painting to the scrollable body region.
        p.save()
        p.setClipRect(QRectF(0, self._BODY_T - 3, w, h - self._BODY_T + 1))

        for i, hop in enumerate(self._hops):
            ty = self._BODY_T + i * self._stride - self._scroll
            th = self._TILE_H
            if ty > h + 2:
                break
            if ty + th < 2:
                continue

            sc = _status_color(hop.status)
            is_sel = hop.number == self._selected
            scd = QColor(sc.red(), sc.green(), sc.blue())

            # â”€â”€ Journey spine: dashed connector + flow arrow in the gap â”€â”€
            if i < n - 1:
                cx = bx + 16
                y0 = ty + th
                y1 = y0 + self._GAP
                p.setPen(QPen(QColor(68, 82, 122), 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(cx, y0 + 1), QPointF(cx, y1 - 1))
                my = y0 + self._GAP / 2
                tri = QPainterPath(QPointF(cx - 3, my - 1.6))
                tri.lineTo(cx + 3, my - 1.6)
                tri.lineTo(cx, my + 2.2)
                tri.closeSubpath()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(91, 111, 151)))
                p.drawPath(tri)

            # â”€â”€ Selection glow behind the tile â”€â”€
            if is_sel:
                p.setBrush(QColor(scd.red(), scd.green(), scd.blue(), 22))
                p.setPen(QPen(QColor(scd.red(), scd.green(), scd.blue(), 90), 1))
                p.drawRoundedRect(QRectF(tile_x - 2, ty - 2, tile_w + 4,
                                         th + 4), 10, 10)

            # â”€â”€ Status rail â”€â”€
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(scd))
            p.drawRoundedRect(QRectF(tile_x + 1, ty + 14, 3, th - 28),
                              1.5, 1.5)

            # â”€â”€ Tile plate â”€â”€
            grad = QLinearGradient(0, ty, 0, ty + th)
            grad.setColorAt(0.0, QColor(23, 29, 51))
            grad.setColorAt(1.0, QColor(14, 19, 36))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(scd if is_sel else _BEZEL, 1.5 if is_sel else 1))
            p.drawRoundedRect(QRectF(tile_x, ty, tile_w, th), 8, 8)

            # â”€â”€ Hop-number badge â”€â”€
            badge = QRectF(bx, ty + (th - 32) / 2, 32, 32)
            p.setBrush(QColor(scd.red(), scd.green(), scd.blue(),
                              46 if hop.status != HopStatus.HEALTHY else 62))
            p.setPen(QPen(QColor(scd.red(), scd.green(), scd.blue(), 200), 1))
            p.drawRoundedRect(badge, 8, 8)
            p.setFont(badge_font)
            if hop.status == HopStatus.TIMEOUT or sc.value() < 150:
                p.setPen(QColor(206, 217, 236))
            else:
                p.setPen(scd)
            p.drawText(badge, Qt.AlignCenter, f"{hop.number:02d}")

            # â”€â”€ Identity lines â”€â”€
            tw_text = max(50, rx - 6 - tx)
            name = hop.location_label or hop.display_name or hop.ip
            name = name_fm.elidedText(name, Qt.ElideRight, int(tw_text))
            p.setFont(name_font)
            p.setPen(QColor(232, 240, 253))
            p.drawText(QRectF(tx, ty + 10, tw_text, 17),
                       Qt.AlignLeft | Qt.AlignVCenter, name)
            sub = sub_fm.elidedText(self._sub_line(hop), Qt.ElideRight,
                                    int(tw_text))
            p.setFont(sub_font)
            p.setPen(QColor(133, 149, 177))
            p.drawText(QRectF(tx, ty + 30, tw_text, 14),
                       Qt.AlignLeft | Qt.AlignVCenter, sub)

            # â”€â”€ Big latency readout â”€â”€
            lt = self._latency_text(hop)
            big, _, unit = lt.partition(" ")
            p.setFont(big_font)
            p.setPen(scd if hop.status != HopStatus.TIMEOUT
                     else QColor(150, 160, 178))
            p.drawText(QRectF(rx, ty + 6, rw_read, 24),
                       Qt.AlignVCenter | Qt.AlignRight, big)
            if unit:
                p.setFont(QFont("Segoe UI", 8))
                p.setPen(QColor(scd.red(), scd.green(), scd.blue(), 210)
                         if hop.status != HopStatus.TIMEOUT
                         else QColor(122, 132, 150))
                p.drawText(QRectF(rx, ty + 30, rw_read, 13),
                           Qt.AlignVCenter | Qt.AlignRight, unit)
            p.setFont(small_font)
            p.setPen(QColor(115, 129, 156))
            js = small_fm.elidedText(self._jitter_sub(hop), Qt.ElideRight,
                                     int(rw_read))
            p.drawText(QRectF(rx, ty + 44, rw_read, 12),
                       Qt.AlignVCenter | Qt.AlignRight, js)

            # â”€â”€ Progress meter â”€â”€
            my = ty + th - 6
            mw_use = max(40.0, rx - 8 - tx)
            p.fillRect(QRectF(tx, my, mw_use, 3), QColor(29, 37, 57))
            if hop.status != HopStatus.TIMEOUT and hop.latency > 0:
                frac = min(hop.latency / max_lat, 1.0)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(scd.red(), scd.green(), scd.blue(),
                                         215)))
                p.drawRoundedRect(QRectF(tx, my, max(8.0, mw_use * frac), 3),
                                  1.5, 1.5)
            else:
                p.setPen(QPen(QColor(90, 102, 128), 1, Qt.PenStyle.DashLine))
                p.drawLine(tx, my + 1, tx + mw_use, my + 1)

            p.setPen(Qt.PenStyle.NoPen)

        p.restore()

        # â”€â”€ Scrollbar + affordance â”€â”€
        smax = self._scroll_max()
        _scrollbar(p, w, self._BODY_T - 2, h - 6, self._scroll, smax,
                   n * self._stride)
        if smax > 0:
            p.setPen(QColor(70, 86, 116))
            p.setFont(QFont("JetBrains Mono", 7))
            off = self._scroll // self._stride
            p.drawText(QRectF(8, h - 16, 120, 12), Qt.AlignLeft,
                       f"off +{off}")

        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            y = int(event.position().y()) - self._BODY_T + self._scroll
            idx = y // self._stride if y >= 0 else -1
            if 0 <= idx < len(self._hops):
                self.hop_clicked.emit(self._hops[idx].number)

    def wheelEvent(self, event):
        step = int(event.angleDelta().y() / 120)
        if step == 0:
            return
        self._scroll = max(
            0, min(self._scroll_max(), self._scroll - step * self._stride)
        )
        self.update()


class LatencyGraphWidget(QWidget):
    """RTT SIGNAL // SEGMENTS — bezel-framed latency gauge.

    A console instrument with a bordered panel, corner brackets, a header
    band with live chips, per-hop lanes (chip + identity + gradient bar +
    value), hairline grid, an amber fiber-floor guide, a scale axis in the
    footer, and a drawn cyan scrollbar.
    """

    _HEADER_H = 34
    _ROW_H = 34
    _FOOTER_H = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self._route: Optional[Route] = None
        self._hops: list[Hop] = []
        self._label: str = "Per-Hop Route Latency"
        self._scroll: int = 0
        self.setMinimumHeight(160)
        self.setMaximumHeight(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_route(self, route: Optional[Route]):
        new_hops = route.hops if route else []
        same = (
            len(new_hops) == len(self._hops)
            and all(a.ip == b.ip for a, b in zip(new_hops, self._hops))
        )
        self._route = route
        self._hops = new_hops
        if not same:
            self._scroll = 0
        self.update()

    def set_label(self, label: str):
        self._label = label
        self.update()

    def _max_value(self) -> float:
        vals = [
            h.latency for h in self._hops
            if h.latency > 0 and h.status != HopStatus.TIMEOUT
        ]
        return max(vals) if vals else 0.0

    def _floor(self) -> float:
        return self._route.latency_floor_ms if self._route else 0.0

    def _scroll_max(self) -> int:
        content = max(0, len(self._hops) * self._ROW_H)
        visible = max(0, self.height() - self._HEADER_H - self._FOOTER_H)
        return max(0, content - visible)

    def _value_text(self, hop: Hop) -> str:
        if hop.status != HopStatus.TIMEOUT and hop.latency > 0:
            if hop.latency >= 100:
                return f"{hop.latency:.0f} ms"
            return f"{hop.latency:.1f} ms"
        if hop.probes.raw_hint:
            return "\u2014"
        return "T/O"

    def _sub_text(self, hop: Hop) -> str:
        if hop.status == HopStatus.TIMEOUT:
            return "no reply"
        org = (hop.network.as_org or "").strip()
        if org:
            return org
        return hop.ip or ""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()

        p.fillRect(0, 0, w, h, _PANEL_BG)

        if not self._hops:
            p.setPen(QColor(90, 108, 138))
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(QRectF(8, 0, w - 16, h), Qt.AlignCenter,
                       "NO LATENCY DATA \u2014 RUN A TRACE")
            _draw_frame(p, w, h)
            p.end()
            return

        # â”€â”€ Chrome â”€â”€
        _draw_frame(p, w, h)
        _header_band(p, self._HEADER_H)
        _band_title(p, "> RTT SIGNAL // SEGMENTS", self._HEADER_H)

        total = self._route.total_latency if self._route else 0.0
        floor = self._floor()
        n = len(self._hops)
        chips = [(f"TOTAL {total:.1f} ms", _CYAN)]
        if floor > 0 and w >= 340:
            chips.append((f"FLOOR ~{floor:.0f} ms", _AMBER_DIM))
        if w >= 460:
            chips.append((f"{n} SEG", _INK))
        _right_chips(p, w, (self._HEADER_H - 16) / 2, chips)

        # â”€â”€ Geometry â”€â”€
        val_w = 58
        name_w = min(int(w * 0.16), 200)
        name_x = 48
        val_right = w - 10
        val_x = val_right - val_w
        bar_right = val_x - 8
        bar_x = name_x + name_w + 10
        bar_w = max(60, bar_right - bar_x)

        meas = self._max_value()
        scale_max = max(meas, floor if floor > 0 else 0.0) or 1.0

        name_font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        sub_font = QFont("Segoe UI", 7)
        val_font = QFont("JetBrains Mono", 9)
        name_fm = QFontMetrics(name_font)
        sub_fm = QFontMetrics(sub_font)

        body_top = self._HEADER_H + 4
        foot_top = h - self._FOOTER_H

        # â”€â”€ Vertical hairline grid in the body â”€â”€
        p.setPen(QPen(QColor(255, 255, 255, 6), 1))
        for q in (0.25, 0.5, 0.75):
            gx = bar_x + q * bar_w
            p.drawLine(QPointF(gx, body_top), QPointF(gx, foot_top - 2))

        # â”€â”€ Fiber-floor guide â”€â”€
        if floor > 0 and floor <= scale_max:
            fx = bar_x + (floor / scale_max) * bar_w
            p.setPen(QPen(QColor(251, 191, 36, 120), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(fx, body_top), QPointF(fx, foot_top - 2))
            p.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            p.setPen(QColor(205, 168, 82))
            p.drawText(QRectF(fx + 3, body_top - 2, 100, 12),
                       Qt.AlignLeft, "FLOOR")

        # Scrolled lanes must never bleed over the header band or under the
        # footer — clamp all lane painting to the scrollable body region.
        p.save()
        p.setClipRect(QRectF(0, body_top, w, foot_top - body_top))

        # â”€â”€ Lanes â”€â”€
        for i, hop in enumerate(self._hops):
            y = body_top + i * self._ROW_H - self._scroll
            if y > h + 0.5:
                break
            if y + self._ROW_H < 4:
                continue

            sc = _status_color(hop.status)
            scd = QColor(sc.red(), sc.green(), sc.blue())

            # Hairline lane separator.
            p.setPen(QPen(QColor(255, 255, 255, 8), 1))
            p.drawLine(int(10), int(y + self._ROW_H - 1),
                       int(w - 12), int(y + self._ROW_H - 1))

            # Hop-number chip.
            chip = QRectF(12, y + 6, 26, 12)
            p.setPen(QPen(_CHIP_B, 1))
            p.setBrush(QBrush(QColor(24, 33, 52)))
            p.drawRoundedRect(chip, 6, 6)
            p.setFont(QFont("JetBrains Mono", 8))
            p.setPen(QColor(150, 168, 198))
            p.drawText(chip, Qt.AlignCenter, f"{hop.number:02d}")

            # Name / sub.
            name = hop.location_label or hop.display_name or hop.ip
            name = name_fm.elidedText(name, Qt.ElideRight, int(name_w))
            p.setFont(name_font)
            p.setPen(QColor(226, 236, 251))
            p.drawText(QRectF(name_x, y + 1, name_w, 14),
                       Qt.AlignLeft | Qt.AlignVCenter, name)
            sub = sub_fm.elidedText(self._sub_text(hop), Qt.ElideRight,
                                    int(name_w + bar_w))
            p.setFont(sub_font)
            p.setPen(QColor(109, 126, 156))
            p.drawText(QRectF(name_x, y + 15, bar_x + bar_w - name_x, 12),
                       Qt.AlignLeft | Qt.AlignVCenter, sub)

            # Value.
            p.setFont(val_font)
            p.setPen(scd if hop.status != HopStatus.TIMEOUT
                     else QColor(112, 122, 142))
            p.drawText(QRectF(val_x, y + 6, val_w, 16),
                       Qt.AlignVCenter | Qt.AlignRight,
                       self._value_text(hop))

            # Latency bar.
            by = y + 24
            bh = 8
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(25, 34, 54)))
            p.drawRoundedRect(QRectF(bar_x, by, bar_w, bh), 4, 4)
            if hop.status != HopStatus.TIMEOUT and hop.latency > 0:
                bw = max(6.0, bar_w * min(hop.latency / scale_max, 1.0))
                grad = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
                grad.setColorAt(
                    0.0, QColor(scd.red(), scd.green(), scd.blue(), 90))
                grad.setColorAt(1.0, scd)
                p.setBrush(QBrush(grad))
                p.drawRoundedRect(QRectF(bar_x, by, bw, bh), 4, 4)
                p.setBrush(QBrush(QColor(
                    min(255, scd.red() + 75),
                    min(255, scd.green() + 75),
                    min(255, scd.blue() + 75))))
                p.drawEllipse(QPointF(bar_x + bw - 1, by + bh / 2), 3, 3)
            else:
                p.setPen(QPen(QColor(96, 108, 136), 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(bar_x + 2, by + bh / 2),
                           QPointF(bar_x + bar_w - 2, by + bh / 2))

        p.restore()

        # â”€â”€ Footer: summary + scale axis â”€â”€
        vals = [hp.latency for hp in self._hops
                if hp.latency > 0 and hp.status != HopStatus.TIMEOUT]
        avg = sum(vals) / len(vals) if vals else 0.0
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(_INK_DIM)
        p.drawText(QRectF(12, foot_top, w - 24, 12),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   f"{n} SEGMENTS \u00b7 MAX {meas:.1f} ms \u00b7 AVG {avg:.1f} ms")

        axis_y = foot_top + 16
        p.setPen(QPen(QColor(51, 65, 95), 1))
        p.drawLine(QPointF(bar_x, axis_y), QPointF(bar_x + bar_w, axis_y))
        p.setFont(QFont("JetBrains Mono", 7))
        for q in range(5):
            x = bar_x + (q / 4) * bar_w
            p.setPen(QColor(70, 84, 114))
            p.drawLine(QPointF(x, axis_y), QPointF(x, axis_y + 2.5))
            v = scale_max * q / 4
            lab = f"{v:.0f}" if scale_max >= 100 else f"{v:.1f}"
            p.setPen(QColor(100, 116, 144))
            p.drawText(QRectF(x - 18, axis_y + 3, 36, 9),
                       Qt.AlignTop | Qt.AlignHCenter, lab)

        p.setFont(QFont("JetBrains Mono", 7))
        p.setPen(QColor(70, 84, 114))
        p.drawText(QRectF(bar_x + bar_w - 60, axis_y - 13, 60, 10),
                   Qt.AlignRight, f"SCALE {scale_max:.0f} ms")

        # â”€â”€ Scrollbar â”€â”€
        smax = self._scroll_max()
        _scrollbar(p, w, body_top - 2, foot_top - 2, self._scroll, smax,
                   n * self._ROW_H)

        p.end()

    def wheelEvent(self, event):
        step = int(event.angleDelta().y() / 120)
        if step == 0:
            return
        self._scroll = max(
            0, min(self._scroll_max(), self._scroll - step * self._ROW_H)
        )
        self.update()
