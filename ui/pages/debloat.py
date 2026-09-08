"""Smart Debloater — application-focused, dependency-aware, user-controlled.

Phases: Landing -> Scan -> Results -> Apply -> Complete
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from config.app_config import THEME as T


def _alpha(hex_color: str, opacity: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{opacity})"


# ── Worker threads ───────────────────────────────────────────────────

class _ScanWorker(QThread):
    progress = Signal(str, int)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            from engine.debloat.engine import DebloatEngine
            engine = DebloatEngine()
            result = engine.scan(
                progress_callback=lambda msg, pct: self.progress.emit(msg, pct))
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class _ApplyWorker(QThread):
    finished = Signal(bool, list)
    error = Signal(str)

    def __init__(self, engine, items, os_info, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._items = items
        self._os_info = os_info

    def run(self):
        try:
            ok, errors = self._engine.apply(
                self._items, self._os_info,
                progress_callback=lambda msg, pct: None)
            self.finished.emit(ok, errors)
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
    if kind == "stage_active":
        return (f"{base}font-size:10px;font-weight:700;color:{T['accent']};"
                f"letter-spacing:1.5px;")
    if kind == "stage_done":
        return (f"{base}font-size:10px;font-weight:600;color:{T['text_dim']};"
                f"letter-spacing:1.5px;")
    if kind == "section_title":
        return (f"{base}font-size:16px;font-weight:800;color:{T['text']};"
                f"letter-spacing:2px;")
    if kind == "group_title":
        return (f"{base}font-size:14px;font-weight:700;color:{T['text']};"
                f"letter-spacing:1px;")
    if kind == "item_title":
        return (f"{base}font-size:13px;font-weight:700;color:{T['text']};")
    if kind == "item_desc":
        return (f"{base}font-size:12px;color:{T['text_dim']};line-height:1.5;")
    if kind == "item_detail":
        return (f"{base}font-size:11px;color:{T['text_faint']};"
                f"letter-spacing:0.5px;")
    if kind == "stat_num":
        return (f"{base}font-size:32px;font-weight:900;color:{T['accent']};"
                f"letter-spacing:2px;")
    if kind == "stat_label":
        return (f"{base}font-size:10px;font-weight:600;color:{T['text_faint']};"
                f"letter-spacing:1.5px;")
    if kind == "cat_count":
        return (f"{base}font-size:11px;color:{T['accent']};"
                f"letter-spacing:1px;font-weight:700;")
    return ""


# Scan stages
_SCAN_STAGES = [
    ("os", "Detecting Windows installation"),
    ("appx", "Scanning Microsoft Store apps"),
    ("third_party", "Scanning third-party applications"),
    ("oem", "Scanning OEM software"),
    ("services", "Scanning optional services"),
    ("tasks", "Scanning scheduled tasks"),
    ("startup", "Scanning startup entries"),
    ("dependencies", "Detecting dependencies & hardware"),
    ("protection", "Applying protection rules"),
]


# ── Main page widget ────────────────────────────────────────────────

class DebloatPage(QWidget):

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._worker = None
        self._apply_worker = None
        self._engine = None
        self._result = None
        self._selected_items: set[str] = set()
        self._item_widgets: dict[str, QCheckBox] = {}
        self._group_containers: dict[str, QWidget] = {}
        self._group_collapsed: dict[str, bool] = {}
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
        self._item_widgets.clear()
        self._group_containers.clear()
        self._group_collapsed.clear()
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
        lay.addWidget(self._make_label("SMART DEBLOATER", _style("title")))
        lay.addSpacing(8)
        lay.addWidget(self._make_label(
            "APPLICATION-FOCUSED  \u00b7  DEPENDENCY-AWARE  \u00b7  USER-CONTROLLED",
            _style("stage_active")))
        lay.addSpacing(16)
        lay.addWidget(self._make_label(
            "Scans your actual PC for genuinely unnecessary applications.\n"
            "Checks whether anything depends on them before recommending removal.\n"
            "Only recommends removing things that are genuinely safe to remove.\n\n"
            "Components required by Windows, drivers, games, or your installed\n"
            "applications are automatically protected.",
            _style("subtitle"), wrap=True))
        lay.addSpacing(32)

        # Scan stages overview — centered two-column grid
        outer_grid = QHBoxLayout()
        outer_grid.setContentsMargins(0, 0, 0, 0)
        outer_grid.setSpacing(0)
        outer_grid.setAlignment(Qt.AlignCenter)
        grid = QHBoxLayout()
        grid.setSpacing(32)
        grid.setAlignment(Qt.AlignCenter)
        for col_idx in range(2):
            col = QVBoxLayout()
            col.setSpacing(3)
            start = col_idx * 5
            end = min(start + 5, len(_SCAN_STAGES))
            for i in range(start, end):
                sid, sname = _SCAN_STAGES[i]
                lbl = QLabel(f"0{i+1}  {sname}")
                lbl.setStyleSheet(f"{_style('stage_num')}letter-spacing:1px;")
                col.addWidget(lbl)
            grid.addLayout(col)
        outer_grid.addLayout(grid)
        lay.addLayout(outer_grid)
        lay.addSpacing(40)

        btn = QPushButton("SCAN SYSTEM")
        btn.setObjectName("Primary")
        btn.setFixedWidth(220)
        btn.setFixedHeight(46)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self._start_scan)
        lay.addWidget(btn, alignment=Qt.AlignCenter)

        lay.addStretch()
        scroll.setWidget(body)
        self._root.addWidget(scroll, 1)

    # ── SCAN ────────────────────────────────────────────────────────

    def _start_scan(self):
        self._build_scan_ui()
        self._worker = _ScanWorker(self)
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

        lay.addWidget(self._make_label("SMART DEBLOATER", _style("title")))
        lay.addSpacing(6)

        self._status_label = self._make_label(
            "Scanning Windows installation...", _style("stage_active"))
        lay.addWidget(self._status_label)
        lay.addSpacing(20)

        # Stage list — centered two-column grid
        cols_layout = QHBoxLayout()
        cols_layout.setSpacing(24)
        cols_layout.setAlignment(Qt.AlignCenter)
        col_size = (len(_SCAN_STAGES) + 1) // 2
        for col_idx in range(2):
            outer = QHBoxLayout()
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)
            outer.addStretch(1)
            col_lay = QVBoxLayout()
            col_lay.setSpacing(2)
            col_lay.setContentsMargins(0, 0, 0, 0)
            start = col_idx * col_size
            end = min(start + col_size, len(_SCAN_STAGES))
            for i in range(start, end):
                sid, sname = _SCAN_STAGES[i]
                row = QHBoxLayout()
                row.setSpacing(6)

                num = QLabel(f"0{i+1}")
                num.setStyleSheet(_style("stage_num"))
                num.setFixedWidth(20)
                num.setAlignment(Qt.AlignTop | Qt.AlignRight)

                dot = QLabel("\u25cf")
                dot.setStyleSheet(f"font-size:7px;color:{T['text_faint']};")
                dot.setFixedWidth(10)
                dot.setAlignment(Qt.AlignTop | Qt.AlignCenter)

                name = QLabel(sname)
                name.setStyleSheet(_style("stage_name"))

                row.addWidget(num)
                row.addWidget(dot)
                row.addWidget(name, 1)
                col_lay.addLayout(row)
                self._stage_rows[sid] = (num, dot, name, row)

            outer.addLayout(col_lay)
            outer.addStretch(1)
            cols_layout.addLayout(outer, 1)
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

    def _on_progress(self, msg, pct):
        self._status_label.setText(msg)

        bar_w = self._progress_bar.width()
        fill_w = int(bar_w * min(pct, 100) / 100)
        self._progress_fill.setGeometry(0, 0, fill_w, 3)

        for i, (sid, sname) in enumerate(_SCAN_STAGES):
            rows = self._stage_rows.get(sid)
            if not rows:
                continue
            num, dot, name, _ = rows
            if i < self._scan_idx:
                dot.setText("\u2713")
                dot.setStyleSheet(f"font-size:10px;color:{T['green']};")
                name.setStyleSheet(_style("stage_done"))
            elif i == self._scan_idx:
                dot.setStyleSheet(f"font-size:7px;color:{T['accent']};")
                name.setStyleSheet(_style("stage_active"))
            else:
                dot.setText("\u25cf")
                dot.setStyleSheet(f"font-size:7px;color:{T['text_faint']};")
                name.setStyleSheet(_style("stage_name"))

        new_idx = min(int(pct / (100 / len(_SCAN_STAGES))), len(_SCAN_STAGES) - 1)
        if new_idx > self._scan_idx:
            self._scan_idx = new_idx

    def _on_finished(self, result):
        self._result = result
        self._engine = result
        if not result or not result.items:
            self._build_error("Scan completed with no unnecessary applications found.")
            return
        self._build_results()

    def _on_error(self, msg):
        self._build_error(f"Scan failed: {msg}")

    # ── ERROR ───────────────────────────────────────────────────────

    def _build_error(self, msg):
        self._clear()
        lay = QVBoxLayout()
        lay.setContentsMargins(40, 60, 40, 60)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._make_label("ERROR", _style("title")))
        lay.addSpacing(16)
        lay.addWidget(self._make_label(msg, _style("item_desc"), wrap=True))
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
        os_info = r.os_info
        groups = r.groups

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
        lay.addWidget(self._make_label("SCAN COMPLETE", _style("title")))
        lay.addSpacing(4)

        os_text = (f"{os_info.product_name}  \u00b7  Build {os_info.build}  \u00b7  "
                   f"{os_info.architecture}  \u00b7  {os_info.edition}")
        lay.addWidget(self._make_label(os_text, _style("subtitle")))
        lay.addSpacing(16)

        # Stats row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(32)
        stats_row.setAlignment(Qt.AlignCenter)

        # Gaming PC badge
        if r.is_gaming_pc:
            badge = QLabel("\u2605  GAMING PC DETECTED")
            badge.setStyleSheet(
                f"font-size:11px;font-weight:700;color:{T['green']};"
                f"background:{_alpha(T['green'], 0.12)};"
                f"padding:6px 16px;border-radius:6px;letter-spacing:1px;")
            stats_row.addWidget(badge)

        # Protected count
        prot_col = QVBoxLayout()
        prot_col.setSpacing(0)
        prot_num = QLabel(str(r.total_protected))
        prot_num.setStyleSheet(_style("stat_num"))
        prot_num.setAlignment(Qt.AlignCenter)
        prot_lbl = QLabel("PROTECTED")
        prot_lbl.setStyleSheet(_style("stat_label"))
        prot_lbl.setAlignment(Qt.AlignCenter)
        prot_col.addWidget(prot_num)
        prot_col.addWidget(prot_lbl)
        stats_row.addLayout(prot_col)

        # Debloatable count
        deb_col = QVBoxLayout()
        deb_col.setSpacing(0)
        deb_num = QLabel(str(r.total_debloatable))
        deb_num.setStyleSheet(_style("stat_num"))
        deb_num.setAlignment(Qt.AlignCenter)
        deb_lbl = QLabel("DEBLOATABLE")
        deb_lbl.setStyleSheet(_style("stat_label"))
        deb_lbl.setAlignment(Qt.AlignCenter)
        deb_col.addWidget(deb_num)
        deb_col.addWidget(deb_lbl)
        stats_row.addLayout(deb_col)

        lay.addLayout(stats_row)
        lay.addSpacing(8)

        # Gaming software list
        if r.gaming_software:
            sw_list = ", ".join(r.gaming_software[:5])
            if len(r.gaming_software) > 5:
                sw_list += f" +{len(r.gaming_software) - 5} more"
            lay.addWidget(self._make_label(
                f"Gaming software detected: {sw_list}", _style("item_detail")))
        lay.addSpacing(16)

        lay.addWidget(self._hline())
        lay.addSpacing(12)

        # Explanation
        lay.addWidget(self._make_label(
            f"{r.total_protected} components were automatically protected because they are "
            f"required by Windows, drivers, games, or your installed applications.",
            _style("subtitle"), wrap=True))
        lay.addSpacing(8)
        lay.addWidget(self._make_label(
            f"The {r.total_debloatable} items below are genuinely optional. "
            f"Nothing will be changed until you confirm.",
            _style("subtitle"), wrap=True))
        lay.addSpacing(20)

        # Render each group
        group_order = sorted(groups.keys(), key=lambda g: (-len(groups[g]), g))

        for group_name in group_order:
            group_items = groups[group_name]
            if not group_items:
                continue
            self._render_group(lay, group_name, group_items)

        lay.addSpacing(20)
        lay.addWidget(self._hline())
        lay.addSpacing(16)

        # Bottom action bar
        self._count_label = self._make_label(
            "0 components selected", _style("subtitle"))
        lay.addWidget(self._count_label, alignment=Qt.AlignCenter)
        lay.addSpacing(12)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.setAlignment(Qt.AlignCenter)

        clear_btn = QPushButton("CLEAR ALL")
        clear_btn.setFixedWidth(130)
        clear_btn.setFixedHeight(42)
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_all)
        btn_row.addWidget(clear_btn)

        safe_btn = QPushButton("SELECT SAFE")
        safe_btn.setFixedWidth(140)
        safe_btn.setFixedHeight(42)
        safe_btn.setCursor(Qt.PointingHandCursor)
        safe_btn.clicked.connect(self._select_safe)
        btn_row.addWidget(safe_btn)

        all_btn = QPushButton("SELECT ALL")
        all_btn.setFixedWidth(130)
        all_btn.setFixedHeight(42)
        all_btn.setCursor(Qt.PointingHandCursor)
        all_btn.clicked.connect(self._select_all)
        btn_row.addWidget(all_btn)

        lay.addLayout(btn_row)
        lay.addSpacing(12)

        apply_row = QHBoxLayout()
        apply_row.setSpacing(12)
        apply_row.setAlignment(Qt.AlignCenter)

        again = QPushButton("RESCAN")
        again.setFixedWidth(130)
        again.setFixedHeight(44)
        again.setCursor(Qt.PointingHandCursor)
        again.clicked.connect(self._build_landing)
        apply_row.addWidget(again)

        apply_btn = QPushButton("APPLY SELECTED")
        apply_btn.setObjectName("Primary")
        apply_btn.setFixedWidth(200)
        apply_btn.setFixedHeight(44)
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.clicked.connect(self._show_apply_dialog)
        apply_row.addWidget(apply_btn)
        lay.addLayout(apply_row)

        lay.addSpacing(32)
        scroll.setWidget(body)
        self._root.addWidget(scroll, 1)

    def _render_group(self, lay, group_name, items):
        """Render a group header + items."""
        header = QHBoxLayout()
        header.setSpacing(8)

        toggle_btn = QPushButton(f"\u25be {group_name}")
        toggle_btn.setStyleSheet(
            f"{_style('group_title')}border:none;background:transparent;")
        toggle_btn.setCursor(Qt.PointingHandCursor)
        toggle_btn.clicked.connect(lambda _, g=group_name: self._toggle_group(g))
        header.addWidget(toggle_btn)

        count = QLabel(f"{len(items)} items")
        count.setStyleSheet(_style("cat_count"))
        header.addWidget(count)
        header.addStretch()
        lay.addLayout(header)

        container = QWidget()
        container_lay = QVBoxLayout(container)
        container_lay.setContentsMargins(0, 0, 0, 0)
        container_lay.setSpacing(4)

        for item in items:
            self._render_item(container_lay, item)

        lay.addWidget(container)
        self._group_containers[group_name] = container
        self._group_collapsed[group_name] = False
        lay.addSpacing(8)

    def _toggle_group(self, group_name):
        container = self._group_containers.get(group_name)
        if not container:
            return
        collapsed = not self._group_collapsed.get(group_name, False)
        self._group_collapsed[group_name] = collapsed
        container.setVisible(not collapsed)

    def _render_item(self, lay, item):
        """Render a single debloat item card."""
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{T['card']};border:1px solid {T['border_soft']};"
            f"border-radius:8px;padding:8px;}}"
            f"QFrame:hover{{border-color:{T['border']};}}")
        card_lay = QHBoxLayout(card)
        card_lay.setContentsMargins(12, 10, 12, 10)
        card_lay.setSpacing(10)

        # Checkbox
        cb = QCheckBox()
        cb.setChecked(False)
        cb.setStyleSheet(
            f"QCheckBox::indicator{{width:18px;height:18px;"
            f"border:2px solid {T['border']};border-radius:4px;"
            f"background:transparent;}}"
            f"QCheckBox::indicator:checked{{background:{T['accent']};"
            f"border-color:{T['accent']};}}"
        )
        cb.stateChanged.connect(lambda state, iid=item.id:
                                self._toggle_item(iid, state))
        self._item_widgets[item.id] = cb

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        # Title row with risk badge + confidence
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel(item.name)
        title.setStyleSheet(_style("item_title"))

        risk_color_map = {
            "SAFE": T["green"],
            "OPTIONAL": T["accent"],
            "CAUTION": T["amber"],
            "PROTECTED": T["danger"],
            "UNKNOWN": T["text_faint"],
        }
        risk_col = risk_color_map.get(item.risk.value, T["text_faint"])
        risk_badge = QLabel(item.risk.value)
        risk_badge.setStyleSheet(
            f"font-size:10px;font-weight:600;color:{risk_col};"
            f"background:{_alpha(risk_col, 0.12)};"
            f"padding:2px 8px;border-radius:4px;letter-spacing:1px;")

        # Confidence score
        if item.confidence > 0:
            conf_text = f"Confidence: {item.confidence}%"
            conf_badge = QLabel(conf_text)
            conf_badge.setStyleSheet(
                f"font-size:9px;font-weight:600;color:{T['text_faint']};"
                f"background:{_alpha(T['text_faint'], 0.10)};"
                f"padding:2px 6px;border-radius:3px;letter-spacing:0.5px;")
            title_row.addWidget(conf_badge)

        # Reversibility badge
        rev_text = "REVERSIBLE" if item.reversible else "NOT REVERSIBLE"
        rev_color = T["green"] if item.reversible else T["text_faint"]
        rev_badge = QLabel(rev_text)
        rev_badge.setStyleSheet(
            f"font-size:9px;font-weight:600;color:{rev_color};"
            f"background:{_alpha(rev_color, 0.10)};"
            f"padding:2px 6px;border-radius:3px;letter-spacing:0.5px;")

        title_row.addWidget(title)
        title_row.addWidget(risk_badge)
        title_row.addWidget(rev_badge)
        title_row.addStretch()
        text_col.addLayout(title_row)

        # Description
        desc = QLabel(item.description)
        desc.setStyleSheet(_style("item_desc"))
        desc.setWordWrap(True)
        text_col.addWidget(desc)

        # What happens
        what = QLabel(f"If removed: {item.what_happens}")
        what.setStyleSheet(_style("item_detail"))
        what.setWordWrap(True)
        text_col.addWidget(what)

        # Advanced details for services
        if item.source in ("Service", "Xbox Service"):
            detail_parts = []
            if item.detail_service:
                detail_parts.append(f"Service: {item.detail_service}")
            if item.detail_state:
                detail_parts.append(item.detail_state)
            if item.detail_startup:
                detail_parts.append(item.detail_startup)
            if item.detail_dependencies:
                detail_parts.append(f"Dependencies: {item.detail_dependencies}")
            if detail_parts:
                detail_text = "  \u00b7  ".join(detail_parts)
                detail = QLabel(detail_text)
                detail.setStyleSheet(_style("item_detail"))
                detail.setWordWrap(True)
                text_col.addWidget(detail)

        # Required by
        if item.required_by:
            req_text = f"Required by: {', '.join(item.required_by[:3])}"
            req_lbl = QLabel(req_text)
            req_lbl.setStyleSheet(
                f"{_style('item_detail')}color:{T['amber']};")
            req_lbl.setWordWrap(True)
            text_col.addWidget(req_lbl)

        card_lay.addWidget(cb, 0, Qt.AlignTop)
        card_lay.addLayout(text_col, 1)
        lay.addWidget(card)

    def _toggle_item(self, item_id, state):
        if state == Qt.Checked:
            self._selected_items.add(item_id)
        else:
            self._selected_items.discard(item_id)
        self._update_count()

    def _update_count(self):
        count = len(self._selected_items)
        if count == 0:
            text = "0 components selected"
        else:
            text = f"{count} component{'s' if count != 1 else ''} selected"
        if hasattr(self, "_count_label"):
            self._count_label.setText(text)

    def _clear_all(self):
        self._selected_items.clear()
        for cb in self._item_widgets.values():
            cb.setChecked(False)
        self._update_count()

    def _select_safe(self):
        self._selected_items.clear()
        for cb in self._item_widgets.values():
            cb.setChecked(False)
        if not self._result:
            return
        for item in self._result.items:
            if item.risk.value == "SAFE":
                self._selected_items.add(item.id)
                if item.id in self._item_widgets:
                    self._item_widgets[item.id].setChecked(True)
        self._update_count()

    def _select_all(self):
        self._selected_items.clear()
        if not self._result:
            return
        for item in self._result.items:
            self._selected_items.add(item.id)
            if item.id in self._item_widgets:
                self._item_widgets[item.id].setChecked(True)
        self._update_count()

    # ── APPLY DIALOG ────────────────────────────────────────────────

    def _show_apply_dialog(self):
        if not self._selected_items:
            return
        self._overlay = QWidget(self)
        self._overlay.setGeometry(self.rect())
        self._overlay.setStyleSheet(
            f"background:{_alpha('#000000', 0.7)};")
        self._overlay.show()
        self._overlay.raise_()

        count = len(self._selected_items)
        dialog = QWidget(self._overlay)
        dialog.setFixedSize(500, 420)
        dialog.setStyleSheet(
            f"background:{T['card']};border:1px solid {T['border']};"
            f"border-radius:12px;")
        dialog.move(
            (self.width() - 500) // 2,
            (self.height() - 420) // 2,
        )
        dialog.show()

        dlay = QVBoxLayout(dialog)
        dlay.setContentsMargins(32, 28, 32, 24)
        dlay.setSpacing(0)

        dlay.addWidget(self._make_label(
            "READY TO APPLY", _style("title")))
        dlay.addSpacing(8)
        dlay.addWidget(self._make_label(
            f"{count} component{'s' if count != 1 else ''} selected\n"
            f"A backup will be created before any changes are made.\n"
            f"If anything fails, MAXimum will automatically roll back.",
            _style("subtitle"), wrap=True))
        dlay.addSpacing(16)

        # Show selected items
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(160)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                             "QScrollArea>QWidget>QWidget{background:transparent;}")
        sel_widget = QWidget()
        sel_lay = QVBoxLayout(sel_widget)
        sel_lay.setContentsMargins(0, 0, 0, 0)
        sel_lay.setSpacing(2)

        if self._result:
            for item in self._result.items:
                if item.id in self._selected_items:
                    sel_lay.addWidget(self._make_label(
                        f"\u2022  {item.name}  ({item.risk.value})",
                        _style("item_desc"), align=Qt.AlignLeft))

        scroll.setWidget(sel_widget)
        dlay.addWidget(scroll)

        dlay.addSpacing(12)
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
        apply_btn.clicked.connect(self._apply_selected)
        btn_row.addWidget(apply_btn)
        dlay.addLayout(btn_row)
        dlay.addStretch()

    def _hide_apply_dialog(self):
        if hasattr(self, "_overlay") and self._overlay:
            self._overlay.deleteLater()
            self._overlay = None

    # ── APPLYING ────────────────────────────────────────────────────

    def _apply_selected(self):
        self._hide_apply_dialog()

        selected = [
            item for item in self._result.items
            if item.id in self._selected_items
        ]
        os_info = self._result.os_info.to_dict()

        self._clear()
        lay = QVBoxLayout()
        lay.setContentsMargins(40, 60, 40, 60)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._make_label(
            "APPLYING CHANGES", _style("title")))
        lay.addSpacing(8)
        self._apply_status = self._make_label(
            "Creating backup and applying selected changes...",
            _style("subtitle"))
        lay.addWidget(self._apply_status)
        lay.addSpacing(20)

        self._apply_worker = _ApplyWorker(
            self._engine, selected, os_info, self)
        self._apply_worker.finished.connect(self._on_apply_done)
        self._apply_worker.error.connect(self._on_apply_error)
        self._apply_worker.start()
        lay.addStretch()
        self._root.addLayout(lay)

    def _on_apply_done(self, ok, errors):
        self._build_complete(ok, errors)

    def _on_apply_error(self, msg):
        self._build_error(f"Apply failed: {msg}")

    # ── COMPLETE ────────────────────────────────────────────────────

    def _build_complete(self, ok, errors):
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

        if ok:
            title = "CHANGES APPLIED"
            subtitle = "All selected components were successfully processed."
        else:
            title = "PARTIAL SUCCESS"
            subtitle = "Some changes could not be applied. Failed items were automatically rolled back."

        lay.addWidget(self._make_label(title, _style("title")))
        lay.addSpacing(4)
        lay.addWidget(self._make_label(subtitle, _style("subtitle"), wrap=True))
        lay.addSpacing(20)

        count = len(self._selected_items)
        lay.addWidget(self._make_label(
            f"{count} component{'s' if count != 1 else ''} processed",
            _style("cat_count")))
        lay.addSpacing(16)

        if errors:
            lay.addWidget(self._make_label(
                "ERRORS", _style("section_title")))
            lay.addSpacing(8)
            for err in errors:
                row = self._make_label(
                    f"\u2022  {err}", _style("item_desc"), align=Qt.AlignLeft, wrap=True)
                row.setStyleSheet(
                    _style("item_desc").replace(T["text_dim"], T["danger"]))
                lay.addWidget(row)
            lay.addSpacing(16)

        lay.addWidget(self._hline())
        lay.addSpacing(16)

        # Rollback button
        if self._engine and self._engine.backup.has_rollback():
            rb_btn = QPushButton("ROLLBACK LAST CHANGES")
            rb_btn.setFixedWidth(240)
            rb_btn.setFixedHeight(44)
            rb_btn.setCursor(Qt.PointingHandCursor)
            rb_btn.clicked.connect(self._do_rollback)
            lay.addWidget(rb_btn, alignment=Qt.AlignCenter)
            lay.addSpacing(16)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.setAlignment(Qt.AlignCenter)

        again = QPushButton("SCAN AGAIN")
        again.setFixedWidth(160)
        again.setFixedHeight(44)
        again.setCursor(Qt.PointingHandCursor)
        again.clicked.connect(self._build_landing)
        btn_row.addWidget(again)
        lay.addLayout(btn_row)

        lay.addSpacing(32)
        scroll.setWidget(body)
        self._root.addWidget(scroll, 1)

    def _do_rollback(self):
        if not self._engine:
            return
        ok, errors = self._engine.rollback()
        self._clear()
        lay = QVBoxLayout()
        lay.setContentsMargins(40, 60, 40, 60)
        lay.setAlignment(Qt.AlignCenter)
        if ok:
            lay.addWidget(self._make_label("ROLLBACK COMPLETE", _style("title")))
            lay.addSpacing(8)
            lay.addWidget(self._make_label(
                "All changes have been reverted to their original state.",
                _style("subtitle"), wrap=True))
        else:
            lay.addWidget(self._make_label("ROLLBACK ISSUES", _style("title")))
            lay.addSpacing(8)
            for err in errors:
                lay.addWidget(self._make_label(
                    f"\u2022  {err}", _style("item_desc"), wrap=True))
        lay.addSpacing(24)
        btn = QPushButton("GO BACK")
        btn.setFixedWidth(160)
        btn.setFixedHeight(40)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self._build_landing)
        lay.addWidget(btn, alignment=Qt.AlignCenter)
        lay.addStretch()
        self._root.addLayout(lay)
