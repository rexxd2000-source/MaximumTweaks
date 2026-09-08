"""AI Assistant page — exact port of ai-assistant-revamp.html.

Two columns over the reference atmosphere (pink + violet blobs, masked dot
grid): the chat column (mini-bar, centered hero with 6 prompt cards until the
first message, typing indicator, composer) and the 320px context panel
("What I can see": live specs, tweaks-applied stat, offline note, capability
tags, Clear chat). Chat runs on engine.chat.ChatWorker; UI never blocks.
Typography stays on native system faces (Segoe UI / JetBrains Mono).
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QRadialGradient
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config.app_config import BOT_NAME, THEME as T
from engine import state as state_mgr
from engine.chat import ChatAssistant, llm_configured
from ui.widgets import FlowLayout, clear_layout, toast

# Reference palette (ai-assistant-revamp.html)
_BG = "#08060F"
_VIOLET = "#8B6BFF"
_VIOLET_SOFT = "#C9C0FF"
_PINK = "#E879C9"
_AMBER = "#E6B34B"
_GREEN = "#3DDC97"
_TEXT_1 = "#F6F4FC"
_TEXT_4 = "#928AAD"
_TEXT_6 = "#514A70"
_BORDER = "rgba(255,255,255,0.09)"
_BORDER_SOFT = "rgba(255,255,255,0.06)"
_GLASS = "rgba(255,255,255,0.03)"
_DISPLAY = '"Segoe UI", sans-serif'
_MONO = '"JetBrains Mono", monospace'

MIN_TYPING = 0.85

PROMPTS = [
    ("Show my specs", "Pull a full hardware summary"),
    ("What tweaks are applied?", "List everything currently active"),
    ("Why is my ping high?", "Walk through likely causes"),
    ("Is my PC good for gaming?", "Assess against this hardware"),
    ("Best budget gaming mouse?", "A web-informed recommendation"),
    ("What can you do?", "See the full capability list"),
]

# Reference SVG glyphs (viewBox 0 0 24 24, stroke)
_SVG = {
    "sparkle": ('<path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z"/>'
                '<path d="M19 15l1 2.5 2.5 1-2.5 1-1 2.5-1-2.5-2.5-1 '
                '2.5-1z"/>', 1.6),
    "chat": ('<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 '
             '0 012 2z"/>', 1.6),
    "mic": ('<rect x="9" y="2" width="6" height="12" rx="3"/>'
            '<path d="M5 10a7 7 0 0014 0M12 19v3"/>', 1.6),
    "eye": ('<path d="M12 4.5C7 4.5 2.7 7.6 1 12c1.7 4.4 6 7.5 11 7.5'
            's9.3-3.1 11-7.5c-1.7-4.4-6-7.5-11-7.5z"/>'
            '<circle cx="12" cy="12" r="3"/>', 1.8),
}


def _ref_svg(name: str, color: str, size: int) -> QLabel:
    """Reference stroke icon rendered from its SVG path (crisp at any size)."""
    from PySide6.QtGui import QPixmap
    from PySide6.QtSvg import QSvgRenderer
    paths, sw = _SVG[name]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="{sw}" '
           f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    r = QSvgRenderer()
    r.load(svg.encode("utf-8"))
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setPixmap(pm)
    lbl.setStyleSheet("background:transparent;border:none;")
    return lbl


class _Atmosphere(QWidget):
    """#08060F base + pink blob (upper-left-ish) + violet blob (lower-right)
    + the 34px dot grid masked around 45%/25%, per the reference .app."""

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(_BG))
        # Reference blobs are position:fixed on the full window (sidebar is
        # 264px), so convert their window coords into this content-pane's
        # frame: pink center (460-264, 40), violet center (w-510, h+10).
        ga = QRadialGradient(QPointF(196, 40), 360)
        ga.setColorAt(0.0, QColor(232, 121, 201, 23))
        ga.setColorAt(0.7, QColor(232, 121, 201, 0))
        p.fillRect(self.rect(), ga)
        gb = QRadialGradient(QPointF(w - 510, h + 10), 330)
        gb.setColorAt(0.0, QColor(139, 107, 255, 23))
        gb.setColorAt(0.7, QColor(139, 107, 255, 0))
        p.fillRect(self.rect(), gb)
        cx, cy = 0.32 * w, 0.25 * h
        rx, ry = 0.65 * (w + 264), 0.55 * h
        if rx > 0 and ry > 0:
            y = 17.0
            while y < h:
                x = 17.0
                while x < w:
                    t = (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2) ** 0.5
                    if t < 0.85:
                        a = int(34 * (1.0 - t / 0.85))
                        if a > 3:
                            p.setPen(QColor(200, 190, 240, a))
                            p.drawPoint(QPointF(x, y))
                    x += 34.0
                y += 34.0
        p.end()


class TypingIndicator(QWidget):
    """'Maximum is typing' with three dots gliding on a continuous sine
    wave (60fps paint loop — no per-widget animation stutter)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(2, 0, 2, 0)
        outer.setSpacing(8)
        self.prefix = QLabel(f"{BOT_NAME} is typing")
        self.prefix.setStyleSheet(
            f"color: {_TEXT_4}; font-size: 12px; background:transparent;")
        outer.addWidget(self.prefix)
        self._host = _TypingDots()
        outer.addWidget(self._host)
        outer.addStretch(1)

    def start(self):
        self._host.run()
        self.show()

    def stop(self):
        self._host.stop()
        self.hide()


class _TypingDots(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 22)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._phase += 0.09
        if self._phase > 1e6:
            self._phase = 0.0
        self.update()

    def run(self):
        self._phase = 0.0
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def paintEvent(self, _):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setPen(Qt.NoPen)
        for i in range(3):
            t = self._phase - i * 0.45
            s = math.sin(t * 2.0)
            y = 11.0 + 4.0 * s
            # fade toward the bottom of the arc for a gel-like feel
            a = 150 + int(90 * max(0.0, s))
            p.setBrush(QColor(232, 121, 201, a))
            p.drawEllipse(QPointF(9 + i * 13, y), 3.4, 3.4)
        p.end()


class ChatWorker(QThread):
    """Runs one assistant turn off the UI thread."""

    done = Signal(str, list)
    error = Signal(str)

    def __init__(self, question: str, profile: dict, history: list[dict],
                 parent=None):
        super().__init__(parent)
        self.question = question
        self.profile = profile
        self.history = history
        self._assistant = ChatAssistant()

    def run(self):
        try:
            result = self._assistant.respond(
                self.question, self.profile, self.history)
            self.done.emit(result["text"], result["tools"])
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
#  Panels
# ---------------------------------------------------------------------------

def _centered(widget):
    """HBox with side stretches — centers a width-capped Expanding widget
    without shrinking it to its sizeHint (an AlignHCenter flag does that)."""
    box = QHBoxLayout()
    box.setContentsMargins(0, 0, 0, 0)
    box.addStretch(1)
    box.addWidget(widget)
    box.addStretch(1)
    return box


class _PromptCard(QFrame):
    clicked = Signal(str)

    def __init__(self, title, sub, ask, parent=None):
        super().__init__(parent)
        self.setObjectName("PromptCard")
        self.ask = ask
        self.setCursor(Qt.PointingHandCursor)
        self._paint_base()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)
        t = QLabel(title)
        t.setStyleSheet(
            f"font-size:13px; font-weight:600; color:{_TEXT_1};"
            f" background:transparent;")
        s = QLabel(sub)
        s.setStyleSheet(
            f"font-size:11px; color:{_TEXT_6}; background:transparent;")
        lay.addWidget(t)
        lay.addWidget(s)

    def enterEvent(self, ev):
        self.setStyleSheet(
            "#PromptCard{background:rgba(255,255,255,0.03);"
            " border:1px solid rgba(232,121,201,0.40); border-radius:13px;}")
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._paint_base()
        super().leaveEvent(ev)

    def _paint_base(self):
        self.setStyleSheet(
            "#PromptCard{background:rgba(255,255,255,0.03);"
            " border:1px solid rgba(255,255,255,0.09); border-radius:13px;}")

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self.ask)
        super().mousePressEvent(ev)


class _ContextPanel(QFrame):
    clear_requested = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("CtxPanel")
        self.setFixedWidth(320)
        self.setStyleSheet(
            "#CtxPanel{background:rgba(255,255,255,0.015);"
            " border-left:1px solid rgba(255,255,255,0.06);}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea>QWidget>QWidget{background:transparent;}")
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(22, 26, 22, 22)
        v.setSpacing(0)
        scroll.setWidget(inner)
        lay.addWidget(scroll)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_ref_svg("eye", _PINK, 13), 0, Qt.AlignVCenter)
        ht = QLabel("What I can see")
        ht.setStyleSheet(
            f"font-family:{_MONO}; font-size:10.5px; color:{_TEXT_4};"
            f" background:transparent;")
        hf = ht.font()
        hf.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
        ht.setFont(hf)
        head.addWidget(ht)
        head.addStretch()
        v.addLayout(head)
        v.addSpacing(16)

        self.spec_card = _GlassCard(13)
        sl = QVBoxLayout(self.spec_card)
        sl.setContentsMargins(16, 6, 16, 6)
        sl.setSpacing(0)
        self._spec_rows: dict[str, QLabel] = {}
        for key in ("CPU", "GPU", "RAM", "OS"):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 8, 0, 8)
            l = QLabel(key)
            l.setStyleSheet(
                f"font-size:12px; color:{_TEXT_4}; background:transparent;")
            val = QLabel("—")
            val.setStyleSheet(
                f"font-size:12px; color:{_TEXT_1}; font-weight:500;"
                f" background:transparent;")
            rl.addWidget(l)
            rl.addStretch()
            rl.addWidget(val)
            sl.addWidget(row)
            if key != "CPU":
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(
                    "background:rgba(255,255,255,0.06); border:none;")
                sl.addWidget(sep)
            self._spec_rows[key] = val
        v.addWidget(self.spec_card)
        v.addSpacing(14)

        stat = _GlassCard(13)
        stl = QVBoxLayout(stat)
        stl.setContentsMargins(16, 12, 16, 16)
        stl.setSpacing(2)
        self.n_lbl = QLabel("0")
        self.n_lbl.setAlignment(Qt.AlignCenter)
        self.n_lbl.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:24px; font-weight:700;"
            f" color:{_VIOLET_SOFT}; background:transparent;")
        nl = QLabel("TWEAKS APPLIED")
        nl.setAlignment(Qt.AlignCenter)
        nl.setStyleSheet(
            f"font-size:10.5px; color:{_TEXT_6}; background:transparent;")
        stl.addWidget(self.n_lbl)
        stl.addWidget(nl)
        v.addWidget(stat)
        v.addSpacing(14)

        note = _GlassCard(13)
        nl2 = QVBoxLayout(note)
        nl2.setContentsMargins(16, 14, 16, 14)
        nb = QLabel(
            f"<span style='color:{_AMBER};font-weight:600;'>Offline mode</span>"
            f"<span style='color:{_TEXT_4};'> means I'm answering from this "
            "machine's local data only — I won't reach the web until you're "
            "back online.</span>")
        nb.setWordWrap(True)
        nb.setTextFormat(Qt.RichText)
        nb.setStyleSheet("font-size:11.5px; background:transparent;")
        nl2.addWidget(nb)
        v.addWidget(note)
        v.addSpacing(14)

        tags = _GlassCard(13)
        tg = FlowLayout(tags, hspacing=6, vspacing=6)
        tg.setContentsMargins(14, 12, 14, 12)
        for label in ("Reads specs", "Tracks tweaks", "Web lookup",
                      "Shares links"):
            tag = QLabel(label)
            tag.setStyleSheet(
                f"font-size:10.5px; color:{_TEXT_4};"
                f" border:1px solid rgba(255,255,255,0.06);"
                " border-radius:6px; padding:4px 9px;"
                " background:transparent;")
            tg.addWidget(tag)
        v.addWidget(tags)
        v.addSpacing(4)

        self.clear_btn = QPushButton("Clear chat")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setStyleSheet(
            "QPushButton{font-size:12.5px; font-weight:600;"
            f" color:{_TEXT_4}; background:rgba(255,255,255,0.03);"
            " border:1px solid rgba(255,255,255,0.09); border-radius:10px;"
            " padding:10px;}"
            "QPushButton:hover{color:#F6F4FC;"
            " background:rgba(255,255,255,0.06);}")
        self.clear_btn.clicked.connect(self.clear_requested)
        v.addWidget(self.clear_btn)
        v.addStretch()

        ctx.profile_changed.connect(self.refresh)
        ctx.state_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        p = self.ctx.profile or {}
        cpu = (p.get("cpu_name") or "—")
        gpus = p.get("gpu_names") or []
        gpu = (gpus[0] if gpus else "—")
        ram = p.get("ram_gb")
        os_v = p.get("win_version")
        self._spec_rows["CPU"].setText(
            cpu.replace("AMD ", "").replace("Intel ", "")[:18] or "—")
        self._spec_rows["GPU"].setText(
            gpu.replace("NVIDIA GeForce ", "").replace("AMD ", "")[:16]
            or "—")
        self._spec_rows["RAM"].setText(
            f"{ram} GB" if ram else "—")
        self._spec_rows["OS"].setText(
            f"Windows {os_v}" if os_v else "—")
        try:
            self.n_lbl.setText(str(len(list(state_mgr.applied_ids()))))
        except Exception:
            self.n_lbl.setText("0")


class _GlassCard(QFrame):
    def __init__(self, radius=13, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("GlassCard2")
        self.setStyleSheet(
            f"#GlassCard2{{background:{_GLASS};"
            f" border:1px solid {_BORDER}; border-radius:{radius}px;}}")


# ---------------------------------------------------------------------------
#  Page
# ---------------------------------------------------------------------------

class ChatPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._worker: ChatWorker | None = None
        self._history: list[dict] = []
        self._pending_reply: str | None = None
        self._turn_id = 0
        self._typing_started = 0.0

        self._hero_sub = None
        self._grid_host = None
        self._comp_row = None
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._atmo = _Atmosphere(self)
        self._atmo.setGeometry(0, 0, 10, 10)
        self._atmo.lower()

        # ================= chat column =================
        chat_col = QWidget()
        chat_col.setStyleSheet("background:transparent;")
        cl = QVBoxLayout(chat_col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        root.addWidget(chat_col, 1)

        bar = QFrame()
        bar.setObjectName("MiniBar")
        bar.setStyleSheet(
            "#MiniBar{border-bottom:1px solid rgba(255,255,255,0.06);}")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(36, 20, 36, 20)
        name = QHBoxLayout()
        name.setSpacing(9)
        dot = QLabel()
        dot.setFixedSize(6, 6)
        dot.setStyleSheet(
            "background:transparent;border:none;"
            f"border-radius:3px;background-color:{_AMBER};")
        dot.setProperty("class", "amber")
        name.addWidget(dot, 0, Qt.AlignVCenter)
        nm = QLabel("AI Assistant")
        nm.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:14.5px; font-weight:600;"
            f" color:{_TEXT_1}; background:transparent;")
        name.addWidget(nm)
        bl.addLayout(name)
        bl.addStretch()
        self.engine_lbl = QLabel()
        self.engine_lbl.setStyleSheet("background:transparent;")
        bl.addWidget(self.engine_lbl, 0, Qt.AlignVCenter)
        cl.addWidget(bar)

        # ---- scrollable body
        body_scroll = QScrollArea()
        self._body_scroll = body_scroll
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea>QWidget>QWidget{background:transparent;}")
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        self.body_lay = QVBoxLayout(body)
        self.body_lay.setContentsMargins(30, 30, 30, 12)
        self.body_lay.setSpacing(10)
        body_scroll.setWidget(body)
        cl.addWidget(body_scroll, 1)

        # ---- hero (empty state)
        self.hero = QWidget()
        self.hero.setStyleSheet("background:transparent;")
        hv = QVBoxLayout(self.hero)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(0)
        hv.addSpacing(18)
        hv.addStretch(1)

        hicon = _GlassCard(18)
        hicon.setFixedSize(60, 60)
        hicon.setStyleSheet(
            "#GlassCard2{background:rgba(232,121,201,0.10);"
            " border:1px solid rgba(232,121,201,0.30); border-radius:18px;}")
            # box-shadow equivalent: none in QSS; the pink glass reads enough
        hil = QHBoxLayout(hicon)
        hil.setContentsMargins(0, 0, 0, 0)
        hil.setAlignment(Qt.AlignCenter)
        hil.addWidget(_ref_svg("sparkle", _PINK, 26))
        hv.addWidget(hicon, 0, Qt.AlignHCenter)
        hv.addSpacing(20)

        h1 = QLabel("Ask Maximum anything about this PC.")
        h1.setAlignment(Qt.AlignCenter)
        h1.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:24px; font-weight:600;"
            f" color:{_TEXT_1}; background:transparent;")
        hv.addWidget(h1)
        hv.addSpacing(10)

        sub = QLabel("I read this machine's real hardware and tweak state, "
                     "and I can look up almost anything online and share "
                     "links \u2014 try a prompt below, or type your own.")
        # Reliable wrap: stretch-box + capped width (a QVBoxLayout alignment
        # flag uses sizeHint and clips wrapped lines; the HBox honors
        # heightForWidth).
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        self._hero_sub = sub
        sub.setFixedWidth(720)
        sub.setStyleSheet(
            f"font-size:14.5px; color:{_TEXT_4}; background:transparent;")
        subrow = QHBoxLayout()
        subrow.setContentsMargins(0, 0, 0, 0)
        subrow.addStretch(1)
        subrow.addWidget(sub, 0, Qt.AlignHCenter)
        subrow.addStretch(1)
        hv.addLayout(subrow)
        hv.addSpacing(34)

        grid_host = QWidget()
        grid_host.setStyleSheet("background:transparent;")
        self._grid_host = grid_host
        grid_host.setFixedWidth(1120)
        gg = QGridLayout(grid_host)
        gg.setContentsMargins(0, 0, 0, 0)
        gg.setHorizontalSpacing(10)
        gg.setVerticalSpacing(10)
        for i, (pt, ps) in enumerate(PROMPTS):
            ask = pt if i != 4 else "What's the best budget gaming mouse?"
            card = _PromptCard(pt, ps, ask)
            card.clicked.connect(self._send)
            gg.addWidget(card, i // 2, i % 2)
        for c in range(2):
            gg.setColumnStretch(c, 1)
        hv.addWidget(grid_host, 0, Qt.AlignHCenter)
        hv.addStretch(3)
        self.body_lay.addWidget(self.hero)

        # ---- message area (below hero, grows with the conversation)
        self.msg_host = QWidget()
        self.msg_host.setStyleSheet("background:transparent;")
        self.msg_lay = QVBoxLayout(self.msg_host)
        self.msg_lay.setContentsMargins(0, 0, 0, 0)
        self.msg_lay.setSpacing(10)
        self.msg_lay.addStretch(1)   # conversation anchors to the bottom
        self.msg_host.setVisible(False)  # hidden until the first message
        self.body_lay.addWidget(self.msg_host, 1)

        self.typing = TypingIndicator()
        self.typing.setVisible(False)
        self.msg_lay.addWidget(self.typing, 0, Qt.AlignLeft)

        # ---- composer
        comp = QFrame()
        comp.setObjectName("Composer")
        comp.setStyleSheet(
            "#Composer{border-top:1px solid rgba(255,255,255,0.06);}")
        cpl = QVBoxLayout(comp)
        cpl.setContentsMargins(36, 18, 36, 26)
        cpl.setSpacing(0)
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        # reference .input-row: max-width 760, centered. Use a cap + Expanding
        # so it reaches 760px on wide windows but shrinks on narrow ones.
        self._comp_row = row
        row.setFixedWidth(1320)
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)

        ibar = QFrame()
        ibar.setObjectName("InputBar")
        ibar.setFixedHeight(50)
        ibar.setStyleSheet(
            "#InputBar{background:rgba(255,255,255,0.03);"
            " border:1px solid rgba(255,255,255,0.09); border-radius:13px;}")
        il = QHBoxLayout(ibar)
        il.setContentsMargins(16, 0, 14, 0)
        il.setSpacing(10)
        il.addWidget(_ref_svg("chat", _TEXT_6, 16), 0, Qt.AlignVCenter)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask about your PC...")
        self.input.setFrame(False)
        # No inner vertical padding: the bar is fixed at 44px, so 12+12px of
        # padding + text height overflows and Qt CLIPS the placeholder
        # (the "can't see the full text" bug). Center a full-height edit.
        self.input.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.input.setMinimumHeight(50)
        self.input.setStyleSheet(
            "QLineEdit{background:transparent;border:none;padding:0 2px;"
            f" font-size:15px; color:{_TEXT_1};}}"
            "QLineEdit::placeholder{color:#514A70;}")
        self.input.returnPressed.connect(self._on_submit)
        il.addWidget(self.input, 1)
        rl.addWidget(ibar, 1)

        mic = QFrame()
        mic.setObjectName("MicBtn")
        mic.setFixedSize(50, 50)
        mic.setCursor(Qt.PointingHandCursor)
        mic.setStyleSheet(
            "#MicBtn{background:rgba(255,255,255,0.03);"
            " border:1px solid rgba(255,255,255,0.09); border-radius:13px;}")
        ml = QHBoxLayout(mic)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setAlignment(Qt.AlignCenter)
        ml.addWidget(_ref_svg("mic", _TEXT_4, 16))
        mic.mousePressEvent = lambda _ev: toast(
            "Voice input is coming soon.", "info", self)
        rl.addWidget(mic)

        self.send_btn = QPushButton("Send")
        self.send_btn.setFixedHeight(50)
        self.send_btn.setMinimumWidth(96)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setStyleSheet(
            "QPushButton{color:#fff;border:none;border-radius:13px;"
            " font-size:13.5px; font-weight:600;"
            " background:qlineargradient(x1:0,y1:0,x2:1,y2:0.35,"
            " stop:0 #8B6BFF, stop:1 #6D4FE0);}"
            "QPushButton:hover:enabled{background:qlineargradient("
            "x1:0,y1:0,x2:1,y2:0.35, stop:0 #9C80FF, stop:1 #7C5FF0);}"
            "QPushButton:disabled{background:rgba(139,107,255,0.30);"
            " color:rgba(255,255,255,0.5);}")
        self.send_btn.clicked.connect(self._on_submit)
        rl.addWidget(self.send_btn)

        cpl.addLayout(_centered(row))
        cl.addWidget(comp)

        # ================= context panel =================
        self.context = _ContextPanel(ctx)
        self.context.clear_requested.connect(self._clear)
        root.addWidget(self.context)

        self._set_engine_label()
        ctx.license_changed.connect(self._set_engine_label)

    # ---- chrome ---------------------------------------------------------
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._atmo.setGeometry(self.rect())
        self._atmo.lower()
        self._rescale()

    def _rescale(self):
        # Widths scale with the chat pane so the AI page fills big and
        # ultrawide screens instead of shrinking to a tiny island; caps
        # keep it HTML-proportioned on 1080p.
        colw = max(360, self.width() - (320 + 80))
        if self._comp_row is not None:
            self._comp_row.setFixedWidth(max(600, min(int(colw * 0.96), 1900)))
        if self._grid_host is not None:
            self._grid_host.setFixedWidth(max(600, min(int(colw * 0.84), 1560)))
        if self._hero_sub is not None:
            self._hero_sub.setFixedWidth(max(480, min(int(colw * 0.62), 1080)))

    def _set_engine_label(self):
        if llm_configured():
            self.engine_lbl.setText(
                f"<span style='color:{_GREEN};'>\u25cf</span>"
                f"<span style='color:{_GREEN};font-family:{_MONO};"
                "font-size:10.5px;'> Online</span>")
        else:
            self.engine_lbl.setText(
                f"<span style='color:{_AMBER};'>\u25cf</span>"
                f"<span style='color:{_AMBER};font-family:{_MONO};"
                "font-size:10.5px;'> Offline mode</span>")

    # ---- messages -------------------------------------------------------
    def _add_message(self, role: str, text: str):
        self.hero.setVisible(False)
        self.msg_host.setVisible(True)
        if "<" not in text:  # plain model/user text: keep line breaks
            import html as _html
            shown = _html.escape(text).replace("\n", "<br>")
        else:
            shown = text
        bubble = QFrame()
        own = role == "user"
        bubble.setObjectName("BubbleU" if own else "BubbleA")
        bubble.setMaximumWidth(1100)
        if own:
            bubble.setStyleSheet(
                "#BubbleU{background:qlineargradient(x1:0,y1:0,x2:1,y2:0.5,"
                " stop:0 rgba(139,107,255,0.28), stop:1 rgba(109,79,224,0.20));"
                " border:1px solid rgba(139,107,255,0.35);"
                " border-radius:13px;}")
        else:
            bubble.setStyleSheet(
                "#BubbleA{background:rgba(255,255,255,0.03);"
                " border:1px solid rgba(255,255,255,0.09);"
                " border-radius:13px;}")
        lay = QVBoxLayout(bubble)
        lay.setContentsMargins(16, 12, 16, 12)
        body = QLabel(shown)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setTextFormat(Qt.RichText)
        body.setStyleSheet(
            f"color:{_TEXT_1}; font-size:13px; background:transparent;")
        # Size the bubble to its content (wide, readable lines) instead of
        # letting Qt collapse a wordWrap label to minimum width.
        import re as _re
        from PySide6.QtGui import QFont, QFontMetrics
        plain = _re.sub(r"<[^>]+>", " ", text)
        plain = " ".join(plain.split("\n"))
        f = QFont(body.font())
        f.setPixelSize(13)
        fm = QFontMetrics(f)
        longest = max((fm.horizontalAdvance(line) for line in
                       _re.sub(r"<[^>]+>", " ", text).split("\n")),
                      default=200)
        cap = 820 if not own else 700
        target = int(max(260, min(cap, longest + 44)))
        bubble.setFixedWidth(target)
        inner_w = target - 34
        body.setFixedWidth(inner_w)
        body.setMinimumHeight(
            max(18, body.heightForWidth(inner_w)))
        lay.addWidget(body)

        row = QWidget()
        row.setStyleSheet("background:transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        if own:
            rl.addStretch(1)
            rl.addWidget(bubble)
        else:
            rl.addWidget(bubble)
            rl.addStretch(1)
        self.msg_lay.addWidget(row)
        self._history.append({"role": role, "text": text})
        self._scroll_bottom()

    def _scroll_bottom(self):
        QTimer.singleShot(
            0, lambda: self._body_scroll.verticalScrollBar().setValue(
                self._body_scroll.verticalScrollBar().maximum()))

    def _clear(self):
        if self._worker is not None and self._worker.isRunning():
            return
        clear_layout(self.msg_lay)
        self.msg_lay.addStretch(1)
        self._history.clear()
        self.hero.setVisible(True)
        self.msg_host.setVisible(False)

    # ---- send flow ------------------------------------------------------
    def _on_submit(self):
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self._send(text)

    def _send(self, text: str):
        if self._worker is not None and self._worker.isRunning():
            toast("Still thinking\u2026", "info", self)
            return
        self._add_message("user", text)
        self._turn_id += 1
        self._pending_reply = None
        self._typing_started = time.monotonic()
        # keep the typing line glued to the bottom of the conversation
        self.msg_lay.removeWidget(self.typing)
        self.msg_lay.addWidget(self.typing, 0, Qt.AlignLeft)
        self.typing.start()
        self.send_btn.setEnabled(False)

        self._worker = ChatWorker(text, self.ctx.profile, list(self._history),
                                  self)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_done(self, reply, tools):
        self._pending_reply = reply

    def _on_error(self, msg):
        self._pending_reply = f"Something went wrong: {msg}"

    def _on_finished(self):
        self.send_btn.setEnabled(True)
        self._worker = None
        reply, turn = self._pending_reply, self._turn_id
        self._pending_reply = None
        remaining = MIN_TYPING - (time.monotonic() - self._typing_started)
        if remaining > 0:
            QTimer.singleShot(int(remaining * 1000),
                              lambda: self._deliver(reply, turn))
        else:
            self._deliver(reply, turn)

    def _deliver(self, reply, turn):
        self.typing.stop()
        if reply is None or turn != self._turn_id:
            return
        self._add_message("assistant", reply)
