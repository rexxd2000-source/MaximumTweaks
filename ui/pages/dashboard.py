"""Maximum Tweaks Engine Dashboard — reference redesign v2.2.

Rebuilt to match the dashboard.html reference layout:
  · flat #05060A backdrop with glow blobs + 34px dot grid
  · topbar identity ("Welcome back, …") + glass status pills
  · mono hardware chip row
  · Live telemetry panel: three ring gauges (CPU gold / GPU cyan / RAM violet)
  · Thermal & clock stability chart with GPU/CPU tabs + gold/cyan legend
  · Ultra Mode rollout panel (lock, 64% progress, waitlist ghost button)
  · System storage panel (segmented OS/Games bar, key + AppData foot) with
    one-click cache cleanup
  · Active profile quick-state card with gradient primary CTA

Metrics keep streaming from engine.telemetry on a background thread.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsBlurEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config.app_config import DIRS, current_windows_user
from engine import license as license_mgr, state as state_mgr
from engine.telemetry import TelemetrySampler, invalidate_disk_cache
from ui.monitor_widgets import (
    CleanupThread,
    DiskBar,
    GlassPanel,
    LatencyChart,
    LinkLabel,
    PulseDot,
    RingGauge,
    TogglePill,
)
from ui.widgets import clear_layout, nav_icon_pixmap, toast

# Reference palette
GOLD = "#FFB454"
CYAN = "#4BE8D8"
VIOLET = "#9C80FF"
TEXT = "#F6F4FC"
MUTED = "#928AAD"
FAINT = "#514A70"


class DashPill(QWidget):
    """Glass pill with a glowing status dot, used in the topbar/panels."""

    def __init__(self, text, dot_color, pulse=False, parent=None):
        super().__init__(parent)
        self._dot_color = dot_color
        self.setObjectName("DashStatusPill")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        dot = PulseDot(dot_color, 6) if pulse else self._plain_dot()
        lay.addWidget(dot)
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 11.5px; color: #928AAD;")
        lay.addWidget(lbl)
        self._lbl = lbl

    def _plain_dot(self):
        dot = QLabel()
        dot.setFixedSize(6, 6)
        dot.setStyleSheet(
            f"background-color: {self._dot_color}; border-radius: 3px;"
            f" border: 1px solid {self._dot_color};")
        return dot

    def set_text(self, text):
        self._lbl.setText(text)


class _GradText(QLabel):
    """background-clip:text gradient heading (html h1 in ultra/profile)."""

    def __init__(self, text, top="#FFFFFF", bottom="#D8C9FF",
                 top_stop=0.40, parent=None):
        super().__init__(text, parent)
        self._top = QColor(top)
        self._bottom = QColor(bottom)
        self._stop = top_stop

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        from PySide6.QtGui import QFontMetrics
        tw = QFontMetrics(self.font()).horizontalAdvance(self.text())
        g = QLinearGradient(0, 0, max(20.0, tw * 1.02), self.height())
        g.setColorAt(0.0, self._top)
        g.setColorAt(self._stop, self._top)
        g.setColorAt(1.0, self._bottom)
        pen = QPen()
        pen.setBrush(QBrush(g))
        p.setPen(pen)
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, self.text())
        p.end()


class _LockChip(QFrame):
    """html .lock — 34px amber gradient tile with blurred halo + svg."""

    LOCK_SVG = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        'fill="none"><rect x="5" y="11" width="14" height="9" rx="2" '
        'stroke="#f0b429" stroke-width="2"/>'
        '<path d="M8 11V7a4 4 0 018 0v4" stroke="#f0b429" '
        'stroke-width="2"/></svg>')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtWidgets import QVBoxLayout
        pm = QPixmap(15, 15)
        pm.fill(Qt.transparent)
        pp = QPainter(pm)
        pp.setRenderHint(QPainter.Antialiasing)
        pp.setRenderHint(QPainter.TextAntialiasing)
        r = QSvgRenderer()
        r.load(self.LOCK_SVG.encode("utf-8"))
        r.render(pp, QRectF(0, 0, 15, 15))
        pp.end()
        lbl = QLabel(self)
        lbl.setPixmap(pm)
        lbl.move(10, 10)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        glow = QRadialGradient(17, 17, 25)
        glow.setColorAt(0.0, QColor(240, 180, 41, 76))
        glow.setColorAt(1.0, QColor(240, 180, 41, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawRoundedRect(-8, -8, 50, 50, 16, 16)
        g = QLinearGradient(0, 0, 0.36, 1)
        g.setColorAt(0.0, QColor("#3A2B0F"))
        g.setColorAt(1.0, QColor("#1C150A"))
        p.setBrush(g)
        p.setPen(QPen(QColor(240, 180, 41, 64), 1))
        p.drawRoundedRect(0.5, 0.5, 33, 33, 9, 9)
        p.end()


class _UltraCard(QFrame):
    """html .card — #0c0a13 with the amber radial top-right."""

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 16, 16)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor("#0C0A13"))
        g = QRadialGradient(self.width(), -self.height() * 0.15, 320)
        g.setColorAt(0.0, QColor(240, 180, 41, 23))
        g.setColorAt(1.0, QColor(240, 180, 41, 0))
        p.fillRect(self.rect(), g)
        p.end()


class _UltraWrap(QFrame):
    """html .card-wrap — 1px amber\u2192violet gradient border ring."""

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        g = QLinearGradient(0, 0, self.width() * 0.38, self.height())
        g.setColorAt(0.0, QColor(240, 180, 41, 115))
        g.setColorAt(0.6, QColor(155, 140, 255, 71))
        g.setColorAt(1.0, QColor(255, 255, 255, 13))
        p.setPen(QPen(QBrush(g), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(0.5, 0.5, self.width() - 1, self.height() - 1,
                          17, 17)
        p.end()


class GaugeGlyph(QWidget):
    """Renders the real bundled CPU / GPU / RAM logo PNG — the exact glossy
    icons used in the sidebar and category cards."""

    def __init__(self, kind, color, size=18, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        pm = QPixmap()
        path = DIRS["assets"] / "icons" / f"{kind}.png"
        if path.is_file():
            pm = QPixmap(str(path))
        if pm.isNull():
            pm = nav_icon_pixmap(kind, color=color, size=size)
            self._pm = pm
            return
        self._pm = pm.scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        if self._pm.isNull():
            return
        p.drawPixmap(0, 0, self._pm)
        p.end()


class _Atmosphere(QWidget):
    """Flat dashboard backdrop: glow blobs + a subtle dot grid."""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()

        base = QColor("#05060A")
        base.setAlpha(255)
        p.fillRect(self.rect(), base)

        # violet glow top-left
        ga = QRadialGradient(QPointF(w * 0.1 - 60, h * 0.12), max(w, h) * 0.55)
        ga.setColorAt(0.0, QColor(167, 139, 255, 90))
        ga.setColorAt(0.55, QColor(167, 139, 255, 24))
        ga.setColorAt(1.0, QColor(167, 139, 255, 0))
        p.fillRect(self.rect(), ga)

        # cyan glow bottom-right
        gb = QRadialGradient(QPointF(w * 1.05, h * 1.05), max(w, h) * 0.5)
        gb.setColorAt(0.0, QColor(95, 227, 236, 55))
        gb.setColorAt(0.6, QColor(95, 227, 236, 14))
        gb.setColorAt(1.0, QColor(95, 227, 236, 0))
        p.fillRect(self.rect(), gb)

        # .dots — 34px dot grid masked around the upper-center (replaces the
        # old HUD line grid, which read as scribbled overlapping lines).
        cx, cy = 0.60 * w, 0.20 * h
        rx, ry = 0.70 * w, 0.60 * h
        if rx > 0 and ry > 0:
            y = 17.0
            while y < h:
                x = 17.0
                while x < w:
                    t = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
                    t **= 0.5
                    if t < 0.85:
                        alpha = int(45 * (1.0 - t / 0.85))
                        if alpha > 3:
                            p.setPen(QColor(200, 190, 240, alpha))
                            p.drawPoint(QPointF(x, y))
                    x += 34.0
                y += 34.0


class DashboardPage(QWidget):
    def __init__(self, ctx, navigate, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.navigate = navigate
        self._last: dict = {}
        self._clean_thread: CleanupThread | None = None
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Flat reference backdrop sitting behind the scroll content.
        self._atmo = _Atmosphere(self)
        self._atmo.setGeometry(0, 0, 10, 10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 24, 28, 40)
        lay.setSpacing(16)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(16)

        cl.addWidget(self._build_topbar())
        cl.addWidget(self._build_hw_row())

        telemetry = self._build_telemetry_panel()
        cl.addWidget(telemetry)

        # grid-2: thermal chart — full width now the profile card is gone
        chart = self._build_chart_panel()
        cl.addWidget(chart)

        # grid-2b: storage (1.2fr) + Ultra Mode (1fr) — Ultra moved into the
        # slot the active-profile card used to occupy
        grid2b = QGridLayout()
        grid2b.setSpacing(14)
        storage = self._build_storage_panel()
        ultra = self._build_ultra_panel()
        grid2b.addWidget(storage, 0, 0)
        grid2b.addWidget(ultra, 0, 1)
        grid2b.setColumnStretch(0, 12)
        grid2b.setColumnStretch(1, 10)
        cl.addLayout(grid2b)

        cl.addStretch()
        lay.addWidget(content)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self._atmo.raise_()
        self._atmo.lower()

        self.ctx.profile_changed.connect(self._refresh_hw)
        self.ctx.pfp_changed.connect(self._refresh_hw)
        self.ctx.license_changed.connect(self._refresh_license_pill)
        self._refresh_hw()
        self._refresh_license_pill()

        self.sampler = TelemetrySampler(self)
        self.sampler.metrics.connect(self._on_metrics)
        self.sampler.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._atmo.setGeometry(self.rect())

    # ---------------- Topbar: identity + status pills ----------------

    def _build_topbar(self):
        top = QWidget()
        lay = QHBoxLayout(top)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        ident = QVBoxLayout()
        ident.setSpacing(3)
        self.welcome_label = QLabel(f"Welcome back, {current_windows_user()}")
        self.welcome_label.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #F6F4FC;")
        ident.addWidget(self.welcome_label)
        self.quote_label = QLabel("Every optimization counts.")
        self.quote_label.setStyleSheet(
            "font-size: 12.5px; color: #928AAD;")
        ident.addWidget(self.quote_label)
        ident.addStretch()
        lay.addLayout(ident, 1)

        status = QHBoxLayout()
        status.setSpacing(9)
        self.license_pill = DashPill("License active", "#6FE29A")
        live_pill = DashPill("Telemetry live", VIOLET, pulse=True)
        status.addWidget(self.license_pill)
        status.addWidget(live_pill)
        lay.addLayout(status)
        return top

    def _refresh_license_pill(self):
        if getattr(self, "license_pill", None) is None:
            return
        sess = license_mgr.session()
        if sess and license_mgr.is_authorized():
            self.license_pill.set_text("License active")
        else:
            self.license_pill.set_text("Awaiting activation")

    # ---------------- Hardware chip row ----------------

    def _build_hw_row(self):
        bar = QWidget()
        self.hw_lay = QHBoxLayout(bar)
        self.hw_lay.setContentsMargins(0, 0, 0, 12)
        self.hw_lay.setSpacing(8)
        self.scan_status = QLabel("Scanning system...")
        self.scan_status.setStyleSheet(
            "font-size: 11.5px; font-family: \"JetBrains Mono\", \"JetBrains Mono\","
            " monospace; color: #928AAD; background-color: rgba(255,255,255,0.03);"
            " border: 1px solid rgba(255,255,255,0.09); border-radius: 8px;"
            " padding: 5px 11px;")
        return bar

    def _hw_chip(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("DashChip")
        return lbl

    def _refresh_hw(self):
        clear_layout(self.hw_lay)
        profile = self.ctx.profile or {}
        if profile:
            self.hw_lay.addWidget(self._hw_chip(
                f"Windows {profile.get('win_version', '?')} \u00b7 build {profile.get('win_build', 0)}"))
            self.hw_lay.addWidget(self._hw_chip(
                "Laptop" if profile.get("laptop") else "Desktop"))
            cpu = (profile.get("cpu_name") or "")[:34]
            if cpu:
                self.hw_lay.addWidget(self._hw_chip(cpu))
            gpu = " / ".join(profile.get("gpu_names", []))
            if gpu:
                self.hw_lay.addWidget(self._hw_chip(gpu))
            self.hw_lay.addWidget(self._spacer())
        else:
            self.hw_lay.addWidget(self.scan_status)
            self.hw_lay.addWidget(self._spacer())

    def _spacer(self):
        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Policy.Expanding,
                         QSizePolicy.Policy.Fixed)
        return sp

    # ---------------- Live telemetry: ring gauges ----------------

    def _build_telemetry_panel(self):
        panel = GlassPanel(corner=VIOLET)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(14)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Live telemetry")
        title.setObjectName("DashPanelTitle")
        sub = QLabel("updated every second")
        sub.setObjectName("DashPanelSub")
        hl.addWidget(title)
        hl.addWidget(sub)
        hl.addStretch()
        lay.addWidget(head)

        row = QHBoxLayout()
        row.setSpacing(16)
        self._cpu_gauge = self._gauge_card(row, "CPU", GOLD, "cpu")
        self._gpu_gauge = self._gauge_card(row, "GPU", CYAN, "gpu")
        self._ram_gauge = self._gauge_card(row, "RAM", VIOLET, "ram")
        lay.addLayout(row)
        return panel

    def _gauge_card(self, row, name, color, kind):
        card = QWidget()
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        wrap = QWidget()
        g = QGridLayout(wrap)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(16)
        gauge = RingGauge(color)
        g.addWidget(gauge, 0, 0, 2, 1, Qt.AlignCenter)

        info = QVBoxLayout()
        info.setSpacing(6)
        lbl = QHBoxLayout()
        lbl.setSpacing(7)
        ic = GaugeGlyph(kind, color)
        nm = QLabel(name)
        nm.setStyleSheet("font-size: 12.5px; font-weight: 600; color: #F6F4FC;")
        lbl.addWidget(ic)
        lbl.addWidget(nm)
        lbl.addStretch()
        info.addLayout(lbl)

        detail = QLabel("")
        detail.setStyleSheet(
            "font-family: \"JetBrains Mono\", \"JetBrains Mono\", monospace;"
            " font-size: 11px; color: #928AAD; line-height: 1.7;")
        info.addWidget(detail)
        info.addStretch()
        g.addLayout(info, 0, 1)

        v.addWidget(wrap)
        v.addStretch()
        row.addWidget(card, 1)
        return gauge, detail

    # ---------------- Thermal & clock stability chart ----------------

    def _build_chart_panel(self):
        panel = GlassPanel(corner=CYAN)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(14)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Thermal & clock stability")
        title.setObjectName("DashPanelTitle")
        hl.addWidget(title)
        hl.addStretch()
        self.chart_pill = TogglePill(["GPU", "CPU"], default=1)
        self.chart_pill.changed.connect(self._on_chart_mode)
        hl.addWidget(self.chart_pill)
        lay.addWidget(head)

        # legend: gold temperature + cyan clock
        legend = QWidget()
        ll = QHBoxLayout(legend)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(16)
        for color, txt in ((GOLD, "Temperature"), (CYAN, "Clock speed")):
            item = QWidget()
            il = QHBoxLayout(item)
            il.setContentsMargins(0, 0, 0, 0)
            il.setSpacing(8)
            sw = QLabel()
            sw.setFixedSize(14, 2)
            sw.setStyleSheet(f"background-color: {color}; border-radius: 1px;")
            il.addWidget(sw)
            t = QLabel(txt)
            t.setStyleSheet("font-size: 11.5px; color: #928AAD;")
            il.addWidget(t)
            ll.addWidget(item)
        ll.addStretch()
        lay.addWidget(legend)

        self.latency_chart = LatencyChart()
        lay.addWidget(self.latency_chart)
        return panel

    def _on_chart_mode(self, mode: str):
        self.latency_chart.set_mode(mode.lower())

    # ---------------- Ultra Mode rollout panel ----------------

    def _build_ultra_panel(self):
        wrap = _UltraWrap()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(1, 1, 1, 1)
        card = _UltraCard()
        wl.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 22, 22, 24)
        lay.setSpacing(0)

        lay.addWidget(_LockChip())
        lay.addSpacing(14)

        eyebrow = QLabel("Ultra Mode")
        eyebrow.setStyleSheet(
            "font-size:11.5px;font-weight:600;color:#F0B429;"
            "background:transparent;")
        lay.addWidget(eyebrow)
        lay.addSpacing(14)

        title = _GradText("Building the max\u2011performance preset")
        tf = QFont(title.font())
        tf.setPixelSize(21)
        tf.setWeight(QFont.Bold)
        tf.setLetterSpacing(QFont.AbsoluteSpacing, -0.3)
        title.setFont(tf)
        title.setFixedHeight(30)
        lay.addWidget(title)
        lay.addSpacing(10)

        body = QLabel(
            "A single-click tuning profile that pushes clocks and fan "
            "curves to their tested ceiling. In closed testing now.")
        body.setWordWrap(True)
        body.setStyleSheet(
            "font-size:12.5px;color:#8B899C;background:transparent;")
        lay.addWidget(body)
        lay.addSpacing(22)

        plab = QHBoxLayout()
        pll = QLabel("Rollout progress")
        pll.setStyleSheet(
            "font-size:11px;color:#524F61;background:transparent;")
        pp = QLabel("64%")
        pp.setStyleSheet(
            "font-family:'JetBrains Mono',JetBrains Mono,monospace;"
            "font-size:12px;font-weight:600;color:#F5F3FA;"
            "background:transparent;")
        plab.addWidget(pll)
        plab.addStretch()
        plab.addWidget(pp)
        lay.addLayout(plab)
        lay.addSpacing(8)

        track = QFrame()
        track.setFixedHeight(5)
        track.setStyleSheet(
            "background:#1D1B28;border:none;border-radius:3px;")
        tl = QHBoxLayout(track)
        tl.setContentsMargins(0, 0, 0, 0)
        fill = QFrame()
        fill.setFixedHeight(5)
        fill.setMinimumWidth(0)
        fill.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #7C6DF2,stop:1 #9B8CFF);border:none;border-radius:3px;")
        tl.addWidget(fill)
        tl.addStretch()
        lay.addWidget(track)
        lay.addSpacing(20)

        wait = QPushButton("Join the waitlist")
        wait.setCursor(Qt.PointingHandCursor)
        wait.setStyleSheet(
            "QPushButton{border:none;border-top:1px solid"
            " rgba(255,255,255,0.25);border-radius:10px;"
            "padding:11px 0;font-size:13px;font-weight:600;color:#fff;"
            "background:qlineargradient(x1:0,y1:0,x2:0.37,y2:1,"
            "stop:0 #A99CFF,stop:1 #7C6DF2);}"
            "QPushButton:hover{background:qlineargradient("
            "x1:0,y1:0,x2:0.37,y2:1,stop:0 #B8ADFF,stop:1 #8878F5);}")
        wait.clicked.connect(
            lambda: toast("Ultra Mode is in closed testing \u2014 the "
                          "waitlist opens soon.", "info", self))
        lay.addWidget(wait)
        lay.addSpacing(14)

        link = LinkLabel("View the tweaks")
        link.setStyleSheet(
            "font-size:12.5px;font-weight:500;color:#9B8CFF;"
            "background:transparent;border:none;")
        link.setCursor(Qt.PointingHandCursor)
        link.clicked.connect(lambda: self.navigate("tweaks"))
        from PySide6.QtSvg import QSvgRenderer
        arr_pm = QPixmap(12, 12)
        arr_pm.fill(Qt.transparent)
        ap = QPainter(arr_pm)
        ap.setRenderHint(QPainter.Antialiasing)
        ap.setRenderHint(QPainter.TextAntialiasing)
        rr = QSvgRenderer()
        rr.load(
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            b'fill="none"><path d="M5 12h14M13 6l6 6-6 6" '
            b'stroke="#9b8cff" stroke-width="2" stroke-linecap="round" '
            b'stroke-linejoin="round"/></svg>')
        rr.render(ap, QRectF(0, 0, 12, 12))
        ap.end()
        arrow = QLabel()
        arrow.setPixmap(arr_pm)
        lr = QHBoxLayout()
        lr.setContentsMargins(0, 0, 0, 0)
        lr.addStretch()
        lr.addWidget(link)
        lr.addSpacing(5)
        lr.addWidget(arrow)
        lr.addStretch()
        lay.addLayout(lr)

        def grow():
            w = int(track.width() * 0.64)
            anim = QPropertyAnimation(fill, b"minimumWidth", self)
            anim.setDuration(1100)
            anim.setStartValue(0)
            anim.setEndValue(max(0, w))
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            self._ultra_anim = anim
        QTimer.singleShot(300, grow)
        return wrap

    # ---------------- System storage ----------------

    def _build_storage_panel(self):
        panel = GlassPanel(corner=CYAN)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("System storage")
        title.setObjectName("DashPanelTitle")
        head.addWidget(title)
        head.addStretch()
        clean = QPushButton("Clean system cache")
        clean.setObjectName("DashSmall")
        clean.setCursor(Qt.PointingHandCursor)
        clean.clicked.connect(self._on_clean)
        head.addWidget(clean)
        lay.addLayout(head)

        self.disk_used = QLabel("\u2014 GB of \u2014 GB used")
        self.disk_used.setStyleSheet(
            "font-family: \"JetBrains Mono\", \"JetBrains Mono\", monospace;"
            " font-size: 24px; font-weight: 600; color: #F6F4FC;"
            " margin-top: 4px;")
        lay.addWidget(self.disk_used)

        self.disk_free = QLabel("")
        self.disk_free.setStyleSheet(
            f"font-size: 11.5px; color: {FAINT}; margin-bottom: 12px;")
        lay.addWidget(self.disk_free)

        self.disk_bar = DiskBar()
        lay.addWidget(self.disk_bar)

        self.key_lbls: dict[str, tuple[QLabel, QLabel]] = {}
        key = QHBoxLayout()
        key.setSpacing(18)
        for keyname, color in (("OS", CYAN), ("Games", GOLD), ("Free", "#514A70")):
            item = QWidget()
            il = QHBoxLayout(item)
            il.setContentsMargins(0, 0, 0, 0)
            il.setSpacing(6)
            dot = QLabel()
            dot.setFixedSize(7, 7)
            dot.setStyleSheet(
                f"background-color: {color}; border-radius: 4px;")
            nm = QLabel(keyname)
            nm.setStyleSheet("font-size: 12px; color: #F6F4FC;")
            amt = QLabel("")
            amt.setStyleSheet(
                "font-family: \"JetBrains Mono\", \"JetBrains Mono\", monospace;"
                " font-size: 11px; color: #928AAD;")
            il.addWidget(dot)
            il.addWidget(nm)
            il.addWidget(amt)
            key.addWidget(item)
            self.key_lbls[keyname] = (nm, amt)
        key.addStretch()
        wrap = QWidget()
        wk = QVBoxLayout(wrap)
        wk.setContentsMargins(0, 14, 0, 0)
        wk.setSpacing(0)
        wk.addLayout(key)
        lay.addWidget(wrap)

        self.appdata_lbl = QLabel("")
        self.appdata_lbl.setStyleSheet(
            "font-family: \"JetBrains Mono\", \"JetBrains Mono\", monospace;"
            " font-size: 11.5px; color: #514A70;"
            " border-top: 1px solid rgba(255,255,255,0.06);"
            " padding-top: 10px; margin-top: 10px;")
        lay.addWidget(self.appdata_lbl)
        return panel

    def _update_disk(self, data: dict):
        used = data.get("disk_used_gb", 0)
        total = data.get("disk_total_gb", 0)
        free = data.get("disk_free_gb", 0)
        games = data.get("disk_games_gb", 0)
        appdata = data.get("disk_appdata_gb", 0)
        os_used = max(0.0, used - games)

        self.disk_used.setText(f"{used:.1f} GB of {total:.1f} GB used")
        label = data.get("disk_label")
        self.disk_free.setText(
            f"{free:.1f} GB free" + (f"  \u00b7  {label}" if label else ""))
        self.disk_bar.set_segments(
            [("OS", os_used, CYAN),
             ("Games", games, GOLD)],
            total)
        self.key_lbls["OS"][1].setText(f"{os_used:.0f} GB")
        self.key_lbls["Games"][1].setText(f"{games:.0f} GB")
        self.key_lbls["Free"][1].setText(f"{free:.0f} GB")
        if total:
            pct = appdata / total * 100.0
            self.appdata_lbl.setText(
                f"Local AppData \u00b7 {appdata:.1f} GB \u00b7 "
                f"{pct:.1f}% of this drive")

    # ---------------- Active profile ----------------

    def _on_metrics(self, data: dict):
        self._last = data

        freq = data.get("cpu_freq_mhz")
        freq_txt = f"{freq} MHz" if freq else "? MHz"
        self._cpu_gauge[0].set_value(data.get("cpu_percent", 0), GOLD)
        temp_txt = ""
        if data.get("cpu_temp"):
            temp_txt = f"  \u00b7  {data['cpu_temp']:.0f}\u00b0C"
        self._cpu_gauge[1].setText(
            f"{freq_txt}{temp_txt}\n"
            f"{data.get('cpu_threads', '?')} threads")

        gpu_util = data.get("gpu_util")
        if gpu_util is None:
            self._gpu_gauge[0].set_value(0, CYAN)
            self._gpu_gauge[1].setText("No GPU data available")
        else:
            self._gpu_gauge[0].set_value(gpu_util, CYAN)
            name = (data.get("gpu_name") or "GPU")[:28]
            temp_g = ""
            if data.get("gpu_temp"):
                temp_g = f" \u00b7  {data['gpu_temp']:.0f}\u00b0C"
            mem = f"{data.get('gpu_mem_used', 0)} / {data.get('gpu_mem_total', 0)} MB"
            self._gpu_gauge[1].setText(f"{name}{temp_g}\n{mem}")

        ram = data.get("ram_pct", 0)
        self._ram_gauge[0].set_value(ram, VIOLET)
        self._ram_gauge[1].setText(
            f"{data.get('ram_used_gb', 0)} / {data.get('ram_total_gb', 0)} GB\n"
            "allocated")

        self.latency_chart.add(data.get("cpu_temp"), data.get("gpu_temp"),
                               data.get("cpu_freq_mhz"))
        self._update_disk(data)

    # ---------------- Disk cleanup ----------------

    def _on_clean(self):
        if self._clean_thread is not None and self._clean_thread.isRunning():
            return
        self._clean_thread = CleanupThread(self)
        self._clean_thread.done.connect(self._on_clean_done)
        self._clean_thread.start()
        toast("Cleaning system cache\u2026", "info", self)

    def _on_clean_done(self, result: dict):
        errors = result.get("errors", 0)
        files = result.get("files", 0)
        if files:
            freed_mb = result.get("freed_bytes", 0) / 2**20
            msg = (f"Cleaned {files} files \u00b7 {result.get('folders', 0)} folders"
                   f" \u00b7 freed {freed_mb:.0f} MB")
            toast(msg, "warning" if errors else "success", self)
        else:
            toast("Temporary files are already clean.", "success", self)
        invalidate_disk_cache()

    # ---------------- Helpers ----------------

    def set_busy(self, busy: bool):
        self._busy = busy