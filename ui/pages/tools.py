"""Tools page — Diagnostics-style clean layout.

A single centered column: header (title + dot stats + slim actions),
one search line, then the tools grouped into mono-labelled glass lists.
One row per tool: icon chip, name, one-line description, action button.
No pills, no card grid, no pagination — everything scrolls.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QRadialGradient
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.app_config import THEME as T
from engine.tools_runner import launch_tool, run_tweak
from ui.categories import group_tweaks
from ui.widgets import toast

_BG = "#08060F"
_VIOLET = "#8B6BFF"
_INK_100 = "#F6F4FC"
_INK_400 = "#928AAD"
_INK_600 = "#514A70"
_BORDER = "rgba(255,255,255,0.09)"
_BORDER_SOFT = "rgba(255,255,255,0.06)"
_GLASS = "rgba(255,255,255,0.03)"
_DISPLAY = '"Segoe UI", sans-serif'
_MONO = '"JetBrains Mono", monospace'

ALL_KEY = "__all__"
QL_KEY = "Quick Launch"
CAT_ORDER = [QL_KEY, "System Tools", "Diagnostics", "Repair"]

TOOL_META = {
    QL_KEY: ("\u25c9", "#FFB454"),
    "System Tools": ("\u2699", "#6C93FF"),
    "Diagnostics": ("\u2661", "#4BE8D8"),
    "Repair": ("\u2692", "#FFB454"),
}

QUICK_LAUNCH = [
    {"name": "Windows Version",
     "desc": "Check your Windows edition and OS build details.",
     "btn_text": "Check Version", "launch_key": "winver"},
    {"name": "System Information",
     "desc": "Open the full CPU, motherboard and hardware summary.",
     "btn_text": "Open System Info", "launch_key": "msinfo32"},
    {"name": "DirectX Diagnostics",
     "desc": "Launch dxdiag for GPU, driver and feature-level info.",
     "btn_text": "Run dxdiag", "launch_key": "dxdiag"},
    {"name": "Device Manager",
     "desc": "Manage drivers and connected hardware devices.",
     "btn_text": "Open Device Manager", "launch_key": "devmgmt"},
    {"name": "Network Tools",
     "desc": "Flush the DNS cache and reset resolver state.",
     "btn_text": "Flush DNS", "launch_key": "flushdns"},
]


def _quick_launch_items() -> list[dict]:
    return [
        {**q, "id": "ql_" + q["launch_key"], "category": QL_KEY}
        for q in QUICK_LAUNCH
    ]


def _has_cmd(tweak: dict) -> bool:
    return any(isinstance(a, (tuple, list)) and a and a[0] == "cmd"
               for a in tweak.get("actions", []))


def _dedupe(items: list[dict]) -> list[dict]:
    """A quick-launch shortcut and a tweak of the same tool are one row."""
    out, seen = [], set()
    for t in items:
        k = t["name"].strip().lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


class ToolRunner(QThread):
    """Runs a tool/launcher in the background so a UAC prompt or console
    wait never freezes the UI thread. Emits (ok, kind) when done."""

    finished_ok = Signal(bool, str)

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.key = item["id"]

    def run(self):
        item = self.item
        try:
            if item.get("launch_key"):
                ok, kind = launch_tool(item["launch_key"]), "run"
            else:
                ok, kind = run_tweak(item)
        except Exception:
            ok, kind = False, "run"
        self.finished_ok.emit(ok, kind)


class _Atmosphere(QWidget):
    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(_BG))
        ga = QRadialGradient(QPointF(340, 20), 420)
        ga.setColorAt(0.0, QColor(255, 180, 84, 16))
        ga.setColorAt(1.0, QColor(255, 180, 84, 0))
        p.fillRect(self.rect(), ga)
        gb = QRadialGradient(QPointF(w - 120, h), 440)
        gb.setColorAt(0.0, QColor(139, 107, 255, 20))
        gb.setColorAt(1.0, QColor(139, 107, 255, 0))
        p.fillRect(self.rect(), gb)
        cx, cy = 0.6 * w, 0.18 * h
        rx, ry = 0.7 * w, 0.6 * h
        if rx > 0 and ry > 0:
            y = 17.0
            while y < h:
                x = 17.0
                while x < w:
                    t = (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2) ** 0.5
                    if t < 0.85:
                        a = int(40 * (1.0 - t / 0.85))
                        if a > 3:
                            p.setPen(QColor(200, 190, 240, a))
                            p.drawPoint(QPointF(x, y))
                    x += 34.0
                y += 34.0
        p.end()


class _DotStat(QLabel):
    def __init__(self, color, text):
        super().__init__()
        self.color = color
        self.setText(text)

    def setText(self, text):
        self.setTextFormat(Qt.RichText)
        QLabel.setText(
            self,
            f"<span style='color:{self.color};'>\u25cf</span>"
            f"<span style='color:{_INK_400};'>&nbsp; {text}</span>")


class _ToolRow(QFrame):
    clicked = Signal(dict)

    def __init__(self, item):
        super().__init__()
        self.item = item
        self.setToolTip(
            item["name"] + " — " + (item.get("desc") or ""))
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("TRow")
        self.setStyleSheet(
            "#TRow{background:transparent;border:none;border-bottom:1px "
            "solid " + _BORDER_SOFT + ";}"
            "#TRow:hover{background:rgba(255,255,255,0.02);}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 13, 22, 13)
        lay.setSpacing(14)
        cat = item.get("category") or QL_KEY
        glyph, color = TOOL_META.get(cat, ("\u2699", _VIOLET))
        ic = QLabel(glyph)
        ic.setFixedSize(30, 30)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet(
            "QLabel{font-size:13px;color:" + color + ";"
            "background:rgba(255,255,255,0.03);"
            "border:1px solid " + _BORDER + ";border-radius:8px;}")
        lay.addWidget(ic, 0, Qt.AlignVCenter)
        box = QVBoxLayout()
        box.setSpacing(2)
        nm = QLabel(item["name"])
        nm.setStyleSheet(
            "font-size:13.5px;font-weight:600;color:" + _INK_100
            + ";background:transparent;")
        de = QLabel(item.get("desc", ""))
        de.setStyleSheet(
            "font-size:11.5px;color:" + _INK_600 + ";background:transparent;")
        de.setWordWrap(False)
        self._full_desc = item.get("desc", "")
        self._de = de
        box.addWidget(nm)
        box.addWidget(de)
        lay.addLayout(box, 1)
        if item.get("admin"):
            ad = QLabel("ADMIN")
            ad.setStyleSheet(
                "font-family:" + _MONO + ";font-size:9px;color:#FFB454;"
                "background:rgba(255,180,84,0.08);"
                "border:1px solid rgba(255,180,84,0.28);border-radius:6px;"
                "padding:3px 7px;")
            lay.addWidget(ad, 0, Qt.AlignVCenter)
        text = item.get("btn_text") or ("Run" if _has_cmd(item) else "Guide")
        self.btn = QPushButton(text)
        self.btn.setObjectName("Secondary")
        self.btn.setFixedHeight(30)
        self.btn.clicked.connect(
            lambda _=False, it=item: self.clicked.emit(it))
        lay.addWidget(self.btn, 0, Qt.AlignVCenter)

    def _elide(self):
        from PySide6.QtGui import QFontMetrics
        avail = max(60, self._de.width())
        fm = QFontMetrics(self._de.font())
        self._de.setText(
            fm.elidedText(self._full_desc, Qt.ElideRight, avail))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._elide()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.btn.isEnabled():
            self.clicked.emit(self.item)
            return
        super().mousePressEvent(ev)


class ToolsPage(QWidget):
    def __init__(self, ctx, navigate, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.navigate = navigate
        self.key = ALL_KEY
        self._orig_text: dict[str, str] = {}
        self._workers: list[ToolRunner] = []
        self._rows: dict[str, _ToolRow] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._atmo = _Atmosphere(self)
        self._atmo.lower()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea>QWidget>QWidget{background:transparent;}")
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(44, 40, 44, 60)
        cl.setSpacing(0)
        wrap = QHBoxLayout()
        wrap.addWidget(col)
        root.addLayout(wrap)

        # ---- header
        bar = QHBoxLayout()
        bar.setSpacing(10)
        hbox = QVBoxLayout()
        hbox.setSpacing(4)
        title = QLabel("Tools")
        title.setStyleSheet(
            "font-family:" + _DISPLAY + ";font-size:26px;font-weight:600;"
            "color:" + _INK_100 + ";background:transparent;")
        hbox.addWidget(title)
        self.stats = QHBoxLayout()
        self.stats.setSpacing(16)
        self.stat_count = _DotStat("#FFB454", "0 tools")
        self.stats.addWidget(self.stat_count)
        hbox.addLayout(self.stats)
        bar.addLayout(hbox, 1)
        for label, obj, slot in (
                ("Scan Hardware", "Secondary", "detect"),
                ("Quick Optimize", "Secondary", "optimize"),
                ("Logs", "Secondary", "logs")):
            b = QPushButton(label)
            b.setObjectName(obj)
            b.setFixedHeight(34)
            b.clicked.connect(lambda _=False, s=slot: self.navigate(s))
            bar.addWidget(b)
        cl.addLayout(bar)
        cl.addSpacing(20)

        # ---- search
        search_row = QHBoxLayout()
        search_row.setSpacing(10)
        box = QFrame()
        box.setFixedHeight(38)
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setObjectName("SearchBox")
        box.setStyleSheet(
            "#SearchBox{background:" + _GLASS + ";border:1px solid "
            + _BORDER + ";border-radius:10px;}")
        bl = QHBoxLayout(box)
        bl.setContentsMargins(12, 0, 10, 0)
        bl.setSpacing(8)
        ico = QLabel("\u2315")
        ico.setStyleSheet(
            "font-size:13px;color:" + _INK_600 + ";background:transparent;")
        bl.addWidget(ico)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search tools\u2026")
        self.search.setClearButtonEnabled(True)
        self.search.setStyleSheet(
            "QLineEdit{background:transparent;border:none;font-size:13px;"
            "color:" + _INK_100 + ";}"
            "QLineEdit::placeholder{color:" + _INK_600 + ";}")
        self.search.textChanged.connect(lambda _: self.refresh())
        bl.addWidget(self.search, 1)
        search_row.addWidget(box)
        cl.addLayout(search_row)
        cl.addSpacing(22)

        self._list_host = QVBoxLayout()
        self._list_host.setSpacing(22)
        cl.addLayout(self._list_host)
        cl.addStretch()

        self.refresh()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._atmo.setGeometry(self.rect())
        self._atmo.lower()

    # ---------------- data ----------------

    def select(self, key: str):
        self.key = key
        self.search.clear()
        self.refresh()

    def _visible(self) -> list[dict]:
        if self.key == ALL_KEY:
            tools = _quick_launch_items() + group_tweaks("tools")
        elif self.key == QL_KEY:
            tools = _quick_launch_items()
        else:
            tools = [t for t in group_tweaks("tools")
                     if t.get("category") == self.key]
        text = self.search.text().strip().lower()
        if not text:
            return _dedupe(tools)
        return _dedupe([
            t for t in tools
            if text in t["id"].lower()
            or text in t["name"].lower()
            or text in (t.get("desc") or "").lower()
            or text in (t.get("category") or "").lower()
        ])

    # ---------------- render ----------------

    def refresh(self):
        tools = self._visible()
        self.stat_count.setText(f"{len(tools)} tools")
        for i in reversed(range(self._list_host.count())):
            it = self._list_host.takeAt(i)
            if it and it.widget():
                it.widget().setParent(None)
                it.widget().deleteLater()
        self._rows.clear()
        if not tools:
            e = QLabel("No tools match this search.")
            e.setAlignment(Qt.AlignCenter)
            e.setStyleSheet(
                "font-size:12.5px;color:" + _INK_600 + ";"
                "background:transparent;padding:26px;")
            self._list_host.addWidget(e)
            return
        grouped: dict[str, list[dict]] = {}
        for t in tools:
            grouped.setdefault(
                t.get("category") or "Tools", []).append(t)
        order = [c for c in CAT_ORDER if c in grouped]
        order += [c for c in grouped if c not in order]
        for cat in order:
            items = grouped[cat]
            label = QLabel(cat.upper())
            f = QFont(label.font())
            f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
            label.setFont(f)
            label.setStyleSheet(
                "font-family:" + _MONO + ";font-size:10.5px;color:"
                + _INK_400 + ";background:transparent;")
            host = QVBoxLayout()
            host.setSpacing(10)
            card = QFrame()
            card.setAttribute(Qt.WA_StyledBackground, True)
            card.setObjectName("TList")
            card.setStyleSheet(
                "#TList{background:" + _GLASS + ";border:1px solid "
                + _BORDER + ";border-radius:16px;}")
            cl2 = QVBoxLayout(card)
            cl2.setContentsMargins(0, 0, 0, 0)
            cl2.setSpacing(0)
            for i, it in enumerate(items):
                row = _ToolRow(it)
                row.clicked.connect(self._run)
                cl2.addWidget(row)
                if i < len(items) - 1:
                    sep = QFrame()
                    sep.setFixedHeight(1)
                    sep.setStyleSheet(
                        "background:" + _BORDER_SOFT + ";border:none;")
                    cl2.addWidget(sep)
                self._rows[it["id"]] = row
            host.addWidget(label)
            host.addWidget(card)
            w = QWidget()
            w.setLayout(host)
            self._list_host.addWidget(w)

    # ---------------- run ----------------

    def _run(self, item: dict):
        row = self._rows.get(item["id"])
        if row is None:
            return
        self._orig_text[item["id"]] = row.btn.text()
        row.btn.setEnabled(False)
        row.btn.setText("Running\u2026")
        worker = ToolRunner(item)
        worker.finished_ok.connect(self._finish_slot)
        worker.finished.connect(self._on_worker_finished)
        self._workers.append(worker)
        worker.start()

    def _finish_slot(self, ok, kind):
        worker = self.sender()
        if worker is None:
            return
        self._finish(worker.key, ok, worker.item, kind)

    def _on_worker_finished(self):
        self._workers = [w for w in self._workers if not w.isFinished()]

    def _finish(self, key, ok, item, kind="run"):
        row = self._rows.get(key)
        if row is not None:
            row.btn.setEnabled(True)
            row.btn.setText(self._orig_text.get(key, "Run"))
        name = item["name"]
        if not ok:
            msg = f"Failed to launch {name}."
            if item.get("admin"):
                msg += " It needs administrator permission."
            toast(msg, "error", self)
            return
        if kind == "guidance":
            self._show_guidance(item)
        else:
            toast(f"Launched {name} successfully.", "success", self)

    def _show_guidance(self, tweak: dict):
        text = ""
        for action in tweak.get("actions", []):
            if (isinstance(action, (tuple, list)) and action
                    and action[0] == "guidance"):
                text = action[1] if len(action) > 1 else ""
                break
        if not text:
            text = tweak.get("desc", "")
        box = QMessageBox(self)
        box.setWindowTitle(tweak["name"])
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(text)
        desc = tweak.get("desc", "")
        if desc and desc != text:
            box.setInformativeText(desc)
        why = tweak.get("why")
        if why:
            box.setDetailedText(f"Why it matters:\n{why}")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
