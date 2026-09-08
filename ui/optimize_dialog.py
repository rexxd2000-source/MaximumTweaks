"""Per-category Optimize dialog — port of optimize_system_flow.html.

Scan -> Overview -> Details(apply list) -> Applying -> Done, inside a
frameless 860x620 window with the reference titlebar. Every number shown
is real: the scan runs the genuine category optimizers, the findings come
from the merged report, specs are read live, and Apply Selected executes
BatchWorker with post-apply verification exactly as before.
"""
from __future__ import annotations

import os as _os
import subprocess
import tempfile as _tmp

from PySide6.QtCore import (
    QEvent,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.app_config import THEME as T
from engine.optimizer import BUTTON_LABELS, merge_reports
from rexlog import logger
from ui.widgets import BatchWorker, clear_layout, toast

# ---- reference palette (optimize_system_flow.html) ----
BG = "#0D0B14"
SURF2 = "#151320"
BORDER = "#211F2E"
BORDER_SOFT = "#1A1824"
TEXT1 = "#F5F3FA"
TEXT2 = "#8B899C"
TEXT3 = "#54516E"
VIOLET = "#9B8CFF"
VIOLET_DIM = "#7C6DF2"
TEAL = "#3ED6C8"
AMBER = "#F0B429"
GREEN = "#4ADE80"
RED = "#FF6B6B"
MONO = "'JetBrains Mono', JetBrains Mono, monospace"
DISPLAY = "Space Grotesk, 'Segoe UI', sans-serif"

EVIDENCE_LABEL = {"HIGH": "High evidence", "MEDIUM": "Medium evidence",
                  "LOW": "Low evidence", "UNKNOWN": "No evidence"}

CIRCLE_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
              b'fill="none"><circle cx="12" cy="12" r="9" '
              b'stroke="currentColor" stroke-width="2"/></svg>')
CHECK_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
             b'fill="none"><path d="M20 6L9 17l-5-5" stroke="currentColor" '
             b'stroke-width="2.5" stroke-linecap="round" '
             b'stroke-linejoin="round"/></svg>')


def _svg_icon(svg: bytes, color: str, size: int) -> QPixmap:
    from PySide6.QtSvg import QSvgRenderer
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    r = QSvgRenderer()
    r.load(svg.replace(b"currentColor", color.encode("utf-8")))
    r.render(p)
    p.end()
    return pm


CHECK_ICON = _os.path.join(_tmp.gettempdir(), "mt_check_white_v2.png").replace(
    "\\", "/")
_BOLD_CHECK = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
               b'fill="none"><path d="M20 6L9 17l-5-5" stroke="#FFFFFF" '
               b'stroke-width="4.5" stroke-linecap="round" '
               b'stroke-linejoin="round"/></svg>')
if not _os.path.isfile(CHECK_ICON):
    from PySide6.QtSvg import QSvgRenderer as _R
    _pm = QPixmap(13, 13)
    _pm.fill(Qt.transparent)
    _pp = QPainter(_pm)
    _pp.setRenderHint(QPainter.Antialiasing)
    _pp.setRenderHint(QPainter.TextAntialiasing)
    _r = _R()
    _r.load(_BOLD_CHECK)
    _r.render(_pp)
    _pp.end()
    _pm.save(CHECK_ICON)


PREFIX_CAT = {
    "reg": "Registry", "power": "Power", "sys": "System",
    "start": "Startup", "win": "Windows", "adv": "Advanced",
    "cpu": "CPU", "sched": "Scheduling", "net": "Network",
    "eth": "Network", "ram": "Memory", "perf": "Performance",
    "stor": "Storage", "svc": "Services", "bg": "Background",
    "privacy": "Privacy", "game": "Gaming", "gpu": "GPU",
    "nv": "NVIDIA", "amd": "AMD", "mouse": "Mouse",
    "kbd": "Keyboard", "audio": "Audio", "usb": "USB",
    "display": "Display", "int": "Intel", "pp": "Power Plan",
    "fpsb": "FPS Boost", "dd": "Delay", "aim": "Aim",
}


KEY_CAT = [
    ("hpet", "System"), ("timer", "System"), ("win32", "Scheduling"),
    ("priority", "Scheduling"), ("mmcss", "Scheduling"),
    ("parking", "CPU"), ("sched", "Scheduling"), ("latency", "System"),
    ("startup", "Startup"), ("boot", "Startup"), ("logon", "Startup"),
    ("power", "Power"), ("sleep", "Power"), ("usb", "USB"),
    ("mouse", "Mouse"), ("keyboard", "Keyboard"), ("kbd", "Keyboard"),
    ("net", "Network"), ("tcp", "Network"), ("dns", "Network"),
    ("game", "Gaming"), ("dvr", "Gaming"), ("gamebar", "Gaming"),
    ("gpu", "GPU"), ("vsync", "GPU"), ("frame", "GPU"),
    ("ram", "Memory"), ("memory", "Memory"), ("paging", "Memory"),
    ("ssd", "Storage"), ("disk", "Storage"), ("ntfs", "Storage"),
    ("audio", "Audio"), ("telemetry", "Privacy"), ("privacy", "Privacy"),
    ("bloat", "Debloat"), ("service", "Services"), ("visualeffects", "Windows"),
    ("win-", "Windows"), ("menu", "Windows"), ("explorer", "Windows"),
]


def _cat_of(rec) -> str:
    """Short subsystem label: reg-012 -> Registry, disable_hpet -> System."""
    tid = str(getattr(rec, "tid", "") or "").lower()
    prefix = tid.split("-")[0] if "-" in tid else ""
    if prefix in PREFIX_CAT:
        return PREFIX_CAT[prefix]
    for key, cat in KEY_CAT:
        if key in tid:
            return cat
    cat = str((rec.tweak or {}).get("category") or "Other")
    return cat


class OptimizeWorker(QThread):
    """Run category optimizers in a background thread."""

    done = Signal(object)
    error = Signal(str)
    phase = Signal(str)
    phase_key = Signal(str)

    def __init__(self, optimizers, ctx, parent=None, title="", subtitle=""):
        super().__init__(parent)
        self.optimizers = list(optimizers) if isinstance(
            optimizers, (list, tuple)) else [optimizers]
        self.ctx = ctx
        self.title = title
        self.subtitle = subtitle
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        reports, failures = [], []
        for opt in self.optimizers:
            if self._cancelled:
                return
            label = BUTTON_LABELS.get(opt.key, opt.title)
            self.phase_key.emit(opt.key)
            self.phase.emit(f"Scanning {label}")
            try:
                reports.append(opt.run(self.ctx, refresh=True))
            except Exception as exc:  # noqa: BLE001
                logger.warn(f"optimize {opt.key}: {type(exc).__name__}: {exc}")
                failures.append(opt.key)
        if self._cancelled:
            return
        if not reports:
            self.error.emit(
                "no optimizer produced results: " + ", ".join(failures))
            return
        title = self.title or reports[0].title
        subtitle = self.subtitle or reports[0].subtitle
        self.done.emit(merge_reports(reports, title, subtitle))


class _Elide(QLabel):
    """Left-elides on resize, tooltip keeps the full string."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setToolTip(text)

    def setText(self, text):
        self._full = text or ""
        QLabel.setToolTip(self, self._full)
        self._repaint()

    def _repaint(self):
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(self.font())
        QLabel.setText(self, fm.elidedText(self._full, Qt.ElideRight,
                                           max(20, self.width())))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._repaint()


class _ActiveDot(QWidget):
    """html .cat-row.active — blinking violet dot with a halo ring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self._op = 1.0
        self._t = QTimer(self)
        self._t.setInterval(500)
        self._t.timeout.connect(self._flip)

    def _flip(self):
        self._op = 0.35 if self._op > 0.9 else 1.0
        self.update()

    def run(self):
        self._t.start()
        self.update()

    def stop(self):
        self._t.stop()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(155, 140, 255, 46))
        p.drawEllipse(QPointF_(), 8, 8)
        p.setBrush(QColor(155, 140, 255, int(255 * self._op)))
        p.drawEllipse(QPointF_(8, 8), 4, 4)
        p.end()


def QPointF_(x=8, y=8):
    from PySide6.QtCore import QPointF
    return QPointF(x, y)


class OptimizeDialog(QDialog):
    """Category optimization flow: scan -> overview -> details -> apply."""

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
        self._report = None
        self._worker: OptimizeWorker | None = None
        self._apply_worker: BatchWorker | None = None
        self._rows: dict[str, tuple] = {}
        self._checkboxes: list = []
        self._recs_all: list = []
        self._cards: dict = {}
        self._scan_kind = "scan"
        self._scan_cat = ""
        self._dots_phase = 0.0
        self._drag_pos: QPoint | None = None

        self.setWindowTitle("Optimize System — Maximum Tweaks")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setFixedWidth(860)
        self.setMinimumHeight(560)
        self.resize(860, 620)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        shell = QFrame()
        shell.setObjectName("OShell")
        shell.setStyleSheet(
            "#OShell{background:" + BG + ";border:1px solid " + BORDER
            + ";border-radius:14px;}")
        sl = QVBoxLayout(shell)
        sl.setContentsMargins(1, 1, 1, 1)
        sl.setSpacing(0)
        sl.addWidget(self._build_titlebar())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_scanning_page())
        self.stack.addWidget(self._build_overview_page())
        self.stack.addWidget(self._build_details_page())
        self.stack.addWidget(self._build_apply_page())
        self.stack.addWidget(self._build_done_page())
        sl.addWidget(self.stack, 1)
        self.footer = self._build_footer()
        sl.addWidget(self.footer)
        self.footer.setVisible(False)
        outer.addWidget(shell)

        self._dots_timer = QTimer(self)
        self._dots_timer.setInterval(350)
        self._dots_timer.timeout.connect(self._cycle_dots)

        self._start_scan()

    # ---------------- titlebar ----------------

    def _build_titlebar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("OTitle")
        bar.setFixedHeight(45)
        bar.setStyleSheet(
            "#OTitle{border:none;border-bottom:1px solid " + BORDER_SOFT
            + ";background:transparent;}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 12, 0)
        lay.setSpacing(9)
        mark = QLabel("M")
        mark.setFixedSize(20, 20)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet(
            "QLabel{color:#fff;font-size:11px;font-weight:700;"
            "border:none;border-radius:6px;"
            "background:qlineargradient(x1:0,y1:0,x2:0.6,y2:1,"
            "stop:0 #9B8CFF,stop:1 #6F5DE0);}")
        lbl = QLabel(self.group_title + " \u2014 Maximum Tweaks")
        lbl.setStyleSheet(
            f"color:{TEXT2};font-size:12.5px;font-weight:500;"
            "background:transparent;border:none;")
        close = QPushButton("\u2715")
        close.setFixedSize(24, 24)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(
            "QPushButton{color:" + TEXT3 + ";background:transparent;"
            "border:none;border-radius:6px;font-size:11px;}"
            "QPushButton:hover{background:" + SURF2 + ";color:" + TEXT1 + ";}")
        close.clicked.connect(self.reject)
        lay.addWidget(mark)
        lay.addWidget(lbl)
        lay.addStretch()
        seg = QFrame()
        seg.setObjectName("SegSwitch")
        seg.setStyleSheet(
            "#SegSwitch{background:" + SURF2 + ";border:1px solid " + BORDER
            + ";border-radius:10px;}")
        seg_lay = QHBoxLayout(seg)
        seg_lay.setContentsMargins(4, 4, 4, 4)
        seg_lay.setSpacing(4)
        self._seg_btns: dict[int, QPushButton] = {}
        for idx, cap in ((0, "Scanning"), (1, "Overview"), (2, "Details")):
            b = QPushButton(cap)
            b.setCursor(Qt.PointingHandCursor)
            b.setEnabled(idx == 0)
            b.clicked.connect(
                lambda _c=False, i=idx: self._set_page(i))
            seg_lay.addWidget(b)
            self._seg_btns[idx] = b
        self._paint_segments()
        lay.addWidget(seg)
        lay.addSpacing(10)
        lay.addWidget(close)
        return bar

    def _paint_segments(self):
        if not hasattr(self, 'stack'):
            return
        cur = self.stack.currentIndex()
        for idx, b in self._seg_btns.items():
            if idx == cur:
                b.setStyleSheet(
                    "QPushButton{background:" + VIOLET_DIM + ";border:none;"
                    "color:#fff;border-radius:7px;padding:7px 11px;"
                    "font-size:11.5px;font-weight:500;}")
            else:
                b.setStyleSheet(
                    "QPushButton{background:transparent;border:none;color:"
                    + TEXT2 + ";border-radius:7px;padding:7px 11px;"
                    "font-size:11.5px;font-weight:500;}"
                    "QPushButton:hover:enabled{color:" + TEXT1 + ";}"
                    "QPushButton:disabled{color:#3B3850;}")

    def _set_page(self, idx):
        if not hasattr(self, 'stack'):
            return
        self.stack.setCurrentIndex(idx)
        if self._report is not None:
            self._seg_btns[0].setEnabled(True)
            self._seg_btns[1].setEnabled(True)
            self._seg_btns[2].setEnabled(True)
        self.footer.setVisible(idx in (1, 2))
        if idx == 2:
            self._btn_back.setVisible(True)
            self._update_apply_label()
        elif idx == 1:
            self._btn_back.setVisible(False)
            self._update_apply_label()
        self._paint_segments()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and ev.position().y() < 45:
            self._drag_pos = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        # Frameless dialogs get placed on virtual-desktop coords that can
        # land fully off-screen — pin to the primary monitor center once.
        if not getattr(self, "_centered", False):
            self._centered = True
            from PySide6.QtGui import QGuiApplication
            from PySide6.QtWidgets import QApplication
            scr = (QApplication.primaryScreen()
                   or QGuiApplication.primaryScreen())
            geo = scr.availableGeometry()
            self.move(geo.x() + (geo.width() - self.width()) // 2,
                      geo.y() + (geo.height() - self.height()) // 2)

    def mouseMoveEvent(self, ev):
        if self._drag_pos is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._drag_pos = None
        super().mouseReleaseEvent(ev)

    # ---------------- page 1: scanning ----------------

    def _build_scanning_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(0)
        eb = QLabel("MAXIMUM OPTIMIZATION ENGINE")
        ebf = QFont(eb.font())
        ebf.setLetterSpacing(QFont.AbsoluteSpacing, 0.9)
        eb.setFont(ebf)
        eb.setStyleSheet(
            f"color:{VIOLET};font-size:11px;font-weight:600;"
            "background:transparent;")
        lay.addWidget(eb)
        lay.addSpacing(10)
        h1 = QLabel(self.group_title)
        h1f = QFont(h1.font())
        h1f.setPixelSize(26)
        h1f.setWeight(QFont.Black)
        h1f.setLetterSpacing(QFont.AbsoluteSpacing, -0.5)
        h1.setFont(h1f)
        h1.setStyleSheet(f"color:{TEXT1};background:transparent;")
        lay.addWidget(h1)
        lay.addSpacing(6)
        self.scan_status = QLabel("Scanning")
        self.scan_status.setStyleSheet(
            f"color:{TEXT2};font-size:12.5px;background:transparent;")
        lay.addWidget(self.scan_status)
        lay.addSpacing(16)

        track = QFrame()
        track.setObjectName("ScanTrack")
        track.setFixedHeight(4)
        track.setStyleSheet(
            "#ScanTrack{background:" + BORDER_SOFT + ";border:none;"
            "border-radius:2px;}")
        tl = QHBoxLayout(track)
        tl.setContentsMargins(0, 0, 0, 0)
        self.scan_fill = QFrame()
        self.scan_fill.setFixedHeight(4)
        self.scan_fill.setMinimumWidth(0)
        self.scan_fill.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #7C6DF2,stop:1 #9B8CFF);border:none;border-radius:2px;")
        tl.addWidget(self.scan_fill)
        tl.addStretch()
        self._scan_track = track
        lay.addWidget(track)
        lay.addSpacing(28)

        list_host = QWidget()
        ll = QVBoxLayout(list_host)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(2)
        for opt in self.optimizers:
            row = self._scan_row(opt.key, BUTTON_LABELS.get(opt.key, opt.title))
            ll.addWidget(row)
            self._rows[opt.key] = (row, row._dot, row._count)
        lay.addWidget(list_host)
        lay.addStretch(1)
        return page

    def _scan_row(self, key, name) -> QFrame:
        row = QFrame()
        row.setObjectName("CatRow")
        row.setStyleSheet(
            "#CatRow{background:transparent;border:none;"
            "border-bottom:1px solid " + BORDER_SOFT + ";}")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(4, 11, 4, 11)
        lay.setSpacing(12)
        state_host = QFrame()
        state_host.setFixedSize(16, 16)
        sl = QHBoxLayout(state_host)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setAlignment(Qt.AlignCenter)
        queued = QLabel()
        queued.setPixmap(_svg_icon(CIRCLE_SVG, TEXT3, 12))
        sl.addWidget(queued)
        dot = _ActiveDot(state_host)
        dot.setVisible(False)
        lay.addWidget(state_host)
        nm = QLabel(name)
        nm.setStyleSheet(
            f"color:{TEXT2};font-size:13px;font-weight:400;"
            "background:transparent;")
        lay.addWidget(nm, 1)
        cnt = QLabel("")
        cnt.setObjectName("catCount")
        cnt.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        cnt.setMinimumWidth(80)
        cnt.setStyleSheet(
            f"color:{TEXT3};font-size:12px;background:transparent;")
        lay.addWidget(cnt)
        op = QGraphicsOpacityEffect(row)
        op.setOpacity(0.45)
        row.setGraphicsEffect(op)
        row._queued, row._dot, row._check, row._count, row._op = (
            queued, dot, None, cnt, op)
        return row

    def _start_scan(self):
        self._set_page(0)
        self._dots_timer.start()
        self.scan_status.setText("Scanning " + self._dots())
        self._worker = OptimizeWorker(
            self.optimizers, self.ctx, self,
            title=self.group_title, subtitle=self.group_subtitle)
        self._worker.done.connect(self._on_scanned)
        self._worker.error.connect(self._on_scan_error)
        self._worker.phase_key.connect(self._on_phase_key)
        self._worker.start()

    def _dots(self):
        return "." * (int(self._dots_phase) % 4)

    def _cycle_dots(self):
        self._dots_phase += 1
        if self._scan_kind == "scan":
            self.scan_status.setText(f"Scanning {self._scan_cat}{self._dots()}")
        else:
            self.apply_status.setText(
                f"Applying {self._scan_cat}{self._dots()}")

    def _on_phase_key(self, key):
        n = len(self.optimizers)
        for i, opt in enumerate(self.optimizers):
            rec = self._rows.get(opt.key)
            if rec is None:
                continue
            _row, dot, _cnt = rec
            queued = getattr(_row, "_queued", None)
            check = getattr(_row, "_check", None)
            if opt.key == key:
                _row._op.setOpacity(1.0)
                queued.setVisible(False)
                dot.setVisible(True)
                dot.run()
            elif i < self._phase_index(key):
                queued.setVisible(False)
                dot.stop()
                dot.setVisible(False)
                if check is not None:
                    check.setVisible(True)
        self._set_scan_pct(self._phase_index(key) / max(1, n))
        label = BUTTON_LABELS.get(key, key)
        self._scan_cat = label
        self.scan_status.setText(f"Scanning {label}{self._dots()}")

    def _phase_index(self, key):
        for i, o in enumerate(self.optimizers):
            if o.key == key:
                return i
        return 0

    def _set_scan_pct(self, frac):
        def grow():
            w = max(0, int(self._scan_track.width() * frac))
            self.scan_fill.setMinimumWidth(w)
        QTimer.singleShot(0, grow)

    def _on_scan_error(self, msg):
        self._dots_timer.stop()
        self.scan_status.setText(f"Scan failed: {msg}")
        self.scan_status.setStyleSheet(f"color:{RED};font-size:12.5px;")
        toast(f"Optimization scan failed \u2014 {msg}", "error", self)

    def _on_scanned(self, report):
        self._dots_timer.stop()
        self._report = report
        # finish all scan rows: green checks + real counts per section
        counts = {}
        try:
            for skey, _title, recs in report.grouped():
                counts[skey] = len(recs)
        except Exception:
            pass
        total = 0
        for opt in self.optimizers:
            rec = self._rows.get(opt.key)
            if rec is None:
                continue
            row, dot, cnt = rec
            row._op.setOpacity(1.0)
            getattr(row, "_queued").setVisible(False)
            dot.stop()
            dot.setVisible(False)
            _c = getattr(row, "_check", None)
            if _c is not None:
                _c.setVisible(True)
            n = counts.get(opt.key, 0)
            total += n
            cnt.setText(f"<b style='color:{TEXT1};'>{n}</b> found")
            cnt.setStyleSheet(f"color:{TEXT2};font-size:12px;"
                              "background:transparent;")
        self._scan_cat = "Complete"
        self.scan_status.setText("Scanning Complete")
        self._set_scan_pct(1.0)
        self._build_overview(report)
        self._build_details(report)
        QTimer.singleShot(700, self._show_overview)

    def _show_overview(self):
        self._set_page(1)

    # ---------------- page 2: overview ----------------

    def _build_overview_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(30, 26, 30, 20)
        lay.setSpacing(0)
        head = QHBoxLayout()
        hb = QVBoxLayout()
        hb.setSpacing(6)
        self.ov_title = QLabel(self.group_title)
        otf = QFont(self.ov_title.font())
        otf.setPixelSize(22)
        otf.setWeight(QFont.Black)
        otf.setLetterSpacing(QFont.AbsoluteSpacing, -0.3)
        self.ov_title.setFont(otf)
        self.ov_title.setStyleSheet(
            f"color:{TEXT1};background:transparent;")
        self.ov_sub = QLabel()
        self.ov_sub.setWordWrap(True)
        self.ov_sub.setStyleSheet(
            f"color:{TEXT2};font-size:12.5px;background:transparent;")
        self.ov_sub.setMaximumWidth(480)
        hb.addWidget(self.ov_title)
        hb.addWidget(self.ov_sub)
        head.addLayout(hb, 1)
        badge = QFrame()
        badge.setObjectName("ScoreBadge")
        badge.setStyleSheet(
            "#ScoreBadge{background:" + SURF2 + ";border:1px solid " + BORDER
            + ";border-radius:11px;}")
        bl = QHBoxLayout(badge)
        bl.setContentsMargins(14, 9, 14, 9)
        bl.setSpacing(9)
        self.ov_score = QLabel("0")
        self.ov_score.setStyleSheet(
            f"color:{VIOLET};font-family:{MONO};font-size:20px;"
            f"font-weight:700;background:transparent;border:none;")
        cap = QLabel("CHANGES<br>RECOMMENDED")
        cap.setStyleSheet(
            f"color:{TEXT2};font-size:10px;letter-spacing:0.5px;"
            "background:transparent;border:none;")
        bl.addWidget(self.ov_score)
        bl.addWidget(cap)
        head.addWidget(badge, 0, Qt.AlignTop)
        lay.addLayout(head)
        lay.addSpacing(16)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        specs_card_host = self._ov_card("Detected system")
        self._ov_specs_host = specs_card_host[1]
        bars_card_host = self._ov_card("Findings by category")
        self.ov_bar_host = bars_card_host[1]
        grid.addWidget(specs_card_host[0], 0, 0)
        grid.addWidget(bars_card_host[0], 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        lay.addLayout(grid, 1)
        return page

    def _ov_card(self, title) -> tuple:
        card = QFrame()
        card.setObjectName("OvCard")
        card.setStyleSheet(
            "#OvCard{background:" + SURF2 + ";border:1px solid " + BORDER_SOFT
            + ";border-radius:12px;}")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)
        tt = QLabel(title)
        tt.setStyleSheet(
            f"color:{TEXT1};font-size:12px;font-weight:600;"
            "background:transparent;")
        lay.addWidget(tt)
        host = QWidget()
        host.setStyleSheet("background:transparent;")
        lay.addWidget(host, 1)
        lay.addStretch()
        return card, host

    def _build_overview(self, report):
        self.ov_sub.setText(self.group_subtitle or "")
        recs = report.ready()
        self.ov_score.setText(str(len(recs)))
        # specs (live reads)
        host = self._ov_specs_host
        if host.layout() is not None:
            clear_layout(host.layout())
        g = QGridLayout(host)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(11)
        rows = self._system_specs()
        for fact_k, fact_v in list(report.detection_facts or []):
            if len(str(fact_v)) <= 30 and len(rows) < 14:
                rows.append((str(fact_k), str(fact_v)))
        for idx, (k, v) in enumerate(rows[:12]):
            kk = QLabel(str(k))
            kk.setStyleSheet(
                f"color:{TEXT3};font-size:10.5px;background:transparent;")
            vv = QLabel(str(v))
            vv.setWordWrap(True)
            vv.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            vvf = QFont(vv.font())
            vvf.setFamilies(["JetBrains Mono"])
            vvf.setPixelSize(12)
            vv.setFont(vvf)
            vv.setStyleSheet(
                f"color:{TEXT1};font-size:12px;background:transparent;")
            r, c = divmod(idx, 2)
            g.addWidget(kk, r * 2, c * 2)
            g.addWidget(vv, r * 2 + 1, c * 2, 1, 2)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(2, 1)
        # category bars
        host2 = self.ov_bar_host
        if host2.layout() is not None:
            clear_layout(host2.layout())
        vl = QVBoxLayout(host2)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(9)
        sections = []
        try:
            sections = [(t, len(rs)) for (_k, t, rs) in report.grouped() if rs]
        except Exception:
            pass
        mx = max((n for _t, n in sections), default=1)
        for title, n in sections:
            row = QHBoxLayout()
            row.setSpacing(10)
            nm = QLabel(title)
            nm.setMinimumWidth(104)
            nm.setStyleSheet(
                f"color:{TEXT2};font-size:12px;background:transparent;")
            bar = QFrame()
            bar.setFixedHeight(5)
            bar.setObjectName("CatBar")
            bar.setStyleSheet(
                "#CatBar{background:" + BORDER_SOFT + ";border:none;"
                "border-radius:3px;}")
            bl2 = QHBoxLayout(bar)
            bl2.setContentsMargins(0, 0, 0, 0)
            fill = QFrame()
            fill.setFixedHeight(5)
            fill.setStyleSheet(
                "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 {TEAL},stop:1 {VIOLET});border:none;"
                "border-radius:3px;")
            fill.setMinimumWidth(max(4, int(bar.width() or 120) * n // mx))
            bl2.addWidget(fill)
            bl2.addStretch()
            num = QLabel(str(n))
            num.setFixedWidth(24)
            num.setAlignment(Qt.AlignRight)
            numf = QFont(num.font())
            numf.setFamilies(["JetBrains Mono"])
            numf.setPixelSize(11.5)
            num.setFont(numf)
            num.setStyleSheet(
                f"color:{TEXT1};font-size:11.5px;background:transparent;")
            row.addWidget(nm)
            row.addWidget(bar, 1)
            row.addWidget(num)
            vl.addLayout(row)
        vl.addStretch(1)

    def _system_specs(self) -> list:
        import winreg
        p = self.ctx.profile or {}
        out = []
        try:
            with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
                prod = winreg.QueryValueEx(k, "ProductName")[0]
                build = winreg.QueryValueEx(k, "CurrentBuildNumber")[0]
            out.append(("OS", f"{prod} ({build})"))
        except OSError:
            out.append(("OS", f"Windows {p.get('win_version', '?')}"))
        cpu = str(p.get("cpu_name") or "—").strip()
        for drop in ("AMD ", "Intel(R) ", "Intel "):
            cpu = cpu.replace(drop, "")
        out.append(("CPU", cpu.strip()))
        gpu = "—"
        try:
            gpus = p.get("gpu_names") or []
            gpu = (gpus[0] if gpus else str(p.get("gpu") or "—"))
            gpu = str(gpu)
            for drop in ("NVIDIA GeForce ", "NVIDIA ", "AMD Radeon ",
                         "Radeon Graphics", "(R)", "  Series"):
                gpu = gpu.replace(drop, "")
            gpu = gpu.strip()
            vram = p.get("gpu_vram_gb")
            if vram:
                gpu = f"{gpu[:20]} \u00b7 {vram:g}GB"
        except Exception:
            pass
        out.append(("GPU", gpu))
        ram = p.get("ram_gb")
        out.append(("RAM", f"{ram:.1f} GB" if isinstance(ram, float)
                    else f"{ram} GB"))
        out.append(("Form factor", "Laptop" if p.get("laptop") else "Desktop"))
        try:
            from PySide6.QtWidgets import QApplication
            scr = QApplication.primaryScreen()
            geo = scr.geometry()
            refresh = int(p.get("monitor_refresh") or scr.refreshRate() or 0)
            out.append(("Display", f"{geo.width()}×{geo.height()} @{refresh}Hz"))
        except Exception:
            out.append(("Display", "—"))
        out.append(("Storage", ("NVMe SSD" if p.get("nvme")
                                else "SSD" if p.get("ssd") else "HDD")))
        out.append(("Power plan", self._power_plan()))
        return out

    def _power_plan(self) -> str:
        try:
            txt = subprocess.run(
                ["powercfg", "/getactivescheme"], capture_output=True,
                text=True, errors="ignore",
                creationflags=0x08000000).stdout or ""
            if "(" in txt and ")" in txt:
                return txt[txt.rindex("(") + 1:txt.rindex(")")].strip()
        except Exception:
            pass
        return "—"

    # ---------------- page 3: details ----------------

    def _build_details_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(30, 22, 30, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        hb = QVBoxLayout()
        hb.setSpacing(4)
        h1 = QLabel(self.group_title)
        hf = QFont(h1.font())
        hf.setPixelSize(20)
        hf.setWeight(QFont.Black)
        hf.setLetterSpacing(QFont.AbsoluteSpacing, -0.3)
        h1.setFont(hf)
        h1.setStyleSheet(f"color:{TEXT1};background:transparent;")
        self.det_sub = QLabel()
        self.det_sub.setStyleSheet(
            f"color:{TEXT2};font-size:12px;background:transparent;")
        hb.addWidget(h1)
        hb.addWidget(self.det_sub)
        head.addLayout(hb, 1)
        head.addStretch()
        lay.addLayout(head)
        lay.addSpacing(16)

        self.chip_row = QHBoxLayout()
        self.chip_row.setSpacing(6)
        lay.addLayout(self.chip_row)
        lay.addSpacing(16)

        self._all_cards: list = []
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea>QWidget>QWidget{background:transparent;}"
            "QScrollBar:vertical{width:11px;background:" + BORDER_SOFT
            + ";border-radius:6px;margin:2px;}"
            "QScrollBar::handle:vertical{background:#453F60;"
            "border-radius:5px;min-height:34px;}"
            "QScrollBar::handle:vertical:hover{background:" + VIOLET_DIM
            + ";}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical"
            "{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical"
            "{background:transparent;}")
        inner = QWidget()
        self.det_lay = QVBoxLayout(inner)
        self.det_lay.setContentsMargins(0, 0, 8, 14)
        self.det_lay.setSpacing(9)
        scroll.setWidget(inner)
        self._det_scroll = scroll
        lay.addWidget(scroll, 1)
        return page

    def _build_details(self, report):
        self._recs_all = []
        clear_layout(self.det_lay)
        clear_layout(self.chip_row)
        self._checkboxes = [c for c in self._checkboxes
                            if c.parent() is not None]
        cats = []
        for skey, _title, recs in report.grouped():
            for rec in recs:
                cat = _cat_of(rec)
                if cat not in cats:
                    cats.append(cat)
                self._recs_all.append((cat, rec))
        self.det_sub.setText(
            f"Showing {len(self._recs_all)} of {len(self._recs_all)} "
            "recommended changes")
        chips = ["All"] + cats
        self._chips: dict[str, QPushButton] = {}
        for i, name in enumerate(chips):
            ch = QPushButton(name)
            ch.setCheckable(True)
            ch.setChecked(i == 0)
            ch.setCursor(Qt.PointingHandCursor)
            ch.clicked.connect(
                lambda _c=False, nm=name: self._filter(nm))
            self.chip_row.addWidget(ch)
            self._chips[name] = ch
        self.chip_row.addStretch()
        self._refresh_chips_style()
        self._recs_all.sort(key=lambda x: cats.index(x[0]))
        last_title = None
        for title, rec in self._recs_all:
            if title != last_title:
                sec = QLabel(title.upper())
                sf = QFont(sec.font())
                sf.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
                sec.setFont(sf)
                sec.setStyleSheet(
                    f"color:{TEXT3};font-size:10px;font-weight:600;"
                    "background:transparent;padding-top:6px;")
                sec.setObjectName("SecHead:" + title)
                self.det_lay.addWidget(sec)
                last_title = title
            self._add_tweak_card(rec)
            card = self._cards[id(rec)]
            card._sec_title = title
        self.det_lay.addStretch(1)
        self._filter("All")
        self._update_apply_label()

    def _filter(self, name):
        for title, rec in self._recs_all:
            card = self._cards[id(rec)]
            card.setVisible(name == "All" or title == name)
        for i in range(self.det_lay.count()):
            it = self.det_lay.itemAt(i)
            w = it.widget() if it else None
            if w is not None and w.objectName().startswith("SecHead:"):
                sec = w.objectName().split(":", 1)[1]
                w.setVisible(name == "All" or sec == name)
        shown = sum(1 for t, r in self._recs_all
                    if name == "All" or t == name)
        self.det_sub.setText(
            f"Showing {shown} of {len(self._recs_all)} recommended changes")
        for nm, ch in self._chips.items():
            ch.setChecked(nm == name)
        self._refresh_chips_style()

    def _refresh_chips_style(self):
        for nm, ch in self._chips.items():
            if ch.isChecked():
                ch.setStyleSheet(
                    "QPushButton{background:" + VIOLET_DIM + ";border:1px solid "
                    + VIOLET_DIM + ";color:#fff;border-radius:20px;"
                    "padding:6px 12px;font-size:11.5px;font-weight:500;}")
            else:
                ch.setStyleSheet(
                    "QPushButton{background:" + SURF2 + ";border:1px solid "
                    + BORDER_SOFT + ";color:" + TEXT2 + ";border-radius:20px;"
                    "padding:6px 12px;font-size:11.5px;font-weight:500;}"
                    "QPushButton:hover{color:" + TEXT1 + ";border-color:#332F47;}")

    def _add_tweak_card(self, rec):
        card = QFrame()
        card.setObjectName("TweakCard")
        card.setStyleSheet(
            "#TweakCard{background:" + SURF2 + ";border:1px solid "
            + BORDER_SOFT + ";border-radius:11px;}")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 13, 14, 13)
        lay.setSpacing(12)
        box = QCheckBox()
        box.setObjectName("RecToggle")
        box.tweak_id = rec.tid
        box.setStyleSheet(
            "QCheckBox#RecToggle::indicator{width:19px;height:19px;"
            "border-radius:6px;border:1px solid " + BORDER + ";"
            "background:" + BG + ";}"
            "QCheckBox#RecToggle::indicator:checked{"
            "background:qlineargradient(x1:0,y1:0,x2:0.6,y2:1,"
            "stop:0 #A99CFF,stop:1 #7C6DF2);border:1px solid #7C6DF2;}"
            "QCheckBox#RecToggle::indicator:disabled{opacity:0.3;}")
        if rec.selectable:
            box.setChecked(rec.default_checked)
            box.toggled.connect(self._update_apply_label)
            self._checkboxes.append(box)
        else:
            box.setChecked(False)
            box.setEnabled(False)
        lay.addWidget(box, 0, Qt.AlignTop)
        body = QVBoxLayout()
        body.setSpacing(5)
        trow = QHBoxLayout()
        trow.setSpacing(8)
        nm = QLabel(rec.name)
        nm.setStyleSheet(
            f"color:{TEXT1};font-size:13.5px;font-weight:600;"
            "background:transparent;")
        trow.addWidget(nm)
        tid = QLabel(rec.tid)
        tf = QFont(tid.font())
        tf.setFamilies(["JetBrains Mono"])
        tf.setPixelSize(10.5)
        tid.setFont(tf)
        tid.setStyleSheet(
            f"color:{TEXT3};font-size:10.5px;background:transparent;")
        trow.addWidget(tid)
        ev = rec.evidence or rec.tweak.get("evidence", "UNKNOWN")
        trow.addWidget(self._pill(EVIDENCE_LABEL.get(ev, ev), VIOLET))
        trow.addWidget(self._pill(
            "Impact: " + str(rec.tweak.get("impact", "low")).capitalize(),
            TEAL))
        risk = str(rec.tweak.get("risk", "low"))
        rc = {
            "safe": GREEN, "low": GREEN, "moderate": AMBER,
            "advanced": RED, "high": RED}.get(risk, TEXT2)
        trow.addWidget(self._pill(
            "Risk: " + risk.capitalize(), rc))
        trow.addStretch()
        body.addLayout(trow)
        why = QLabel(rec.reason or rec.tweak.get("desc", ""))
        why.setWordWrap(True)
        why.setStyleSheet(
            f"color:{TEXT2};font-size:12px;line-height:150%;"
            "background:transparent;")
        body.addWidget(why)
        lay.addLayout(body, 1)
        self.det_lay.addWidget(card)
        self._cards[id(rec)] = card

    def _pill(self, text, color):
        from PySide6.QtGui import QColor as _C
        c = _C(color)
        lbl = QLabel(text)
        lf = QFont(lbl.font())
        lf.setPixelSize(10)
        lbl.setFont(lf)
        lbl.setStyleSheet(
            f"color:{color};background:rgba({c.red()},{c.green()},"
            f"{c.blue()},0.12);border:none;border-radius:5px;"
            "padding:2px 7px;font-size:10px;font-weight:500;")
        return lbl

    # ---------------- shared footer ----------------

    def _build_footer(self) -> QFrame:
        foot = QFrame()
        foot.setObjectName("OFoot")
        foot.setStyleSheet(
            "#OFoot{background:transparent;border:none;border-top:1px solid "
            + BORDER_SOFT + ";}")
        lay = QHBoxLayout(foot)
        lay.setContentsMargins(30, 14, 30, 14)
        lay.setSpacing(16)
        note = QLabel(
            "Every change is verified against the live system after it's "
            "applied, and can be reverted anytime from the Tweaks page.")
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color:{TEXT2};font-size:11.5px;background:transparent;")
        lay.addWidget(note, 1)
        self._btn_back = QPushButton("Back")
        self._btn_back.setCursor(Qt.PointingHandCursor)
        self._btn_back.setStyleSheet(
            "QPushButton{background:" + SURF2 + ";color:" + TEXT2
            + ";border:1px solid " + BORDER + ";border-radius:9px;"
            "padding:10px 18px;font-size:13px;font-weight:600;}"
            "QPushButton:hover{color:" + TEXT1 + ";border-color:#332F47;}")
        self._btn_back.clicked.connect(self._back_to_overview)
        self._btn_back.setVisible(False)
        cancel = QPushButton("Cancel")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            "QPushButton{background:" + SURF2 + ";color:" + TEXT2
            + ";border:1px solid " + BORDER + ";border-radius:9px;"
            "padding:10px 18px;font-size:13px;font-weight:600;}"
            "QPushButton:hover{color:" + TEXT1 + ";border-color:#332F47;}")
        cancel.clicked.connect(self.reject)
        self.btn_apply = QPushButton("Apply Selected")
        self.btn_apply.setCursor(Qt.PointingHandCursor)
        self.btn_apply.setStyleSheet(
            "QPushButton{border:none;border-radius:9px;padding:10px 18px;"
            "font-size:13px;font-weight:600;color:#fff;"
            "background:qlineargradient(x1:0,y1:0,x2:0.37,y2:1,"
            "stop:0 #A99CFF,stop:1 #7C6DF2);}"
            "QPushButton:hover:enabled{filter:brightness(1.07);}"
            "QPushButton:disabled{background:#2A2740;color:#54516E;}")
        self.btn_apply.clicked.connect(self._footer_primary)
        lay.addWidget(self._btn_back)
        lay.addWidget(cancel)
        lay.addWidget(self.btn_apply)
        return foot

    def _back_to_overview(self):
        self._set_page(1)

    def _footer_primary(self):
        idx = self.stack.currentIndex()
        if idx == 1:  # overview -> open the full details list
            self._set_page(2)
            return
        if idx == 2:
            self._start_apply()
            return
        self.accept()

    def _update_apply_label(self):
        if not hasattr(self, "btn_apply"):
            return
        n = sum(1 for cb in self._checkboxes if cb.isChecked())
        if self.stack.currentIndex() == 1:
            self.btn_apply.setText(f"Review changes ({n})")
            self.btn_apply.setEnabled(True)
        else:
            self.btn_apply.setText(f"Apply Selected ({n})")
            self.btn_apply.setEnabled(n > 0)

    # ---------------- page 4: applying ----------------

    def _build_apply_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(0)
        eb = QLabel("MAXIMUM OPTIMIZATION ENGINE")
        ebf = QFont(eb.font())
        ebf.setLetterSpacing(QFont.AbsoluteSpacing, 0.9)
        eb.setFont(ebf)
        eb.setStyleSheet(
            f"color:{VIOLET};font-size:11px;font-weight:600;"
            "background:transparent;")
        lay.addWidget(eb)
        lay.addSpacing(10)
        h1 = QLabel("Applying changes")
        hf = QFont(h1.font())
        hf.setPixelSize(26)
        hf.setWeight(QFont.Black)
        hf.setLetterSpacing(QFont.AbsoluteSpacing, -0.5)
        h1.setFont(hf)
        h1.setStyleSheet(f"color:{TEXT1};background:transparent;")
        lay.addWidget(h1)
        lay.addSpacing(6)
        self.apply_status = QLabel("Starting…")
        self.apply_status.setStyleSheet(
            f"color:{TEXT2};font-size:12.5px;background:transparent;")
        lay.addWidget(self.apply_status)
        lay.addSpacing(16)
        track = QFrame()
        track.setObjectName("ApplyTrack")
        track.setFixedHeight(4)
        track.setStyleSheet(
            "#ApplyTrack{background:" + BORDER_SOFT + ";border:none;"
            "border-radius:2px;}")
        tl = QHBoxLayout(track)
        tl.setContentsMargins(0, 0, 0, 0)
        self.apply_fill = QFrame()
        self.apply_fill.setFixedHeight(4)
        self.apply_fill.setMinimumWidth(0)
        self.apply_fill.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #7C6DF2,stop:1 #9B8CFF);border:none;border-radius:2px;")
        tl.addWidget(self.apply_fill)
        tl.addStretch()
        self._apply_track = track
        lay.addWidget(track)
        lay.addSpacing(24)
        self.apply_log = QLabel()
        self.apply_log.setWordWrap(True)
        self.apply_log.setTextFormat(Qt.RichText)
        self.apply_log.setStyleSheet(
            f"color:{TEXT2};font-size:12px;background:transparent;")
        lay.addWidget(self.apply_log)
        lay.addStretch(1)
        return page

    def _start_apply(self):
        ids = [cb.tweak_id for cb in self._checkboxes if cb.isChecked()]
        if not ids:
            toast("Select at least one tweak to apply.", "warning", self)
            return
        self._set_page(3)
        self._scan_kind = "apply"
        self._total_apply = len(ids)
        self._done_apply = 0
        self._ok_apply = 0
        self._scan_cat = "tweaks"
        self._dots_timer.start()
        self.apply_log.setText("")
        self._apply_worker = BatchWorker(ids, "apply", self,
                                         profile=self.ctx.profile)
        self._apply_worker.progress.connect(self._on_progress)
        self._apply_worker.batch_done.connect(self._on_apply_done)
        self._apply_worker.batch_error.connect(self._on_apply_error)
        self._apply_worker.start()

    def _on_progress(self, done, total, tid, ok, summary):
        self._done_apply = done
        self._ok_apply += 1 if ok else 0

        def grow():
            self.apply_fill.setMinimumWidth(
                int(self._apply_track.width() * done / max(1, total)))
        QTimer.singleShot(0, grow)
        col = GREEN if ok else RED
        mark = "VERIFIED" if ok else "FAILED"
        self.apply_log.setText(
            self.apply_log.text()
            + f"<div style='margin-bottom:4px;'>"
              f"<span style='color:{col};font-weight:700;'>{mark}</span> "
              f"<span style='font-family:{MONO};color:{TEXT1};'>{tid}</span>"
              f"<span style='color:{TEXT3};'>  {summary}</span></div>")

    def _on_apply_done(self, result):
        self._apply_worker = None
        self._dots_timer.stop()
        results = result.get("results", {})
        applied = result.get("applied", [])
        ok_ids = [tid for tid, r in results.items()
                  if r.get("ok") and r.get("status") != "dry_run"]
        failed = [tid for tid, r in results.items() if not r.get("ok")]
        unverified = [
            tid for tid, r in results.items()
            if tid in ok_ids and tid not in applied]
        self.ctx.invalidate_state()
        self.ctx.force_audit_ids(list(results))
        self.ctx.note_state_change()
        self._show_done(applied, failed, unverified)

    def _on_apply_error(self, msg):
        self._dots_timer.stop()
        self._show_done([], [f"apply error: {msg}"])

    # ---------------- page 5: done ----------------

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(0)
        self.done_title = QLabel()
        dtf = QFont(self.done_title.font())
        dtf.setPixelSize(26)
        dtf.setWeight(QFont.Black)
        dtf.setLetterSpacing(QFont.AbsoluteSpacing, -0.5)
        self.done_title.setFont(dtf)
        self.done_title.setStyleSheet(
            f"color:{TEXT1};background:transparent;")
        lay.addWidget(self.done_title)
        lay.addSpacing(6)
        self.done_body = QLabel()
        self.done_body.setWordWrap(True)
        self.done_body.setStyleSheet(
            f"color:{TEXT2};font-size:13px;line-height:160%;"
            "background:transparent;")
        lay.addWidget(self.done_body)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch()
        btn = QPushButton("Close")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton{border:none;border-radius:9px;padding:10px 22px;"
            "font-size:13px;font-weight:600;color:#fff;"
            "background:qlineargradient(x1:0,y1:0,x2:0.37,y2:1,"
            "stop:0 #A99CFF,stop:1 #7C6DF2);}")
        btn.clicked.connect(self.accept)
        row.addWidget(btn)
        lay.addLayout(row)
        return page

    def _show_done(self, applied, failed, unverified=()):
        self._set_page(4)
        ok = not failed and not unverified
        self.done_title.setText(
            f"{self.group_title} \u2014 "
            + ("Complete" if ok else "Partially complete"))
        if failed or unverified:
            parts = [f"{len(applied)} tweak(s) applied and verified"]
            if unverified:
                parts.append(
                    f"{len(unverified)} applied but could not be re-read "
                    "on this system")
            parts.append(f"{len(failed)} failed or were blocked")
            self.done_body.setText(". ".join(parts) + ". You can retry from "
                                   "the Tweaks page or revert any change.")
        else:
            self.done_body.setText(
                f"All {len(applied)} selected tweak(s) were applied and "
                "verified against the live system. Revert them any time "
                "from this category.")
        toast(f"{self.group_title} \u2014 {len(applied)} applied, verified.",
              "success" if ok else "warning", self)

    def closeEvent(self, event):
        self._dots_timer.stop()
        for w in (self._worker, self._apply_worker):
            if w is not None and w.isRunning():
                if hasattr(w, "cancel"):
                    w.cancel()
                w.wait(5000)
        super().closeEvent(event)
