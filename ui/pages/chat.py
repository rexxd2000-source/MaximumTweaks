"""AI Assistant page: a chat panel wired to the system-aware chat engine.

The page itself is model-agnostic: it renders bubbles, runs each question on a
background thread through ``engine.chat.ChatAssistant`` (the tool-plumbing
backend), and displays the reply. Swapping in a real LLM only changes the
engine, not this UI.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.app_config import THEME as T
from engine.chat import ChatAssistant
from ui.widgets import IconTile, clear_layout, toast

SUGGESTIONS = [
    "Show my specs",
    "What tweaks are applied?",
    "Why is my ping high?",
    "Is my PC good for gaming?",
    "How do I boost my FPS?",
    "What can you do?",
]


class ChatWorker(QThread):
    """Runs one assistant turn off the UI thread."""

    done = Signal(str, list)
    error = Signal(str)

    def __init__(self, question: str, profile: dict, parent=None):
        super().__init__(parent)
        self.question = question
        self.profile = profile
        self._assistant = ChatAssistant()

    def run(self):
        try:
            result = self._assistant.respond(self.question, self.profile)
            self.done.emit(result["text"], result["tools"])
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"{type(exc).__name__}: {exc}")


class ChatPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._worker: ChatWorker | None = None
        self._history: list[dict] = []  # {"role", "text"}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_suggestions())

        # ---- Message scroll
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self.msg_lay = QVBoxLayout(inner)
        self.msg_lay.setContentsMargins(4, 6, 4, 6)
        self.msg_lay.setSpacing(10)
        self.msg_lay.addStretch(1)
        self.scroll.setWidget(inner)
        root.addWidget(self.scroll, 1)

        # ---- Typing indicator (hidden until a turn is in flight)
        self.typing = QLabel("Assistant is thinking\u2026")
        self.typing.setStyleSheet(
            f"color: {T['text_dim']}; font-size: 12px; padding: 2px 6px;")
        self.typing.setVisible(False)
        root.addWidget(self.typing)

        # ---- Input row
        root.addWidget(self._build_input())

        self._greet()

    # ---------------- Header / toolbar ----------------

    def _build_header(self) -> QFrame:
        head = QFrame()
        hl = QVBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(IconTile("\u2728", T["accent"], size=46, font_scale=0.5,
                               radius=11, bg="#1A202C"))
        box = QVBoxLayout()
        box.setSpacing(1)
        title = QLabel("AI Assistant")
        title.setStyleSheet("font-size: 23px; font-weight: 800;")
        sub = QLabel("Ask about your PC \u2014 it reads this machine's real "
                     "specs and tweak state.")
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        box.addWidget(title)
        box.addWidget(sub)
        top.addLayout(box, 1)
        hl.addLayout(top)
        return head

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.engine_lbl = QLabel()
        self.engine_lbl.setObjectName("StatChip")
        self._set_engine_label()
        lay.addWidget(self.engine_lbl)

        lay.addStretch()

        btn_clear = QPushButton("Clear Chat")
        btn_clear.setObjectName("Secondary")
        btn_clear.setMinimumHeight(32)
        btn_clear.clicked.connect(self._clear)
        lay.addWidget(btn_clear)
        return bar

    def _set_engine_label(self):
        self.engine_lbl.setText(
            f"<span style='color:{T['warning']}; font-size:12px; font-weight:700;'>"
            f"\u25cf&nbsp; DEMO ENGINE</span>"
            f"<span style='color:{T['text_faint']}; font-size:10px;'>&nbsp;&nbsp;"
            f"connect a model in engine/chat.py</span>")

    def _build_suggestions(self) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for text in SUGGESTIONS:
            btn = QPushButton(text)
            btn.setObjectName("FilterPill")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, t=text: self._send(t))
            lay.addWidget(btn)
        lay.addStretch()
        return wrap

    def _build_input(self) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        box = QFrame()
        box.setObjectName("SearchBox")
        bl = QHBoxLayout(box)
        bl.setContentsMargins(10, 0, 6, 0)
        bl.setSpacing(6)
        icon = QLabel("\u2315")
        icon.setObjectName("SearchIcon")
        bl.addWidget(icon)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask about your PC\u2026")
        self.input.returnPressed.connect(self._on_submit)
        bl.addWidget(self.input, 1)
        lay.addWidget(box, 1)

        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("Primary")
        self.send_btn.setMinimumHeight(34)
        self.send_btn.clicked.connect(self._on_submit)
        lay.addWidget(self.send_btn)
        return row

    # ---------------- Messages ----------------

    def _greet(self):
        self._add_message(
            "assistant",
            "Hi! I can read this PC's real hardware and tweak state. "
            "Try a suggestion above, or ask things like:\n"
            "\u2022 show my specs\n"
            "\u2022 explain net-005\n"
            "\u2022 what tweaks are applied?",
            highlight=True)

    def _add_message(self, role: str, text: str, highlight: bool = False):
        bubble = QFrame()
        bubble.setObjectName("ActionCard")
        lay = QVBoxLayout(bubble)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(3)

        tag = QLabel("YOU" if role == "user" else "REX")
        tag.setStyleSheet(
            f"color: {T['accent'] if role == 'user' else T['text_dim']}; "
            "font-size: 10px; font-weight: 800; letter-spacing: 1.5px;")
        lay.addWidget(tag)

        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet(
            f"color: {T['text'] if not highlight else T['text_dim']}; "
            "font-size: 13.5px; line-height: 1.35;")
        lay.addWidget(body)

        self.msg_lay.insertWidget(self.msg_lay.count() - 1, bubble)
        self._history.append({"role": role, "text": text})
        self._scroll_bottom()

    def _scroll_bottom(self):
        QTimer_ = __import__("PySide6.QtCore", fromlist=["QTimer"]).QTimer
        QTimer_.singleShot(0, lambda: self.scroll.verticalScrollBar()
                           .setValue(self.scroll.verticalScrollBar().maximum()))

    def _clear(self):
        if self._worker is not None and self._worker.isRunning():
            return
        clear_layout(self.msg_lay)
        self.msg_lay.addStretch(1)
        self._history.clear()
        self._greet()

    # ---------------- Send flow ----------------

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
        self.typing.setVisible(True)
        self.send_btn.setEnabled(False)

        self._worker = ChatWorker(text, self.ctx.profile, self)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_done(self, reply, tools):
        self._add_message("assistant", reply)

    def _on_error(self, msg):
        self._add_message("assistant", f"Something went wrong: {msg}")

    def _on_finished(self):
        self.typing.setVisible(False)
        self.send_btn.setEnabled(True)
        self._worker = None
