"""Per-category Optimize dialog.

One instance is launched per category's single "Optimize <Category>" button.
It runs every optimizer that belongs to that category (real detection ->
compatibility scan -> ranking) in a background thread, merges the reports into
one review list, lets the user check the recommendations they want, then
applies only the selected tweaks and reports verification.

This replaces the old single global "Apply Recommended for this System"
wizard — there is no cross-category button anymore.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.app_config import THEME as T
from engine.optimizer import BUTTON_LABELS, merge_reports
from rexlog import logger
from ui.widgets import BatchWorker, clear_layout, toast

MARK = {
    "compatible": ("\u2713", T["success"]),
    "optional": ("\u25cb", T["accent"]),
    "driver_dependent": ("\u26a0", T["warning"]),
    "unknown": ("\u00b7", T["text_dim"]),
    "guidance": ("\u2139", T["text_dim"]),
    "already_active": ("\u25cf", T["success"]),
    "not_applicable": ("\u2715", T["text_faint"]),
    "conflicting": ("\u2715", T["danger"]),
    "outdated": ("\u2715", T["danger"]),
    "placebo": ("\u2715", T["danger"]),
    "invalid": ("\u2715", T["danger"]),
}

EVIDENCE_LABEL = {"HIGH": "High evidence", "MEDIUM": "Medium evidence",
                  "LOW": "Low evidence", "UNKNOWN": "No evidence"}


class OptimizeWorker(QThread):
    """Runs every optimizer in a category group off the UI thread."""

    done = Signal(object)
    error = Signal(str)
    phase = Signal(str)

    def __init__(self, optimizers, ctx, parent=None, title="", subtitle=""):
        super().__init__(parent)
        self.optimizers = list(optimizers) if isinstance(
            optimizers, (list, tuple)) else [optimizers]
        self.ctx = ctx
        self.title = title
        self.subtitle = subtitle

    def run(self):
        reports, failures = [], []
        for opt in self.optimizers:
            self.phase.emit(f"Scanning {BUTTON_LABELS.get(opt.key, opt.title)} \u2026")
            try:
                reports.append(opt.run(self.ctx, refresh=True))
            except Exception as exc:  # noqa: BLE001
                logger.warn(f"optimize {opt.key}: {type(exc).__name__}: {exc}")
                failures.append(opt.key)
        if not reports:
            self.error.emit(
                "no optimizer produced results: " + ", ".join(failures))
            return
        title = self.title or reports[0].title
        subtitle = self.subtitle or reports[0].subtitle
        self.done.emit(merge_reports(reports, title, subtitle))


class OptimizeDialog(QDialog):
    """Category optimization flow: scan -> review -> apply -> verify."""

    def __init__(self, ctx, optimizers, label=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.optimizers = list(optimizers) if isinstance(
            optimizers, (list, tuple)) else [optimizers]
        self.optimizer = self.optimizers[0]
        self.label = label or BUTTON_LABELS.get(
            self.optimizer.key, self.optimizer.title)
        self.group_title = f"Optimize {self.label}"
        if len(self.optimizers) == 1:
            self.group_subtitle = self.optimizer.subtitle
        else:
            subs = ", ".join(
                BUTTON_LABELS.get(o.key, o.title) for o in self.optimizers)
            self.group_subtitle = f"Combined scan across {subs} for this system."
        self._checkboxes: list = []
        self._worker: OptimizeWorker | None = None
        self._apply_worker: BatchWorker | None = None
        self._report = None

        self.setWindowTitle(self.group_title + " \u2014 Rex Tweaks")
        self.setModal(True)
        self.resize(760, 700)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._build_loading_page())
        self.stack.addWidget(self._build_results_page())
        self.stack.addWidget(self._build_apply_page())
        self.stack.addWidget(self._build_done_page())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.stack)

        self._start_scan()

    # ---------------- Phase 1: scanning ----------------

    def _build_loading_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(36, 30, 36, 30)
        lay.setSpacing(10)

        kicker = QLabel("REX OPTIMIZATION ENGINE \u2014 CATEGORY SCAN")
        kicker.setStyleSheet(
            f"color: {T['accent']}; font-size: 11px; font-weight: 800;"
            "letter-spacing: 3px;")
        lay.addWidget(kicker)

        self.scan_title = QLabel(self.group_title)
        self.scan_title.setStyleSheet(
            "font-size: 26px; font-weight: 900; color: #F2F5F9;")
        lay.addWidget(self.scan_title)

        self.scan_status = QLabel()
        self.scan_status.setObjectName("PageSub")
        self.scan_status.setWordWrap(True)
        lay.addWidget(self.scan_status)

        bar = QProgressBar()
        bar.setRange(0, 0)  # indeterminate
        bar.setTextVisible(False)
        bar.setFixedHeight(4)
        lay.addWidget(bar)
        lay.addStretch(1)
        return page

    def _start_scan(self):
        self.scan_status.setText(
            "Detecting hardware, drivers and current configuration for this "
            "category \u2014 then validating every candidate tweak\u2026")
        self._worker = OptimizeWorker(
            self.optimizers, self.ctx, self,
            title=self.group_title, subtitle=self.group_subtitle)
        self._worker.done.connect(self._on_scanned)
        self._worker.error.connect(self._on_scan_error)
        self._worker.phase.connect(self.scan_status.setText)
        self._worker.start()

    def _on_scanned(self, report):
        self._report = report
        self._build_results(report)
        self.stack.setCurrentIndex(1)

    def _on_scan_error(self, msg):
        self.scan_status.setText(f"Scan failed: {msg}")
        self.scan_status.setStyleSheet(f"color: {T['danger']};")
        toast(f"Optimization scan failed \u2014 {msg}", "error", self)

    # ---------------- Phase 2: results ----------------

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(26, 22, 26, 20)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.res_title = QLabel()
        self.res_title.setStyleSheet(
            "font-size: 22px; font-weight: 900; color: #F2F5F9;")
        self.res_sub = QLabel()
        self.res_sub.setObjectName("PageSub")
        self.res_sub.setWordWrap(True)
        title_box.addWidget(self.res_title)
        title_box.addWidget(self.res_sub)
        head.addLayout(title_box, 1)
        self.res_count = QLabel()
        self.res_count.setObjectName("StatChip")
        head.addWidget(self.res_count, alignment=Qt.AlignTop)
        lay.addLayout(head)

        self.facts_box = None
        self.facts_lay = None

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self.results_lay = QVBoxLayout(inner)
        self.results_lay.setContentsMargins(0, 4, 6, 4)
        self.results_lay.setSpacing(6)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        note = QLabel(
            "\u2713  Every change below is verified against the live system "
            "after it is applied and can be reverted at any time from the "
            "Tweaks page.")
        note.setStyleSheet(
            f"color: {T['text_dim']}; font-size: 12px; padding-top: 2px;")
        note.setWordWrap(True)
        lay.addWidget(note)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_apply = QPushButton("Apply Selected")
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.setMinimumHeight(38)
        self.btn_apply.clicked.connect(self._start_apply)
        row.addWidget(self.btn_apply)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cancel.setMinimumHeight(38)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        row.addStretch()
        lay.addLayout(row)
        return page

    def _build_results(self, report):
        self.res_title.setText(report.title)
        self.res_sub.setText(report.subtitle)
        ready = len(report.ready())
        self.res_count.setText(
            f"<span style='color:{T['accent']}; font-size:15px; font-weight:800;'>"
            f"{ready}</span>"
            f"<span style='color:{T['text_dim']}; font-size:11px; font-weight:700;'>"
            f"&nbsp;&nbsp;RECOMMENDED</span>")

        self._checkboxes.clear()
        clear_layout(self.results_lay)
        facts = self._facts_card(report.detection_facts)
        if facts is not None:
            self.results_lay.addWidget(facts)
        for section_key, title, recs in report.grouped():
            self.results_lay.addWidget(self._section_label(title))
            for rec in recs:
                self.results_lay.addWidget(self._result_row(rec))
        self.results_lay.addStretch(1)
        self._update_apply_label()

    def _facts_card(self, facts):
        if not facts:
            return None
        box = QFrame()
        box.setObjectName("Card")
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        half = (len(facts) + 1) // 2
        for idx, (k, v) in enumerate(facts):
            kk = QLabel(str(k))
            kk.setObjectName("Tag")
            kk.setFixedWidth(150)
            vv = QLabel(str(v))
            vv.setWordWrap(True)
            vv.setStyleSheet("color: #C9D2DC; font-size: 12px; font-weight: 600;")
            r, c = divmod(idx, 2)
            grid.addWidget(kk, r, c * 2)
            grid.addWidget(vv, r, c * 2 + 1)
        return box

    def _section_label(self, text) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {T['text_dim']}; font-size: 11px; font-weight: 800;"
            "letter-spacing: 1.5px; padding-top: 8px;")
        return lbl

    def _result_row(self, rec) -> QFrame:
        row = QFrame()
        row.setObjectName("RecRow")
        lay = QVBoxLayout(row)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(10)
        marker, mcolor = MARK.get(rec.state, ("\u00b7", T["text_dim"]))
        box = QCheckBox()
        box.setObjectName("RecToggle")
        box.tweak_id = rec.tid
        box.setStyleSheet(
            "QCheckBox#RecToggle { spacing: 0px; }"
            "QCheckBox#RecToggle::indicator { width: 18px; height: 18px;"
            " border-radius: 5px; border: 1px solid #2A323D;"
            " background-color: #151A21; }"
            "QCheckBox#RecToggle::indicator:checked { background-color: #00F2FE;"
            " border-color: #00F2FE; }")
        if rec.selectable:
            box.setChecked(rec.default_checked)
            box.toggled.connect(self._update_apply_label)
            self._checkboxes.append(box)
        else:
            box.setEnabled(False)
            box.setVisible(False)
        head.addWidget(box, alignment=Qt.AlignTop)

        state_lbl = QLabel(f"<span style='color:{mcolor}; font-size:14px; "
                           f"font-weight:900;'>{marker}</span>")
        state_lbl.setFixedWidth(20)
        state_lbl.setAlignment(Qt.AlignCenter)
        head.addWidget(state_lbl, alignment=Qt.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(1)
        name = QLabel(rec.name)
        name.setStyleSheet("font-size: 13.5px; font-weight: 800; color: #F2F5F9;")
        text.addWidget(name)
        meta = QHBoxLayout()
        meta.setSpacing(6)
        tid = QLabel(rec.tid)
        tid.setStyleSheet(f"font-size: 10px; color: {T['text_faint']};")
        meta.addWidget(tid)
        ev = rec.evidence or rec.tweak.get("evidence", "UNKNOWN")
        meta.addWidget(self._mini_chip(EVIDENCE_LABEL.get(ev, ev)))
        impact = rec.tweak.get("impact", "low")
        meta.addWidget(self._mini_chip("Impact: " + impact.capitalize()))
        risk = rec.tweak.get("risk", "low")
        risk_color = {"safe": T["success"], "low": T["text_dim"],
                      "moderate": T["warning"], "advanced": T["danger"]}.get(
            risk, T["text_dim"])
        meta.addWidget(self._mini_chip("Risk: " + risk.capitalize(), risk_color))
        meta.addStretch()
        text.addLayout(meta)
        why = QLabel(rec.reason)
        why.setStyleSheet("color: #94A3B8; font-size: 11.5px;")
        why.setWordWrap(True)
        text.addWidget(why)
        head.addLayout(text, 1)
        lay.addLayout(head)
        return row

    def _mini_chip(self, text, color=None):
        lbl = QLabel(text)
        c = color or T["text_dim"]
        lbl.setStyleSheet(
            f"color: {c}; background-color: rgba(148, 163, 184, 0.08);"
            f"border: 1px solid rgba(148, 163, 184, 0.20); border-radius: 7px;"
            "padding: 1px 7px; font-size: 10px; font-weight: 600;")
        return lbl

    def _update_apply_label(self):
        if not hasattr(self, "btn_apply"):
            return
        n = sum(1 for cb in self._checkboxes if cb.isChecked())
        self.btn_apply.setText(f"Apply Selected ({n})")
        self.btn_apply.setEnabled(n > 0)

    # ---------------- Phase 3: apply ----------------

    def _build_apply_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 26, 28, 24)
        lay.setSpacing(14)

        title = QLabel("Applying Recommended Tweaks")
        title.setStyleSheet("font-size: 24px; font-weight: 900; color: #F2F5F9;")
        lay.addWidget(title)
        self.apply_status = QLabel("Starting\u2026")
        self.apply_status.setObjectName("PageSub")
        self.apply_status.setWordWrap(True)
        lay.addWidget(self.apply_status)

        self.apply_bar = QProgressBar()
        self.apply_bar.setRange(0, 1)
        self.apply_bar.setValue(0)
        self.apply_bar.setTextVisible(True)
        self.apply_bar.setFixedHeight(26)
        lay.addWidget(self.apply_bar)

        self.apply_log = QLabel()
        self.apply_log.setObjectName("RecFeedBox")
        self.apply_log.setWordWrap(True)
        lay.addWidget(self.apply_log, 1)
        return page

    def _start_apply(self):
        ids = [cb.tweak_id for cb in self._checkboxes if cb.isChecked()]
        if not ids:
            toast("Select at least one tweak to apply.", "warning", self)
            return
        self.stack.setCurrentIndex(2)
        self.apply_bar.setRange(0, len(ids))
        self.apply_bar.setValue(0)
        self.apply_status.setText(
            f"Applying {len(ids)} tweak(s) \u2014 each change is verified "
            "against the live system after it runs.")
        self._apply_worker = BatchWorker(ids, "apply", self)
        self._apply_worker.progress.connect(self._on_progress)
        self._apply_worker.batch_done.connect(self._on_apply_done)
        self._apply_worker.batch_error.connect(self._on_apply_error)
        self._apply_worker.start()

    def _on_progress(self, done, total, tid, ok, summary):
        self.apply_bar.setValue(done)
        color = T["success"] if ok else T["danger"]
        mark = "VERIFIED" if ok else "FAILED"
        self.apply_status.setText(f"({done}/{total}) {tid}")
        self.apply_log.setText(
            f"<span style='color:{color}; font-weight:800;'>{mark}</span>"
            f"  {tid}<br/>"
            f"<span style='color:{T['text_dim']};'>{summary}</span><br/>")

    def _on_apply_done(self, result):
        self._apply_worker = None
        results = result.get("results", {})
        applied = result.get("applied", [])
        failed = [tid for tid, (ok, _d) in results.items() if not ok]
        unverified = [
            tid for tid, (ok, _d) in results.items()
            if ok and tid not in applied]
        self.ctx.invalidate_state()
        self.ctx.force_audit_ids(list(results))
        self.ctx.note_state_change()
        self._show_done(applied, failed, unverified)

    def _on_apply_error(self, msg):
        self._show_done([], [f"apply error: {msg}"])

    # ---------------- Phase 4: done ----------------

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 26, 28, 24)
        lay.setSpacing(14)
        self.done_title = QLabel()
        self.done_title.setStyleSheet(
            "font-size: 24px; font-weight: 900; color: #F2F5F9;")
        self.done_body = QLabel()
        self.done_body.setWordWrap(True)
        self.done_body.setMinimumHeight(110)
        lay.addWidget(self.done_title)
        lay.addWidget(self.done_body)
        lay.addStretch(1)
        btn = QPushButton("Close")
        btn.setObjectName("Primary")
        btn.setMinimumHeight(38)
        btn.clicked.connect(self.accept)
        lay.addWidget(btn, alignment=Qt.AlignRight)
        return page

    def _show_done(self, applied, failed, unverified=()):
        self.stack.setCurrentIndex(3)
        self.done_title.setText(f"{self.group_title} \u2014 Complete")
        if failed or unverified:
            parts = [
                f"{len(applied)} tweak(s) applied and verified"]
            if unverified:
                parts.append(
                    f"{len(unverified)} applied but could not be verified "
                    "against the live system")
            parts.append(
                f"{len(failed)} failed or were blocked")
            self.done_body.setText(
                ". ".join(parts) + ". Re-run the scan or open the Tweaks "
                "page to adjust them individually.")
            self.done_body.setStyleSheet(
                f"color: {T['warning']}; font-size: 14px; font-weight: 600;")
        else:
            self.done_body.setText(
                f"All {len(applied)} selected tweak(s) were applied and verified "
                "against the live system. They are fully revertable \u2014 open "
                "this category and flip any toggle off, or use Revert All.")
            self.done_body.setStyleSheet(
                f"color: {T['success']}; font-size: 14px; font-weight: 600;")
        toast(f"{self.group_title} \u2014 {len(applied)} applied, verified.",
              "success", self)

    def closeEvent(self, event):
        for w in (self._worker, self._apply_worker):
            if w is not None and w.isRunning():
                w.terminate()
                w.wait(2000)
        super().closeEvent(event)
