"""Tools page: quick-launch, diagnostics and repair tools in one clean grid.

Top down (mirrors the Tweaks page so the layout math is identical):
  * Page header (title + subtitle)
  * Toolbar - search field, live "N TOOLS" counter, Scan Hardware (primary)
  * Category pills - All / Quick Launch / System Tools / Diagnostics / Repair
  * Responsive tool-card grid + pagination

Each card is a proper card (icon, name, description, chips) whose whole
surface is clickable; the primary action runs the tool or opens the guide.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
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
from ui.widgets import IconTile, chip, clear_layout, toast

# Fixed chrome heights (must match TweaksPage so cards fit the window).
HEADER_H = 92
TOOLBAR_H = 48
PILLS_H = 46
PAGER_H = 46

ALL_KEY = "__all__"
QL_KEY = "Quick Launch"
PILL_KEYS = [ALL_KEY, QL_KEY, "System Tools", "Diagnostics", "Repair"]

# Category -> icon + accent color for tool cards.
TOOL_META = {
    QL_KEY: ("\u25c9", T["accent"]),
    "System Tools": ("\u2699", T["accent"]),
    "Diagnostics": ("\u2661", "#38bdf8"),
    "Repair": ("\u2692", "#fbbf24"),
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


class ToolCard(QFrame):
    """Card-style tool: icon, name, description, chips + run/guide button.

    Styled exactly like the tweak cards (objectName "ActionCard") so it reads
    as a first-class card, and the whole card is clickable for fast launch.
    """

    GRID_HEIGHT = 186

    def __init__(self, item: dict, on_click, parent=None):
        super().__init__(parent)
        self.setObjectName("ActionCard")
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = on_click

        cat = item["category"]
        icon, color = TOOL_META.get(cat, ("\u2699", T["accent"]))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(8)

        # ---- Head: icon tile + name + id
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(IconTile(icon, color, size=40, font_scale=0.5,
                                radius=10, bg="#1A202C"))
        box = QVBoxLayout()
        box.setSpacing(1)
        name_lbl = QLabel(item["name"])
        name_lbl.setStyleSheet("font-size: 14px; font-weight: 800; color: #F2F5F9;")
        name_lbl.setWordWrap(True)
        box.addWidget(name_lbl)
        id_lbl = QLabel(item["id"])
        id_lbl.setStyleSheet(f"font-size: 10px; color: {T['text_faint']};")
        box.addWidget(id_lbl)
        head.addLayout(box, 1)
        outer.addLayout(head)

        # ---- Description
        desc = QLabel(item.get("desc", ""))
        desc.setObjectName("PageSub")
        desc.setWordWrap(True)
        desc.setMinimumHeight(34)
        outer.addWidget(desc)

        # ---- Chips row: admin warning + category
        chips = QHBoxLayout()
        chips.setSpacing(6)
        if item.get("admin"):
            chips.addWidget(chip("\u26a0 ADMIN", T["warning"]))
        chips.addWidget(chip(cat, T["text_faint"]))
        chips.addStretch()
        outer.addLayout(chips)

        outer.addStretch(1)

        # ---- Footer: primary action
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.btn = QPushButton(self._btn_text(item))
        self.btn.setObjectName("Primary")
        self.btn.setFixedHeight(30)
        self.btn.clicked.connect(on_click)
        foot.addWidget(self.btn)
        foot.addStretch()
        outer.addLayout(foot)

    @staticmethod
    def _btn_text(item: dict) -> str:
        if item.get("btn_text"):
            return item["btn_text"]
        return "Run" if _has_cmd(item) else "Guide"

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_click is not None \
                and self.btn.isEnabled():
            self._on_click()
            event.accept()
            return
        super().mousePressEvent(event)


class ToolsPage(QWidget):
    MIN_CARD_W = 240
    MAX_COLS = 4
    GAP = 14

    def __init__(self, ctx, navigate, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.navigate = navigate
        self.key = ALL_KEY
        self.page = 1
        self._pages = 1
        self._filtered: list[dict] = []
        self._cards: dict[str, ToolCard] = {}
        self._orig_text: dict[str, str] = {}
        self._relayout_pending = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_pills())

        # ---- Card grid
        self.grid_host = QWidget()
        self.grid_host.installEventFilter(self)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(self.GAP)
        root.addWidget(self.grid_host)

        # ---- Pager
        self.pager = QWidget()
        self.pager.setObjectName("PageBar")
        self.pager.setFixedHeight(PAGER_H)
        self.pager_lay = QHBoxLayout(self.pager)
        self.pager_lay.setContentsMargins(0, 10, 0, 0)
        self.pager_lay.setSpacing(6)
        root.addWidget(self.pager)
        root.addStretch(1)

        QTimer.singleShot(0, self.refresh)

    # ---------------- Header ----------------

    def _build_header(self) -> QFrame:
        head = QFrame()
        head.setFixedHeight(HEADER_H)
        hl = QVBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(IconTile("\u2699", "#94a3b8", size=46, font_scale=0.5,
                               radius=11, bg="#1A202C"))
        box = QVBoxLayout()
        box.setSpacing(1)
        title = QLabel("System Tools")
        title.setStyleSheet("font-size: 23px; font-weight: 800;")
        sub = QLabel("Diagnostics, repair actions and quick-access utilities "
                     "for your system.")
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        box.addWidget(title)
        box.addWidget(sub)
        top.addLayout(box, 1)
        hl.addLayout(top)
        return head

    # ---------------- Toolbar ----------------

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(TOOLBAR_H)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search tools\u2026")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._on_filters())

        search_box = QFrame()
        search_box.setObjectName("SearchBox")
        sl = QHBoxLayout(search_box)
        sl.setContentsMargins(10, 0, 6, 0)
        sl.setSpacing(6)
        icon = QLabel("\u2315")
        icon.setObjectName("SearchIcon")
        sl.addWidget(icon)
        sl.addWidget(self.search, 1)
        lay.addWidget(search_box, 1)

        self.counter_lbl = QLabel()
        self.counter_lbl.setObjectName("StatChip")
        lay.addWidget(self.counter_lbl)

        btn_scan = QPushButton("Scan Hardware")
        btn_scan.setObjectName("Primary")
        btn_scan.setMinimumHeight(34)
        btn_scan.clicked.connect(lambda: self.navigate("detect"))
        lay.addWidget(btn_scan)

        btn_opt = QPushButton("Quick Optimize")
        btn_opt.setObjectName("Secondary")
        btn_opt.setMinimumHeight(34)
        btn_opt.clicked.connect(lambda: self.navigate("optimize"))
        lay.addWidget(btn_opt)

        btn_logs = QPushButton("Logs")
        btn_logs.setObjectName("Secondary")
        btn_logs.setMinimumHeight(34)
        btn_logs.clicked.connect(lambda: self.navigate("logs"))
        lay.addWidget(btn_logs)

        return bar

    # ---------------- Category pills ----------------

    def _build_pills(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(PILLS_H)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        content = QWidget()
        lay = QHBoxLayout(content)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(8)
        self.pill_btns = {}
        for key in PILL_KEYS:
            label = "All" if key == ALL_KEY else key
            btn = QPushButton(label)
            btn.setObjectName("FilterPill")
            btn.setProperty("active", "false")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.select(k))
            lay.addWidget(btn)
            self.pill_btns[key] = btn
        lay.addStretch()
        scroll.setWidget(content)
        return scroll

    # ---------------- Public API ----------------

    def select(self, key: str):
        changed = key != self.key
        self.key = key
        if changed:
            self.page = 1
            self.search.clear()
        self._mark_pills()
        self.refresh()

    def refresh(self):
        self._filtered = self._visible_tools()
        self._set_stats()
        self._mark_pills()
        self._schedule_relayout()

    def _on_filters(self):
        self.page = 1
        self.refresh()

    # ---------------- Data ----------------

    def _source_tools(self) -> list[dict]:
        if self.key == ALL_KEY:
            return _quick_launch_items() + group_tweaks("tools")
        if self.key == QL_KEY:
            return _quick_launch_items()
        return [t for t in group_tweaks("tools") if t["category"] == self.key]

    def _visible_tools(self) -> list[dict]:
        text = self.search.text().strip().lower()
        tools = self._source_tools()
        if not text:
            return tools
        return [
            t for t in tools
            if text in t["id"].lower()
            or text in t["name"].lower()
            or text in (t.get("desc") or "").lower()
            or text in (t.get("category") or "").lower()
        ]

    def _set_stats(self):
        count = len(self._filtered)
        color = T["accent"] if count else T["text_dim"]
        self.counter_lbl.setText(
            f"<span style='color:{color}; font-size:13px; font-weight:800;'>"
            f"{count}</span>"
            f"<span style='color:{T['text_faint']}; font-size:10px; "
            f"font-weight:700;'>&nbsp;&nbsp;TOOLS</span>")

    def _mark_pills(self):
        for key, btn in self.pill_btns.items():
            active = key == self.key
            if btn.property("active") != ("true" if active else "false"):
                btn.setProperty("active", "true" if active else "false")
                btn.style().unpolish(btn)
                btn.style().polish(btn)

    # ---------------- Grid layout / pagination ----------------

    def _geometry(self) -> tuple[int, int]:
        width = max(10, self.grid_host.width())
        cols = max(1, min(self.MAX_COLS, (width + self.GAP) // (self.MIN_CARD_W + self.GAP)))
        host_h = max(10, self.grid_host.height())
        rows = max(1, host_h // (ToolCard.GRID_HEIGHT + self.GAP))
        return cols, rows

    def _schedule_relayout(self):
        if self._relayout_pending:
            return
        self._relayout_pending = True
        QTimer.singleShot(0, self._do_relayout)

    def _do_relayout(self):
        self._relayout_pending = False
        self._relayout()

    def _relayout(self):
        cols, rows = self._geometry()
        per_page = cols * rows
        total = len(self._filtered)
        self._pages = max(1, (total + per_page - 1) // per_page)
        if self.page > self._pages:
            self.page = self._pages
        # Idempotency guard: rebuilding clears + recreates every card, and the
        # layout churn emits Resize events that re-trigger this method, so skip
        # the rebuild entirely when the visible state is unchanged. The ids are
        # part of the signature so switching section/page/search always rebuilds.
        start = (self.page - 1) * per_page
        cards = self._filtered[start:start + per_page]
        width = max(10, self.grid_host.width())
        card_w = max(self.MIN_CARD_W, (width - self.GAP * (cols - 1)) // cols)
        sig = (cols, rows, self.page, self._pages, total,
               tuple(item["id"] for item in cards), card_w)
        if sig == getattr(self, "_built_sig", None):
            return
        self._built_sig = sig
        self._rebuild_grid(cols, rows, per_page)
        self._rebuild_pager()

    def _rebuild_grid(self, cols, rows, per_page):
        clear_layout(self.grid)
        self._cards.clear()
        start = (self.page - 1) * per_page
        cards = self._filtered[start:start + per_page]
        width = max(10, self.grid_host.width())
        card_w = max(self.MIN_CARD_W, (width - self.GAP * (cols - 1)) // cols)
        n_rows = max(1, (len(cards) + cols - 1) // cols)
        # Size cards to fill the host exactly so there is no leftover space for
        # the grid to spread between rows (uniform 14px gaps, cards top-seated).
        host_h = max(10, self.grid_host.height())
        card_h = ToolCard.GRID_HEIGHT
        if n_rows > 1:
            card_h = max(ToolCard.GRID_HEIGHT,
                         (host_h - self.GAP * (n_rows - 1)) // n_rows)
        for idx, item in enumerate(cards):
            card = ToolCard(item, lambda _=False, it=item: self._run(it))
            self._cards[item["id"]] = card
            card.setFixedSize(card_w, card_h)
            r, c = divmod(idx, cols)
            self.grid.addWidget(card, r, c)
        # Absorb any residual space below a partial/single row.
        self.grid.setRowStretch(n_rows, 1)

    def _rebuild_pager(self):
        clear_layout(self.pager_lay)
        if self._pages <= 1:
            self.pager.setVisible(False)
            return
        self.pager.setVisible(True)
        prev = QPushButton("\u2039  Prev")
        prev.setObjectName("PageNav")
        prev.setEnabled(self.page > 1)
        prev.clicked.connect(lambda: self._go(self.page - 1))
        self.pager_lay.addWidget(prev)
        self.pager_lay.addSpacing(4)
        for num in self._page_window():
            btn = QPushButton(str(num))
            btn.setObjectName("PageNum")
            btn.setProperty("current", "true" if num == self.page else "false")
            btn.clicked.connect(lambda _=False, n=num: self._go(n))
            self.pager_lay.addWidget(btn)
        self.pager_lay.addSpacing(4)
        nxt = QPushButton("Next  \u203a")
        nxt.setObjectName("PageNav")
        nxt.setEnabled(self.page < self._pages)
        nxt.clicked.connect(lambda: self._go(self.page + 1))
        self.pager_lay.addWidget(nxt)
        self.pager_lay.addStretch()

    def _page_window(self) -> list[int]:
        total, cur = self._pages, self.page
        if total <= 7:
            return list(range(1, total + 1))
        pages = {1, total, cur - 1, cur, cur + 1}
        if cur <= 3:
            pages.update({2, 3, 4})
        if cur >= total - 2:
            pages.update({total - 3, total - 2, total - 1})
        return sorted(p for p in pages if 1 <= p <= total)

    def _go(self, page):
        if 1 <= page <= self._pages:
            self.page = page
            self._relayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_relayout()

    def eventFilter(self, obj, event):
        if obj is self.grid_host and event.type() == QEvent.Type.Resize:
            self._schedule_relayout()
        return super().eventFilter(obj, event)

    # ---------------- Run / Guide ----------------

    def _run(self, item: dict):
        key = item["id"]
        card = self._cards.get(key)
        if card is None:
            return
        self._begin_busy(key, "Running\u2026")
        launch_key = item.get("launch_key")
        try:
            if launch_key:
                ok, kind = launch_tool(launch_key), "run"
            else:
                ok, kind = run_tweak(item)
        except Exception:
            ok, kind = False, "run"
        QTimer.singleShot(450, lambda: self._finish_busy(key, ok, item, kind))

    def _finish_busy(self, key, ok, item, kind="run"):
        card = self._cards.get(key)
        if card is not None:
            card.btn.setEnabled(True)
            card.btn.setText(self._orig_text.get(key, "Run"))
        name = item["name"]
        if not ok:
            toast(f"Failed to launch {name}: Process execution error.", "error", self)
            return
        if kind == "guidance":
            self._show_guidance(item)
        else:
            toast(f"Launched {name} successfully.", "success", self)

    def _begin_busy(self, key, text):
        card = self._cards.get(key)
        if card is None:
            return
        self._orig_text[key] = card.btn.text()
        card.btn.setEnabled(False)
        card.btn.setText(text)

    def _show_guidance(self, tweak: dict):
        box = QMessageBox(self)
        box.setWindowTitle(tweak["name"])
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(tweak.get("desc", ""))
        for action in tweak.get("actions", []):
            if isinstance(action, (tuple, list)) and action and action[0] == "guidance":
                box.setDetailedText(action[1] if len(action) > 1 else "")
                break
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
