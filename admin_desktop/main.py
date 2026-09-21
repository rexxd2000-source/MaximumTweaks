"""Maximum Tweaks Admin - "Sigil" key manager (desktop).

A native port of the key-manager.html mockup: teal/ink surfaces, gold serif
headings, plan chips, per-key 30-day activity strips, a sticky detail panel
with the per-PC day grid, create-key and revoke dialogs, and a toast.

Sign in with the operator token; the app exchanges it for the server's
HttpOnly session cookie and then manages licenses through the hosted backend.
Network calls always run on a background thread pool (never the UI thread).

Run from source:   python -m admin_desktop.main        (repo root)
Built EXE:         build.ps1  ->  dist\\MaximumTweaksAdmin.exe
"""
from __future__ import annotations

import sys
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from PySide6.QtCore import QObject, QPointF, QRunnable, Qt, QThreadPool, QTimer, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from .api import AdminClient, ApiError
from .theme import (
    ICON_PATH, SIGIL, SIGIL_QSS, register_fonts, repolish, rgba,
)
from .theme import MONO, SANS, SERIF

APP_NAME = "Sigil"
DEFAULT_URL = "https://maximumtweaks.onrender.com"

T = SIGIL
DAY_MS = 86400 * 1000
MINUTE = 60


# ---------------------------------------------------------------------------
# Background task plumbing (network calls never block the UI thread)
# ---------------------------------------------------------------------------

class _Signals(QObject):
    finished = Signal(object, object)   # (result, error)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self._fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            self.signals.finished.emit(self._fn(), None)
        except ApiError as e:
            self.signals.finished.emit(None, e)
        except Exception as e:  # noqa: BLE001 - surface anything unexpected
            self.signals.finished.emit(None, ApiError(str(e)))


class TaskHost(QObject):
    """Owner object that keeps a reference to the last task so it is not
    garbage-collected mid-flight."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._active: list = []

    def run(self, fn: Callable[[], object],
            on_done: Callable[[object | None, ApiError | None], None]) -> None:
        task = _Task(fn)
        task.signals.finished.connect(on_done)
        task.signals.finished.connect(lambda *_: self._purge(task))
        self._active.append(task)
        self._pool.start(task)

    def _purge(self, task) -> None:
        with suppress(ValueError):
            self._active.remove(task)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _fmt_ts(ts: str | None) -> str:
    """'2026-09-21 12:00:00' (UTC) -> '21 Sep 2026'."""
    if not ts:
        return "—"
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return ts
    return dt.strftime("%d %b %Y")


def _ago(ts: str | None) -> str | None:
    """Minutes-ago label for a UTC timestamp; None when not usable."""
    if not ts:
        return None
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None
    mins = (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    if mins < 1:
        return "Just now"
    if mins < 60:
        return f"{int(mins)} min ago"
    if mins < 1440:
        return f"{round(mins / 60)} hour{'s' if round(mins / 60) != 1 else ''} ago"
    return f"{int(mins // 1440)} day{'s' if int(mins // 1440) != 1 else ''} ago"


def _day_labels(span: int) -> list[str]:
    today = datetime.now(timezone.utc).date()
    return [(today - timedelta(days=span - 1 - i)).isoformat()
            for i in range(span)]


PLANS = {
    "1m": ("1 Month", "m1", 30),
    "monthly": ("1 Month", "m1", 30),
    "6m": ("6 Months", "m6", 180),
    "custom": ("6 Months", "m6", 180),
    "yearly": ("6 Months", "m6", 365),
    "life": ("Lifetime", "life", None),
    "lifetime": ("Lifetime", "life", None),
}


def plan_label(plan: str) -> str:
    return PLANS.get((plan or "life"), PLANS["life"])[0]


def plan_chip(plan: str) -> str:
    return PLANS.get((plan or "life"), PLANS["life"])[1]


# ---------------------------------------------------------------------------
# Custom paint widgets (gold strips + day grids, like the mockup)
# ---------------------------------------------------------------------------

class StripWidget(QWidget):
    """Last-14-days activity strip: one gold bar per day, height by PC count."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.values: list[int] = []   # per-day PC counts (oldest -> newest)
        self.max_v = 1
        self.setFixedHeight(22)
        self.setMinimumWidth(96)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_counts(self, counts: list[int], max_pcs: int) -> None:
        self.values = counts[-14:]
        self.max_v = max(1, max_pcs or 1, *(self.values or [0]))
        self.update()

    def paintEvent(self, event) -> None:
        if not self.values:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        n = len(self.values)
        w = (self.width() - (n - 1) * 2) / n
        for i, v in enumerate(self.values):
            h = (6 + (16 * v / self.max_v)) if v else 3
            x = i * (w + 2)
            color = QColor(T["gold"]) if v else QColor(T["muted"])
            if not v:
                color.setAlphaF(0.28)
            p.fillRect(QRectF(x, self.height() - h, max(w, 2), h), color)
        p.end()


class ActivityChart(QWidget):
    """30-day daily PC grid: a bars row (PCs active per day) then one row of
    cells per PC, matching the mockup's ``.chart`` block."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.days = 30
        self.day_counts: list[int] = []
        self.pcs: list[dict] = []      # {name, days: {iso: True}}
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def set_data(self, pcs: list[dict], day_counts: list[int]) -> None:
        self.pcs = pcs
        self.day_counts = day_counts
        self.update()

    def _layout(self) -> tuple[float, float, float, float]:
        label_w = 96.0
        gap = 2.0
        bar_h = 34.0
        row_h = 16.0
        cell = (self.width() - label_w - gap * (self.days - 1)) / self.days
        y = 6.0
        return label_w, bar_h, row_h, cell

    def sizeHint(self):
        from PySide6.QtCore import QSize
        _, bar_h, row_h, _ = self._layout()
        return QSize(560, int(bar_h + len(self.pcs) * row_h + 18))

    def paintEvent(self, event) -> None:
        if not self.pcs:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        label_w, bar_h, row_h, cell = self._layout()
        y = 6.0
        max_pcs = max(1, len(self.pcs))

        # bars row: how many PCs were active each day
        for i in range(self.days):
            v = self.day_counts[i] if i < len(self.day_counts) else 0
            h = bar_h * (0.35 + 0.65 * v / max_pcs) if v else 4.0
            x = label_w + i * (cell + 2)
            color = QColor(T["gold"]) if v else QColor(T["muted"])
            if not v:
                color.setAlphaF(0.24)
            p.fillRect(QRectF(x, y + bar_h - h, max(cell, 2), h), color)
        y += bar_h + 6

        # per-PC cell rows
        for pc in self.pcs:
            days = pc.get("days", {})
            for i in range(self.days):
                day = _day_labels(30)[i]
                on = days.get(day, False)
                x = label_w + i * (cell + 2)
                color = QColor(T["gold_hi"]) if on else QColor("#ffffff")
                if on:
                    p.fillRect(QRectF(x, y, cell, row_h), QColor("#d9bd7a"))
                else:
                    p.setPen(QPen(QColor("#ffffff"), 0))
                    p.fillRect(QRectF(x, y, cell, row_h), QColor("#ffffff").withAlphaF(0.075))
            y += row_h + 2
        p.end()


# ---------------------------------------------------------------------------
# Painted monitor icon (no emoji / font dependency)
# ---------------------------------------------------------------------------

class PcIcon(QWidget):
    """Small outline of a desktop monitor, drawn with QPainter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#8ea3a0"))
        pen.setWidthF(1.3)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(1.5, 1.5, 13, 9), 1.5, 1.5)
        p.drawLine(5.5, 13.5, 10.5, 13.5)
        p.drawLine(8, 10.5, 8, 13.5)
        p.end()


# ---------------------------------------------------------------------------
# Row widget (one key in the list)
# ---------------------------------------------------------------------------

class KeyRow(QFrame):
    clicked = Signal(str)

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.data = data
        self.setObjectName("Row")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selected = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 14, 24, 14)
        outer.setSpacing(18)

        # who / key
        who_col = QVBoxLayout()
        who_col.setSpacing(2)
        name = QLabel(data.get("customer") or data.get("note") or "—")
        name.setObjectName("RowName")
        name.setToolTip(name.text())
        key = QLabel(data.get("key", ""))
        key.setObjectName("Key")
        who_col.addWidget(name)
        who_col.addWidget(key)

        # plan chip
        chip = QLabel(plan_label(data.get("plan", "life")))
        chip.setObjectName("Chip")
        chip.setProperty("class", plan_chip(data.get("plan", "life")))
        repolish(chip)

        # PCs used
        used = data.get("used_pcs", 0)
        max_pcs = data.get("max_pcs", 1)
        pcs_lbl = QLabel(f"{used}/{max_pcs}")
        pcs_lbl.setFont(self._mono())
        if data.get("blocked_week"):
            pcs_lbl.setStyleSheet(f"color:{T['warn']};")
            pcs_lbl.setToolTip(f"{data['blocked_week']} blocked attempt(s) this week")

        # 14-day strip
        strip = StripWidget()
        counts = day_counts_for(data, 14)
        strip.set_counts(counts, max_pcs)

        # last check-in
        last = self._last_label(data)
        last.setObjectName("RowLast")

        # action / status
        act = QLabel()
        st = status_of(data)
        if st == "active":
            btn = QPushButton("Revoke")
            btn.setObjectName("BtnRose")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda: self.clicked.emit("revoke:" + data.get("key", "")))
            act = btn
        else:
            act.setText("Expired" if st == "expired" else "Revoked")
            act.setStyleSheet(f"color:{T['warn'] if st == 'expired' else T['rose']}"
                              f";font-weight:600;")
            act.setAlignment(Qt.AlignmentFlag.AlignRight)

        outer.addLayout(who_col, 3)
        outer.addWidget(chip, 0)
        outer.addWidget(pcs_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(strip, 1)
        outer.addWidget(last, 2)
        outer.addWidget(act, 0)

        self.setMinimumHeight(58)

    @staticmethod
    def _mono():
        f = QFont("IBM Plex Mono")
        f.setPointSize(12)
        return f

    def _last_label(self, data: dict) -> QWidget:
        st = status_of(data)
        if st == "revoked":
            lbl = QLabel("Signed out")
            lbl.setStyleSheet(f"color:{T['muted']};")
            return lbl
        last = data.get("last_seen")
        if not last:
            lbl = QLabel("Not used yet")
            lbl.setStyleSheet(f"color:{T['muted']};")
            return lbl
        mins = _minutes_since(last)
        if mins is not None and mins < 5:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            dot = QLabel()
            dot.setFixedSize(7, 7)
            dot.setObjectName("Dot")
            t = QLabel("Online now")
            t.setObjectName("Online")
            h.addWidget(dot)
            h.addWidget(t)
            return w
        lbl = QLabel(_ago(last) or "—")
        lbl.setStyleSheet(f"color:{T['muted']};")
        return lbl

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self.setProperty("selected", "true" if on else "false")
        repolish(self)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit("select:" + self.data.get("key", ""))
        super().mousePressEvent(event)


def status_of(k: dict) -> str:
    st = k.get("status", "active")
    if st == "revoked":
        return "revoked"
    exp = k.get("expires_at")
    if exp and _minutes_since(exp) is not None and _minutes_since(exp) < 0:
        return "expired"
    return "active"


def _minutes_since(ts: str) -> int | None:
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None
    return int((datetime.now(timezone.utc) - dt).total_seconds() // 60)


def day_counts_for(data: dict, span: int) -> list[int]:
    """Turn the day_counts map (iso date -> pc count) into a dense array."""
    dc = data.get("day_counts", {})
    out = []
    for d in _day_labels(span):
        out.append(int(dc.get(d, 0)))
    return out


# ---------------------------------------------------------------------------
# Detail panel content
# ---------------------------------------------------------------------------

def build_detail(data: dict, activity: dict | None,
                 on_revoke: Callable[[str], None],
                 on_copy: Callable[[str], None],
                 on_remove_pc: Callable[[str, str], None]) -> QWidget:
    """Render the sticky right-hand detail panel for one key."""
    root = QWidget()
    lay = QVBoxLayout(root)
    lay.setContentsMargins(26, 24, 26, 24)
    lay.setSpacing(14)

    st = status_of(data)
    key = data.get("key", "")

    # heading + pill
    head = QHBoxLayout()
    head.setSpacing(12)
    left = QVBoxLayout()
    left.setSpacing(3)
    who = QLabel(data.get("customer") or data.get("note") or "—")
    who.setObjectName("DetailTitle")
    created = QLabel("Created " + _fmt_ts(data.get("created_at")))
    created.setObjectName("DetailSub")
    left.addWidget(who)
    left.addWidget(created)
    pill = QLabel("Revoked" if st == "revoked" else ("Expired" if st == "expired"
                                                      else "Active"))
    pill.setObjectName("Pill")
    pill.setProperty("state", st)
    repolish(pill)
    head.addLayout(left, 1)
    head.addWidget(pill, 0, Qt.AlignmentFlag.AlignTop)
    lay.addLayout(head)

    # keybox
    kb = QFrame()
    kb.setObjectName("KeyBox")
    kb_l = QHBoxLayout(kb)
    kb_l.setContentsMargins(16, 9, 10, 9)
    kb_l.setSpacing(10)
    code = QLabel(key)
    code.setObjectName("KeyCode")
    code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    copy_btn = QPushButton("Copy")
    copy_btn.setObjectName("BtnGhost")
    copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    copy_btn.clicked.connect(lambda: on_copy(key))
    kb_l.addWidget(code, 1)
    kb_l.addWidget(copy_btn)
    lay.addWidget(kb)

    # banners
    if st == "revoked":
        note = QLabel(f"{data.get('customer') or key} was revoked. Every PC on this "
                      "key is signed out and can't use it again.")
        note.setObjectName("NoteRose")
        note.setWordWrap(True)
        lay.addWidget(note)
    elif st == "expired":
        note = QLabel(f"This key ran out on {_fmt_ts(data.get('expires_at'))}. "
                      "PCs on it can no longer open the app.")
        note.setObjectName("NoteAmber")
        note.setWordWrap(True)
        lay.addWidget(note)

    # facts grid
    facts = QFrame()
    fl = QHBoxLayout(facts)
    fl.setSpacing(18)
    cells = [
        ("Plan", plan_label(data.get("plan", "life"))),
        ("Expires", _fmt_ts(data.get("expires_at")) if data.get("expires_at")
         else "Never"),
        ("PCs used", f"{data.get('used_pcs', 0)} of {data.get('max_pcs', 1)} allowed"),
        ("Last check-in", _last_text(data, st)),
    ]
    for name, value in cells:
        c = QVBoxLayout()
        c.setSpacing(3)
        lbl = QLabel(name)
        lbl.setObjectName("FactName")
        val = QLabel(value)
        val.setObjectName("FactValue" if st == "active" else "FactValue")
        val.setWordWrap(True)
        c.addWidget(lbl)
        c.addWidget(val)
        fl.addLayout(c, 1)
    lay.addWidget(facts)

    # blocked attempts warning (instead of "More PCs than allowed")
    blocked = (activity or {}).get("blocked", []) if activity else []
    blocked_week = data.get("blocked_week", 0)
    if blocked_week:
        note = QLabel(f"{blocked_week} blocked attempt{'s' if blocked_week != 1 else ''} "
                      "this week — a new PC tried to check in beyond this key's PC limit.")
        note.setObjectName("NoteAmber")
        note.setWordWrap(True)
        lay.addWidget(note)

    # activity section
    sec = QFrame()
    sl = QVBoxLayout(sec)
    sl.setContentsMargins(0, 0, 0, 0)
    sl.setSpacing(8)
    title = QLabel("Activity in the last 30 days")
    title.setObjectName("SectionTitle")
    pcs = data.get("pcs", [])
    if pcs:
        sum_lbl = QLabel("Darker cells are days that PC checked in. "
                         "Hover a bar to see which PCs were on.")
        sum_lbl.setObjectName("SectionSum")
        chart = ActivityChart()
        chart.set_data(pcs, day_counts_for(data, 30))
        sl.addWidget(title)
        sl.addWidget(sum_lbl)
        sl.addWidget(chart)
    else:
        empty = QLabel("No PC has used this key yet. Activity appears here after "
                       "the first check-in.")
        empty.setObjectName("NoteAmber")
        empty.setWordWrap(True)
        sl.addWidget(title)
        sl.addWidget(empty)
    lay.addWidget(sec)

    # PCs on this key (with Remove PC buttons)
    if pcs:
        pcsec = QFrame()
        pl = QVBoxLayout(pcsec)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        ptitle = QLabel("PCs on this key")
        ptitle.setObjectName("SectionTitle")
        pmax = QLabel(f"PCs used: {data.get('used_pcs', 0)} of {data.get('max_pcs', 1)} allowed")
        pmax.setObjectName("RowLast")
        pl.addWidget(ptitle)
        pl.addWidget(pmax)
        pl.addSpacing(8)
        for pc in pcs:
            pl.addWidget(_pc_row(pc, st, key, on_remove_pc))
        lay.addWidget(pcsec)

    # footer revoke
    if st == "active":
        dfoot = QFrame()
        fh = QHBoxLayout(dfoot)
        fh.setContentsMargins(2, 12, 2, 12)
        fh.setSpacing(12)
        note = QLabel("Revoking stops this key right away.")
        note.setObjectName("RowLast")
        rev = QPushButton("Revoke key")
        rev.setObjectName("BtnRoseSolid")
        rev.setCursor(Qt.CursorShape.PointingHandCursor)
        rev.clicked.connect(lambda: on_revoke(key))
        fh.addWidget(note, 1)
        fh.addWidget(rev)
        lay.addWidget(dfoot)

    lay.addStretch(1)
    return root


def _merge_pcs(overview_pcs: list[dict], activity_pcs: list[dict]) -> list[dict]:
    """Join overview PC rows (name/last_seen) with activity PC rows (days),
    one dict per hwid so the chart and "Active X of 30 days" both work."""
    merged: dict[str, dict] = {}
    for pc in overview_pcs:
        h = pc.get("hwid")
        if h:
            merged[h] = dict(pc)
    for pc in activity_pcs:
        h = pc.get("hwid")
        if not h:
            continue
        if h in merged:
            merged[h].update(pc)
        else:
            merged[h] = dict(pc)
    return list(merged.values())


def _last_text(data: dict, st: str) -> str:
    if st == "revoked":
        return "Signed out"
    last = data.get("last_seen")
    if not last:
        return "Not used yet"
    mins = _minutes_since(last)
    if mins is not None and mins < 5:
        return "Online now"
    return _ago(last) or "—"


def _pc_row(pc: dict, key_status: str, key: str,
            on_remove: Callable[[str, str], None]) -> QWidget:
    last = pc.get("last_seen")
    days_on = len([v for v in pc.get("days", {}).values() if v])
    mins = _minutes_since(last) if last else None

    row = QFrame()
    row.setObjectName("PcvPC")
    lay = QHBoxLayout(row)
    lay.setContentsMargins(2, 10, 2, 10)
    lay.setSpacing(12)

    dot = PcIcon()

    mid = QVBoxLayout()
    mid.setSpacing(1)
    pn = QLabel(pc.get("name") or "PC")
    pn.setObjectName("PcName")
    hw = QLabel((pc.get("hwid") or "")[:12] + "…")
    hw.setObjectName("PcHw")
    mid.addWidget(pn)
    mid.addWidget(hw)

    right = QVBoxLayout()
    right.setSpacing(1)
    right.setAlignment(Qt.AlignmentFlag.AlignRight)
    status = QLabel()
    status.setObjectName("PcStatus")
    if key_status == "revoked":
        status.setText("Signed out")
        status.setStyleSheet(f"color:{T['rose']};")
    elif mins is not None and mins < 5:
        status.setText("Online now")
        status.setStyleSheet(f"color:{T['live']};font-weight:600;")
    else:
        status.setText(("Seen " + (_ago(last) or "—")) if last else "Not seen")
        status.setStyleSheet(f"color:{T['ink_2']};")
    small = QLabel(f"Active {days_on} of 30 days")
    small.setObjectName("MiniStat")
    right.addWidget(status, 0, Qt.AlignmentFlag.AlignRight)
    right.addWidget(small, 0, Qt.AlignmentFlag.AlignRight)

    remove = QPushButton("Remove PC")
    remove.setObjectName("BtnRose")
    remove.setCursor(Qt.CursorShape.PointingHandCursor)
    remove.setToolTip("Free this slot so another PC can check in")
    remove.clicked.connect(lambda: on_remove(key, pc.get("hwid", "")))

    lay.addWidget(dot)
    lay.addLayout(mid, 1)
    lay.addLayout(right)
    lay.addWidget(remove)
    return row


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setModal(True)
        self.setMinimumWidth(420)

        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("Operator token")
        self.hint = QLabel("Sign in to manage license keys.")
        self.hint.setObjectName("DlgHint")
        self.hint.setWordWrap(True)

        sign_btn = QPushButton("Sign in")
        sign_btn.setObjectName("BtnGold")
        sign_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sign_btn.clicked.connect(self.start_login)
        self.sign_btn = sign_btn

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)
        title = QLabel("Sigil")
        title.setObjectName("DialogTitle")
        sub = QLabel("Licence keys for Maximum Tweaks")
        sub.setObjectName("DlgHint")
        layout.addWidget(title)
        layout.addWidget(sub)
        layout.addSpacing(6)
        layout.addWidget(self.token)
        layout.addSpacing(6)
        layout.addWidget(sign_btn)
        layout.addWidget(self.hint)

        self.client = None
        self._host = TaskHost(self)

    def start_login(self) -> None:
        token = self.token.text().strip()
        if not token:
            self.hint.setText("Enter your operator token.")
            self.hint.setStyleSheet(f"color:{T['rose']};")
            return
        self.sign_btn.setEnabled(False)
        self.hint.setText("Signing in…")
        self.hint.setStyleSheet(f"color:{T['muted']};")
        client = AdminClient(DEFAULT_URL)

        def task():
            client.login(token)
            return client.me()

        def done(result, error):
            self.sign_btn.setEnabled(True)
            if error is not None:
                self.hint.setText("Could not sign in. Check the token and try again.")
                self.hint.setStyleSheet(f"color:{T['rose']};")
                return
            self.client = client
            self.accept()

        self._host.run(task, done)


# ---------------------------------------------------------------------------
# Create-key dialog (mockup plans + PC stepper)
# ---------------------------------------------------------------------------

class PlanCard(QWidget):
    clicked = Signal(str)

    def __init__(self, plan_id: str, label: str, sub: str, parent=None):
        super().__init__(parent)
        self.plan_id = plan_id
        self.setObjectName("PlanCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("on", "false")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(2)
        b = QLabel(label)
        b.setStyleSheet("font-size:15px;font-weight:700;background:transparent;")
        s = QLabel(sub)
        s.setStyleSheet(f"color:{T['muted']};font-size:12px;background:transparent;")
        lay.addWidget(b)
        lay.addWidget(s)

    def set_on(self, on: bool) -> None:
        self.setProperty("on", "true" if on else "false")
        repolish(self)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.plan_id)
        super().mousePressEvent(event)


class CreateKeyDialog(QDialog):
    def __init__(self, client: AdminClient, host: TaskHost, parent=None):
        super().__init__(parent)
        self.client = client
        self.host = host
        self.setWindowTitle("Create a key")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_form())
        self._stack.addWidget(self._build_done())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._stack)

        self.plan_id = "1m"
        self.pc_max = 1

    def _build_form(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(30, 26, 30, 26)
        lay.setSpacing(14)

        title = QLabel("Create a key")
        title.setObjectName("DialogTitle")
        lead = QLabel("Pick how long it lasts and how many PCs can use it.")
        lead.setObjectName("DlgHint")
        lead.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(lead)
        lay.addSpacing(6)

        who_lbl = QLabel("Customer or label")
        who_lbl.setObjectName("DlgFieldName")
        self.who = QLineEdit()
        self.who.setPlaceholderText("For example, Thabo N.")
        self.who.setMaxLength(40)
        self.err = QLabel("")
        self.err.setObjectName("DlgErr")
        lay.addWidget(who_lbl)
        lay.addWidget(self.who)
        lay.addWidget(self.err)

        plan_lbl = QLabel("Plan")
        plan_lbl.setObjectName("DlgFieldName")
        lay.addWidget(plan_lbl)
        self.cards: dict[str, PlanCard] = {}
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        for pid, label, sub in (("1m", "1 Month", "30 days of access"),
                                ("6m", "6 Months", "180 days of access"),
                                ("life", "Lifetime", "Never expires")):
            card = PlanCard(pid, label, sub)
            card.clicked.connect(self._select_plan)
            self.cards[pid] = card
            cards_row.addWidget(card, 1)
        lay.addLayout(cards_row)

        pcs_lbl = QLabel("PCs allowed")
        pcs_lbl.setObjectName("DlgFieldName")
        lay.addWidget(pcs_lbl)
        step_row = QHBoxLayout()
        step_row.setSpacing(8)
        minus = QPushButton("−")
        minus.setObjectName("BtnGhost")
        minus.setFixedWidth(40)
        minus.clicked.connect(lambda: self._step_pc(-1))
        plus = QPushButton("+")
        plus.setObjectName("BtnGhost")
        plus.setFixedWidth(40)
        plus.clicked.connect(lambda: self._step_pc(1))
        self.pc_out = QLabel("1")
        self.pc_out.setObjectName("KeyCode")
        self.pc_out.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pc_out.setMinimumWidth(48)
        hint = QLabel("How many different PCs can be active on this key.")
        hint.setObjectName("DlgHint")
        step_row.addWidget(minus)
        step_row.addWidget(self.pc_out)
        step_row.addWidget(plus)
        step_row.addSpacing(8)
        step_row.addWidget(hint, 1)
        lay.addLayout(step_row)
        lay.addSpacing(10)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("BtnGhost")
        cancel.clicked.connect(self.reject)
        go = QPushButton("Create key")
        go.setObjectName("BtnGold")
        go.setCursor(Qt.CursorShape.PointingHandCursor)
        go.clicked.connect(self.create)
        actions.addWidget(cancel)
        actions.addWidget(go)
        lay.addLayout(actions)
        return w

    def _build_done(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(30, 26, 30, 26)
        lay.setSpacing(12)
        title = QLabel("Key created")
        title.setObjectName("DialogTitle")
        self.done_who = QLabel("")
        self.done_who.setObjectName("DlgHint")
        self.done_who.setWordWrap(True)
        big = QFrame()
        big.setObjectName("KeyBox")
        big_l = QVBoxLayout(big)
        big_l.setContentsMargins(20, 18, 20, 18)
        self.done_key = QLabel("")
        self.done_key.setObjectName("KeyCode")
        self.done_key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.done_key.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        big_l.addWidget(self.done_key)
        self.done_sum = QLabel("")
        self.done_sum.setObjectName("DlgHint")
        self.done_sum.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        lay.addWidget(self.done_who)
        lay.addWidget(big)
        lay.addWidget(self.done_sum)
        lay.addSpacing(10)
        actions = QHBoxLayout()
        actions.addStretch(1)
        copy = QPushButton("Copy key")
        copy.setObjectName("BtnGhost")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(
            self.done_key.text()))
        done = QPushButton("Done")
        done.setObjectName("BtnGold")
        done.clicked.connect(self.accept)
        actions.addWidget(copy)
        actions.addWidget(done)
        lay.addLayout(actions)
        return w

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._stack.setCurrentIndex(0)
        self.who.setFocus()
        self._select_plan("1m")
        self._set_pc(1)

    def _select_plan(self, pid: str) -> None:
        self.plan_id = pid
        for k, card in self.cards.items():
            card.set_on(k == pid)

    def _step_pc(self, delta: int) -> None:
        self._set_pc(self.pc_max + delta)

    def _set_pc(self, value: int) -> None:
        self.pc_max = max(1, min(10, value))
        self.pc_out.setText(str(self.pc_max))

    def create(self) -> None:
        name = self.who.text().strip()
        if not name:
            self.err.setText("Add a name so you can find this key later.")
            self.who.setFocus()
            return
        self.err.setText("")

        def task():
            return self.client.create_key(
                customer=name, plan=self.plan_id, max_pcs=self.pc_max)

        def done(result, error):
            if error is not None:
                self.err.setText(error.message)
                return
            key = result.get("key", "")
            plan_key = result.get("plan", "life")
            self.done_key.setText(key)
            self.done_who.setText(f"Send this key to {name}. It works as soon "
                                  "as their PC checks in.")
            exp = result.get("expires_at")
            self.done_sum.setText(
                f"{plan_label(plan_key)}. "
                f"{('Expires ' + _fmt_ts(exp)) if exp else 'Never expires'}. "
                f"{self.pc_max} PC{'s' if self.pc_max != 1 else ''} allowed.")
            self._stack.setCurrentIndex(1)

        self.host.run(task, done)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class AdminMainWindow(QMainWindow):
    def __init__(self, client: AdminClient):
        super().__init__()
        self.client = client
        self.host = TaskHost(self)
        self.setWindowTitle(APP_NAME + " — License keys")
        self.resize(1360, 820)
        self.setMinimumSize(980, 640)
        if hasattr(ICON_PATH, "startswith") and ICON_PATH:
            with suppress(Exception):
                from PySide6.QtGui import QIcon
                self.setWindowIcon(QIcon(ICON_PATH))

        self.keys: list[dict] = []
        self.stats: dict = {}
        self.selected_key: str | None = None
        self.tab = "active"
        self._toast_t = QTimer(self)
        self._toast_t.setSingleShot(True)
        self._toast_t.timeout.connect(lambda: self._toast.hide())

        central = QWidget()
        central.setObjectName("AppRoot")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        body = QScrollArea()
        body.setWidgetResizable(True)
        body.setFrameShape(QFrame.Shape.NoFrame)
        body_widget = QWidget()
        body_layout = QVBoxLayout(body_widget)
        body_layout.setContentsMargins(28, 30, 28, 40)
        body_layout.setSpacing(20)
        body_layout.addWidget(self._build_hero())
        body_layout.addWidget(self._build_stats_row())
        body_layout.addWidget(self._build_main(), 1)
        body.setWidget(body_widget)
        root.addWidget(body, 1)

        self._toast = QLabel(central)
        self._toast.setObjectName("Toast")
        self._toast.hide()
        self._toast.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(350)
        self.search_timer.timeout.connect(self._reload)

        self._build_last = datetime.now(timezone.utc)
        self.refresh()
        self.poll = QTimer(self)
        self.poll.setInterval(60 * 1000)
        self.poll.timeout.connect(self.refresh)
        self.poll.start()

    # -- chrome -----------------------------------------------------------

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Header")
        bar.setFixedHeight(64)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(28, 10, 28, 10)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(0)
        brand = QLabel("Sigil")
        brand.setObjectName("Brand")
        sub = QLabel("LICENSE ADMIN")
        sub.setObjectName("BrandSub")
        brand_col.addWidget(brand)
        brand_col.addWidget(sub)

        create = QPushButton("  +  Create key")
        create.setObjectName("BtnGold")
        create.setCursor(Qt.CursorShape.PointingHandCursor)
        create.clicked.connect(self.open_create)

        signout = QPushButton("Sign out")
        signout.setObjectName("BtnGhost")
        signout.clicked.connect(self.sign_out)

        lay.addLayout(brand_col)
        lay.addStretch(1)
        lay.addWidget(create)
        lay.addWidget(signout)
        return bar

    def _build_hero(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        title = QLabel("License keys")
        title.setObjectName("HeroTitle")
        sub = QLabel("Create keys, see which PCs use each one every day, and "
                     "revoke access the moment you need to.")
        sub.setObjectName("HeroSub")
        lay.addWidget(title)
        lay.addWidget(sub)
        return w

    def _build_stats_row(self) -> QWidget:
        box = QFrame()
        box.setObjectName("Panel")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(0)
        self.stat_cards: dict[str, tuple[QLabel, QLabel]] = {}
        for key, label in (("active_keys", "Active keys"),
                           ("online_now", "PCs online now"),
                           ("active_today", "PCs active today"),
                           ("expiring_7d", "Keys expiring within 7 days")):
            cell = QFrame()
            cell.setObjectName("Stat")
            c = QVBoxLayout(cell)
            c.setContentsMargins(22, 18, 22, 18)
            c.setSpacing(2)
            num = QLabel("—")
            num.setObjectName("StatNum")
            lbl = QLabel(label)
            lbl.setObjectName("StatLabel")
            c.addWidget(num)
            c.addWidget(lbl)
            lay.addWidget(cell, 1)
            self.stat_cards[key] = (num, lbl)
        return box

    def _build_main(self) -> QWidget:
        split = QSplitter()
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_list_panel())
        split.addWidget(self._build_detail_panel())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([780, 560])
        return split

    # -- list -------------------------------------------------------------

    def _build_list_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(24, 20, 24, 14)
        head.setSpacing(8)
        tabs_wrap = QHBoxLayout()
        tabs_wrap.setSpacing(22)
        self.tab_buttons: dict[str, tuple[QPushButton, QLabel]] = {}
        for tid, label in (("active", "Active"), ("expired", "Expired"),
                           ("revoked", "Revoked"), ("all", "All keys")):
            btn = QPushButton(label)
            btn.setObjectName("Tab")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, v=tid: self.set_tab(v))
            cnt = QLabel("0")
            cnt.setObjectName("TabCount")
            self.tab_buttons[tid] = (btn, cnt)
            tabs_wrap.addWidget(btn)
            tabs_wrap.addWidget(cnt)
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Search name or key")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self.search_timer.start())
        head.addLayout(tabs_wrap, 1)
        head.addWidget(self.search, 0)
        lay.addLayout(head)

        colhead = QHBoxLayout()
        colhead.setContentsMargins(24, 10, 24, 10)
        for text, stretch in (("Customer", 3), ("Plan", 0), ("PCs", 0),
                              ("Last 14 days", 1), ("Last check-in", 2), ("", 0)):
            lbl = QLabel(text) if text else QLabel("")
            lbl.setObjectName("ColHead")
            if text == "Plan":
                lbl.setFixedWidth(86)
            elif text == "PCs":
                lbl.setFixedWidth(44)
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            elif text == "Last 14 days":
                lbl.setFixedWidth(120)
            elif text == "Last check-in":
                lbl.setFixedWidth(130)
            colhead.addWidget(lbl, stretch)
        lay.addLayout(colhead)

        self.rows_box = QVBoxLayout()
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(0)
        container = QWidget()
        container.setLayout(self.rows_box)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(container)
        area.setObjectName("KeyList")
        lay.addWidget(area, 1)
        self.list_area = area
        self.rows_container = container
        return panel

    # -- detail -----------------------------------------------------------

    def _build_detail_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)

        self.detail_stack = QStackedWidget()
        empty = QLabel("Select a key to see its activity, the PCs using it, "
                       "and its 30-day check-in grid.")
        empty.setObjectName("DetailSub")
        empty.setWordWrap(True)
        empty.setAlignment(Qt.AlignmentFlag.AlignTop)
        ew = QWidget()
        el = QVBoxLayout(ew)
        el.setContentsMargins(26, 24, 26, 24)
        el.addWidget(empty)
        self.detail_stack.addWidget(ew)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_stack.addWidget(scroll)
        lay.addWidget(self.detail_stack)
        return panel

    # -- data -------------------------------------------------------------

    def refresh(self) -> None:
        def task():
            return self.client.keys()

        def done(result, error):
            if error is not None:
                self._handle_error(error)
                return
            data = result or {}
            self.keys = data.get("keys", [])
            self.stats = data.get("stats", {})
            self._apply_counts()
            self._render_rows()
            self._render_stats()
            self._render_detail(keep=True)

        self.host.run(task, done)

    def _reload(self) -> None:
        self.refresh()

    def _apply_counts(self) -> None:
        counts = {"active": 0, "expired": 0, "revoked": 0}
        for k in self.keys:
            counts[status_of(k)] += 1
        for tid, (btn, cnt) in self.tab_buttons.items():
            n = len(self.keys) if tid == "all" else counts.get(tid, 0)
            cnt.setText(str(n))
        self.tab_buttons[self.tab][0].setChecked(True)

    def _render_stats(self) -> None:
        s = self.stats or {}
        for key, (num, _) in self.stat_cards.items():
            num.setText(str(s.get(key, 0)))

    def _render_rows(self) -> None:
        while self.rows_box.count():
            item = self.rows_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        active_tab = self.tab
        query = self.search.text().strip().lower()
        shown: list[dict] = []
        for k in self.keys:
            st = status_of(k)
            if active_tab != "all" and st != active_tab:
                continue
            if query:
                hay = f"{k.get('customer','')} {k.get('note','')} {k.get('key','')}".lower()
                if query not in hay:
                    continue
            shown.append(k)

        if not shown:
            empty = QLabel("No keys in this list yet." if not query
                           else "No keys match that search.")
            empty.setObjectName("DetailSub")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("padding:36px;")
            self.rows_box.addWidget(empty)
        else:
            for k in shown:
                row = KeyRow(k)
                row.clicked.connect(self._row_clicked)
                row.set_selected(k.get("key") == self.selected_key)
                self.rows_box.addWidget(row)

    def _row_clicked(self, action: str) -> None:
        if action.startswith("select:"):
            self.selected_key = action[len("select:"):]
            self._render_rows()
            self._render_detail()
        elif action.startswith("revoke:"):
            key = action[len("revoke:"):]
            self.ask_revoke(key)

    def _render_detail(self, keep: bool = False) -> None:
        if not self.selected_key:
            self.detail_stack.setCurrentIndex(0)
            return
        data = next((k for k in self.keys if k.get("key") == self.selected_key),
                    None)
        if data is None:
            if keep:
                return
            self.selected_key = None
            self.detail_stack.setCurrentIndex(0)
            return

        def task():
            return self.client.key_activity(data["key"])

        def done(result, error):
            activity = result if error is None else None
            if activity is None:
                activity = {}
            d = dict(data)  # shallow copy; pcs list is rebuilt below
            d["pcs"] = _merge_pcs(data.get("pcs", []), activity.get("pcs", []))
            widget = build_detail(
                d, activity,
                on_revoke=self.ask_revoke,
                on_copy=self.copy_key,
                on_remove_pc=self.remove_pc,
            )
            scroll = self.detail_stack.widget(1)
            scroll.setWidget(widget)
            if self.detail_stack.currentIndex() != 1:
                self.detail_stack.setCurrentIndex(1)

        self.detail_stack.setCurrentIndex(0)  # brief "loading" (empty)
        self.host.run(task, done)

    # -- actions -----------------------------------------------------------

    def set_tab(self, value: str) -> None:
        self.tab = value
        for tid, (btn, _) in self.tab_buttons.items():
            btn.setChecked(tid == value)
        self._render_rows()

    def open_create(self) -> None:
        dlg = CreateKeyDialog(self.client, self.host, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.toast_msg("Key created.")
            self.refresh()

    def copy_key(self, key: str) -> None:
        QApplication.clipboard().setText(key)
        self.toast_msg("Key copied.")

    def ask_revoke(self, key: str) -> None:
        data = next((k for k in self.keys if k.get("key") == key), None)
        who = (data or {}).get("customer") or key
        if QMessageBox.question(
                self, "Revoke this key?",
                f"Revoke {who} ({key})?\nIt stops working right away. Any PC "
                "using it is signed out the next time the app checks in.") \
                != QMessageBox.StandardButton.Yes:
            return

        def task():
            return self.client.revoke(key, "revoked from Sigil admin")

        def done(result, error):
            if error is not None:
                self._handle_error(error)
                return
            self.toast_msg("Key revoked.")
            self.refresh()

        self.host.run(task, done)

    def remove_pc(self, key: str, hwid: str) -> None:
        if QMessageBox.question(
                self, "Remove this PC?",
                "Removing a PC frees its slot so another PC can check in.\n"
                "The PC is signed out on its next check-in.") \
                != QMessageBox.StandardButton.Yes:
            return

        def task():
            return self.client.remove_pc(key, hwid)

        def done(result, error):
            if error is not None:
                self._handle_error(error)
                return
            self.toast_msg("PC removed — slot freed.")
            self.refresh()

        self.host.run(task, done)

    def sign_out(self) -> None:
        def task():
            self.client.logout()
            return None

        def done(result, error):
            self.close()

        self.host.run(task, done)

    def _position_toast(self) -> None:
        self._toast.adjustSize()
        x = (self.width() - self._toast.width()) // 2
        y = max(8, self.height() - self._toast.height() - 30)
        self._toast.move(x, y)

    def toast_msg(self, text: str, danger: bool = False) -> None:
        self._toast.setText(text)
        self._toast.setProperty("danger", "true" if danger else "false")
        repolish(self._toast)
        self._position_toast()
        self._toast.show()
        self._toast.raise_()
        self._toast_t.start(2200)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._toast.isVisible():
            self._position_toast()

    def _handle_error(self, error: ApiError) -> None:
        if error.status == 401:
            QMessageBox.warning(self, "Session expired", "Please sign in again.")
            self.close()
            return
        self.toast_msg(error.message, danger=True)


# ---------------------------------------------------------------------------

def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    register_fonts()
    app.setFont(QFont("Manrope", 10))
    app.setStyleSheet(SIGIL_QSS)

    login = LoginDialog()
    if login.exec() != QDialog.DialogCode.Accepted:
        return 0
    window = AdminMainWindow(login.client)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())