"""Delay Destroyer — cinematic 17-stage diagnostic experience.

Phases: Landing -> Scan -> Results -> Apply -> Complete
"""
from __future__ import annotations

import math
from PySide6.QtCore import (
    QThread, Qt, QTimer, Signal, QPropertyAnimation,
    QEasingCurve, QPoint, QRect, Property,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QFont, QPen, QBrush
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget, QGraphicsOpacityEffect,
)

from pathlib import Path
from config.app_config import THEME as T, DIRS
from engine.delay_destroyer.risk import Risk, risk_label, risk_color

_ASSETS = DIRS["assets"]


def _alpha(hex_color: str, opacity: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{opacity})"


# ── Worker thread ───────────────────────────────────────────────────

class _Worker(QThread):
    progress = Signal(str, str, int, int)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            from engine.delay_destroyer.engine import DelayDestroyer
            dd = DelayDestroyer()
            dd.set_progress_callback(
                lambda ph, det, pct, idx: self.progress.emit(ph, det, pct, idx))
            result = dd.run()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class _ApplyWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, result, fixes, parent=None):
        super().__init__(parent)
        self._result = result
        self._fixes = fixes

    def run(self):
        try:
            from engine.delay_destroyer.engine import DelayDestroyer
            dd = DelayDestroyer()
            r = dd.run_apply(self._result, self._fixes)
            self.finished.emit(r)
        except Exception as e:
            self.error.emit(str(e))


# ── Styles ──────────────────────────────────────────────────────────

def _style(kind: str) -> str:
    base = "font-family:'Segoe UI',sans-serif;"
    if kind == "title":
        return (f"{base}font-size:28px;font-weight:900;color:{T['text']};"
                f"letter-spacing:5px;")
    if kind == "subtitle":
        return (f"{base}font-size:13px;color:{T['text_dim']};"
                f"line-height:1.6;letter-spacing:1px;")
    if kind == "stage_num":
        return (f"{base}font-size:10px;font-weight:700;color:{T['text_faint']};"
                f"letter-spacing:2px;min-width:20px;")
    if kind == "stage_name":
        return (f"{base}font-size:10px;font-weight:600;color:{T['text_faint']};"
                f"letter-spacing:1.5px;")
    if kind == "stage_desc":
        return (f"{base}font-size:10px;color:{T['text_faint']};")
    if kind == "stage_active":
        return (f"{base}font-size:10px;font-weight:700;color:{T['accent']};"
                f"letter-spacing:1.5px;")
    if kind == "stage_done":
        return (f"{base}font-size:10px;font-weight:600;color:{T['text_dim']};"
                f"letter-spacing:1.5px;")
    if kind == "section_title":
        return (f"{base}font-size:16px;font-weight:800;color:{T['text']};"
                f"letter-spacing:2px;")
    if kind == "finding_title":
        return (f"{base}font-size:13px;font-weight:700;color:{T['text']};")
    if kind == "finding_desc":
        return (f"{base}font-size:12px;color:{T['text_dim']};line-height:1.5;")
    if kind == "evidence":
        return (f"{base}font-size:11px;color:{T['text_faint']};"
                f"letter-spacing:0.5px;")
    if kind == "big_num":
        return (f"{base}font-size:48px;font-weight:900;color:{T['accent']};"
                f"letter-spacing:2px;")
    return ""


# ── Main page widget ────────────────────────────────────────────────

class DelayDestroyerPage(QWidget):

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._worker = None
        self._apply_worker = None
        self._result = None
        self._selected_fixes = set()
        self._stage_rows: dict[str, tuple] = {}
        self._scan_idx = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._root = root
        self._build_landing()

    # ── Helpers ─────────────────────────────────────────────────────

    def _clear(self):
        self._stage_rows.clear()
        self._clear_layout(self._root)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            sub = item.layout()
            if sub is not None:
                self._clear_layout(sub)
                sub.deleteLater()

    def _make_label(self, text, style, align=Qt.AlignCenter, wrap=False):
        w = QLabel(text)
        w.setStyleSheet(style)
        w.setAlignment(align)
        if wrap:
            w.setWordWrap(True)
        return w

    def _hline(self):
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"background:{T['border_soft']};max-height:1px;")
        return f

    # ── LANDING ─────────────────────────────────────────────────────

    def _build_landing(self):
        self._clear()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                             "QScrollArea>QWidget>QWidget{background:transparent;}")
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(40, 32, 40, 32)
        lay.setSpacing(0)

        lay.addSpacing(40)
        lay.addWidget(self._make_label("DELAY DESTROYER", _style("title")))
        lay.addSpacing(8)
        lay.addWidget(self._make_label(
            "17-STAGE DELAY INVESTIGATION ENGINE", _style("stage_active")))
        lay.addSpacing(16)
        lay.addWidget(self._make_label(
            "A focused delay investigation engine that measures what is actually "
            "happening on your system — DPC/ISR latency, input delay, driver "
            "stability, memory pressure, storage bottlenecks, power management, "
            "and background contention.\n\n"
            "Every finding includes measured evidence. Nothing is modified "
            "without your review and explicit approval.",
            _style("subtitle"), wrap=True))
        lay.addSpacing(32)

        # 17-stage overview grid
        from engine.delay_destroyer.engine import SCAN_STAGES
        grid = QHBoxLayout()
        grid.setSpacing(6)
        col1 = QVBoxLayout()
        col1.setSpacing(3)
        col2 = QVBoxLayout()
        col2.setSpacing(3)
        col3 = QVBoxLayout()
        col3.setSpacing(3)
        for i, s in enumerate(SCAN_STAGES):
            lbl = QLabel(f"{s['num']}  {s['name']}")
            lbl.setStyleSheet(
                f"{_style('stage_num')}letter-spacing:1px;")
            if i < 6:
                col1.addWidget(lbl)
            elif i < 12:
                col2.addWidget(lbl)
            else:
                col3.addWidget(lbl)
        grid.addLayout(col1, 1)
        grid.addLayout(col2, 1)
        grid.addLayout(col3, 1)
        lay.addLayout(grid)
        lay.addSpacing(40)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.setAlignment(Qt.AlignCenter)

        btn = QPushButton("INVESTIGATE DELAY")
        btn.setObjectName("Primary")
        btn.setFixedWidth(220)
        btn.setFixedHeight(46)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self._start(True))
        btn_row.addWidget(btn)

        btn2 = QPushButton("DIAGNOSE ONLY")
        btn2.setFixedWidth(160)
        btn2.setFixedHeight(46)
        btn2.setCursor(Qt.PointingHandCursor)
        btn2.clicked.connect(lambda: self._start(False))
        btn_row.addWidget(btn2)
        lay.addLayout(btn_row)

        lay.addSpacing(12)
        lay.addWidget(self._make_label(
            "Investigate Delay = find and fix delay sources.  Diagnose Only = no changes.",
            _style("stage_desc")))
        lay.addStretch()
        scroll.setWidget(body)
        self._root.addWidget(scroll, 1)

    # ── SCAN ────────────────────────────────────────────────────────

    def _start(self, apply_fixes):
        self._apply_mode = apply_fixes
        self._build_scan_ui()
        self._worker = _Worker(self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _build_scan_ui(self):
        self._clear()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                             "QScrollArea>QWidget>QWidget{background:transparent;}")
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(40, 24, 40, 24)
        lay.setSpacing(0)

        lay.addWidget(self._make_label("DELAY DESTROYER", _style("title")))
        lay.addSpacing(6)

        self._status_label = self._make_label(
            "Initializing delay investigation...", _style("stage_active"))
        lay.addWidget(self._status_label)
        lay.addSpacing(20)

        # Stage list — 3 columns for 17 stages
        from engine.delay_destroyer.engine import SCAN_STAGES

        cols_layout = QHBoxLayout()
        cols_layout.setSpacing(24)

        # Split stages into 3 columns
        col_size = (len(SCAN_STAGES) + 2) // 3
        for col_idx in range(3):
            col_lay = QVBoxLayout()
            col_lay.setSpacing(2)
            col_lay.setContentsMargins(0, 0, 0, 0)
            start = col_idx * col_size
            end = min(start + col_size, len(SCAN_STAGES))
            for i in range(start, end):
                s = SCAN_STAGES[i]
                row = QHBoxLayout()
                row.setSpacing(6)

                num = QLabel(s["num"])
                num.setStyleSheet(_style("stage_num"))
                num.setFixedWidth(20)
                num.setAlignment(Qt.AlignTop | Qt.AlignRight)

                dot = QLabel("\u25cf")
                dot.setStyleSheet(f"font-size:7px;color:{T['text_faint']};")
                dot.setFixedWidth(10)
                dot.setAlignment(Qt.AlignTop | Qt.AlignCenter)

                name = QLabel(s["name"])
                name.setStyleSheet(_style("stage_name"))

                row.addWidget(num)
                row.addWidget(dot)
                row.addWidget(name, 1)
                col_lay.addLayout(row)
                self._stage_rows[s["id"]] = (num, dot, name, row)

            cols_layout.addLayout(col_lay, 1)
        lay.addLayout(cols_layout)
        lay.addSpacing(16)

        # Progress bar
        self._progress_bar = QWidget()
        self._progress_bar.setFixedHeight(3)
        self._progress_bar.setStyleSheet(
            f"background:{T['border_soft']};border-radius:1px;")
        self._progress_fill = QWidget(self._progress_bar)
        self._progress_fill.setStyleSheet(
            f"background:{T['accent']};border-radius:1px;")
        self._progress_fill.setGeometry(0, 0, 0, 3)
        lay.addWidget(self._progress_bar)

        lay.addStretch()
        scroll.setWidget(body)
        self._root.addWidget(scroll, 1)

    def _on_progress(self, stage_id, detail, pct, stage_idx):
        self._scan_idx = stage_idx
        self._status_label.setText(detail)

        bar_w = self._progress_bar.width()
        fill_w = int(bar_w * min(pct, 100) / 100)
        self._progress_fill.setGeometry(0, 0, fill_w, 3)

        from engine.delay_destroyer.engine import SCAN_STAGES
        for i, s in enumerate(SCAN_STAGES):
            rows = self._stage_rows.get(s["id"])
            if not rows:
                continue
            num, dot, name, _ = rows
            if i < stage_idx:
                dot.setText("\u2713")
                dot.setStyleSheet(f"font-size:10px;color:{T['green']};")
                name.setStyleSheet(_style("stage_done"))
            elif i == stage_idx:
                dot.setStyleSheet(f"font-size:7px;color:{T['accent']};")
                name.setStyleSheet(_style("stage_active"))
            else:
                dot.setText("\u25cf")
                dot.setStyleSheet(f"font-size:7px;color:{T['text_faint']};")
                name.setStyleSheet(_style("stage_name"))

    def _on_finished(self, result):
        self._result = result
        if not result or not result.report:
            self._build_error("Scan completed with no results.")
            return
        self._build_results()

    def _on_error(self, msg):
        self._build_error(f"Analysis failed: {msg}")

    # ── ERROR ───────────────────────────────────────────────────────

    def _build_error(self, msg):
        self._clear()
        lay = QVBoxLayout()
        lay.setContentsMargins(40, 60, 40, 60)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._make_label("ERROR", _style("title")))
        lay.addSpacing(16)
        lay.addWidget(self._make_label(msg, _style("finding_desc"), wrap=True))
        lay.addSpacing(24)
        btn = QPushButton("GO BACK")
        btn.setFixedWidth(160)
        btn.setFixedHeight(40)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self._build_landing)
        lay.addWidget(btn, alignment=Qt.AlignCenter)
        lay.addStretch()
        self._root.addLayout(lay)

    # ── RESULTS ─────────────────────────────────────────────────────

    def _build_results(self):
        self._clear()
        r = self._result
        report = r.report

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                             "QScrollArea>QWidget>QWidget{background:transparent;}")
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(40, 24, 40, 24)
        lay.setSpacing(0)

        # Header
        lay.addWidget(self._make_label("DELAY INVESTIGATION COMPLETE", _style("title")))
        lay.addSpacing(4)
        lay.addWidget(self._make_label(report.summary_text, _style("subtitle")))
        lay.addSpacing(20)

        # System Summary
        self._render_section(lay, report.system_summary)

        lay.addSpacing(8)
        lay.addWidget(self._hline())
        lay.addSpacing(8)

        # Findings
        self._render_section(lay, report.findings_section)

        # Correlations
        if report.correlation_section:
            lay.addSpacing(8)
            lay.addWidget(self._hline())
            lay.addSpacing(8)
            self._render_section(lay, report.correlation_section)

        # Selectable fixes
        if r.fixes_selected:
            lay.addSpacing(16)
            lay.addWidget(self._make_label(
                "DELAY SOURCES IDENTIFIED", _style("section_title")))
            lay.addSpacing(4)
            lay.addWidget(self._make_label(
                "The following delay sources were identified. "
                "Nothing will be changed until you confirm.",
                _style("subtitle"), wrap=True))
            lay.addSpacing(12)

            self._fix_rows = []
            for fix in r.fixes_selected:
                self._render_fix_item(lay, fix)

            lay.addSpacing(20)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(12)
            btn_row.setAlignment(Qt.AlignCenter)

            again = QPushButton("INVESTIGATE AGAIN")
            again.setFixedWidth(160)
            again.setFixedHeight(44)
            again.setCursor(Qt.PointingHandCursor)
            again.clicked.connect(self._build_landing)
            btn_row.addWidget(again)

            apply_btn = QPushButton("APPLY SELECTED FIXES")
            apply_btn.setObjectName("Primary")
            apply_btn.setFixedWidth(240)
            apply_btn.setFixedHeight(44)
            apply_btn.setCursor(Qt.PointingHandCursor)
            apply_btn.clicked.connect(self._show_apply_dialog)
            btn_row.addWidget(apply_btn)
            lay.addLayout(btn_row)
        else:
            lay.addSpacing(16)
            lay.addWidget(self._make_label(
                "No significant delay sources detected. Your system appears responsive.",
                _style("subtitle"), wrap=True))
            lay.addSpacing(12)
            btn = QPushButton("INVESTIGATE AGAIN")
            btn.setFixedWidth(160)
            btn.setFixedHeight(44)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(self._build_landing)
            lay.addWidget(btn, alignment=Qt.AlignCenter)

        lay.addSpacing(32)
        scroll.setWidget(body)
        self._root.addWidget(scroll, 1)

    def _render_section(self, lay, section):
        if not section:
            return
        lay.addWidget(self._make_label(
            f"{section.icon}  {section.title}", _style("section_title")))
        lay.addSpacing(8)
        for item in section.items:
            self._render_item(lay, item)

    def _render_item(self, lay, item):
        row = QHBoxLayout()
        row.setSpacing(10)

        icon = QLabel()
        icon.setFixedSize(8, 8)
        status_col = T["accent"]
        if item.status == "info":
            status_col = T["text_faint"]
        elif item.status == "applied":
            status_col = T["green"]
        elif item.status == "failed":
            status_col = T["danger"]
        elif item.status == "warning":
            status_col = T["amber"]
        icon.setStyleSheet(
            f"background:{status_col};border-radius:4px;")

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title = QLabel(item.title)
        title.setStyleSheet(_style("finding_title"))
        desc = QLabel(item.description)
        desc.setStyleSheet(_style("finding_desc"))
        desc.setWordWrap(True)
        text_col.addWidget(title)
        text_col.addWidget(desc)

        if item.evidence:
            ev = QLabel(item.evidence)
            ev.setStyleSheet(_style("evidence"))
            ev.setWordWrap(True)
            text_col.addWidget(ev)

        row.addWidget(icon, 0, Qt.AlignTop)
        row.addLayout(text_col, 1)
        lay.addLayout(row)
        lay.addSpacing(6)

    def _render_fix_item(self, lay, fix):
        row = QHBoxLayout()
        row.setSpacing(10)

        cb = QCheckBox()
        cb.setChecked(True)
        cb.setStyleSheet(
            f"QCheckBox::indicator{{width:18px;height:18px;"
            f"border:2px solid {T['border']};border-radius:4px;"
            f"background:transparent;}}"
            f"QCheckBox::indicator:checked{{background:{T['accent']};"
            f"border-color:{T['accent']};}}"
        )
        cb.stateChanged.connect(lambda state, fid=fix.id:
                                self._toggle_fix(fid, state))
        self._selected_fixes.add(fix.id)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel(fix.title)
        title.setStyleSheet(_style("finding_title"))
        risk_badge = QLabel(risk_label(fix.risk))
        risk_badge.setStyleSheet(
            f"font-size:10px;font-weight:600;color:{risk_color(fix.risk)};"
            f"background:{_alpha(risk_color(fix.risk), 0.12)};"
            f"padding:2px 8px;border-radius:4px;letter-spacing:1px;")
        title_row.addWidget(title)
        title_row.addWidget(risk_badge)
        title_row.addStretch()
        text_col.addLayout(title_row)

        why = QLabel(fix.why)
        why.setStyleSheet(_style("finding_desc"))
        why.setWordWrap(True)
        text_col.addWidget(why)

        effect = QLabel(f"Expected: {fix.expected_effect}")
        effect.setStyleSheet(_style("evidence"))
        effect.setWordWrap(True)
        text_col.addWidget(effect)

        row.addWidget(cb, 0, Qt.AlignTop)
        row.addLayout(text_col, 1)
        lay.addLayout(row)
        lay.addSpacing(8)

    def _toggle_fix(self, fix_id, state):
        if state == Qt.Checked:
            self._selected_fixes.add(fix_id)
        else:
            self._selected_fixes.discard(fix_id)

    # ── APPLY DIALOG ────────────────────────────────────────────────

    def _show_apply_dialog(self):
        if not self._selected_fixes:
            return
        self._overlay = QWidget(self)
        self._overlay.setGeometry(self.rect())
        self._overlay.setStyleSheet(
            f"background:{_alpha('#000000', 0.7)};")
        self._overlay.show()
        self._overlay.raise_()

        dialog = QWidget(self._overlay)
        dialog.setFixedSize(480, 400)
        dialog.setStyleSheet(
            f"background:{T['card']};border:1px solid {T['border']};"
            f"border-radius:12px;")
        dialog.move(
            (self.width() - 480) // 2,
            (self.height() - 400) // 2,
        )
        dialog.show()

        dlay = QVBoxLayout(dialog)
        dlay.setContentsMargins(32, 28, 32, 24)
        dlay.setSpacing(0)

        dlay.addWidget(self._make_label(
            "READY TO APPLY FIXES", _style("title")))
        dlay.addSpacing(8)
        dlay.addWidget(self._make_label(
            f"{len(self._selected_fixes)} delay fixes will be applied to your system.\n"
            f"A backup will be created before any changes.",
            _style("subtitle"), wrap=True))
        dlay.addSpacing(16)

        for fix in self._result.fixes_selected:
            if fix.id in self._selected_fixes:
                dlay.addWidget(self._make_label(
                    f"\u2022  {fix.title}", _style("finding_desc")))
        dlay.addSpacing(20)
        dlay.addWidget(self._hline())
        dlay.addSpacing(16)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.setAlignment(Qt.AlignCenter)

        cancel = QPushButton("CANCEL")
        cancel.setFixedWidth(140)
        cancel.setFixedHeight(42)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self._hide_apply_dialog)
        btn_row.addWidget(cancel)

        apply_btn = QPushButton("APPLY CHANGES")
        apply_btn.setObjectName("Primary")
        apply_btn.setFixedWidth(180)
        apply_btn.setFixedHeight(42)
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.clicked.connect(self._apply_fixes)
        btn_row.addWidget(apply_btn)
        dlay.addLayout(btn_row)
        dlay.addStretch()

    def _hide_apply_dialog(self):
        if hasattr(self, "_overlay") and self._overlay:
            self._overlay.deleteLater()
            self._overlay = None

    # ── APPLYING ────────────────────────────────────────────────────

    def _apply_fixes(self):
        self._hide_apply_dialog()
        self._clear()

        lay = QVBoxLayout()
        lay.setContentsMargins(40, 60, 40, 60)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._make_label(
            "APPLYING DELAY FIXES", _style("title")))
        lay.addSpacing(8)
        self._apply_status = self._make_label(
            "Creating backup and applying delay fixes...",
            _style("subtitle"))
        lay.addWidget(self._apply_status)
        lay.addSpacing(20)

        fixes_to_apply = [f for f in self._result.fixes_selected
                          if f.id in self._selected_fixes]
        self._apply_worker = _ApplyWorker(self._result, fixes_to_apply, self)
        self._apply_worker.finished.connect(self._on_apply_done)
        self._apply_worker.error.connect(self._on_apply_error)
        self._apply_worker.start()
        lay.addStretch()
        self._root.addLayout(lay)

    def _on_apply_done(self, result):
        self._result = result
        self._build_complete()

    def _on_apply_error(self, msg):
        self._build_error(f"Apply failed: {msg}")

    # ── COMPLETE ────────────────────────────────────────────────────

    def _build_complete(self):
        self._clear()
        r = self._result
        plan = r.plan

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                             "QScrollArea>QWidget>QWidget{background:transparent;}")
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(40, 24, 40, 24)
        lay.setSpacing(0)

        if plan and plan.applied > 0:
            title = "DELAY FIXES APPLIED"
        elif plan and plan.failed > 0:
            title = "PARTIAL SUCCESS"
        else:
            title = "INVESTIGATION COMPLETE"

        lay.addWidget(self._make_label(title, _style("title")))
        lay.addSpacing(4)
        lay.addWidget(self._make_label(
            r.report.summary_text if r.report else "Done.",
            _style("subtitle"), wrap=True))
        lay.addSpacing(20)

        if plan and plan.results:
            lay.addWidget(self._make_label(
                "DELAY FIXES APPLIED", _style("section_title")))
            lay.addSpacing(8)
            for fr in plan.results:
                status_color = T["green"] if fr.success else (
                    T["amber"] if fr.rolled_back else T["danger"])
                status_text = "Applied" if fr.success else (
                    "Rolled back" if fr.rolled_back else "Failed")
                row = self._make_label(
                    f"\u2022  {fr.title} -- {status_text}",
                    _style("finding_desc"))
                row.setStyleSheet(
                    _style("finding_desc").replace(T["text_dim"], status_color))
                lay.addWidget(row)
            lay.addSpacing(16)

        if r.report:
            if r.report.system_summary:
                self._render_section(lay, r.report.system_summary)
            if r.report.baseline_section:
                lay.addSpacing(8)
                self._render_section(lay, r.report.baseline_section)

        lay.addSpacing(20)
        btn = QPushButton("INVESTIGATE AGAIN")
        btn.setFixedWidth(160)
        btn.setFixedHeight(44)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self._build_landing)
        lay.addWidget(btn, alignment=Qt.AlignCenter)
        lay.addSpacing(32)

        scroll.setWidget(body)
        self._root.addWidget(scroll, 1)

    # ── Resize ──────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_overlay") and self._overlay:
            self._overlay.setGeometry(self.rect())
