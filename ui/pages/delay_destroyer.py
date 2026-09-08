"""Delay Destroyer — tweak card library.

No scanner, no scores. One optimization = one card.
Cards use TweakCard + BatchWorker from the standard Maximum infrastructure.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget, QSizePolicy,
)

from config.app_config import THEME as T
from database.tweaks import TWEAKS as ALL_TWEAKS
from engine import state as state_mgr
from ui.widgets import BatchWorker, TweakCard, clear_layout, toast


# Sub-category groupings for the DD tweaks.
_SUB_CATEGORIES = [
    ("Input Latency", "INPUT LATENCY", "Mouse, keyboard and HID response time."),
    ("System Responsiveness", "SYSTEM RESPONSIVENESS", "Windows scheduling and CPU affinity."),
    ("Gaming & Frame Time", "GAMING & FRAME TIME", "Game Bar, fullscreen and multimedia scheduling."),
    ("Network", "NETWORK", "TCP/IP stack and DNS tuning."),
    ("USB & Peripherals", "USB & PERIPHERALS", "USB power management and transfer timeouts."),
]


def _dd_tweaks() -> list[dict]:
    return [t for t in ALL_TWEAKS if t.get("module") == "delay_destroyer"]


class DelayDestroyerPage(QWidget):
    MIN_CARD_W = 240
    MAX_COLS = 4
    GAP = 10

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._busy = False
        self._worker = None
        self._cards: dict[str, TweakCard] = {}
        self._in_flight: set[str] = set()
        self._batch_ids: list[str] = []
        self._batch_mode: str = "apply"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._root = outer

        self._build_view()

    # ── Helpers ──────────────────────────────────────────────────────

    def _clear(self):
        clear_layout(self._root)

    def _make_label(self, text, style_key, align=Qt.AlignLeft, wrap=False):
        w = QLabel(text)
        base = "font-family:'Segoe UI',sans-serif;"
        styles = {
            "title": f"{base}font-size:22px;font-weight:700;color:{T['text']};letter-spacing:3px;",
            "sub": f"{base}font-size:12px;color:{T['text_dim']};letter-spacing:1px;",
            "section": f"{base}font-size:14px;font-weight:700;color:{T['text']};letter-spacing:2px;",
            "section_sub": f"{base}font-size:11px;color:{T['text_faint']};letter-spacing:1px;",
            "empty": f"{base}font-size:13px;color:{T['text_faint']};letter-spacing:1px;",
        }
        w.setStyleSheet(styles.get(style_key, ""))
        w.setAlignment(align)
        if wrap:
            w.setWordWrap(True)
        return w

    def _hline(self):
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"background:{T['border_soft']};max-height:1px;")
        return f

    # ── Build ────────────────────────────────────────────────────────

    def _build_view(self):
        self._clear()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea>QWidget>QWidget{background:transparent;}")
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 18, 24, 24)
        lay.setSpacing(0)

        # Header
        lay.addWidget(self._make_label("DELAY DESTROYER", "title"))
        lay.addSpacing(4)
        lay.addWidget(self._make_label(
            "One optimization per card. Apply or revert individually.",
            "sub"))
        lay.addSpacing(20)

        # Tweak cards grouped by sub-category
        tweaks = _dd_tweaks()
        if not tweaks:
            lay.addWidget(self._make_label(
                "No Delay Destroyer tweaks found.", "empty",
                align=Qt.AlignCenter))
            lay.addStretch()
            scroll.setWidget(body)
            self._root.addWidget(scroll, 1)
            return

        # Group by sub_category
        grouped: dict[str, list[dict]] = {}
        for t in tweaks:
            cat = t.get("sub_category", "Other")
            grouped.setdefault(cat, []).append(t)

        # Render each sub-category section
        for cat_key, cat_label, cat_desc in _SUB_CATEGORIES:
            cat_tweaks = grouped.get(cat_key, [])
            if not cat_tweaks:
                continue

            sec = QHBoxLayout()
            sec.setSpacing(8)
            sec.addWidget(self._make_label(cat_label.upper(), "section"))
            sec.addStretch()
            lay.addLayout(sec)

            desc_lbl = self._make_label(cat_desc, "section_sub")
            desc_lbl.setContentsMargins(0, 0, 0, 8)
            lay.addWidget(desc_lbl)

            # Card grid
            grid = QGridLayout()
            grid.setSpacing(self.GAP)
            for idx, t in enumerate(cat_tweaks):
                card = TweakCard(self.ctx, t)
                self._cards[t["id"]] = card
                card.apply_requested.connect(self._apply)
                card.revert_requested.connect(self._revert)
                r, c = divmod(idx, self.MAX_COLS)
                grid.addWidget(card, r, c)
            lay.addLayout(grid)

            lay.addSpacing(8)
            lay.addWidget(self._hline())
            lay.addSpacing(8)

        # Tweaks not in any sub-category
        seen = set()
        for cat_key, _, _ in _SUB_CATEGORIES:
            for t in grouped.get(cat_key, []):
                seen.add(t["id"])
        orphan = [t for t in tweaks if t["id"] not in seen]
        if orphan:
            sec = QHBoxLayout()
            sec.setSpacing(8)
            sec.addWidget(self._make_label("OTHER", "section"))
            sec.addStretch()
            lay.addLayout(sec)

            grid = QGridLayout()
            grid.setSpacing(self.GAP)
            for idx, t in enumerate(orphan):
                card = TweakCard(self.ctx, t)
                self._cards[t["id"]] = card
                card.apply_requested.connect(self._apply)
                card.revert_requested.connect(self._revert)
                r, c = divmod(idx, self.MAX_COLS)
                grid.addWidget(card, r, c)
            lay.addLayout(grid)

        lay.addStretch()

        scroll.setWidget(body)
        self._root.addWidget(scroll, 1)

        # Re-layout cards when viewport resizes
        self.ctx.state_changed.connect(self._refresh_cards)

    # ── Refresh ──────────────────────────────────────────────────────

    def _refresh_cards(self):
        for card in self._cards.values():
            card.refresh()

    # ── Apply / Revert ───────────────────────────────────────────────

    def _apply(self, tid):
        self._run_batch([tid], "apply")

    def _revert(self, tid):
        self._run_batch([tid], "revert")

    def _run_batch(self, ids, mode):
        if self._busy:
            toast("A batch is already running — wait a moment.", "warning", self)
            return
        self._busy = True
        self._in_flight.update(ids)
        self._batch_ids = list(ids)
        self._batch_mode = mode
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        self._worker = BatchWorker(ids, mode, self, profile=self.ctx.profile)
        self._worker.batch_done.connect(self._on_batch_done)
        self._worker.batch_error.connect(self._on_batch_error)
        self._worker.start()

    def _on_batch_done(self, result):
        self._busy = False
        results = result.get("results", {})
        ok_ids = [tid for tid, r in results.items()
                  if r.get("ok") and r.get("status") != "dry_run"]
        failed = len(results) - len(ok_ids)
        total = len(results)
        verb = "Reverted" if self._batch_mode == "revert" else "Applied"
        if failed:
            toast(f"{len(ok_ids)} of {total} tweaks — {failed} failed or blocked.",
                  "warning", self)
        else:
            toast(f"{verb} {total} tweak{'s' if total != 1 else ''} successfully.",
                  "success", self)

        for tid in self._batch_ids:
            r = results.get(tid) or {}
            ok = r.get("ok") and r.get("status") != "dry_run"
            if not ok:
                self.ctx.live.pop(tid, None)
                continue
            if self._batch_mode == "revert":
                state_mgr.unmark_applied(tid)
                state_mgr.mark_disabled(tid)
                self.ctx.live[tid] = False
            else:
                state_mgr.mark_applied(tid)
                state_mgr.unmark_disabled(tid)
                self.ctx.live[tid] = True

        self._in_flight.clear()
        self.ctx.invalidate_state()
        self.ctx.force_audit_ids(ok_ids)
        self.ctx.note_state_change()
        self._refresh_cards()

    def _on_batch_error(self, msg):
        self._busy = False
        self._in_flight.clear()
        self.ctx.invalidate_state()
        self.ctx.note_state_change()
        self._refresh_cards()
        toast(f"Batch error — {msg}", "error", self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._rebuild_cards)

    def _rebuild_cards(self):
        pass
