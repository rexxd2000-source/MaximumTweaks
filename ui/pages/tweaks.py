"""Tweaks page: single clean view of all tweak categories.

Top down:
  * Page header (title + subtitle, reflects the active category)
  * Toolbar  - search field, sort dropdown, live "X/Y APPLIED" counter,
               Apply All (primary), Revert All (secondary)
  * Responsive toggle-card grid + pagination

Category switching is driven entirely by the left sidebar (no pill bar).
The page drives its own apply/revert batches (background worker + toast), so
cards flip instantly and the UI never blocks.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config.app_config import THEME as T
from ui.categories import (
    ALL_TWEAK_KEYS,
    CATEGORY_GROUPS,
    group_tweaks,
    recommended_count,
)
from ui.widgets import (
    BatchWorker,
    IconTile,
    TweakCard,
    clear_layout,
    toast,
)

# Fixed chrome heights used to compute how many card rows fit.
HEADER_H = 76
TOOLBAR_H = 48
PAGER_H = 46

SORT_MODES = [
    ("recommended", "Recommended first"),
    ("impact", "Impact: High \u2192 Low"),
    ("risk", "Risk: Safe first"),
    ("name", "Name A\u2013Z"),
]
IMPACT_RANK = {"extreme": 6, "high": 5, "moderate": 4, "low": 3, "very low": 2}
RISK_RANK = {"safe": 0, "low": 1, "moderate": 2, "advanced": 3}
REC_RANK = {
    "recommended": 0, "optional": 1, "experimental": 2,
    "advanced": 3, "not_recommended": 4,
}

ALL_KEY = "__all__"

# Page-header titles per sidebar category (fall back to CATEGORY_GROUPS).
HEADER_TITLES = {
    "cpu": "CPU Tweaks",
    "gpu": "GPU Optimizations",
    "ram": "RAM Tweaks",
    "input": "Aim / Input Tweaks",
    "mouse": "Mouse Tweaks",
    "keyboard": "Keyboard Tweaks",
    "network": "Network Tweaks",
    "storage": "Storage / SSD Tweaks",
    "system": "Windows / System",
    "performance": "Performance Tweaks",
    "fortnite": "Fortnite Tweaks",
    "games": "Game Tweaks",
}

HEADER_ICONS = {
    "cpu": "\u2b22",
    "gpu": "\u25c6",
    "ram": "\u2588",
    "input": "\u2694",
    "mouse": "\u21a8",
    "keyboard": "\u2328",
    "network": "\u2637",
    "storage": "\u25b6",
    "system": "\u2699",
    "performance": "\u26a1",
    "fortnite": "\u25c9",
    "games": "\u2605",
}


class TweaksPage(QWidget):
    """All tweaks in one place — sidebar-driven, searchable, sortable."""

    MIN_CARD_W = 240
    MAX_COLS = 4
    GAP = 10

    def __init__(self, ctx, parent=None, fixed_group=None):
        super().__init__(parent)
        self.ctx = ctx
        self.fixed_group = fixed_group
        self.key = fixed_group or ALL_KEY
        self.page = 1
        self._pages = 1
        self._filtered: list[dict] = []
        self._cards: dict[str, TweakCard] = {}
        self._busy = False
        self._worker = None
        self._relayout_pending = False
        self._in_flight: set[str] = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Scrollable content (header + toolbar + card grid) fills the page and
        # scrolls internally; the pager is pinned below it so it is never
        # clipped off the bottom of the window.
        self.scroll = QScrollArea(self)
        scroll = self.scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        wrapper = QWidget()
        wrapper.setObjectName("category-view-wrapper")
        root = QVBoxLayout(wrapper)
        root.setContentsMargins(14, 10, 14, 16)
        root.setSpacing(8)

        if not fixed_group:
            self.header = self._build_header()
            self.header.setObjectName("category-header")
            root.addWidget(self.header)
            root.addSpacing(10)
            toolbar = self._build_toolbar()
            toolbar.setObjectName("search-bar-container")
            root.addWidget(toolbar)
            root.addSpacing(10)

        # ---- Card grid (hugs its content; trailing stretch absorbs leftover
        # viewport space so there is no dead band below the cards)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("tweaks-grid")
        self.grid_host.installEventFilter(self)
        self.grid_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(self.GAP)
        root.addWidget(self.grid_host)
        root.addStretch(1)

        outer.addWidget(scroll, 1)
        scroll.setWidget(wrapper)

        # ---- Pager: fixed bar below the scroll area (always visible)
        self.pager = QWidget()
        self.pager.setObjectName("PageBar")
        self.pager.setFixedHeight(PAGER_H)
        self.pager.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.pager_lay = QHBoxLayout(self.pager)
        self.pager_lay.setContentsMargins(10, 0, 10, 0)
        self.pager_lay.setSpacing(6)
        self.pager_lay.setAlignment(Qt.AlignLeft)
        outer.addWidget(self.pager)

        self.ctx.state_changed.connect(self.refresh)
        self.ctx.live_state_changed.connect(self._on_live_state)
        QTimer.singleShot(0, self.refresh)

    # ---------------- Header ----------------

    def _build_header(self):
        head = QFrame()
        head.setFixedHeight(HEADER_H)
        hl = QVBoxLayout(head)
        hl.setContentsMargins(0, 12, 0, 0)
        hl.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(12)
        top.setAlignment(Qt.AlignVCenter)
        self.head_icon = IconTile("\u26a1", "#94a3b8", size=46, font_scale=0.5,
                                  radius=11, bg="#1A202C")
        top.addWidget(self.head_icon)
        box = QVBoxLayout()
        box.setSpacing(4)
        self.title_lbl = QLabel("Optimize Your PC")
        self.title_lbl.setStyleSheet("font-size: 23px; font-weight: 800;")
        self.blurb_lbl = QLabel(
            "Toggle the optimizations you want \u2014 tweaks are pre-checked for "
            "your hardware, and each flips instantly.")
        self.blurb_lbl.setObjectName("PageSub")
        self.blurb_lbl.setWordWrap(True)
        box.addWidget(self.title_lbl)
        box.addWidget(self.blurb_lbl)
        top.addLayout(box, 1)
        self.btn_recommended = QPushButton("\u26a1  Apply Recommended for this System")
        self.btn_recommended.setObjectName("Primary")
        self.btn_recommended.setMinimumHeight(38)
        self.btn_recommended.setCursor(Qt.PointingHandCursor)
        self.btn_recommended.setToolTip(
            "Deep-checks this PC, then applies the tweaks that fit it. "
            "Everything applied here is fully revertable.")
        self.btn_recommended.clicked.connect(self._open_recommended)
        top.addWidget(self.btn_recommended, alignment=Qt.AlignVCenter)
        hl.addLayout(top)
        return head

    def _header_for(self, key) -> tuple[str, str]:
        if key == ALL_KEY:
            return ("Optimize Your PC",
                    "Toggle the optimizations you want \u2014 tweaks are pre-checked "
                    "for your hardware, and each flips instantly.")

        meta = CATEGORY_GROUPS.get(key)
        if meta:
            return (HEADER_TITLES.get(key, meta["title"]), meta["blurb"])
        return (HEADER_TITLES.get(key, "Tweaks"), "")

    def _update_header(self):
        if not hasattr(self, "title_lbl"):
            return
        title, blurb = self._header_for(self.key)
        self.title_lbl.setText(title)
        self.blurb_lbl.setText(blurb)
        self.head_icon.setText(HEADER_ICONS.get(self.key, "\u26a1"))
        self.head_icon.setToolTip(title)

    # ---------------- Toolbar ----------------

    def _build_toolbar(self):
        bar = QWidget()
        bar.setFixedHeight(TOOLBAR_H)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search tweaks\u2026")
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

        self.sort_combo = QComboBox()
        for key, label in SORT_MODES:
            self.sort_combo.addItem(label, key)
        self.sort_combo.setFixedWidth(190)
        self.sort_combo.currentIndexChanged.connect(lambda _: self._on_filters())
        lay.addWidget(self.sort_combo)

        lay.addStretch()

        self.counter_lbl = QLabel()
        self.counter_lbl.setObjectName("StatChip")
        lay.addWidget(self.counter_lbl)

        self.btn_apply_all = QPushButton("Apply All")
        self.btn_apply_all.setObjectName("Primary")
        self.btn_apply_all.setMinimumHeight(34)
        self.btn_apply_all.clicked.connect(self._apply_all)
        lay.addWidget(self.btn_apply_all)

        self.btn_revert_all = QPushButton("Revert All")
        self.btn_revert_all.setObjectName("Secondary")
        self.btn_revert_all.setMinimumHeight(34)
        self.btn_revert_all.clicked.connect(self._revert_all)
        lay.addWidget(self.btn_revert_all)

        return bar

    # ---------------- Public API ----------------

    def select(self, key):
        if self.fixed_group:
            return
        changed = key != self.key
        self.key = key
        if changed:
            self.page = 1
            self.search.clear()
        self.refresh()

    def refresh(self):
        if not self.key:
            return
        self._set_stats()
        self._filtered = self._visible_tweaks()
        self._set_toolbar()
        self._update_header()
        self._schedule_relayout()
        self._request_audit()

    def _request_audit(self):
        """Background-check the live system state of the current group."""
        if not self.key:
            return
        self.ctx.request_audit(self._source_tweaks())

    def _on_live_state(self, tid, value):
        if tid in self._in_flight:
            return  # stale audit result; a batch is in progress for this tweak
        card = self._cards.get(tid)
        if card is not None:
            card.set_detected(value)
        self._set_stats()

    # ---------------- Actions ----------------

    def _apply(self, tid):
        self._run_batch([tid], "apply")

    def _revert(self, tid):
        self._run_batch([tid], "revert")

    def _apply_all(self):
        ids = [
            t["id"] for t in self._visible_tweaks()
            if self.ctx.state_of(t["id"]) not in ("incompatible", "not_for_you")
            and not self.ctx.live_active(t["id"])
        ]
        if not ids:
            toast("Nothing to apply \u2014 every visible tweak is already active "
                  "on your system.", "info", self)
            return
        if not self._confirm(
                "Apply All",
                f"Apply {len(ids)} visible compatible tweak(s) to your system?\n\n"
                "This changes registry, services and power settings. Everything "
                "can be reverted with Revert All."):
            return
        toast(f"Applying {len(ids)} tweaks\u2026", "info", self)
        self._run_batch(ids, "apply")

    def _revert_all(self):
        ids = [
            t["id"] for t in self._visible_tweaks()
            if self.ctx.state_of(t["id"]) not in ("incompatible", "not_for_you")
            and self.ctx.live_active(t["id"])
        ]
        if not ids:
            toast("Nothing to revert \u2014 no active tweaks in view.", "info", self)
            return
        if not self._confirm(
                "Revert All",
                f"Revert {len(ids)} applied tweak(s) back to their defaults?"):
            return
        toast(f"Reverting {len(ids)} tweaks\u2026", "info", self)
        self._run_batch(ids, "revert")

    def _open_recommended(self):
        """Launch the deep-check 'Apply Recommended' wizard."""
        from ui.recommend_wizard import RecommendWizard
        wizard = RecommendWizard(self.ctx, self)
        wizard.exec()

    @staticmethod
    def _confirm(title, text) -> bool:
        box = QMessageBox()
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Warning)
        yes = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _run_batch(self, ids, mode):
        if self._busy:
            toast("A batch is already running \u2014 wait a moment.", "warning", self)
            return
        self._busy = True
        self._in_flight.update(ids)
        self._set_toolbar()
        # Clean up any previous worker.
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(2000)
        self._worker = BatchWorker(ids, mode, self)
        self._worker.batch_done.connect(self._on_batch_done)
        self._worker.batch_error.connect(self._on_batch_error)
        self._worker.start()

    def _post_batch(self, ids):
        """Invalidate cached reads and re-check the real system state so the
        toggles converge on what is actually applied (even if an older audit
        is still streaming stale results)."""
        self._in_flight.clear()
        self.ctx.invalidate_state()
        self.ctx.force_audit_ids(ids)
        self.ctx.note_state_change()
        self.refresh()

    def _on_batch_done(self, result):
        self._busy = False
        results = result.get("results", {})
        ok_ids = [tid for tid, (ok, _d) in results.items() if ok]
        failed = len(results) - len(ok_ids)
        total = len(results)
        if failed:
            msg = (f"{len(ok_ids)} of {total} tweaks "
                   f"\u2014 {failed} failed or blocked.")
            toast(msg.strip(), "warning", self)
        else:
            verb = "Applied" if total else "Done"
            toast(f"{verb} {total} tweak{'s' if total != 1 else ''} "
                  "successfully.", "success", self)
        self._post_batch(ok_ids)

    def _on_batch_error(self, msg):
        self._busy = False
        self._in_flight.clear()
        self._set_toolbar()
        toast(f"Batch error \u2014 {msg}", "error", self)
        self.ctx.invalidate_state()
        self.ctx.note_state_change()
        self.refresh()

    # ---------------- Data / filters / sort ----------------

    def _source_tweaks(self) -> list[dict]:
        if self.key == ALL_KEY:
            out = []
            for k in ALL_TWEAK_KEYS:
                out.extend(group_tweaks(k))
            return out
        return group_tweaks(self.key)

    def _visible_tweaks(self) -> list[dict]:
        text = ""
        if hasattr(self, "search"):
            text = self.search.text().strip().lower()
        tweaks = self._source_tweaks()
        if text:
            tweaks = [
                t for t in tweaks
                if (text in t["id"].lower()
                    or text in t["name"].lower()
                    or text in (t.get("desc") or "").lower()
                    or text in (t.get("category") or "").lower()
                    or text in " ".join(t.get("tags") or []).lower())
            ]
        mode = self.sort_combo.currentData() if hasattr(self, "sort_combo") else None
        if mode == "impact":
            tweaks.sort(key=lambda t: -IMPACT_RANK.get(t.get("impact", "low"), 0))
        elif mode == "risk":
            tweaks.sort(key=lambda t: RISK_RANK.get(t.get("risk", "safe"), 0))
        elif mode == "name":
            tweaks.sort(key=lambda t: t["name"].lower())
        else:
            tweaks.sort(
                key=lambda t: (REC_RANK.get(t.get("recommended", "optional"), 9),
                               t["name"].lower()))
        return tweaks

    def _on_filters(self):
        self.page = 1
        self.refresh()

    # ---------------- Stats / toolbar state ----------------

    def _set_stats(self):
        if self.fixed_group or not hasattr(self, "counter_lbl"):
            return
        all_tweaks = self._source_tweaks()
        applied = sum(1 for t in all_tweaks if self.ctx.live_active(t["id"]))
        rec = recommended_count(all_tweaks)
        color = T["accent"] if applied else T["text_dim"]
        self.counter_lbl.setText(
            f"<span style='color:{color}; font-size:13px; font-weight:800;'>"
            f"{applied} / {len(all_tweaks)}</span>"
            f"<span style='color:{T['text_dim']}; font-size:10px; font-weight:700;'>"
            f"&nbsp;&nbsp;APPLIED</span>"
            f"<span style='color:{T['text_faint']}; font-size:10px; font-weight:600;'>"
            f"&nbsp;&nbsp;\u00b7&nbsp; {rec} RECOMMENDED</span>")

    def _set_toolbar(self):
        if self.fixed_group or not hasattr(self, "btn_apply_all"):
            return
        self.btn_apply_all.setEnabled(not self._busy)
        self.btn_revert_all.setEnabled(not self._busy)

    # ---------------- Grid layout / pagination ----------------

    def _geometry(self) -> tuple[int, int]:
        width = max(10, self.grid_host.width())
        cols = max(1, min(self.MAX_COLS, (width + self.GAP) // (self.MIN_CARD_W + self.GAP)))
        # Rows are derived from the visible scroll viewport (minus header,
        # toolbar and their spacers) so pagination never underestimates and
        # the last page never leaves a dead band at the bottom.
        chrome = HEADER_H + TOOLBAR_H + 20 if not self.fixed_group else 0
        view_h = max(10, self.scroll.viewport().height() - chrome)
        rows = max(1, view_h // (TweakCard.GRID_HEIGHT + self.GAP))
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
        # part of the signature so switching category/page/search always rebuilds.
        start = (self.page - 1) * per_page
        cards = self._filtered[start:start + per_page]
        width = max(10, self.grid_host.width())
        card_w = max(self.MIN_CARD_W, (width - self.GAP * (cols - 1)) // cols)
        sig = (cols, rows, self.page, self._pages, total,
               tuple(t["id"] for t in cards), card_w)
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
        card_h = TweakCard.GRID_HEIGHT
        for idx, t in enumerate(cards):
            card = TweakCard(self.ctx, t)
            self._cards[t["id"]] = card
            card.apply_requested.connect(self._apply)
            card.revert_requested.connect(self._revert)
            card.setFixedSize(card_w, card_h)
            r, c = divmod(idx, cols)
            self.grid.addWidget(card, r, c)

    def _rebuild_pager(self):
        clear_layout(self.pager_lay)
        if self._pages <= 1:
            self.pager.setVisible(False)
            return
        self.pager.setVisible(True)
        prev = QPushButton("\u2039")
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
        self.pager_lay.addStretch(1)

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
        if self.key:
            self._schedule_relayout()

    def eventFilter(self, obj, event):
        if obj is self.grid_host and event.type() == QEvent.Type.Resize and self.key:
            self._schedule_relayout()
        return super().eventFilter(obj, event)
