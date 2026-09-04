"""Controller Overclock tool — port of controller-overclock-final.html.

Shows the ACTUAL controller plugged into this PC (USB or Bluetooth, detected
from the PnP device tree) and exposes only genuine, reversible Windows
tweaks: USB selective suspend (powercfg), per-device power management
(root\\wmi MSPower_DeviceEnable), HID/hub/Bluetooth-radio handling, and a
live polling-rate measurement (XInput packet counter / HID report stream).
Rows Windows does not actually expose are labelled honestly, never faked.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QRadialGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from engine import controller as eng
from engine import state as state_mgr
from ui.widgets import BatchWorker, PillSwitch, toast

# Reference palette (tools = amber)
_BG = "#08060F"
_AMBER = "#FFB454"
_VIOLET = "#8B6BFF"
_VIOLET_SOFT = "#C9C0FF"
_GREEN = "#3DDC97"
_RED = "#FF6F6F"
_CYAN = "#4BE8D8"
_TEXT_1 = "#F6F4FC"
_TEXT_4 = "#928AAD"
_TEXT_6 = "#514A70"
_BORDER = "rgba(255,255,255,0.09)"
_GLASS = "rgba(255,255,255,0.03)"
_DISPLAY = '"Segoe UI", sans-serif'
_MONO = '"JetBrains Mono", monospace'

GAMEPAD_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200" '
    'viewBox="-10 -10 300 200">'
    '<defs>'
    '<radialGradient id="halo" cx="50%" cy="50%" r="50%">'
    '<stop offset="0%" stop-color="#ffb454" stop-opacity="0.30"/>'
    '<stop offset="70%" stop-color="#ffb454" stop-opacity="0"/>'
    '</radialGradient>'
    '<linearGradient id="padFill" x1="0%" y1="0%" x2="100%" y2="100%">'
    '<stop offset="0%" stop-color="#1c1710"/><stop offset="100%" stop-color="#0c0916"/>'
    '</linearGradient>'
    '<linearGradient id="padStroke" x1="0%" y1="0%" x2="100%" y2="0%">'
    '<stop offset="0%" stop-color="#ffb454"/><stop offset="100%" stop-color="#8b6bff"/>'
    '</linearGradient></defs>'
    '<ellipse cx="140" cy="95" rx="150" ry="92" fill="url(#halo)"/>'
    '<path d="M70 40 h140 a45 45 0 0 1 45 45 v10 a40 40 0 0 1 -8 55 '
    'a30 30 0 0 1 -46 8 l-20 -22 h-82 l-20 22 a30 30 0 0 1 -46 -8 '
    'a40 40 0 0 1 -8 -55 v-10 a45 45 0 0 1 45 -45 z" '
    'fill="url(#padFill)" stroke="url(#padStroke)" stroke-width="2"/>'
    '<path d="M100 78 h16 M108 70 v16" stroke="#a49bc4" stroke-width="4" '
    'stroke-linecap="round"/>'
    '<circle cx="196" cy="72" r="6" fill="none" stroke="#a49bc4" stroke-width="2.5"/>'
    '<circle cx="212" cy="86" r="6" fill="none" stroke="#a49bc4" stroke-width="2.5"/>'
    '<circle cx="212" cy="58" r="6" fill="none" stroke="#a49bc4" stroke-width="2.5"/>'
    '<circle cx="228" cy="72" r="6" fill="none" stroke="#a49bc4" stroke-width="2.5"/>'
    '<circle cx="120" cy="112" r="14" fill="rgba(255,180,84,0.12)" '
    'stroke="#ffb454" stroke-width="2"/>'
    '<circle cx="120" cy="112" r="4" fill="#ffb454"/>'
    '<circle cx="190" cy="120" r="14" fill="rgba(255,180,84,0.12)" '
    'stroke="#ffb454" stroke-width="2"/>'
    '<circle cx="190" cy="120" r="4" fill="#ffb454"/>'
    '<rect x="76" y="30" width="34" height="8" rx="4" fill="none" '
    'stroke="#615a80" stroke-width="2"/>'
    '<rect x="170" y="30" width="34" height="8" rx="4" fill="none" '
    'stroke="#615a80" stroke-width="2"/>'
    '<circle cx="140" cy="60" r="4" fill="#3ddc97"/>'
    '</svg>')

RATE_STEPS = ((125, "~8 ms"), (250, "~4 ms"), (500, "~2 ms"), (1000, "~1 ms"))


class _Atmosphere(QWidget):
    """#08060F base + amber blob (top-left) + violet blob (bottom-right) +
    the masked 34px dot grid, per the reference .main."""

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(_BG))
        ga = QRadialGradient(QPointF(360, 40), 380)
        ga.setColorAt(0.0, QColor(255, 180, 84, 26))
        ga.setColorAt(0.55, QColor(255, 180, 84, 8))
        ga.setColorAt(1.0, QColor(255, 180, 84, 0))
        p.fillRect(self.rect(), ga)
        gb = QRadialGradient(QPointF(w - 140, h), 340)
        gb.setColorAt(0.0, QColor(139, 107, 255, 26))
        gb.setColorAt(0.6, QColor(139, 107, 255, 8))
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


# ---------------------------------------------------------------- threads

class _DetectWorker(QThread):
    done = Signal(object)

    def run(self):
        try:
            self.done.emit(eng.detect())
        except Exception:
            self.done.emit({"pads": [], "pm": {}, "sel_suspend": None,
                            "xinput": False})


class _TestWorker(QThread):
    done = Signal(object)

    def __init__(self, pad):
        super().__init__()
        self.pad = pad

    def run(self):
        try:
            self.done.emit(eng.test_controller(self.pad))
        except Exception as exc:
            self.done.emit({"ok": False, "note": str(exc)})


class _OpWorker(QThread):
    """Runs a list of (fn, args) engine calls off the UI thread."""
    done = Signal(bool)

    def __init__(self, ops):
        super().__init__()
        self.ops = ops

    def run(self):
        ok = True
        for fn, args in self.ops:
            try:
                ok = bool(fn(*args)) and ok
            except Exception:
                ok = False
        self.done.emit(ok)


# ---------------------------------------------------------------- atoms

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


def _section_head(title, subtitle):
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(9)
    h2 = QLabel(title.upper())
    h2.setStyleSheet(
        f"font-family:{_MONO}; font-size:11px; color:{_TEXT_4};"
        f" font-weight:500; background:transparent;")
    f = h2.font()
    f.setLetterSpacing(QFont.AbsoluteSpacing, 1.3)
    h2.setFont(f)
    lay.addWidget(h2)
    p = QLabel(f"\u00b7 {subtitle}")
    p.setStyleSheet(
        f"font-size:11.5px; color:{_TEXT_6}; background:transparent;")
    lay.addWidget(p)
    lay.addStretch()
    return w


class _Card(QFrame):
    def __init__(self, radius=16, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("CoCard")
        self.setStyleSheet(
            "#CoCard{background-color:%s; border:1px solid %s;"
            " border-radius:%dpx;}" % (_GLASS, _BORDER, radius))


class _Chip(QLabel):
    """Small status chip (supported / unavailable / wired...)."""

    def __init__(self, text, color=_TEXT_6):
        super().__init__(text.upper())
        self.setStyleSheet(
            f"font-family:{_MONO}; font-size:9px; color:{color};"
            f" background-color:{_GLASS}; border:1px solid {_BORDER};"
            " border-radius:5px; padding:2px 6px;")


class _TweakRow(QFrame):
    """A .row inside the tweaks card-list; clicking toggles the switch and
    emits toggled(id, state)."""

    toggled = Signal(str, bool)

    def __init__(self, rid, title, desc, state=False, chip_text=None,
                 parent=None):
        super().__init__(parent)
        self.rid = rid
        self._state = bool(state)
        self._enabled = chip_text is None
        self.setMinimumHeight(64)
        self.setStyleSheet(
            "#CoRow{background:transparent;border:none;}"
            "#CoRow:hover{background:rgba(255,255,255,0.02);}")
        self.setObjectName("CoRow")
        self.setCursor(Qt.PointingHandCursor if self._enabled else
                       Qt.ArrowCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 10, 22, 10)
        lay.setSpacing(16)
        box = QVBoxLayout()
        box.setSpacing(3)
        t = QLabel(title)
        t.setStyleSheet(
            f"font-size:13.5px; font-weight:600; color:{_TEXT_1};"
            f" background:transparent;")
        d = QLabel(desc)
        d.setStyleSheet(
            f"font-size:12px; color:{_TEXT_4}; background:transparent;")
        d.setWordWrap(True)
        d.setMaximumWidth(600)
        box.addWidget(t)
        box.addWidget(d)
        lay.addLayout(box, 1)
        self.sw = None
        self.chip = None
        if self._enabled:
            self.sw = PillSwitch(_AMBER)
            self.sw.set_on(self._state)
            lay.addWidget(self.sw, 0, Qt.AlignVCenter | Qt.AlignRight)
        else:
            self.chip = _Chip(chip_text or "not exposed")
            lay.addWidget(self.chip, 0, Qt.AlignVCenter | Qt.AlignRight)

    def downgrade(self, chip_text):
        """Replace the switch with an honest status chip (unsupported /
        no device). Idempotent."""
        if not self._enabled:
            return
        self._enabled = False
        if self.sw is not None:
            self.layout().removeWidget(self.sw)
            self.sw.deleteLater()
            self.sw = None
        self.chip = _Chip(chip_text)
        self.layout().addWidget(self.chip, 0,
                                Qt.AlignVCenter | Qt.AlignRight)
        self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, ev):
        if self._enabled and ev.button() == Qt.LeftButton:
            self._state = not self._state
            self.sw.set_on(self._state)
            self.toggled.emit(self.rid, self._state)
        super().mousePressEvent(ev)

    def set_state(self, state):
        self._state = bool(state)
        if self.sw:
            self.sw.set_on(self._state)


class _RateBtn(QFrame):
    clicked = Signal(int)

    def __init__(self, hz, ms, active=False, enabled=True, parent=None):
        super().__init__(parent)
        self.hz = hz
        self.active = bool(active)
        self.enabled = enabled
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self.setObjectName("RateBtn")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 8)
        lay.setSpacing(1)
        h = QLabel(f"{hz}Hz")
        h.setAlignment(Qt.AlignCenter)
        m = QLabel(ms)
        m.setAlignment(Qt.AlignCenter)
        m.setStyleSheet(
            f"font-size:10px; color:{_TEXT_6}; background:transparent;")
        lay.addWidget(h)
        lay.addWidget(m)
        self._hz_lbl = h
        self._paint()

    def _paint(self):
        if not self.enabled:
            ss = ("#RateBtn{background:rgba(255,255,255,0.02);"
                  " border:1px solid rgba(255,255,255,0.05);"
                  " border-radius:9px;}")
            self.setStyleSheet(ss)
            self._hz_lbl.setStyleSheet(
                f"font-size:13px; font-weight:600; color:{_TEXT_6};"
                f" background:transparent;")
            return
        if self.active:
            self.setStyleSheet(
                "#RateBtn{background:rgba(255,180,84,0.10);"
                " border:1px solid rgba(255,180,84,0.50);"
                " border-radius:9px;}")
            self._hz_lbl.setStyleSheet(
                f"font-size:13px; font-weight:600; color:{_AMBER};"
                f" background:transparent;")
        else:
            self.setStyleSheet(
                "#RateBtn{background:rgba(255,255,255,0.02);"
                f" border:1px solid {_BORDER}; border-radius:9px;}}")
            self._hz_lbl.setStyleSheet(
                f"font-size:13px; font-weight:600; color:{_TEXT_1};"
                f" background:transparent;")

    def set_active(self, active):
        self.active = active
        self._paint()

    def mousePressEvent(self, ev):
        if self.enabled and ev.button() == Qt.LeftButton:
            self.clicked.emit(self.hz)
        super().mousePressEvent(ev)


class _PresetCard(QFrame):
    apply_requested = Signal(str)

    def __init__(self, key, name, items, selected=False, primary=False,
                 parent=None):
        super().__init__(parent)
        self.key = key
        self.selected = selected
        self.setObjectName("PresetCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(0)
        n = QLabel(name)
        n.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:14px; font-weight:700;"
            f" color:{_TEXT_1}; background:transparent;")
        lay.addWidget(n)
        lay.addSpacing(10)
        for it in items:
            li = QLabel(f"\u2014  {it}")
            li.setStyleSheet(
                f"font-size:11.5px; color:{_TEXT_4}; background:transparent;")
            li.setWordWrap(True)
            lay.addWidget(li)
            lay.addSpacing(4)
        lay.addStretch()
        lay.addSpacing(10)
        self.btn = QPushButton("Apply" if not primary else "Apply preset")
        self.btn.setObjectName("Primary" if primary else "Secondary")
        self.btn.clicked.connect(lambda: self.apply_requested.emit(self.key))
        lay.addWidget(self.btn)
        self.refresh_style()

    def refresh_style(self):
        if self.selected:
            self.setStyleSheet(
                "#PresetCard{background:rgba(255,180,84,0.06);"
                " border:1px solid rgba(255,180,84,0.50);"
                " border-radius:14px;}")
        else:
            self.setStyleSheet(
                f"#PresetCard{{background:{_GLASS};"
                f" border:1px solid {_BORDER}; border-radius:14px;}}")


class _DiagTile(QFrame):
    def __init__(self, label, value="\u2014", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("DiagTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setStyleSheet(
            f"#DiagTile{{background:{_GLASS}; border:1px solid {_BORDER};"
            " border-radius:13px;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 15, 16, 15)
        lay.setSpacing(2)
        self.val = QLabel(value)
        self.val.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:14px; font-weight:600;"
            f" color:{_TEXT_1}; background:transparent;")
        self.lbl = QLabel(label.upper())
        self.lbl.setStyleSheet(
            f"font-size:10.5px; color:{_TEXT_6}; background:transparent;")
        f = self.lbl.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
        self.lbl.setFont(f)
        lay.addWidget(self.val)
        lay.addWidget(self.lbl)

    def set_value(self, text):
        self.val.setText(text)


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
            f"<span style='color:{_TEXT_4};'>&nbsp; {text}</span>")


class _HidRow(QFrame):
    """One hidden-tier knob: title, honest description, Apply/Revert, live
    status chip."""

    apply_requested = Signal(str)
    revert_requested = Signal(str)

    def __init__(self, key, title, desc, note=None):
        super().__init__()
        self.key = key
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("HidRow")
        self.setStyleSheet(
            "#HidRow{background:rgba(255,255,255,0.02); border:1px solid "
            "rgba(255,255,255,0.07); border-radius:13px;}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(14)
        box = QVBoxLayout()
        box.setSpacing(3)
        trow = QHBoxLayout()
        trow.setSpacing(8)
        t = QLabel(title)
        t.setStyleSheet(
            f"font-size:13.5px; font-weight:600; color:{_TEXT_1};"
            f" background:transparent;")
        trow.addWidget(t)
        self.chip = QLabel("IDLE")
        self.chip.setStyleSheet(
            f"font-family:{_MONO}; font-size:9px; color:{_TEXT_6};"
            f" background-color:{_GLASS}; border:1px solid {_BORDER};"
            " border-radius:5px; padding:2px 6px;")
        trow.addWidget(self.chip)
        trow.addStretch()
        box.addLayout(trow)
        d = QLabel(desc)
        d.setStyleSheet(
            f"font-size:11.5px; color:{_TEXT_4}; background:transparent;")
        d.setWordWrap(True)
        box.addWidget(d)
        if note:
            n = QLabel(note)
            n.setStyleSheet(
                f"font-family:{_MONO}; font-size:10px; color:{_AMBER};"
                f" background:transparent;")
            box.addWidget(n)
        lay.addLayout(box, 1)
        self.btn_a = QPushButton("Engage")
        self.btn_a.setObjectName("Primary")
        self.btn_a.clicked.connect(lambda: self.apply_requested.emit(self.key))
        self.btn_r = QPushButton("Revert")
        self.btn_r.setObjectName("Secondary")
        self.btn_r.clicked.connect(
            lambda: self.revert_requested.emit(self.key))
        lay.addWidget(self.btn_a, 0, Qt.AlignVCenter)
        lay.addWidget(self.btn_r, 0, Qt.AlignVCenter)

    def set_state(self, active: bool, text=None, color=None):
        self.chip.setText((text or ("ACTIVE" if active else "IDLE")).upper())
        self.chip.setStyleSheet(
            f"font-family:{_MONO}; font-size:9px; color:"
            f"{color or (_GREEN if active else _TEXT_6)};"
            f" background-color:{_GLASS}; border:1px solid {_BORDER};"
            " border-radius:5px; padding:2px 6px;")


# ---------------------------------------------------------------- page

class ControllerPage(QWidget):
    TWEAKS = [
        ("suspend", "USB selective suspend",
         "Prevent Windows from putting the controller's USB device into a "
         "low-power state between inputs."),
        ("usbpm", "USB power management",
         "Disable 'allow the computer to turn off this device' for the "
         "controller's USB hardware."),
        ("priority", "Controller device priority",
         "Windows exposes no per-controller priority knob — Maximum only "
         "changes settings that genuinely exist."),
        ("hid", "HID input optimization",
         "Remove power-management behavior from the controller's HID device "
         "so input stays consistent."),
        ("xinput", "XInput optimization",
         "Verify the Windows XInput path for Xbox-compatible controllers, "
         "kept separate from generic HID handling."),
        ("rawinput", "Raw Input optimization",
         "Confirm the controller enumerates through the HID report stream "
         "for games that read Raw Input."),
        ("hub", "USB hub power saving",
         "Disable power-saving on the USB hub the controller connects "
         "through — best for motherboard USB ports."),
        ("conn", "Connection stability",
         "Detect USB vs. Bluetooth and apply the right optimization path "
         "for each connection type."),
    ]

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.pad = None
        self.detect_data = None
        self.rows: dict[str, _TweakRow] = {}
        self.target_hz = 1000
        self.measured_hz = None
        self._detect_worker = None
        self._test_worker = None
        self._op_worker = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._atmo = _Atmosphere(self)
        self._atmo.lower()

        scroll = QScrollArea()
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea>QWidget>QWidget{background:transparent;}")
        body = QWidget()
        root = QVBoxLayout(body)
        # .content padding 40/44/60, max-width 1320
        root.setContentsMargins(44, 40, 44, 60)
        root.setSpacing(0)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self._build_top(root)
        self._build_hero(root)
        self._build_tweaks(root)
        self._build_presets(root)
        self._build_hidden(root)
        self._build_diag(root)
        root.addStretch()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._atmo.setGeometry(self.rect())
        self._atmo.lower()

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.detect_data is None and self._detect_worker is None:
            self._start_detect()

    # ---------- top bar

    def _build_top(self, root):
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        left.setSpacing(5)
        h1 = QLabel("Controller overclock")
        h1.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:26px; font-weight:600;"
            f" color:{_TEXT_1}; background:transparent;")
        sub = QLabel("Reduce input latency and tune polling for your "
                     "connected controller.")
        sub.setStyleSheet(
            f"font-size:13px; color:{_TEXT_4}; background:transparent;")
        left.addWidget(h1)
        left.addWidget(sub)
        bar.addLayout(left, 1)
        stats = QVBoxLayout()
        stats.setSpacing(8)
        self.stat_conn = _DotStat(_RED, "Scanning for controller\u2026")
        self.stat_poll = _DotStat(_TEXT_6, "Polling idle")
        stats.addWidget(self.stat_conn)
        stats.addWidget(self.stat_poll)
        stats.addStretch()
        bar.addLayout(stats)
        root.addLayout(bar)
        root.addSpacing(24)

    # ---------- hero row

    def _build_hero(self, root):
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setColumnStretch(0, 100)
        grid.setColumnStretch(1, 115)

        pad_card = _Card()
        pl = QVBoxLayout(pad_card)
        pl.setContentsMargins(24, 24, 24, 20)
        pl.setSpacing(0)
        art = _svg_label(GAMEPAD_SVG, 300, 200)
        self.pad_art = art
        pl.addWidget(art, 0, Qt.AlignHCenter)
        pl.addSpacing(16)
        self.pad_name = QLabel("No controller detected")
        self.pad_name.setAlignment(Qt.AlignCenter)
        self.pad_name.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:14px; font-weight:600;"
            f" color:{_TEXT_1}; background:transparent;")
        self.pad_meta = QLabel(
            "Plug one in (USB) or pair it (Bluetooth), then open this page.")
        self.pad_meta.setAlignment(Qt.AlignCenter)
        self.pad_meta.setWordWrap(True)
        self.pad_meta.setStyleSheet(
            f"font-size:11.5px; color:{_TEXT_6}; background:transparent;")
        pl.addWidget(self.pad_name)
        pl.addSpacing(3)
        pl.addWidget(self.pad_meta)
        pl.addStretch()
        grid.addWidget(pad_card, 0, 0)

        oc = _Card()
        ol = QVBoxLayout(oc)
        ol.setContentsMargins(24, 22, 24, 20)
        ol.setSpacing(0)
        title_row = QHBoxLayout()
        title_row.setSpacing(9)
        title = QLabel("Controller response")
        title.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:15px; font-weight:600;"
            f" color:{_TEXT_1}; background:transparent;")
        title_row.addWidget(_svg_label(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            'fill="none" stroke="#FFB454" stroke-width="1.7" '
            'stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M13 2L4 14h6l-1 8 9-12h-6z"/></svg>', 26, 26))
        title_row.addWidget(title)
        title_row.addStretch()
        ol.addLayout(title_row)
        ol.addSpacing(4)
        osub = QLabel("Increase the controller's USB report rate where "
                      "supported, to shorten the interval between reports.")
        osub.setWordWrap(True)
        osub.setStyleSheet(
            f"font-size:12px; color:{_TEXT_6}; background:transparent;")
        ol.addWidget(osub)
        ol.addSpacing(16)

        rates = QHBoxLayout()
        self.cur_fig = QLabel("—")
        self.tgt_fig = QLabel(f"{self.target_hz}Hz")
        for lbl, color in ((self.cur_fig, _TEXT_1), (self.tgt_fig, _AMBER)):
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(
                f"font-family:{_DISPLAY}; font-size:26px; font-weight:700;"
                f" color:{color}; background:transparent;")
        cur_l = QLabel("CURRENT")
        tgt_l = QLabel("TARGET")
        for l in (cur_l, tgt_l):
            l.setAlignment(Qt.AlignCenter)
            l.setStyleSheet(
                f"font-size:10.5px; color:{_TEXT_6};"
                f" background:transparent;")
        curbox = QVBoxLayout()
        curbox.setSpacing(2)
        curbox.addWidget(self.cur_fig)
        curbox.addWidget(cur_l)
        tgtbox = QVBoxLayout()
        tgtbox.setSpacing(2)
        tgtbox.addWidget(self.tgt_fig)
        tgtbox.addWidget(tgt_l)
        arrow = QLabel("\u2192")
        arrow.setStyleSheet(
            f"font-size:18px; color:{_TEXT_6}; background:transparent;")
        rates.addStretch()
        rates.addLayout(curbox)
        rates.addSpacing(28)
        rates.addWidget(arrow)
        rates.addSpacing(28)
        rates.addLayout(tgtbox)
        rates.addStretch()
        ol.addLayout(rates)
        ol.addSpacing(18)

        sel = QGridLayout()
        sel.setHorizontalSpacing(8)
        self.rate_btns: list[_RateBtn] = []
        for i, (hz, ms) in enumerate(RATE_STEPS):
            rb = _RateBtn(hz, ms, active=(hz == self.target_hz))
            rb.clicked.connect(self._pick_rate)
            sel.addWidget(rb, 0, i)
            self.rate_btns.append(rb)
        for i in range(4):
            sel.setColumnStretch(i, 1)
        ol.addLayout(sel)
        ol.addSpacing(14)

        self.oc_status = QLabel("Run a controller test to verify what this "
                                "pad actually supports.")
        self.oc_status.setWordWrap(True)
        self.oc_status.setStyleSheet(
            f"font-size:12px; color:{_TEXT_4}; background:transparent;")
        ol.addWidget(self.oc_status)
        ol.addSpacing(16)

        acts = QHBoxLayout()
        acts.setSpacing(10)
        self.btn_test = QPushButton("Test controller")
        self.btn_test.setObjectName("Secondary")
        self.btn_test.clicked.connect(self._run_test)
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.clicked.connect(self._apply_rows)
        acts.addWidget(self.btn_test, 1)
        acts.addWidget(self.btn_apply, 1)
        ol.addLayout(acts)
        ol.addStretch()
        grid.addWidget(oc, 0, 1)
        root.addLayout(grid)
        root.addSpacing(22)

    # ---------- tweaks list

    def _build_tweaks(self, root):
        root.addWidget(_section_head("Tweaks",
                                     "Applied individually, all reversible"))
        root.addSpacing(14)
        card = _Card(radius=14)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for i, (rid, title, desc) in enumerate(self.TWEAKS):
            row = _TweakRow(rid, title, desc)
            row.toggled.connect(self._on_toggle)
            self.rows[rid] = row
            lay.addWidget(row)
            if i < len(self.TWEAKS) - 1:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(
                    "background:rgba(255,255,255,0.06); border:none;")
                lay.addWidget(sep)
        note = QLabel(
            "These tweaks only touch Windows USB power and input-handling "
            "behavior. Maximum won't push a polling rate your controller's "
            "firmware doesn't actually support, and doesn't apply unrelated "
            "registry or network tweaks in this category.")
        note.setWordWrap(True)
        note.setStyleSheet(
            f"font-size:11.5px; color:{_TEXT_6}; background:transparent;"
            " padding: 14px 22px 16px 22px;")
        lay.addWidget(note)
        root.addWidget(card)
        root.addSpacing(22)

    # ---------- presets

    def _build_presets(self, root):
        root.addWidget(_section_head("Presets", "Apply a bundle in one click"))
        root.addSpacing(14)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        self.presets = {}
        defs = [
            ("safe", "Safe default",
             ["Reversible USB power settings only",
              "No firmware or polling changes"]),
            ("low", "Low latency",
             ["USB power management optimized", "Selective suspend off",
              "HID optimization", "Input path verified"]),
            ("max", "Maximum response",
             ["Everything in Low Latency", "Highest supported report rate",
              "USB hub power optimization", "Full diagnostic verification"]),
        ]
        for i, (key, name, items) in enumerate(defs):
            pc = _PresetCard(key, name, items,
                             selected=(key == "low"), primary=(key == "low"))
            pc.apply_requested.connect(self._apply_preset)
            self.presets[key] = pc
            grid.addWidget(pc, 0, i)
            grid.setColumnStretch(i, 1)
        root.addLayout(grid)
        root.addSpacing(22)

    # ---------- hidden tier

    HIDDEN_ROWS = [
        ("lpm", "USB link power management — never suspend",
         "Raises the xHCI Link Power Management timeout on the very USB "
         "controller your pad is plugged into. The link stays hot, so no "
         "report ever waits behind a port wake-up.",
         "requires a reboot to take effect"),
        ("chain", "My controller's devices — never turn off",
         "Applies 'computer may not turn off this device' to the REAL "
         "instances of the connected pad: its HID device and its USB "
         "device itself (hubs are the next row).",
         None),
        ("hubs", "All USB hubs — never sleep",
         "Strips power-saving from EVERY hub in the system, so no "
         "intermediate hub can gate reports from any port.",
         None),
        ("tick", "Constant system ticks (input timing)",
         "Forces fixed-interval hardware timer ticks — the game's polling "
         "loop reads the pad on an even rhythm instead of a jittery one.",
         "requires a reboot to take effect"),
        ("dyntick", "Dynamic tick — off (input timing)",
         "The CPU timer never sleeps between interrupts, cutting the tail "
         "off input-wake latency.",
         "requires a reboot to take effect"),
    ]

    def _build_hidden(self, root):
        root.addSpacing(22)
        root.addWidget(_section_head(
            "Hidden tier",
            "for the best of the best — the pad's USB path and the "
            "timer it's polled on"))
        root.addSpacing(14)
        self._hidden_card = _Card(radius=14)
        hl = QVBoxLayout(self._hidden_card)
        hl.setContentsMargins(22, 20, 22, 20)
        hl.setSpacing(12)
        lock = QLabel(
            "These are the real controller-path switches Windows hides: "
            "the USB link power management of your port's controller, the "
            "power policy of your pad's actual device instances, and the "
            "system timer the input loop runs on. Nothing is touched until "
            "you press Engage, and every row reverts cleanly.")
        lock.setWordWrap(True)
        lock.setAlignment(Qt.AlignCenter)
        lock.setStyleSheet(
            f"font-size:12.5px; color:{_TEXT_4}; background:transparent;")
        self._hidden_lock_lbl = lock
        hl.addWidget(lock)
        self._reveal_btn = QPushButton("Reveal hidden overclocking")
        self._reveal_btn.setObjectName("Secondary")
        self._reveal_btn.clicked.connect(self._reveal_hidden)
        rb = QHBoxLayout()
        rb.addStretch()
        rb.addWidget(self._reveal_btn)
        rb.addStretch()
        hl.addLayout(rb)
        self._hidden_list = QWidget()
        self._hidden_list.setVisible(False)
        self._hl = QVBoxLayout(self._hidden_list)
        self._hl.setContentsMargins(0, 0, 0, 0)
        self._hl.setSpacing(10)
        hl.addWidget(self._hidden_list)
        root.addWidget(self._hidden_card)

    def _reveal_hidden(self):
        self._hidden_lock_lbl.setVisible(False)
        self._reveal_btn.setVisible(False)
        self._hid_rows = {}
        for key, title, desc, note in self.HIDDEN_ROWS:
            row = _HidRow(key, title, desc, note)
            row.apply_requested.connect(self._hid_apply)
            row.revert_requested.connect(self._hid_revert)
            self._hl.addWidget(row)
            self._hid_rows[key] = row
        self._hidden_list.setVisible(True)
        self._hid_refresh()

    def _hid_status(self, key):
        if key in ("tick", "dyntick"):
            st = eng.bcd_status()
            val = st.get("useplatformtick" if key == "tick"
                         else "disabledynamictick", "default")
            if val == "yes":
                return True, "ACTIVE", _GREEN
            if val == "no":
                return False, "OFF (WINDOWS)", _TEXT_6
            return False, "DEFAULT", _TEXT_6
        if key == "hubs":
            on = getattr(self, "_hubs_off", False)
            return on, ("PM OFF" if on else "WINDOWS DEFAULT"), (
                _GREEN if on else _TEXT_6)
        if key == "lpm":
            v = eng.lpm_get()
            if v == 65535:
                return True, "WRITTEN · REBOOT", _AMBER
            return False, "DEFAULT (375 MS)", _TEXT_6
        if key == "chain":
            if not self.pad:
                return False, "NO PAD DETECTED", _RED
            on = getattr(self, "_chain_off", False)
            return on, ("NEVER-OFF SET" if on else "WINDOWS DEFAULT"), (
                _GREEN if on else _TEXT_6)
        return False, "IDLE", _TEXT_6

    def _hid_refresh(self):
        for key, row in getattr(self, "_hid_rows", {}).items():
            active, text, color = self._hid_status(key)
            row.set_state(active, text, color)

    def _hid_apply(self, key):
        if getattr(self, "_hid_busy", False):
            toast("One hidden-tier op at a time — wait for it to finish.",
                  "warning", self)
            return
        self._hid_busy = True
        if key in ("tick", "dyntick"):
            k = "useplatformtick" if key == "tick" else "disabledynamictick"
            self._op_worker = _OpWorker([(eng.bcd_set, (k, "yes"))])
            self._op_worker.done.connect(
                lambda ok: self._hid_finish(ok, "reboot to take effect"))
            self._op_worker.start()
        elif key == "hubs":
            def _hubs():
                n = eng.all_hubs_pm_disable()
                self._hubs_off = n >= 0
                return n >= 0
            self._op_worker = _OpWorker([(_hubs, ())])
            self._op_worker.done.connect(
                lambda ok: self._hid_finish(ok, "hub power saving off"))
            self._op_worker.start()
        elif key == "lpm":
            self._op_worker = _OpWorker([(eng.lpm_set, (True,))])
            self._op_worker.done.connect(
                lambda ok: self._hid_finish(ok, "xHCI LPM timeout — reboot"))
            self._op_worker.start()
        elif key == "chain":
            if not self.pad:
                self._hid_busy = False
                toast("Connect the controller first — this row acts on "
                      "your actual pad's devices.", "warning", self)
                return
            pad = self.pad

            def _chain():
                n = eng.pad_chain_pm_disable(pad)
                self._chain_off = n > 0
                return n > 0
            self._op_worker = _OpWorker([(_chain, ())])
            self._op_worker.done.connect(
                lambda ok: self._hid_finish(
                    ok, "pad device chain set to never-turn-off"))
            self._op_worker.start()

    def _hid_revert(self, key):
        if getattr(self, "_hid_busy", False):
            toast("One hidden-tier op at a time — wait for it to finish.",
                  "warning", self)
            return
        self._hid_busy = True
        if key in ("tick", "dyntick"):
            k = "useplatformtick" if key == "tick" else "disabledynamictick"
            self._op_worker = _OpWorker([(eng.bcd_set, (k, ""))])
            self._op_worker.done.connect(
                lambda ok: self._hid_finish(ok, "back to firmware default"))
            self._op_worker.start()
        elif key == "hubs":
            def _hubs():
                n = eng.all_hubs_pm_restore()
                self._hubs_off = False
                return n >= 0
            self._op_worker = _OpWorker([(_hubs, ())])
            self._op_worker.done.connect(
                lambda ok: self._hid_finish(ok, "hub power saving restored"))
            self._op_worker.start()
        elif key == "lpm":
            self._op_worker = _OpWorker([(eng.lpm_set, (False,))])
            self._op_worker.done.connect(
                lambda ok: self._hid_finish(ok, "xHCI LPM back to default"))
            self._op_worker.start()
        elif key == "chain":
            if not self.pad:
                self._hid_busy = False
                toast("No pad detected to restore.", "warning", self)
                return
            rel = eng.related_instances(self.pad)
            insts = []
            for kind in ("hid", "controller"):
                insts.extend((rel.get(kind) or {}).keys())

            def _chain():
                ok = eng.device_pm_set(insts, True)
                self._chain_off = False
                return ok
            self._op_worker = _OpWorker([(_chain, ())])
            self._op_worker.done.connect(
                lambda ok: self._hid_finish(
                    ok, "pad device chain restored to Windows default"))
            self._op_worker.start()

    # ---------- diagnostics

    def _build_diag(self, root):
        root.addWidget(_section_head("Diagnostics",
                                     "Live readout from the connected pad"))
        root.addSpacing(14)
        grid = QGridLayout()
        grid.setSpacing(12)
        specs = [
            ("avg", "Avg. polling rate"), ("cons", "Consistency"),
            ("irt", "Input-to-report"), ("conn", "Connection"),
            ("vidpid", "VID / PID"), ("mode", "Detection mode"),
            ("disc", "Disconnects (session)"), ("test", "Full latency test"),
        ]
        self.tiles = {}
        for i, (key, label) in enumerate(specs):
            t = _DiagTile(label)
            self.tiles[key] = t
            grid.addWidget(t, i // 4, i % 4)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        root.addLayout(grid)

    # ================= behavior =================

    def _start_detect(self):
        self._detect_worker = _DetectWorker()
        self._detect_worker.done.connect(self._on_detect)
        self._detect_worker.start()

    def _on_detect(self, data):
        self.detect_data = data
        pads = data.get("pads") or []
        pads = [p for p in pads if p.get("name")
                and "system controller" not in p["name"].lower()]
        self.pad = pads[0] if pads else None
        if self.pad:
            vid = (self.pad.get("vid") or "????").lower()
            pid = (self.pad.get("pid") or "????").lower()
            conn = self.pad.get("conn") or "USB"
            drv = self.pad.get("drv") or (
                "USB game class" if self.pad.get("via") == "class05"
                else "HID")
            self.pad_art.setVisible(False)
            real = QLabel("\u2713 REAL DEVICE \u00b7 WINDOWS PnP")
            real.setAlignment(Qt.AlignCenter)
            real.setStyleSheet(
                f"font-family:{_MONO}; font-size:10px; color:{_GREEN};"
                f" background:transparent; padding: 4px 10px;")
            pl.insertWidget(0, real)
            self._real_lbl = real
            self.pad_name.setText(self.pad["name"])
            self.pad_name.setStyleSheet(
                f"font-family:{_DISPLAY}; font-size:17px; font-weight:700;"
                f" color:{_TEXT_1}; background:transparent;")
            self.pad_meta.setText(
                f"{conn} \u00b7 {drv} \u00b7 VID:PID {vid.upper()}:"
                f"{pid.upper()}")
            self.stat_conn.color = _GREEN
            self.stat_conn.setText(f"Connected \u00b7 {conn}")
            self.tiles["conn"].set_value(conn)
            self.tiles["vidpid"].set_value(f"{vid.upper()}:{pid.upper()}")
            mode = "XInput" if data.get("xinput") else "HID"
            self.tiles["mode"].set_value(mode)
        else:
            self.stat_conn.color = _RED
            self.stat_conn.setText("No controller detected")
            self.tiles["conn"].set_value("None")
            self.tiles["vidpid"].set_value("—")
            self.tiles["mode"].set_value("—")
        # selective suspend row reflects the real current state
        ss = data.get("sel_suspend")
        if ss is not None:
            self.rows["suspend"].set_state(not ss)
        self._update_row_availability()

    def _update_row_availability(self):
        pad = self.pad
        rel = eng.related_instances(pad) if pad else {}
        conn = (pad or {}).get("conn", "")

        def _swap(row, chip_text):
            row.downgrade(chip_text)
        if not pad:
            for rid in ("usbpm", "hid", "hub", "conn", "xinput", "rawinput"):
                _swap(self.rows[rid], "no device")
            _swap(self.rows["priority"], "not exposed")
            return
        _swap(self.rows["priority"], "not exposed")
        for rid in ("usbpm", "hid"):
            if not (rel.get("controller") or rel.get("hid")):
                _swap(self.rows[rid], "no device node")
        if not rel.get("hubs"):
            _swap(self.rows["hub"], "no hub node")
        if conn == "Bluetooth":
            self.rows["conn"].setToolTip(
                "Disables power management on the Bluetooth radio.")
        else:
            self.rows["conn"].set_state(True)
            self.rows["conn"].setToolTip("Wired connection — already stable.")
        if not self.detect_data.get("xinput"):
            _swap(self.rows["xinput"], "no xinput device")
        self.rows["xinput"].set_state(bool(self.detect_data.get("xinput")))
        self.rows["rawinput"].set_state(True)

    def _on_toggle(self, rid, state):
        ops = self._ops_for(rid, state)
        if ops:
            self._run_ops(ops, f"{rid} \u2192 "
                          f"{'on' if state else 'off (Windows default)'}")

    def _ops_for(self, rid, state):
        pad = self.pad
        rel = eng.related_instances(pad) if pad else {}
        usb_ctrl = list(rel.get("controller") or {})
        hid_inst = list(rel.get("hid") or {})
        hubs = list(rel.get("hubs") or {})
        if rid == "suspend":
            # Row ON = tweak active = selective suspend DISABLED.
            return [(eng.selective_suspend_set, (state,))]
        if rid == "usbpm":
            return [(eng.device_pm_set, (usb_ctrl or hid_inst, not state))]
        if rid == "hid":
            return [(eng.device_pm_set, (hid_inst, not state))]
        if rid == "hub":
            return [(eng.device_pm_set, (hubs, not state))]
        if rid == "conn":
            if state and (pad or {}).get("conn") == "Bluetooth":
                # The BT radio is the pad's USB parent device (BTHUSB).
                targets = usb_ctrl + [
                    b for b in eng._PM_CACHE if b.startswith("bth")]
                return [(eng.device_pm_set, (targets, False))]
            return []
        return []

    def _run_ops(self, ops, label):
        if self._op_worker and self._op_worker.isRunning():
            return
        self._op_worker = _OpWorker(ops)
        self._op_worker.done.connect(
            lambda ok: toast(("Applied: " if ok else "Partially applied: ")
                             + label,
                             "success" if ok else "warning", self))
        self._op_worker.start()

    def _apply_rows(self):
        ops = []
        for rid, row in self.rows.items():
            if row._enabled and row.sw and row.sw.is_on():
                ops.extend(self._ops_for(rid, True))
        if not ops:
            toast("Nothing enabled to apply.", "info", self)
            return
        self._run_ops(ops, f"{len(ops)} optimization(s)")

    def _apply_preset(self, key):
        plan = {
            "safe": ["suspend"],
            "low": ["suspend", "usbpm", "hid", "xinput", "rawinput", "conn"],
            "max": ["suspend", "usbpm", "hid", "hub", "conn", "xinput",
                    "rawinput"],
        }.get(key, [])
        for rid, row in self.rows.items():
            if row._enabled:
                row.set_state(rid in plan)
        ops = []
        for rid in plan:
            ops.extend(self._ops_for(rid, True))
        if ops:
            self._run_ops(ops, f"{key} preset")
        for k, pc in self.presets.items():
            pc.selected = (k == key)
            pc.refresh_style()

    # ---------- polling test

    def _pick_rate(self, hz):
        self.target_hz = hz
        for rb in self.rate_btns:
            rb.set_active(rb.hz == hz)
        self.tgt_fig.setText(f"{hz}Hz")

    def _run_test(self):
        if not self.pad:
            self._start_detect()
            toast("No controller detected — connect one and try again.",
                  "warning", self)
            return
        if self._test_worker and self._test_worker.isRunning():
            return
        self.btn_test.setEnabled(False)
        self.btn_test.setText("Testing 2s\u2026 move sticks / press!")
        self.stat_poll.color = _AMBER
        self.stat_poll.setText("Polling test running")
        self._test_worker = _TestWorker(self.pad)
        self._test_worker.done.connect(self._on_test)
        self._test_worker.start()

    def _on_test(self, res):
        self.btn_test.setEnabled(True)
        self.btn_test.setText("Test controller")
        self.stat_poll.color = _GREEN
        self.stat_poll.setText("Polling verified")
        if not res.get("ok"):
            self.oc_status.setText(
                f"Status: {res.get('note') or 'no input captured'}")
            self.tiles["test"].set_value("No input")
            return
        hz = res.get("hz")
        self.measured_hz = hz
        self.cur_fig.setText(f"~{hz}Hz")
        self.tiles["avg"].set_value(f"{hz} Hz")
        cons = res.get("consistency")
        self.tiles["cons"].set_value(
            f"{cons:.1f}%" if cons else "\u2014")
        avg_ms = res.get("avg_ms")
        self.tiles["irt"].set_value(
            f"{avg_ms:.2f} ms" if avg_ms else "\u2014")
        self.tiles["disc"].set_value("0 events")
        self.tiles["test"].set_value("Done \u00b7 " + res.get("path", "HID"))
        resp = []
        if res.get("axes"):
            resp.append("sticks OK")
        if res.get("triggers"):
            resp.append("triggers OK")
        if res.get("buttons"):
            resp.append("buttons OK")
        if resp:
            self.oc_status.setText(
                "Status: measured ~" + str(hz) + "Hz live over "
                + res.get("path", "HID") + " — " + ", ".join(resp) + ".")
        else:
            self.oc_status.setText(
                f"Status: ~{hz}Hz report rate confirmed via "
                f"{res.get('path')}. Move sticks / pull triggers during the "
                "test for response checks.")
