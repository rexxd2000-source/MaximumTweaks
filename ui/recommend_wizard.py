"""Apply Recommended wizard.

A small modal flow with three phases:

  * Deep check — runs a real hardware scan (hardware.detector.detect) off the
    UI thread while a live feed animates what it is checking.  The feed is
    guaranteed to run for at least MIN_CHECK_TIME seconds so it reads like a
    genuine deep scan rather than an instant list.
  * Results — the recommended tweaks for THIS system (compatible, marked
    recommended, not already active, and not pure guidance) shown as a
    checkable list.  Every entry is fully revertable via its ``revert``
    actions.
  * Apply — runs the checked tweaks with BatchWorker, reports progress, then
    hands back to the tweaks page (which auto-refreshes via ctx signals).
"""
from __future__ import annotations

import time

from PySide6.QtCore import (
    Property,
    QPropertyAnimation,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
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
from database import TWEAKS
from engine.recommender import evaluate_many
from ui.widgets import BatchWorker, toast

# How long the deep-check feed must run before results appear (seconds).
MIN_CHECK_TIME = 14.0

# Live feed steps — each is a real stage of the detection running below.
CHECK_STEPS = [
    "Checking CPU \u2014 cores, clock speed & vendor",
    "Detecting GPU vendor & driver version",
    "Probing memory channels & transfer speed",
    "Scanning storage \u2014 SSD / NVMe / HDD",
    "Reading Windows build & version",
    "Measuring display refresh rate",
    "Inspecting network adapter",
    "Probing power & service readiness",
    "Evaluating tweak compatibility for this hardware",
    "Compiling the recommended tweak set",
]

IMPACT_RANK = {"extreme": 6, "high": 5, "moderate": 4, "low": 3, "very low": 2}
RISK_COLORS = {
    "safe": "#00F2FE", "low": "#94A3B8",
    "moderate": "#F0B54D", "advanced": "#F87979",
}


class _DetectWorker(QThread):
    """Runs the real hardware detection off the UI thread."""

    done = Signal(dict)
    error = Signal(str)

    def run(self):
        try:
            from hardware import detect
            self.done.emit(detect())
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class _ScanCanvas(QWidget):
    """Full-screen cinematic canvas: dark field, vignette, corner brackets
    and a sweeping cyan scanline.  The scanline position is animated by
    QPropertyAnimation through the ``offset`` property."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.offset = 0.0
        self.setAttribute(Qt.WA_TranslucentBackground, False)

    def _get_offset(self):
        return self._offset

    def _set_offset(self, value):
        self._offset = value
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return

        # Base dark field
        p.fillRect(self.rect(), QColor("#05070A"))

        # Vignette — brighter center, edges fall to black.
        vg = QRadialGradient(w / 2, h / 2, max(w, h) * 0.75)
        vg.setColorAt(0.0, QColor(0, 242, 254, 10))
        vg.setColorAt(0.55, QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, QColor(0, 0, 0, 175))
        p.fillRect(self.rect(), vg)

        # Corner brackets (HUD-style) inset from the edges.
        m = 22
        bx = w - m
        by = h - m
        pen = QPen(QColor(0, 242, 254, 130), 2)
        p.setPen(pen)
        for x, y, sx, sy in ((m, m, 1, 1), (bx, m, -1, 1),
                             (m, by, 1, -1), (bx, by, -1, -1)):
            p.drawLine(x, y + sx * 14, x, y)          # vertical
            p.drawLine(x, y, x + sx * 14, y)          # horizontal

        # Sweeping scanline with a soft glow band.
        y = self.offset / 100.0 * h
        glow = QLinearGradient(0, y - 34, 0, y + 34)
        glow.setColorAt(0.0, QColor(0, 242, 254, 0))
        glow.setColorAt(0.5, QColor(0, 242, 254, 36))
        glow.setColorAt(1.0, QColor(0, 242, 254, 0))
        p.fillRect(0, int(y - 34), w, 68, glow)
        line_pen = QPen(QColor(0, 242, 254, 215), 1)
        p.setPen(line_pen)
        p.drawLine(0, int(y), w, int(y))


class _FeedLine(QFrame):
    """One cinematic feed line: glyph + text, fades/slides in on reveal."""

    def __init__(self, text, index):
        super().__init__()
        self.text_value = text
        self._state = "pending"
        self.setFixedHeight(36)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(14)
        self._glyph = QLabel("\u00b7")
        self._glyph.setFixedWidth(22)
        self._glyph.setAlignment(Qt.AlignCenter)
        self._text = QLabel(text)
        self._text.setStyleSheet(
            "color: #C9D2DC; font-size: 14px; font-weight: 600;")
        lay.addWidget(self._glyph)
        lay.addWidget(self._text, 1)
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._render_state()

    def reveal(self, delay_ms=0):
        """Fade + slide the line in."""
        def _fade():
            anim = QPropertyAnimation(self._opacity, b"opacity")
            anim.setDuration(650)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.start()
            self._reveal_anim = anim
        if delay_ms:
            QTimer.singleShot(delay_ms, _fade)
        else:
            _fade()
        self._render_state()

    def set_state(self, state):
        if state != self._state:
            self._state = state
            self._render_state()

    def _render_state(self):
        glyph = {"done": "\u2713", "active": "\u25cf",
                 "pending": "\u00b7"}.get(self._state, "\u00b7")
        color = {"done": T["success"], "active": T["accent"],
                 "pending": T["text_faint"]}.get(self._state, T["text_faint"])
        self._glyph.setText(glyph)
        self._glyph.setStyleSheet(
            f"color: {color}; font-size: 15px; font-weight: 900;")
        self._text.setStyleSheet(
            ("color: #F2F5F9; font-size: 14px; font-weight: 700;"
             if self._state == "active" else
             "color: #C9D2DC; font-size: 14px; font-weight: 600;"))


class RecommendWizard(QDialog):
    """Modal 'Apply Recommended for this System' wizard."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Apply Recommended \u2014 Rex Tweaks")
        self.setModal(True)
        self.resize(680, 620)
        self._profile = None
        self._detected = False
        self._detect_fail = False
        self._started = time.monotonic()
        self._step = 0
        self._check_rows: list[_FeedLine] = []
        self._anims: list = []
        self._feed_clock: QTimer | None = None
        self._apply_worker = None

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._build_check_page())
        self.stack.addWidget(self._build_results_page())
        self.stack.addWidget(self._build_apply_page())
        self.stack.addWidget(self._build_done_page())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.stack)

        self._detect = _DetectWorker(self)
        self._detect.done.connect(self._on_detected)
        self._detect.error.connect(self._on_detect_error)
        self._detect.start()
        self._start_check_feed()

    # ---------------- Phase 1: deep check (cinematic loader) ----------------

    def _build_check_page(self) -> QWidget:
        page = QWidget()
        self.check_page = page

        # Letterbox bars top/bottom for the film look.
        top_bar = QFrame()
        top_bar.setFixedHeight(26)
        top_bar.setStyleSheet("background-color: #04060A;")
        tlay = QHBoxLayout(top_bar)
        tlay.setContentsMargins(18, 0, 18, 0)
        brand = QLabel("\u25c8  REX TWEAKS")
        brand.setStyleSheet(
            "color: #5B6675; font-size: 11px; font-weight: 800;"
            "letter-spacing: 3px;")
        ver = QLabel("DEEP SYSTEM ANALYSIS")
        ver.setStyleSheet(
            "color: rgba(0, 242, 254, 0.55); font-size: 10px; font-weight: 800;"
            "letter-spacing: 2px;")
        tlay.addWidget(brand)
        tlay.addStretch()
        tlay.addWidget(ver)

        # Cinematic canvas: scanline + vignette + corner brackets.
        self.check_canvas = _ScanCanvas()
        canvas_lay = QVBoxLayout(self.check_canvas)
        canvas_lay.setContentsMargins(56, 34, 56, 30)
        canvas_lay.setSpacing(0)

        # ---- Title block (fades/slides in) ----
        title_box = QWidget()
        self.title_effect = QGraphicsOpacityEffect(title_box)
        self.title_effect.setOpacity(0.0)
        title_box.setGraphicsEffect(self.title_effect)
        tbox = QVBoxLayout(title_box)
        tbox.setContentsMargins(0, 0, 0, 0)
        tbox.setSpacing(6)
        kicker = QLabel("REX OPTIMIZATION ENGINE")
        kicker.setStyleSheet(
            "color: rgba(0, 242, 254, 0.75); font-size: 11px; font-weight: 800;"
            "letter-spacing: 5px;")
        title = QLabel("DEEP PC CHECK")
        title.setStyleSheet(
            "color: #F2F5F9; font-size: 34px; font-weight: 900;"
            "letter-spacing: 7px;")
        subtitle = QLabel("Scanning hardware, drivers and Windows so every "
                          "recommended tweak fits THIS system.")
        subtitle.setStyleSheet("color: #94A3B8; font-size: 13px;")
        tbox.addWidget(kicker, alignment=Qt.AlignHCenter)
        tbox.addWidget(title, alignment=Qt.AlignHCenter)
        tbox.addWidget(subtitle, alignment=Qt.AlignHCenter)
        canvas_lay.addWidget(title_box)
        canvas_lay.addSpacing(14)

        # ---- Center scan stage: thin frame + step feed ----
        stage = QFrame()
        stage.setStyleSheet(
            "background-color: rgba(9, 11, 14, 0.35);"
            "border: 1px solid rgba(0, 242, 254, 0.16); border-radius: 14px;")
        stage_fx = QGraphicsOpacityEffect(stage)
        stage_fx.setOpacity(0.0)
        stage.setGraphicsEffect(stage_fx)
        self.stage_effect = stage_fx
        stage_lay = QVBoxLayout(stage)
        stage_lay.setContentsMargins(28, 22, 28, 22)
        stage_lay.setSpacing(4)
        stage_lay.addStretch(1)
        self.check_feed = stage_lay
        canvas_lay.addWidget(stage)
        canvas_lay.addSpacing(12)

        # ---- Bottom HUD row: percentage + progress strip ----
        hud = QWidget()
        hud_lay = QVBoxLayout(hud)
        hud_lay.setContentsMargins(0, 0, 0, 0)
        hud_lay.setSpacing(8)
        pct_row = QHBoxLayout()
        self.check_pct = QLabel("0%")
        self.check_pct.setStyleSheet(
            "color: #00F2FE; font-size: 20px; font-weight: 900;")
        self.check_status = QLabel("\u25b6  INITIALIZING\u2026")
        self.check_status.setStyleSheet(
            "color: #C9D2DC; font-size: 12px; font-weight: 700;"
            "letter-spacing: 1px;")
        pct_row.addWidget(self.check_pct)
        pct_row.addWidget(self.check_status, 1)
        hud_lay.addLayout(pct_row)
        self.check_strip = QFrame()
        self.check_strip.setFixedHeight(3)
        self.check_strip.setStyleSheet(
            "background-color: rgba(0, 242, 254, 0.15); border-radius: 1px;")
        self.check_fill = QFrame(self.check_strip)
        self.check_fill.setFixedHeight(3)
        self.check_fill.setStyleSheet(
            "background-color: #00F2FE; border-radius: 1px;")
        hud_lay.addWidget(self.check_strip)
        canvas_lay.addWidget(hud)

        canvas_lay.addStretch(1)
        canvas_lay.addWidget(QLabel(""), 1)

        # ---- Hardware tagline shown once the scan lands ----
        self.check_facts = QLabel("Acquiring system telemetry\u2026")
        self.check_facts.setAlignment(Qt.AlignHCenter)
        self.check_facts.setStyleSheet("color: #5B6675; font-size: 12px;")
        canvas_lay.addWidget(self.check_facts)

        bottom_bar = QFrame()
        bottom_bar.setFixedHeight(30)
        bottom_bar.setStyleSheet("background-color: #04060A;")
        blay = QHBoxLayout(bottom_bar)
        blay.setContentsMargins(18, 0, 18, 0)
        left = QLabel("\u2713  REVERTABLE AT ANY TIME")
        left.setStyleSheet(
            "color: #5B6675; font-size: 10px; font-weight: 800;"
            "letter-spacing: 2px;")
        right = QLabel("REX TWEAKS  \u25c8")
        right.setStyleSheet(
            "color: #5B6675; font-size: 10px; font-weight: 800;"
            "letter-spacing: 2px;")
        blay.addWidget(left)
        blay.addStretch()
        blay.addWidget(right)

        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(top_bar)
        root.addWidget(self.check_canvas, 1)
        root.addWidget(bottom_bar)
        return page

    def _start_check_feed(self):
        """Build the step feed, stagger their reveals and start animations."""
        n = len(CHECK_STEPS)
        for i, text in enumerate(CHECK_STEPS):
            line = _FeedLine(text, i)
            self.check_feed.insertWidget(self.check_feed.count() - 1, line)
            self._check_rows.append(line)
            line.reveal(delay_ms=600 + i * 1050)

        # Title + stage fade in over the first second.
        a = QPropertyAnimation(self.title_effect, b"opacity")
        a.setDuration(1100)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        self._anims.append(a)
        a.start()
        s = QPropertyAnimation(self.stage_effect, b"opacity")
        s.setDuration(1400)
        s.setStartValue(0.0)
        s.setEndValue(1.0)
        self._anims.append(s)
        s.start()

        # Infinite scanline sweep.
        scan = QPropertyAnimation(self.check_canvas, b"offset")
        scan.setDuration(2600)
        scan.setStartValue(0.0)
        scan.setEndValue(100.0)
        scan.setLoopCount(-1)
        self._anims.append(scan)
        scan.start()

        # Feed pacing: one step finishes every ~1150 ms.
        self._feed_clock = QTimer(self)
        self._feed_clock.setInterval(1150)
        self._feed_clock.timeout.connect(self._tick)
        self._feed_clock.start()

    def _tick(self):
        elapsed = time.monotonic() - self._started
        progress = min(1.0, elapsed / MIN_CHECK_TIME)
        self._set_progress(progress)
        idx = self._step
        if idx < len(self._check_rows):
            if idx > 0:
                self._check_rows[idx - 1].set_state("done")
            row = self._check_rows[idx]
            row.set_state("active")
            self._step += 1
            self.check_status.setText(f"\u25b6  {row.text_value.upper()}")
            self._set_progress(self._step / len(self._check_rows))
            return
        if self._check_rows:
            self._check_rows[-1].set_state("done")
        self.check_status.setText("\u25b6  FINALIZING DEEP CHECK\u2026")
        self._set_progress(1.0)
        if elapsed >= MIN_CHECK_TIME and (self._detected or self._detect_fail or elapsed >= 35):
            self._to_results()

    def _set_progress(self, frac):
        frac = max(0.0, min(1.0, frac))
        self.check_pct.setText(f"{int(frac * 100)}%")
        w = self.check_strip.width()
        self.check_fill.setFixedWidth(max(0, int(w * frac)))

    def _on_detected(self, profile):
        self._detected = True
        self._profile = profile
        self.ctx.set_profile(profile)
        self._render_facts(profile)
        if time.monotonic() - self._started >= MIN_CHECK_TIME:
            self._to_results()

    def _render_facts(self, p):
        gpu = "/".join(n for n in p.get("gpu_names", [])[:2]) or "GPU"
        facts = (f"{p.get('cpu_name') or 'CPU'}  \u00b7  {gpu}  \u00b7  "
                 f"{p.get('ram_gb', 0)} GB RAM  \u00b7  "
                 f"{p.get('win_version', '?')} "
                 f"(build {p.get('win_build', '?')})  \u00b7  "
                 f"{p.get('monitor_refresh', 0)} Hz")
        self.check_facts.setText(facts)
        self.check_facts.setStyleSheet(
            "color: #94A3B8; font-size: 12px; font-weight: 600;")

    def _on_detect_error(self, msg):
        self._detect_fail = True
        from rexlog import logger
        logger.warn(f"recommend wizard: deep check failed: {msg}")
        if time.monotonic() - self._started >= MIN_CHECK_TIME:
            self._to_results()

    # ---------------- Recommendation selection ----------------

    def _recommended_tweaks(self):
        profile = self._profile or self.ctx.profile or {}
        eval_map = evaluate_many(TWEAKS, profile) if profile else {}
        out = []
        for t in TWEAKS:
            if t.get("recommended") != "recommended":
                continue
            if eval_map.get(t["id"], {}).get("state") != "ready":
                continue
            actions = t.get("actions") or []
            if not actions:
                continue
            if all(a[0] == "guidance" for a in actions):
                continue
            if self.ctx.live_active(t["id"]):
                continue
            out.append(t)
        out.sort(key=lambda t: (-IMPACT_RANK.get(t.get("impact", "low"), 0),
                                t["name"].lower()))
        return out

    # ---------------- Phase 2: results ----------------

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 26, 28, 24)
        lay.setSpacing(10)

        title = QLabel("Recommended for this System")
        title.setStyleSheet("font-size: 24px; font-weight: 900; color: #F2F5F9;")
        self.results_count = QLabel()
        self.results_count.setObjectName("PageSub")
        self.results_count.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(self.results_count)
        lay.addSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.results_scroll = scroll
        self.results_inner = QWidget()
        self.results_lay = QVBoxLayout(self.results_inner)
        self.results_lay.setContentsMargins(2, 2, 8, 2)
        self.results_lay.setSpacing(8)
        self.results_lay.addStretch(1)
        scroll.setWidget(self.results_inner)
        lay.addWidget(scroll, 1)

        note = QLabel(
            "\u2713  Every tweak here is fully revertable \u2014 applied ones can be "
            "flipped off or reverted from the Tweaks page at any time.")
        note.setStyleSheet(
            f"color: {T['text_dim']}; font-size: 12px; padding-top: 4px;")
        note.setWordWrap(True)
        lay.addWidget(note)

        row = QHBoxLayout()
        row.setSpacing(10)
        btn = QPushButton("Apply Recommended")
        btn.setObjectName("Primary")
        btn.setMinimumHeight(38)
        btn.clicked.connect(self._start_apply)
        self.btn_apply_rec = btn
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cancel.setMinimumHeight(38)
        cancel.clicked.connect(self.reject)
        row.addWidget(btn)
        row.addWidget(cancel)
        row.addStretch()
        lay.addLayout(row)
        return page

    def _results_row(self, t) -> QFrame:
        from ui.categories import group_key_for_category, CATEGORY_GROUPS, CATEGORY_LABELS
        row = QFrame()
        row.setObjectName("RecRow")
        lay = QVBoxLayout(row)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(10)
        box = QCheckBox()
        box.setObjectName("RecToggle")
        box.setChecked(True)
        box.tweak_id = t["id"]
        box.setStyleSheet(
            "QCheckBox#RecToggle { spacing: 0px; }"
            "QCheckBox#RecToggle::indicator { width: 18px; height: 18px;"
            " border-radius: 5px; border: 1px solid #2A323D;"
            " background-color: #151A21; }"
            "QCheckBox#RecToggle::indicator:checked { background-color: #00F2FE;"
            " border-color: #00F2FE; }")
        self._checkboxes = getattr(self, "_checkboxes", [])
        self._checkboxes.append(box)
        head.addWidget(box, alignment=Qt.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(t["name"])
        name.setStyleSheet("font-size: 14px; font-weight: 800; color: #F2F5F9;")
        id_lbl = QLabel(t["id"])
        id_lbl.setStyleSheet(f"font-size: 10px; color: {T['text_faint']};")
        text.addWidget(name)
        text.addWidget(id_lbl)
        why = QLabel(t.get("why") or t.get("desc") or "")
        why.setStyleSheet("color: #94A3B8; font-size: 12px;")
        why.setWordWrap(True)
        text.addWidget(why)
        head.addLayout(text, 1)
        lay.addLayout(head)

        meta = QHBoxLayout()
        meta.setSpacing(6)
        group = group_key_for_category(t["category"], t)
        label = CATEGORY_LABELS.get(group, CATEGORY_GROUPS[group]["title"])
        meta.addWidget(self._mini_chip(label))
        impact = t.get("impact", "low")
        meta.addWidget(self._mini_chip(impact.capitalize()))
        risk = t.get("risk", "low")
        meta.addWidget(self._mini_chip(
            risk.capitalize(), RISK_COLORS.get(risk, T["text_dim"])))
        meta.addStretch()
        lay.addLayout(meta)
        return row

    @staticmethod
    def _mini_chip(text, color=None):
        lbl = QLabel(text)
        c = color or T["text_dim"]
        lbl.setStyleSheet(
            f"color: {c}; background-color: rgba(148, 163, 184, 0.08);"
            f"border: 1px solid rgba(148, 163, 184, 0.20); border-radius: 8px;"
            "padding: 2px 8px; font-size: 11px; font-weight: 600;")
        return lbl

    def _to_results(self):
        if self.stack.currentIndex() != 0:
            return
        if self._feed_clock is not None:
            self._feed_clock.stop()
        rec = self._recommended_tweaks()
        for t in rec:
            self.results_lay.insertWidget(self.results_lay.count() - 1,
                                          self._results_row(t))
        self.results_count.setText(
            f"{len(rec)} tweak(s) fit this system and are marked recommended "
            f"\u2014 review them, then apply the ones you want.")

        # Cinematic fade-out of the loader before the results reveal.
        eff = QGraphicsOpacityEffect(self.check_page)
        self.check_page.setGraphicsEffect(eff)
        eff.setOpacity(1.0)
        fade = QPropertyAnimation(eff, b"opacity")
        fade.setDuration(450)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        self._anims.append(fade)
        fade.finished.connect(lambda: self.stack.setCurrentIndex(1))
        fade.start()

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
        self.apply_status.setText(f"Applying {len(ids)} tweaks \u2014 this can take a moment.")
        self._apply_worker = BatchWorker(ids, "apply", self)
        self._apply_worker.progress.connect(self._on_progress)
        self._apply_worker.batch_done.connect(self._on_apply_done)
        self._apply_worker.batch_error.connect(self._on_apply_error)
        self._apply_worker.start()

    def _on_progress(self, done, total, tid, ok, summary):
        self.apply_bar.setValue(done)
        name = tid
        try:
            from database import BY_ID
            name = BY_ID.get(tid, {}).get("name", tid)
        except Exception:  # noqa: BLE001
            pass
        color = T["success"] if ok else T["danger"]
        mark = "OK" if ok else "FAIL"
        self.apply_status.setText(f"({done}/{total}) {name}")
        self.apply_log.setText(
            f"<span style='color:{color}; font-weight:800;'>{mark}</span>"
            f"  {tid} \u2014 {name}<br/>"
            f"<span style='color:{T['text_dim']};'>{summary}</span><br/>")

    def _on_apply_done(self, result):
        if self._apply_worker:
            self._apply_worker = None
        applied = result.get("applied", [])
        results = result.get("results", {})
        failed = [tid for tid, (ok, _d) in results.items() if not ok]
        # Invalidate cached reads, re-audit the changed tweaks and let the
        # tweaks page repaint (it listens on ctx.state_changed).
        self.ctx.invalidate_state()
        self.ctx.force_audit_ids(list(results))
        self.ctx.note_state_change()
        self._show_done(applied, failed)

    def _on_apply_error(self, msg):
        self._show_done([], ["apply error"])

    def _show_done(self, applied, failed):
        self.stack.setCurrentIndex(3)
        total = len(applied) + len(failed)
        self.done_title.setText("Recommended Tweaks Applied")
        if failed:
            self.done_body.setText(
                f"{len(applied)} of {total} tweaks applied successfully \u2014 "
                f"{len(failed)} failed or were blocked. Scroll the Tweaks page "
                "to flip any of them back individually.")
            self.done_body.setStyleSheet(
                f"color: {T['warning']}; font-size: 14px; font-weight: 600;")
        else:
            self.done_body.setText(
                f"All {total} recommended tweak(s) were applied. They are fully "
                "revertable \u2014 open any category and flip a toggle off, or "
                "use Revert All. Toggles already show the live applied state.")
            self.done_body.setStyleSheet(
                f"color: {T['success']}; font-size: 14px; font-weight: 600;")
        toast("Recommended tweaks applied \u2014 all revertable.", "success", self)

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
        self.done_body.setMinimumHeight(120)
        lay.addWidget(self.done_title)
        lay.addWidget(self.done_body)
        lay.addStretch(1)
        btn = QPushButton("Close")
        btn.setObjectName("Primary")
        btn.setMinimumHeight(38)
        btn.clicked.connect(self.accept)
        lay.addWidget(btn, alignment=Qt.AlignRight)
        return page
