"""Network QoS — port of network-qos.html.

Every toggle writes a REAL Windows Policy-based QoS app-tagging policy
(engine.qos) and forces a Group Policy update, verified by read-back.
Games are only listed when their exe genuinely exists on this PC.
"""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QRadialGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from engine import qos as eng
from ui.widgets import toast

_BG = "#08060F"
_AMBER = "#FFB454"
_VIOLET = "#8B6BFF"
_GREEN = "#3DDC97"
_RED = "#FF6F6F"
_INK_100 = "#F6F4FC"
_INK_400 = "#928AAD"
_INK_600 = "#514A70"
_BORDER = "rgba(255,255,255,0.09)"
_BORDER_SOFT = "rgba(255,255,255,0.06)"
_GLASS = "rgba(255,255,255,0.03)"
_DISPLAY = '"Segoe UI", sans-serif'
_MONO = '"JetBrains Mono", monospace'

NET_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
    ' stroke="#FFB454" stroke-width="1.7" stroke-linecap="round"'
    ' stroke-linejoin="round">'
    '<circle cx="6" cy="7" r="2"/><circle cx="18" cy="7" r="2"/>'
    '<circle cx="12" cy="17" r="2"/>'
    '<path d="M6 9v2a2 2 0 002 2h2M18 9v2a2 2 0 01-2 2h-2M12 15v-2"/></svg>')

PLAY_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
    ' stroke="#FFB454" stroke-width="1.7" stroke-linecap="round"'
    ' stroke-linejoin="round"><path d="M6 4l12 8-12 8V4z"/></svg>')


def _svg_label(svg: str, w: int, h: int) -> QLabel:
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    r = QSvgRenderer()
    r.load(svg.encode("utf-8"))
    r.render(p, QRectF(0, 0, w, h))
    p.end()
    lbl = QLabel()
    lbl.setFixedSize(w, h)
    lbl.setPixmap(pm)
    lbl.setStyleSheet("background:transparent;border:none;")
    return lbl


class _Atmosphere(QWidget):
    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(_BG))
        ga = QRadialGradient(QPointF(100 + 520 / 2.4, -120), 520)
        ga.setColorAt(0.0, QColor(255, 180, 84, 24))
        ga.setColorAt(1.0, QColor(255, 180, 84, 0))
        p.fillRect(self.rect(), ga)
        gb = QRadialGradient(QPointF(w, h), 480)
        gb.setColorAt(0.0, QColor(139, 107, 255, 24))
        gb.setColorAt(1.0, QColor(139, 107, 255, 0))
        p.fillRect(self.rect(), gb)
        cx, cy = 0.60 * w, 0.20 * h
        rx, ry = 0.70 * w, 0.60 * h
        if rx > 0 and ry > 0:
            y = 17.0
            while y < h:
                x = 17.0
                while x < w:
                    t = (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2) ** 0.5
                    if t < 0.85:
                        a = int(45 * (1.0 - t / 0.85))
                        if a > 3:
                            p.setPen(QColor(200, 190, 240, a))
                            p.drawPoint(QPointF(x, y))
                    x += 34.0
                y += 34.0
        p.end()


class _Switch(QFrame):
    """Reference .switch (38x21, amber) / .game-toggle (30x17, green)."""

    toggled = Signal(bool)

    def __init__(self, big: bool, color: str):
        super().__init__()
        self._on = False
        self.big = big
        self.color = color
        w, h = (38, 21) if big else (30, 17)
        self.setFixedSize(w, h)
        self.setCursor(Qt.PointingHandCursor)
        self._paint()

    def set_on(self, on: bool):
        self._on = bool(on)
        self._paint()

    def is_on(self) -> bool:
        return self._on

    def _paint(self):
        w, h = self.width(), self.height()
        rr = h / 2 - 1
        if self._on:
            bg = ("rgba(255,180,84,0.22)" if self.color == _AMBER
                  else "rgba(61,220,151,0.20)")
            bd = ("rgba(255,180,84,0.50)" if self.color == _AMBER
                  else "rgba(61,220,151,0.50)")
            knob = self.color
        else:
            bg, bd, knob = "rgba(255,255,255,0.06)", _BORDER, _INK_600
        self.setStyleSheet(
            f"#Sw{{background:{bg};border:1px solid {bd};"
            f"border-radius:{rr:.0f}px;}}")
        self.setObjectName("Sw")
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        d = 15.0 if self.big else 12.0
        x = w - d - 3.5 if self._on else 3.5
        yc = h / 2 - (1.0 if self.big else 0.0)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.color) if self._on else QColor(_INK_600))
        p.drawEllipse(QPointF(x + d / 2, yc), d / 2, d / 2)
        p.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._on = not self._on
            self._paint()
            self.toggled.emit(self._on)
        super().mousePressEvent(ev)


class _POpt(QLabel):
    """Reference .p-opt priority chip; click-to-select within a group."""

    picked = Signal(str)

    def __init__(self, level: str):
        super().__init__(level.upper())
        self.level = level
        self._active = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignCenter)
        f = QFont(self.font())
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.4)
        self.setFont(f)
        self._paint()

    def set_active(self, a: bool):
        self._active = a
        self._paint()

    def _paint(self):
        if self._active:
            self.setStyleSheet(
                "QLabel{font-family:" + _MONO + ";font-size:9.5px;color:"
                + _AMBER + ";background:rgba(255,180,84,0.10);"
                "border:1px solid rgba(255,180,84,0.40);border-radius:6px;"
                "padding:5px 10px;}")
        else:
            self.setStyleSheet(
                "QLabel{font-family:" + _MONO + ";font-size:9.5px;color:"
                + _INK_600 + ";background:transparent;"
                "border:1px solid " + _BORDER + ";border-radius:6px;"
                "padding:5px 10px;}")

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.picked.emit(self.level)
        super().mousePressEvent(ev)


class _GameRow(QFrame):
    level_changed = Signal(str, str)
    enable_changed = Signal(str, bool)

    def __init__(self, name, exe, exe_name, sub, level, enabled):
        super().__init__()
        self.name = name
        self.exe = exe
        self.exe_name = exe_name
        self.level = level
        self.setEnabled_(enabled)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("GRow")
        self.setStyleSheet(
            "#GRow{background:transparent;border:none;"
            "border-bottom:1px solid " + _BORDER_SOFT + ";}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 16, 22, 16)
        lay.setSpacing(16)
        ic = QFrame()
        ic.setFixedSize(34, 34)
        ic.setAttribute(Qt.WA_StyledBackground, True)
        ic.setObjectName("GIcon")
        ic.setStyleSheet(
            "#GIcon{background:rgba(255,180,84,0.10);"
            "border:1px solid rgba(255,180,84,0.25);border-radius:9px;}")
        il = QVBoxLayout(ic)
        il.setContentsMargins(9, 9, 9, 9)
        il.addWidget(_svg_label(PLAY_SVG, 15, 15))
        lay.addWidget(ic, 0, Qt.AlignVCenter)
        box = QVBoxLayout()
        box.setSpacing(2)
        nm = QLabel(name)
        nm.setStyleSheet(
            "font-size:13.5px;font-weight:600;color:" + _INK_100
            + ";background:transparent;")
        self.sub = QLabel(sub)
        self.sub.setStyleSheet(
            "font-size:11.5px;color:" + _INK_600 + ";background:transparent;")
        box.addWidget(nm)
        box.addWidget(self.sub)
        lay.addLayout(box, 1)
        self.status = QLabel("")
        self.status.setStyleSheet(
            "font-family:" + _MONO + ";font-size:9px;color:" + _GREEN
            + ";background:transparent;")
        lay.addWidget(self.status)
        prio = QHBoxLayout()
        prio.setSpacing(5)
        self.opts = {}
        for lv in ("low", "high", "max"):
            o = _POpt(lv)
            o.picked.connect(lambda l, n=name: self.level_changed.emit(n, l))
            prio.addWidget(o)
            self.opts[lv] = o
        lay.addLayout(prio)
        self.tgl = _Switch(big=False, color=_GREEN)
        self.tgl.toggled.connect(
            lambda on, n=self.name: self.enable_changed.emit(n, on))
        lay.setSpacing(10)
        lay.addWidget(self.tgl, 0, Qt.AlignVCenter)
        self._sync()

    def setEnabled_(self, on):
        self._enabled = bool(on)

    def _sync(self):
        for lv, o in self.opts.items():
            o.set_active(lv == self.level)
        self.tgl.set_on(self._enabled)

    def set_level(self, lv):
        self.level = lv
        self._sync()

    def set_enabled(self, on):
        self._enabled = bool(on)
        self._sync()

    def set_running(self, running: bool):
        self.status.setText("\u25cf PRIORITIZING NOW" if running else "")


class _DiscoverWorker(QThread):
    done = Signal(object)

    def run(self):
        try:
            self.done.emit(eng.discover_games())
        except Exception:
            self.done.emit([])


class _PolicyWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, fn, label):
        super().__init__()
        self.fn, self.label = fn, label

    def run(self):
        try:
            self.done.emit(bool(self.fn()), self.label)
        except Exception as exc:
            self.done.emit(False, f"{self.label} ({exc})")


class QosPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.state = eng.load_state()
        self.discovered = []
        self.rows: dict[str, _GameRow] = {}
        self._workers = []

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
        cl.setContentsMargins(44, 36, 44, 60)
        cl.setSpacing(0)
        col.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(col, 1)

        head = QHBoxLayout()
        head.setSpacing(14)
        chip = QFrame()
        chip.setFixedSize(42, 42)
        chip.setAttribute(Qt.WA_StyledBackground, True)
        chip.setObjectName("QosChip")
        chip.setStyleSheet(
            "#QosChip{background:rgba(255,180,84,0.10);"
            "border:1px solid rgba(255,180,84,0.28);border-radius:12px;}")
        chl = QVBoxLayout(chip)
        chl.setContentsMargins(11, 11, 11, 11)
        chl.addWidget(_svg_label(NET_SVG, 19, 19))
        head.addWidget(chip, 0, Qt.AlignTop)
        h1 = QLabel("Network QoS")
        h1.setStyleSheet(
            "font-family:" + _DISPLAY + ";font-size:22px;font-weight:600;"
            "color:" + _INK_100 + ";background:transparent;")
        head.addWidget(h1, 0, Qt.AlignVCenter)
        head.addStretch()
        cl.addLayout(head)
        cl.addSpacing(3)
        intro = QLabel(
            "Automatically prioritizes a game's network traffic over "
            "background downloads and updates while it's running — "
            "extends what Delay Destroyer already targets, applied per "
            "game instead of system-wide.")
        intro.setWordWrap(True)
        intro.setStyleSheet(
            "font-size:13px;color:" + _INK_400 + ";background:transparent;")
        intro.setMaximumWidth(620)
        cl.addWidget(intro)
        cl.addSpacing(22)

        mc = QFrame()
        mc.setAttribute(Qt.WA_StyledBackground, True)
        mc.setObjectName("Master")
        mc.setStyleSheet(
            "#Master{background:" + _GLASS + ";border:1px solid " + _BORDER
            + ";border-radius:16px;}")
        ml = QHBoxLayout(mc)
        ml.setContentsMargins(24, 20, 24, 20)
        ml.setSpacing(0)
        mbox = QVBoxLayout()
        mbox.setSpacing(4)
        mb = QLabel("Auto-detect & prioritize")
        mb.setStyleSheet(
            "font-size:14.5px;font-weight:600;color:" + _INK_100
            + ";background:transparent;")
        mp = QLabel(
            "Writes real Windows Policy-based QoS (DSCP tagging via the "
            "Pacer packet scheduler) for the games below — applied on "
            "launch, removed when you turn a game off.")
        mp.setWordWrap(True)
        mp.setStyleSheet(
            "font-size:12px;color:" + _INK_400 + ";background:transparent;")
        mp.setMaximumWidth(560)
        mbox.addWidget(mb)
        mbox.addWidget(mp)
        ml.addLayout(mbox, 1)
        self.master_sw = _Switch(big=True, color=_AMBER)
        self.master_sw.set_on(bool(self.state.get("master", True)))
        self.master_sw.toggled.connect(self._on_master)
        ml.addWidget(self.master_sw, 0, Qt.AlignVCenter)
        cl.addWidget(mc)
        cl.addSpacing(24)

        lbl = QLabel("DETECTED GAMES")
        f = QFont(lbl.font())
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        lbl.setFont(f)
        lbl.setStyleSheet(
            "font-family:" + _MONO + ";font-size:10.5px;color:" + _INK_400
            + ";background:transparent;")
        cl.addWidget(lbl)
        cl.addSpacing(12)

        self.list_card = QFrame()
        self.list_card.setAttribute(Qt.WA_StyledBackground, True)
        self.list_card.setObjectName("GList")
        self.list_card.setStyleSheet(
            "#GList{background:" + _GLASS + ";border:1px solid " + _BORDER
            + ";border-radius:16px;}")
        self._lay = QVBoxLayout(self.list_card)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._empty = QLabel(
            "No supported games found on this PC yet. Supported: VALORANT,\n"
            "Counter-Strike 2, Fortnite — or add any other game executable.")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet(
            "font-size:12.5px;color:" + _INK_600 + ";background:transparent;"
            "padding:30px 20px;")
        self._lay.addWidget(self._empty)
        addrow = QHBoxLayout()
        addrow.setContentsMargins(22, 14, 22, 16)
        addrow.addStretch()
        self.add_btn = QPushButton("Add game")
        self.add_btn.setObjectName("Secondary")
        self.add_btn.clicked.connect(self._add_game)
        addrow.addWidget(self.add_btn)
        addrow.addStretch()
        self._lay.addLayout(addrow)
        cl.addWidget(self.list_card)

        fn = QLabel(
            "Priority applies only while the game is running — it tags "
            "outbound packets with a DSCP value the local scheduler and "
            "your router can honour. This changes traffic scheduling on "
            "your PC, not your ISP connection, so it won't help if the "
            "bottleneck is outside your network.")
        fn.setWordWrap(True)
        fn.setStyleSheet(
            "font-size:11.5px;color:" + _INK_600 + ";background:transparent;")
        cl.addSpacing(18)
        cl.addWidget(fn)
        cl.addStretch()

        self._watch = QTimer(self)
        self._watch.setInterval(5000)
        self._watch.timeout.connect(self._tick)

        self._worker = _DiscoverWorker()
        self._worker.done.connect(self._on_games)
        self._worker.start()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._atmo.setGeometry(self.rect())
        self._atmo.lower()

    # ------------------------------------------------------------ build

    def _all_games(self):
        games = {g["name"]: g for g in self.discovered}
        for name, meta in (self.state.get("games") or {}).items():
            if name not in games and meta.get("exe"):
                games[name] = {
                    "name": name, "exe": meta["exe"],
                    "exe_name": meta["exe"].split("\\")[-1],
                    "last_run": None,
                }
        return list(games.values())

    def _on_games(self, found):
        self.discovered = found
        for name, meta in (self.state.get("games") or {}).items():
            for g in found:
                if g["name"] == name and meta.get("exe") != g["exe"]:
                    meta["exe"] = g["exe"]
                    meta["exe_name"] = g["exe_name"]
        self._rebuild()
        self._watch.start()

    def _rebuild(self):
        for r in list(self.rows.values()):
            r.setParent(None)
            r.deleteLater()
        self.rows.clear()
        has_any = False
        for g in self._all_games():
            meta = self.state["games"].setdefault(g["name"], {})
            row = _GameRow(
                g["name"], g["exe"], g["exe_name"],
                eng.last_played_text(g.get("last_run")),
                meta.get("level", "high"), bool(meta.get("enabled", False)))
            row.level_changed.connect(self._on_level)
            row.enable_changed.connect(self._on_enable)
            self._lay.insertWidget(self._lay.count() - 2, row)
            self.rows[g["name"]] = row
            has_any = True
        self._empty.setVisible(not has_any)
        eng.save_state(self.state)

    # ------------------------------------------------------------ actions

    def _run(self, fn, label, on_done=None):
        w = _PolicyWorker(fn, label)
        w.done.connect(lambda ok, lab: self._on_done(ok, lab, on_done))
        w.start()
        self._workers.append(w)

    def _on_done(self, ok, label, on_done=None):
        toast(("Applied — " if ok else "Failed — ") + label
              + ("" if ok else " (check admin rights)"),
              "success" if ok else "error", self)
        if on_done:
            on_done(ok)
        eng.save_state(self.state)

    def _persist(self, name, **kw):
        self.state["games"].setdefault(name, {}).update(kw)
        eng.save_state(self.state)

    def _on_level(self, name, level):
        row = self.rows.get(name)
        if not row:
            return
        prev = row.level
        row.set_level(level)
        self._persist(name, level=level)
        if row._enabled and self.master_sw.is_on():
            def undo(ok):
                if not ok:
                    row.set_level(prev)
                    self._persist(name, level=prev)
            self._run(partial(eng.set_policy, name, row.exe, level),
                      f"{name} tagged {level.upper()} "
                      f"(DSCP {eng.LEVELS[level]['dscp']})", undo)

    def _on_enable(self, name, on):
        row = self.rows.get(name)
        if not row:
            return
        self._persist(name, enabled=on, exe=row.exe,
                      exe_name=row.exe_name)
        if on and self.master_sw.is_on():
            def done(ok):
                row.set_enabled(ok)
                self._persist(name, enabled=bool(ok))
            self._run(partial(eng.set_policy, name, row.exe, row.level),
                      f"{name} QoS policy live", done)
        elif not on:
            def done(ok):
                row.set_enabled(not ok and on)
            self._run(partial(eng.remove_policy, name),
                      f"{name} policy removed", done)
        else:
            row.set_enabled(on)
            self._persist(name, enabled=on)

    def _on_master(self, on):
        self.state["master"] = on
        eng.save_state(self.state)
        if on:
            def apply_all():
                ok = True
                for name, row in self.rows.items():
                    if row._enabled:
                        ok = eng.set_policy(name, row.exe, row.level) and ok
                eng.set_non_besteffort_reserve(True)
                return ok
            self._run(apply_all, "all enabled games prioritized")
        else:
            def remove_all():
                for name in self.rows:
                    eng.remove_policy(name)
                return True
            self._run(remove_all,
                      "all QoS policies removed while master is off")

    def _add_game(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose the game's executable", "",
            "Executable (*.exe)")
        if not path:
            return
        name = path.split("\\")[-1].rsplit(".", 1)[0]
        self.state["games"][name] = {
            "exe": path, "exe_name": path.split("\\")[-1],
            "level": "high", "enabled": self.master_sw.is_on(),
        }
        found = {g["name"] for g in self.discovered}
        if name not in found:
            self.discovered.append({
                "name": name, "exe": path,
                "exe_name": path.split("\\")[-1], "last_run": None})
        self._rebuild()
        if self.master_sw.is_on():
            self._run(partial(eng.set_policy, name, path, "high"),
                      f"{name} added and tagged HIGH")

    # ------------------------------------------------------------ watch

    def _tick(self):
        for name, row in self.rows.items():
            run = bool(row._enabled and self.master_sw.is_on()
                       and eng.is_running(row.exe_name))
            row.set_running(run)
