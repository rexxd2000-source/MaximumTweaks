"""Smart Debloater â€” exact port of smart-debloater-scan.html +
smart-debloater-improved.html.

Two states, matching the references:
  SCAN    â€” centered head icon, title, mono tag line, lede, glass panel with
            "Scan system" -> live stats strip, gradient progress bar and the
            9-step checklist (idle dots -> violet spinner -> green check +
            real "N found" counts) -> green "View results".
  RESULTS â€” top bar (amber icon chip + title + OS subtitle + Rescan),
            Protected/Debloatable stat cards, note card, category groups of
            checkable row cards (risk + reversible tags, confidence %,
            description + impact lines) and a fixed bottom action bar
            (Clear all / Select safe / Select all / Rescan / Apply selected).

All numbers are the REAL scan results; applying/rollback use the existing
DebloatEngine. Amber is this category's accent, like the reference.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from engine.debloat.engine import DebloatEngine

# Reference palette (tools = amber)
_BG = "#08060F"
_VIOLET = "#8B6BFF"
_VIOLET_D = "#6D4FE0"
_VIOLET_SOFT = "#C9C0FF"
_CYAN = "#4BE8D8"
_GREEN = "#3DDC97"
_AMBER = "#FFB454"
_RED = "#FF6F6F"
_INK_100 = "#F6F4FC"
_INK_400 = "#928AAD"
_INK_600 = "#514A70"
_BORDER = "rgba(255,255,255,0.09)"
_BORDER_SOFT = "rgba(255,255,255,0.06)"
_GLASS = "rgba(255,255,255,0.03)"
_DISPLAY = '"Segoe UI", sans-serif'
_MONO = '"JetBrains Mono", monospace'

STEPS = (
    ("Detecting Windows installation", None),
    ("Scanning Microsoft Store apps", "Microsoft Store Apps"),
    ("Scanning third-party applications", "Third-Party Apps"),
    ("Scanning OEM software", "OEM Apps"),
    ("Scanning optional services", "Optional Services"),
    ("Scanning scheduled tasks", "Scheduled Tasks"),
    ("Scanning startup entries", "Startup Programs"),
    ("Detecting dependencies & hardware", None),
    ("Applying protection rules", "protected"),
)
STEP_PCT = (5, 15, 30, 45, 60, 72, 80, 88, 94)

TAG_STYLE = {
    "SAFE": _GREEN, "OPTIONAL": _AMBER, "CAUTION": _RED,
    "PROTECTED": _VIOLET_SOFT, "UNKNOWN": _INK_600,
}


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha:.2f})"


def _svg(paths: str, color: str, size: int, sw: float = 1.7) -> QLabel:
    from PySide6.QtSvg import QSvgRenderer
    doc = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="{sw}" '
           f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    r = QSvgRenderer()
    r.load(doc.encode("utf-8"))
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setPixmap(pm)
    lbl.setStyleSheet("background:transparent;border:none;")
    return lbl


class _Atmosphere(QWidget):
    """#08060F + amber blob top-left + violet blob bottom-right + dots."""

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(_BG))
        ga = QRadialGradient(QPointF(360, 40), 380)
        ga.setColorAt(0.0, QColor(255, 180, 84, 26))
        ga.setColorAt(0.7, QColor(255, 180, 84, 0))
        p.fillRect(self.rect(), ga)
        gb = QRadialGradient(QPointF(w - 140, h), 340)
        gb.setColorAt(0.0, QColor(139, 107, 255, 26))
        gb.setColorAt(0.7, QColor(139, 107, 255, 0))
        p.fillRect(self.rect(), gb)
        cx, cy = 0.60 * w, 0.20 * h
        rx, ry = 0.70 * w, 0.60 * h
        if rx > 0 and ry > 0:
            y = 17.0
            while y < h:
                x = 17.0
                while x < w:
                    d = (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2) ** 0.5
                    if d < 0.85:
                        a = int(45 * (1.0 - d / 0.85))
                        if a > 3:
                            p.setPen(QColor(200, 190, 240, a))
                            p.drawPoint(QPointF(x, y))
                    x += 34.0
                y += 34.0
        p.end()


class _ScanWorker(QThread):
    progress = Signal(str, int)
    done = Signal(object)
    error = Signal(str)

    def run(self):
        try:
            eng = DebloatEngine()
            res = eng.scan(progress_callback=lambda m, pct: self.progress.emit(m, pct))
            self.done.emit(res)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class _ApplyWorker(QThread):
    done = Signal(bool, list)
    error = Signal(str)

    def __init__(self, engine, items, os_info, parent=None):
        super().__init__(parent)
        self._e, self._i, self._o = engine, items, os_info

    def run(self):
        try:
            ok, errors = self._e.apply(self._i, self._o)
            self.done.emit(ok, errors)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class _Btn(QPushButton):
    def __init__(self, text, kind="glass"):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        if kind == "primary":
            self.setStyleSheet(
                "QPushButton{font-size:14px;font-weight:600;color:#fff;"
                "border:none;border-radius:12px;padding:14px 34px;"
                f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0.3,"
                f"stop:0 {_VIOLET},stop:1 {_VIOLET_D});}}"
                "QPushButton:hover:enabled{background:qlineargradient("
                f"x1:0,y1:0,x2:1,y2:0.3,stop:0 #9C80FF,stop:1 #7C5FF0);}}"
                "QPushButton:disabled{background:rgba(139,107,255,0.25);"
                "color:rgba(255,255,255,0.4);}")
        elif kind == "barPrimary":
            # .btn.primary in the results action bar: compact like the other
            # bar buttons (12.5px / 10px 18px / radius 10), violet gradient.
            self.setStyleSheet(
                "QPushButton{font-size:12.5px;font-weight:600;color:#fff;"
                "border:none;border-radius:10px;padding:10px 18px;"
                "white-space:nowrap;"
                f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0.3,"
                f"stop:0 {_VIOLET},stop:1 {_VIOLET_D});}}"
                "QPushButton:hover:enabled{background:qlineargradient("
                f"x1:0,y1:0,x2:1,y2:0.3,stop:0 #9C80FF,stop:1 #7C5FF0);}}"
                "QPushButton:disabled{opacity:0.45;}")
        elif kind == "green":
            self.setStyleSheet(
                "QPushButton{font-size:14px;font-weight:600;color:#fff;"
                "border:none;border-radius:12px;padding:14px 34px;"
                "background:qlineargradient(x1:0,y1:0,x2:1,y2:0.3,"
                "stop:0 #3DDC97,stop:1 #1F8F63);}"
                "QPushButton:hover:enabled{background:qlineargradient("
                "x1:0,y1:0,x2:1,y2:0.3,stop:0 #58E8AC,stop:1 #2AA578);}}")
        elif kind == "small":
            self.setStyleSheet(
                "QPushButton{font-size:12.5px;font-weight:600;color:"
                + _INK_100 + ";background:rgba(255,255,255,0.03);"
                "border:1px solid " + _BORDER + ";border-radius:10px;"
                "padding:10px 18px;}"
                "QPushButton:hover:enabled{background:rgba(255,255,255,0.07);"
                "border-color:rgba(255,255,255,0.18);}"
                "QPushButton:disabled{opacity:0.45;}")
        else:
            self.setStyleSheet(
                "QPushButton{font-size:14px;font-weight:600;color:"
                + _INK_400 + ";background:rgba(255,255,255,0.03);"
                "border:1px solid " + _BORDER + ";border-radius:12px;"
                "padding:12px 22px;}"
                "QPushButton:hover:enabled{color:" + _INK_100 + ";"
                "background:rgba(255,255,255,0.06);}")


class _StepRow(QWidget):
    IDLE, ACTIVE, DONE = range(3)

    def __init__(self, text, count=""):
        super().__init__()
        self.setText(text)
        self._text = text
        self._count = count
        self.state = self.IDLE
        self.spin = 0.0
        self.setFixedHeight(38)

    def setText(self, text):
        self._font = QFont("Segoe UI", 13)

    def set_state(self, state, count=None):
        self.state = state
        if count is not None:
            self._count = count
        self.update()

    def tick(self):
        if self.state == self.ACTIVE:
            self.spin = (self.spin + 0.12) % (2 * math.pi)
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w = self.width()
        cy = self.height() / 2
        # marker
        m = QRectF(4, cy - 10, 20, 20)
        if self.state == self.DONE:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(_GREEN))
            p.drawEllipse(m)
            f = QFont("Segoe UI", 10)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#07140F"))
            p.drawText(m, Qt.AlignCenter, "\u2713")
        elif self.state == self.ACTIVE:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(_VIOLET_SOFT), 1.5))
            p.drawEllipse(m)
            pen = QPen(QColor(_VIOLET_SOFT), 1.5)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            s = QRectF(m.center().x() - 4.5, m.center().y() - 4.5, 9, 9)
            p.drawArc(s, int(math.degrees(self.spin) * 16), 90 * 16)
        else:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 23), 1.5))
            p.drawEllipse(m)
        # text
        col = {"idle": _INK_400, "a": _INK_100, "d": _INK_400}
        f = QFont("Segoe UI", 13)
        if self.state == self.ACTIVE:
            f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        base = QColor(_INK_100 if self.state == self.ACTIVE else _INK_400)
        if self.state == self.IDLE:
            base.setAlpha(110)
        p.setPen(base)
        p.drawText(QRectF(36, 0, w - 36 - 110, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self._text)
        if self._count:
            fm = QFont("JetBrains Mono", 11)
            p.setFont(fm)
            dim = QColor(_INK_600)
            if self.state != self.IDLE:
                dim = QColor(_INK_400)
            p.setPen(dim)
            p.drawText(QRectF(w - 150, 0, 146, self.height()),
                       Qt.AlignVCenter | Qt.AlignRight, self._count)
        p.end()


class DebloatPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._engine = DebloatEngine()
        self._result = None
        self._selected: set[str] = set()
        self._rows: dict[str, tuple] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._atmo = _Atmosphere(self)
        self._atmo.lower()
        self._root = outer

        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(60)
        self._spin_timer.timeout.connect(self._spin_tick)

        self._build_scan_state()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._atmo.setGeometry(self.rect())
        self._atmo.lower()

    # ------------------------------------------------------------- shared
    def _reset(self):
        # Remove widgets from the page IMMEDIATELY (setParent(None)); plain
        # deleteLater leaves the old page painted under the new one until the
        # event loop runs, which caused the scan/results overlap.
        self._drain(self._root)
        self._spin_timer.stop()

    def _drain(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            if it is None:
                continue
            wdg = it.widget()
            if wdg is not None:
                wdg.setParent(None)
                wdg.deleteLater()
            sub = it.layout()
            if sub is not None:
                self._drain(sub)

    def _scroll_body(self, margins=(40, 44, 40, 60)):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea>QWidget>QWidget{background:transparent;}")
        body = QWidget()
        self._blay = QVBoxLayout(body)
        self._blay.setContentsMargins(*margins)
        self._blay.setSpacing(0)
        scroll.setWidget(body)
        self._root.addWidget(scroll, 1)
        return body

    def _head_chip(self, size=42):
        chip = QFrame()
        chip.setFixedSize(size, size)
        chip.setAttribute(Qt.WA_StyledBackground, True)
        chip.setObjectName("HeadChip")
        chip.setStyleSheet(
            "#HeadChip{background:rgba(255,180,84,0.10);"
            " border:1px solid rgba(255,180,84,0.28); border-radius:12px;}")
        cl = QHBoxLayout(chip)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setAlignment(Qt.AlignCenter)
        cl.addWidget(_svg(
            '<path d="M11 2v2"/><path d="M12 3h-2"/><path d="M13.5 10.5 22 2"/>'
            '<path d="M14.734 13.841a2 2 0 00-.314-2.42L12.58 9.58a2 2 0 00-2.421-.314l-7.657 4.461A1 1 0 002.3 15.3l6.403 6.403a1 1 0 001.571-.204z"/>'
            '<path d="M20 15v4"/><path d="M22 17h-4"/><path d="M4 4v4"/>'
            '<path d="m5 18 2-2"/><path d="M6 6H2"/><path d="m7.699 10.7 5.602 5.601"/>',
            _AMBER, int(size * 0.45)))
        return chip

    # ------------------------------------------------------- SCAN state
    def _build_scan_state(self):
        self._reset()
        body = self._scroll_body((44, 40, 44, 60))
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 8, 0, 0)
        cl.setSpacing(0)
        wrap = QHBoxLayout()
        wrap.addStretch()
        wrap.addWidget(col)
        wrap.addStretch()
        self._blay.addLayout(wrap)
        col.setFixedWidth(1100)

        iconrow = QHBoxLayout()
        iconrow.addStretch()
        iconrow.addWidget(self._head_chip())
        iconrow.addStretch()
        cl.addLayout(iconrow)
        cl.addSpacing(10)

        h1 = QLabel("Smart Debloater")
        h1.setAlignment(Qt.AlignCenter)
        h1.setStyleSheet(
            f"font-family:{_DISPLAY};font-size:24px;font-weight:600;"
            f"color:{_INK_100};background:transparent;")
        cl.addWidget(h1)
        cl.addSpacing(10)

        tags = QLabel()
        tags.setAlignment(Qt.AlignCenter)
        tags.setTextFormat(Qt.RichText)
        tags.setText(
            f"<span style='font-family:JetBrains Mono;font-size:10.5px;"
            f"letter-spacing:1px;color:{_VIOLET_SOFT}'>APPLICATION-FOCUSED"
            f"</span> <span style='color:{_INK_600}'> \u00b7 </span>"
            f"<span style='font-family:JetBrains Mono;font-size:10.5px;"
            f"letter-spacing:1px;color:{_VIOLET_SOFT}'>DEPENDENCY-AWARE"
            "</span> <span style='color:" + _INK_600 + "'> \u00b7 </span>"
            "<span style='font-family:JetBrains Mono;font-size:10.5px;"
            "letter-spacing:1px;color:" + _VIOLET_SOFT + "'>USER-CONTROLLED"
            "</span>")
        tags.setStyleSheet("background:transparent;")
        cl.addWidget(tags)
        cl.addSpacing(24)

        lede = QLabel(
            "Scans your actual PC for genuinely unnecessary applications "
            "and checks whether anything depends on them before "
            "recommending removal. Components required by Windows, drivers, "
            "games, or your installed applications are automatically "
            "protected.")
        lede.setAlignment(Qt.AlignCenter)
        lede.setWordWrap(True)
        lede.setStyleSheet(
            "font-size:13px;color:" + _INK_400 + ";background:transparent;")
        lede.setMaximumWidth(640)
        lw = QHBoxLayout()
        lw.addStretch()
        lw.addWidget(lede)
        lw.addStretch()
        cl.addLayout(lw)
        cl.addSpacing(30)

        panel = QFrame()
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setObjectName("Panel")
        panel.setStyleSheet(
            "#Panel{background:" + _GLASS + ";border:1px solid " + _BORDER
            + ";border-radius:18px;}")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(32, 32, 32, 32)
        pl.setSpacing(0)

        self._idle_cta = QWidget()
        self._idle_cta.setMinimumHeight(120)
        ic = QHBoxLayout(self._idle_cta)
        ic.setContentsMargins(0, 0, 0, 0)
        self.scan_btn = _Btn("Scan system", "primary")
        self.scan_btn.clicked.connect(self._start_scan)
        ic.addStretch()
        ic.addWidget(self.scan_btn)
        ic.addStretch()
        pl.addWidget(self._idle_cta)

        self._live = QWidget()
        self._live.setVisible(False)
        lv = QVBoxLayout(self._live)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)

        strip = QHBoxLayout()
        strip.setSpacing(14)
        strip.setAlignment(Qt.AlignCenter)
        self._stat_lbls = {}
        for key, label in (("scanned", "Scanned"), ("protected", "Protected"),
                           ("debloatable", "Debloatable")):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            n = QLabel("0")
            n.setAlignment(Qt.AlignCenter)
            n.setStyleSheet(
                "font-family:" + _DISPLAY + ";font-size:22px;"
                "font-weight:700;color:" + _VIOLET_SOFT + ";"
                "background:transparent;")
            l = QLabel(label.upper())
            l.setAlignment(Qt.AlignCenter)
            l.setStyleSheet(
                "font-size:10px;color:" + _INK_600 + ";background:transparent;")
            cell.addWidget(n)
            cell.addWidget(l)
            strip.addLayout(cell)
            self._stat_lbls[key] = n
        lv.addLayout(strip)
        lv.addSpacing(26)

        track = QFrame()
        track.setFixedHeight(5)
        track.setAttribute(Qt.WA_StyledBackground, True)
        track.setObjectName("Track")
        track.setStyleSheet(
            "#Track{background:rgba(255,255,255,0.06);border:none;"
            "border-radius:3px;}")
        tl = QHBoxLayout(track)
        tl.setContentsMargins(0, 0, 0, 0)
        self._bar = QFrame()
        self._bar.setFixedHeight(5)
        self._bar.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 " + _VIOLET + ",stop:1 " + _CYAN + ");"
            "border:none;border-radius:3px;")
        self._bar.setFixedWidth(0)
        tl.addWidget(self._bar, 0, Qt.AlignLeft)
        tl.addStretch()
        lv.addWidget(track)
        self._track = track
        lv.addSpacing(26)

        self._step_rows = []
        for text, _cat in STEPS:
            sr = _StepRow(text)
            self._step_rows.append(sr)
            lv.addWidget(sr)
        lv.addSpacing(10)

        self._done_cta = QWidget()
        self._done_cta.setVisible(False)
        dc = QVBoxLayout(self._done_cta)
        dc.setContentsMargins(0, 8, 0, 0)
        dc.setSpacing(16)
        self._done_lbl = QLabel("")
        self._done_lbl.setAlignment(Qt.AlignCenter)
        self._done_lbl.setWordWrap(True)
        self._done_lbl.setStyleSheet(
            "font-size:13px;color:" + _INK_400 + ";background:transparent;")
        btnrow = QHBoxLayout()
        btnrow.addStretch()
        self.view_btn = _Btn("View results", "green")
        self.view_btn.clicked.connect(self._build_results)
        btnrow.addWidget(self.view_btn)
        btnrow.addStretch()
        dc.addWidget(self._done_lbl)
        dc.addLayout(btnrow)
        lv.addWidget(self._done_cta)

        pl.addWidget(self._live)
        cl.addWidget(panel)
        cl.addStretch()

    def _start_scan(self):
        self._idle_cta.setVisible(False)
        self._live.setVisible(True)
        for i, sr in enumerate(self._step_rows):
            sr.set_state(_StepRow.DONE if False else _StepRow.IDLE)
        self._step_rows[0].set_state(_StepRow.ACTIVE)
        self._spin_timer.start()
        self._worker = _ScanWorker(self)
        self._worker.progress.connect(self._on_scan_progress)
        self._worker.done.connect(self._on_scan_done)
        self._worker.error.connect(self._on_scan_error)
        self._worker.start()

    def _spin_tick(self):
        for sr in self._step_rows:
            sr.tick()

    def _on_scan_progress(self, msg, pct):
        idx = 0
        for i, thr in enumerate(STEP_PCT):
            if pct >= thr:
                idx = i
        for i, sr in enumerate(self._step_rows):
            if i < idx:
                sr.set_state(_StepRow.DONE)
            elif i == idx:
                sr.set_state(_StepRow.ACTIVE)
        self._bar.setMinimumWidth(
            int(self._track.width() * min(0.99, pct / 100.0)))

    def _on_scan_done(self, result):
        self._result = result
        self._spin_timer.stop()
        total = len(result.items) + result.total_protected
        counts = {}
        for it in result.items:
            counts[it.category.value] = counts.get(it.category.value, 0) + 1
        for i, (text, cat) in enumerate(STEPS):
            sr = self._step_rows[i]
            if cat is None:
                sr.set_state(_StepRow.DONE)
            elif cat == "protected":
                sr.set_state(_StepRow.DONE,
                             f"{result.total_protected} protected")
            else:
                n = counts.get(cat, 0)
                sr.set_state(_StepRow.DONE, f"{n} found")
        self._bar.setMinimumWidth(self._track.width())
        self._stat_lbls["scanned"].setText(str(total))
        self._stat_lbls["protected"].setText(str(result.total_protected))
        self._stat_lbls["debloatable"].setText(str(result.total_debloatable))
        self._done_lbl.setText(
            f"Scan complete \u2014 {result.total_debloatable} optional "
            f"components found, {result.total_protected} automatically "
            "protected.")
        self._done_cta.setVisible(True)

    def _on_scan_error(self, msg):
        self._spin_timer.stop()
        self._idle_cta.setVisible(True)
        self._live.setVisible(False)
        self._done_lbl.setText(f"Scan failed: {msg}")

    # ---------------------------------------------------- RESULTS state
    def _os_subtitle(self):
        o = self._result.os_info
        name = (o.product_name or "Windows").replace("Microsoft ", "")
        return " \u00b7 ".join([n for n in (
            name, f"Build {o.build}" if o.build else "",
            o.architecture or "") if n])

    def _glass(self, radius=14):
        card = QFrame()
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setObjectName("GlassCardD")
        card.setStyleSheet(
            "#GlassCardD{background:" + _GLASS + ";border:1px solid "
            + _BORDER + ";border-radius:" + str(radius) + "px;}")
        return card

    def _build_results(self):
        self._reset()
        r = self._result
        body = self._scroll_body((44, 36, 44, 24))
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        col.setMaximumWidth(16777215)
        wrap = QHBoxLayout()
        wrap.addWidget(col)
        self._blay.addLayout(wrap)

        # top bar â€” title block centered above the stat cards; Rescan pinned
        # right with a same-width ghost on the left so centering is exact
        bar = QHBoxLayout()
        left = QHBoxLayout()
        left.setSpacing(14)
        left.addWidget(self._head_chip())
        tbox = QVBoxLayout()
        tbox.setSpacing(3)
        h1 = QLabel("Smart Debloater")
        h1.setStyleSheet(
            "font-family:" + _DISPLAY + ";font-size:21px;font-weight:600;"
            "color:" + _INK_100 + ";background:transparent;")
        sub = QLabel(self._os_subtitle())
        sub.setStyleSheet(
            "font-size:13px;color:" + _INK_400 + ";background:transparent;")
        tbox.addWidget(h1)
        tbox.addWidget(sub)
        left.addLayout(tbox)
        resc = _Btn("Rescan", "small")
        resc.clicked.connect(self._build_scan_state)
        ghost = QLabel()
        ghost.setFixedSize(resc.sizeHint())
        bar.addWidget(ghost, 0, Qt.AlignTop)
        bar.addStretch()
        bar.addLayout(left)
        bar.addStretch()
        bar.addWidget(resc, 0, Qt.AlignTop)
        cl.addLayout(bar)
        cl.addSpacing(22)

        # stat cards
        srow = QHBoxLayout()
        srow.setSpacing(14)
        srow.setAlignment(Qt.AlignCenter)
        for label, val, color in (
                ("Protected", str(r.total_protected), _GREEN),
                ("Debloatable", str(r.total_debloatable), _VIOLET_SOFT)):
            card = self._glass(14)
            cb = QVBoxLayout(card)
            cb.setContentsMargins(22, 16, 22, 16)
            cb.setSpacing(2)
            n = QLabel(val)
            n.setStyleSheet(
                "font-family:" + _DISPLAY + ";font-size:26px;"
                "font-weight:700;color:" + color + ";background:transparent;")
            l = QLabel(label.upper())
            l.setStyleSheet(
                "font-size:11px;color:" + _INK_600 + ";background:transparent;")
            cb.addWidget(n)
            cb.addWidget(l)
            card.setMinimumWidth(140)
            srow.addWidget(card)
        cl.addLayout(srow)
        cl.addSpacing(18)

        note = self._glass(14)
        nl = QVBoxLayout(note)
        nl.setContentsMargins(20, 16, 20, 16)
        nt = QLabel()
        nt.setTextFormat(Qt.RichText)
        nt.setWordWrap(True)
        nt.setStyleSheet("font-size:12.5px;background:transparent;")
        nt.setText(
            f"<span style='color:{_INK_100};font-weight:600'>"
            f"{r.total_protected} components</span>"
            "<span style='color:" + _INK_400 + "'> were automatically "
            "protected because they're required by Windows, drivers, games, "
            "or your installed applications. The </span>"
            "<span style='color:" + _INK_100 + ";font-weight:600'>"
            + str(r.total_debloatable) + " items</span>"
            "<span style='color:" + _INK_400 + "'> below are genuinely "
            "optional \u2014 nothing changes until you confirm.</span>")
        nl.addWidget(nt)
        cl.addWidget(note)
        cl.addSpacing(26)

        groups = {}
        for it in r.items:
            gname = it.group or it.category.value
            groups.setdefault(gname, []).append(it)
        for gname, items in groups.items():
            head = QHBoxLayout()
            h2 = QLabel(gname)
            h2.setStyleSheet(
                "font-size:14.5px;font-weight:600;color:" + _INK_100
                + ";background:transparent;")
            cnt = QLabel(f"{len(items)} item" + ("s" if len(items) != 1 else ""))
            cnt.setStyleSheet(
                "font-family:JetBrains Mono;font-size:11px;color:" + _VIOLET_SOFT
                + ";background:transparent;")
            head.addWidget(h2)
            head.addWidget(cnt)
            head.addStretch()
            cl.addLayout(head)
            cl.addSpacing(12)
            for it in items:
                cl.addWidget(self._result_row(it))
                cl.addSpacing(10)
            cl.addSpacing(12)

        cl.addStretch()

        # fixed bottom action bar
        bar2 = QFrame()
        bar2.setAttribute(Qt.WA_StyledBackground, True)
        bar2.setObjectName("ActionBar")
        bar2.setStyleSheet(
            "#ActionBar{background:rgba(8,6,15,0.85);border-top:1px solid "
            + _BORDER_SOFT + ";}")
        bl = QHBoxLayout(bar2)
        bl.setContentsMargins(44, 16, 44, 16)
        bl.setSpacing(9)
        self._sel_lbl = QLabel()
        self._sel_lbl.setStyleSheet(
            "font-size:12.5px;color:" + _INK_400 + ";background:transparent;")
        bl.addWidget(self._sel_lbl)
        bl.addStretch()
        b1 = _Btn("Clear all", "small")
        b1.clicked.connect(self._clear_sel)
        b2 = _Btn("Select safe", "small")
        b2.clicked.connect(self._select_safe)
        b3 = _Btn("Select all", "small")
        b3.clicked.connect(self._select_all)
        b4 = _Btn("Rescan", "small")
        b4.clicked.connect(self._build_scan_state)
        self._apply_btn = _Btn("Apply selected", "barPrimary")
        self._apply_btn.clicked.connect(self._show_apply_dialog)
        for b in (b1, b2, b3, b4, self._apply_btn):
            bl.addWidget(b)
        self._root.addWidget(bar2)
        self._update_count()

    def _result_row(self, it):
        card = self._glass(13)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 16, 18, 16)
        cl.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(12)
        cbx = _Check()
        cbx.changed.connect(lambda on, i=it: self._toggle(i.id, on))
        top.addWidget(cbx, 0, Qt.AlignVCenter)
        nm = QLabel(it.name)
        nm.setStyleSheet(
            "font-size:13.5px;font-weight:600;color:" + _INK_100
            + ";background:transparent;")
        top.addWidget(nm)
        risk = it.risk.value
        if risk != "UNKNOWN":
            color = TAG_STYLE.get(risk, _INK_600)
            tg = QLabel(risk.upper())
            tg.setStyleSheet(
                "font-family:JetBrains Mono;font-size:9px;letter-spacing:0.5px;"
                "text-transform:uppercase;"
                f"color:{color};background:{_rgba(color, 0.10)};"
                f"border:1px solid {_rgba(color, 0.30)};"
                "border-radius:6px;padding:3px 8px;")
            top.addWidget(tg)
        if it.reversible:
            rv = QLabel("REVERSIBLE")
            rv.setStyleSheet(
                "font-family:JetBrains Mono;font-size:9px;letter-spacing:0.5px;"
                "color:" + _VIOLET_SOFT + ";background:rgba(139,107,255,0.08);"
                "border:1px solid rgba(139,107,255,0.25);"
                "border-radius:6px;padding:3px 8px;")
            top.addWidget(rv)
        top.addStretch()
        conf = QLabel()
        conf.setTextFormat(Qt.RichText)
        conf.setStyleSheet("background:transparent;")
        conf.setText(
            "<span style='font-family:JetBrains Mono;font-size:10px;color:"
            + _INK_600 + "'>Confidence </span>"
            "<span style='font-family:JetBrains Mono;font-size:10px;color:"
            + _INK_400 + ";font-weight:700'>" + str(it.confidence)
            + "%</span>")
        top.addWidget(conf, 0, Qt.AlignVCenter)
        cl.addLayout(top)
        cl.addSpacing(8)
        d = QLabel(it.description)
        d.setStyleSheet(
            "font-size:12.5px;color:" + _INK_400 + ";background:transparent;"
            "margin-left:29px;")
        d.setWordWrap(True)
        cl.addWidget(d)
        cl.addSpacing(4)
        imp = QLabel("If removed: " + (it.what_happens or "no system impact."))
        imp.setStyleSheet(
            "font-size:11.5px;color:" + _INK_600 + ";background:transparent;"
            "margin-left:29px;")
        imp.setWordWrap(True)
        cl.addWidget(imp)
        self._rows[it.id] = (card, cbx)
        return card

    # selection ops
    def _toggle(self, iid, on):
        if on:
            self._selected.add(iid)
        else:
            self._selected.discard(iid)
        self._update_count()

    def _update_count(self):
        # .sel-count: uniform 12.5px ink-400 â€” HTML's #sel-num span carries
        # no styling of its own.
        n = len(self._selected)
        self._sel_lbl.setText(
            f"{n} component{'s' if n != 1 else ''} selected")
        self._apply_btn.setEnabled(n > 0)

    def _clear_sel(self):
        self._selected.clear()
        for _c, cbx in self._rows.values():
            cbx.set_checked(False)
        self._update_count()

    def _select_safe(self):
        self._selected.clear()
        for iid, (_c, cbx) in self._rows.items():
            it = next(i for i in self._result.items if i.id == iid)
            if it.risk.value == "SAFE" and it.reversible:
                self._selected.add(iid)
                cbx.set_checked(True)
            else:
                cbx.set_checked(False)
        self._update_count()

    def _select_all(self):
        self._selected = {iid for iid in self._rows}
        for _c, cbx in self._rows.values():
            cbx.set_checked(True)
        self._update_count()

    # apply flow
    def _show_apply_dialog(self):
        sel = [i for i in self._result.items if i.id in self._selected]
        if not sel:
            return
        self._overlay = QFrame(self)
        self._overlay.setGeometry(self.rect())
        self._overlay.setAttribute(Qt.WA_StyledBackground, True)
        self._overlay.setStyleSheet("background:rgba(0,0,0,0.70);")
        dlg = self._glass(18)
        dl = QVBoxLayout(dlg)
        dl.setContentsMargins(30, 26, 30, 24)
        dl.setSpacing(0)
        t = QLabel("Ready to apply")
        t.setStyleSheet(
            "font-family:" + _DISPLAY + ";font-size:18px;font-weight:600;"
            "color:" + _INK_100 + ";background:transparent;")
        dl.addWidget(t)
        dl.addSpacing(8)
        s = QLabel(
            f"{len(sel)} component(s) selected. A backup will be created "
            "before any change, and anything that fails is rolled back "
            "automatically. Nothing can be uninstalled by accident.")
        s.setWordWrap(True)
        s.setStyleSheet(
            "font-size:12.5px;color:" + _INK_400 + ";background:transparent;")
        dl.addWidget(s)
        dl.addSpacing(14)
        for it in sel[:7]:
            row = QLabel("\u2022  " + it.name
                         + ("  (" + it.risk.value + ")" if it.risk.value !=
                            "SAFE" else ""))
            row.setStyleSheet(
                "font-size:12px;color:" + _INK_400 + ";background:transparent;")
            dl.addWidget(row)
        if len(sel) > 7:
            more = QLabel(f"  \u2026and {len(sel) - 7} more")
            more.setStyleSheet(
                "font-size:12px;color:" + _INK_600 + ";background:transparent;")
            dl.addWidget(more)
        dl.addSpacing(18)
        br = QHBoxLayout()
        br.setSpacing(10)
        br.addStretch()
        cancel = _Btn("Cancel", "small")
        cancel.clicked.connect(self._hide_dialog)
        apply = _Btn("Apply changes", "primary")
        apply.setStyleSheet(apply.styleSheet().replace(
            "padding:14px 34px", "padding:10px 22px"))
        apply.clicked.connect(self._apply_selected)
        br.addWidget(cancel)
        br.addWidget(apply)
        dl.addLayout(br)
        dl.addWidget(QWidget())  # spacer bottom
        self._overlay.show()
        self._overlay.raise_()
        dlg.setParent(self._overlay)
        dlg.adjustSize()
        h = min(dlg.sizeHint().height(), self.height() - 80)
        dlg.resize(min(520, self.width() - 80), h)
        dlg.move((self.width() - dlg.width()) // 2,
                 max(40, (self.height() - dlg.height()) // 2))

    def _hide_dialog(self):
        if getattr(self, "_overlay", None):
            self._overlay.setParent(None)
            self._overlay.deleteLater()
            self._overlay = None

    def _apply_selected(self):
        self._hide_dialog()
        sel = [i for i in self._result.items if i.id in self._selected]
        self._apply_worker = _ApplyWorker(
            self._engine, sel, self._result.os_info.to_dict(), self)
        self._apply_worker.done.connect(self._on_apply_done)
        self._apply_worker.error.connect(
            lambda m: self._on_apply_done(False, [m]))
        self._build_busy("Applying changes",
                         "Creating backup and removing selected components\u2026")
        self._apply_worker.start()

    def _build_busy(self, title, sub):
        self._reset()
        lay = QVBoxLayout()
        lay.setContentsMargins(40, 60, 40, 60)
        lay.setAlignment(Qt.AlignCenter)
        t = QLabel(title)
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet(
            "font-family:" + _DISPLAY + ";font-size:22px;font-weight:600;"
            "color:" + _INK_100 + ";background:transparent;")
        s = QLabel(sub)
        s.setAlignment(Qt.AlignCenter)
        s.setStyleSheet(
            "font-size:13px;color:" + _INK_400 + ";background:transparent;")
        lay.addWidget(t)
        lay.addSpacing(8)
        lay.addWidget(s)
        self._root.addLayout(lay)

    def _on_apply_done(self, ok, errors):
        self._reset()
        body = self._scroll_body()
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 40, 0, 40)
        cl.setSpacing(0)
        wrap = QHBoxLayout()
        wrap.addStretch()
        wrap.addWidget(col)
        wrap.addStretch()
        body.setLayoutDirection(Qt.LeftToRight)
        self._blay.addLayout(wrap)
        col.setMaximumWidth(640)
        t = QLabel("Changes applied" if ok else "Partial success")
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet(
            "font-family:" + _DISPLAY + ";font-size:24px;font-weight:600;"
            "color:" + (_GREEN if ok else _AMBER) + ";background:transparent;")
        cl.addWidget(t)
        cl.addSpacing(8)
        s = QLabel(
            "All selected components were processed." if ok else
            "Some items failed and were rolled back automatically.")
        s.setAlignment(Qt.AlignCenter)
        s.setWordWrap(True)
        s.setStyleSheet(
            "font-size:13px;color:" + _INK_400 + ";background:transparent;")
        cl.addWidget(s)
        if errors:
            cl.addSpacing(14)
            for err in errors[:8]:
                e = QLabel("\u2022  " + str(err))
                e.setWordWrap(True)
                e.setStyleSheet(
                    "font-size:12px;color:" + _RED + ";background:transparent;")
                cl.addWidget(e)
        cl.addSpacing(24)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.setAlignment(Qt.AlignCenter)
        if self._engine.backup.has_rollback():
            rb = _Btn("Rollback last changes")
            rb.clicked.connect(self._do_rollback)
            row.addWidget(rb)
        again = _Btn("Scan again", "primary")
        again.clicked.connect(self._build_scan_state)
        row.addWidget(again)
        cl.addLayout(row)
        cl.addStretch()

    def _do_rollback(self):
        ok, errors = self._engine.rollback()
        self._on_apply_done(ok, errors)


class _Check(QFrame):
    """Reference .cbx â€” 17px rounded checkbox, violet fill + white tick."""

    changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(17, 17)
        self.setCursor(Qt.PointingHandCursor)
        self._on = False
        self._paint()

    def _paint(self):
        if self._on:
            self.setStyleSheet(
                "QFrame{background:" + _VIOLET + ";border:1.5px solid "
                + _VIOLET + ";border-radius:5px;}")
        else:
            self.setStyleSheet(
                "QFrame{background:rgba(255,255,255,0.02);border:1.5px "
                "solid rgba(255,255,255,0.09);border-radius:5px;}")

    def set_checked(self, on):
        self._on = bool(on)
        self._repaint_mark()

    def _repaint_mark(self):
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self._on:
            return
        p = QPainter(self)
        f = QFont("Segoe UI", 9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(self.rect(), Qt.AlignCenter, "\u2713")
        p.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._on = not self._on
            self._paint()
            self.update()
            self.changed.emit(self._on)
        super().mousePressEvent(ev)
