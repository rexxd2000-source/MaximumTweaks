"""Rex Tweaks Engine Dashboard — the original telemetry control center.

Fully custom layout: Rex brand header with a prominent backend status block,
neon utilization bars (CPU / GPU / RAM), a dual-axis thermal + CPU clock
stability chart, an Official Discord community card, a compact Rex Ultra Mode
toggle, a system storage monitor with AppData tracking and one-click cache
cleanup, and the Active Profile quick-state card. Metrics are polled every
second on a background thread (engine.telemetry).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsBlurEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.app_config import ICONS, THEME as T
from engine import activity, discord_auth, state as state_mgr
from engine.telemetry import TelemetrySampler, invalidate_disk_cache
from ui.monitor_widgets import (
    BackendStatusBlock,
    CleanupThread,
    DiscordCommunityCard,
    DiskBar,
    GlassCard,
    LatencyChart,
    LinkLabel,
    NeonBar,
    RexLogo,
    TogglePill,
    threshold_color,
)
from ui import context
from ui.widgets import IconTile, ToggleSwitch, chip, clear_layout, toast


#: Rotating daily mini-quote shown under the dashboard welcome. Picked
#: deterministically from the date so it changes once per day.
DAILY_QUOTES = (
    "Ready to boost your performance.",
    "Every millisecond counts.",
    "Squeeze every last frame.",
    "Low latency, high frames.",
    "Your PC deserves a tune-up.",
    "Silky smooth or nothing.",
    "Turn every setting up.",
    "Fast, fluid, flawless.",
    "Push your hardware harder.",
    "Own the server, own the frame.",
    "More frames, less excuses.",
    "Small tweaks, big gains.",
    "Maximum power, minimum fuss.",
    "Stay ahead of the curve.",
)


class DashboardPage(QWidget):
    def __init__(self, ctx, navigate, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.navigate = navigate
        self._last: dict = {}
        self._clean_thread: CleanupThread | None = None
        self._busy = False
        self._discord_worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(4, 0, 10, 0)
        lay.setSpacing(10)

        lay.addWidget(self._build_header())
        lay.addWidget(self._build_system_bar())

        # ---- Main work area: asymmetric left telemetry / right utilities ----
        work = QGridLayout()
        work.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(10)
        left.addWidget(self._build_telemetry_card())
        left.addWidget(self._build_chart_card())
        work.addLayout(left, 0, 0)

        right = QWidget()
        right.setFixedWidth(324)
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(10)
        rlay.addWidget(DiscordCommunityCard())
        rlay.addWidget(self._build_ultra_card())
        rlay.addStretch()
        work.addWidget(right, 0, 1)
        work.setColumnStretch(0, 1)
        lay.addLayout(work)

        # ---- Bottom row: storage + active profile ----
        bottom = QGridLayout()
        bottom.setSpacing(14)
        bottom.addWidget(self._build_storage_card(), 0, 0)
        bottom.addWidget(self._build_profile_card(), 0, 1)
        bottom.setColumnStretch(0, 1)
        bottom.setColumnStretch(1, 1)
        lay.addLayout(bottom)

        lay.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.ctx.profile_changed.connect(self._refresh_hw)
        self.ctx.state_changed.connect(self._refresh_mode_card)
        self.ctx.state_changed.connect(self._refresh_profile_card)
        self.ctx.pfp_changed.connect(self._refresh_hw)
        self.ctx.discord_changed.connect(self._refresh_backend_block)
        self.ctx.discord_changed.connect(self._refresh_welcome)
        self._refresh_hw()
        self._refresh_mode_card()
        self._refresh_profile_card()

        self.sampler = TelemetrySampler(self)
        self.sampler.metrics.connect(self._on_metrics)
        self.sampler.start()

    # ---------------- Header / brand ----------------

    def _welcome_text(self):
        name = context.DISCORD_USERNAME
        if name:
            return f"Welcome, {name}!"
        return "Welcome, guest!"

    def _refresh_welcome(self):
        if getattr(self, "welcome_label", None) is not None:
            self.welcome_label.setText(self._welcome_text())

    def _daily_quote(self):
        import datetime
        return DAILY_QUOTES[datetime.date.today().toordinal() % len(DAILY_QUOTES)]

    def _build_header(self):
        hero = QFrame()
        hero.setObjectName("Hero")
        lay = QHBoxLayout(hero)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(14)

        brand = QHBoxLayout()
        brand.setSpacing(12)
        self.dash_avatar = RexLogo(46)
        brand.addWidget(self.dash_avatar)
        box = QVBoxLayout()
        box.setSpacing(3)
        self.welcome_label = QLabel(self._welcome_text())
        self.welcome_label.setStyleSheet(
            "font-size: 28px; font-weight: 900; letter-spacing: 0.3px;")
        box.addWidget(self.welcome_label)
        self.quote_label = QLabel(self._daily_quote())
        self.quote_label.setStyleSheet(
            f"color: {T['text_dim']}; font-size: 15px; font-weight: 600;"
            " font-style: italic;")
        box.addWidget(self.quote_label)
        box.addStretch()
        brand.addLayout(box, 1)
        lay.addLayout(brand, 1)

        # Prominent backend status block, vertically centered in the header.
        self.backend_block = BackendStatusBlock()
        self._refresh_backend_block()
        lay.addWidget(self.backend_block, 0, Qt.AlignVCenter)
        return hero

    def _build_system_bar(self):
        bar = QFrame()
        bar.setObjectName("SysBar")
        blay = QHBoxLayout(bar)
        blay.setContentsMargins(12, 8, 12, 8)
        blay.setSpacing(8)
        self.scan_status = QLabel("Scanning system...")
        self.scan_status.setStyleSheet(
            f"color: {T['accent']}; font-size: 11px; font-weight: 600;")
        self.scan_status.hide()
        blay.addWidget(self.scan_status)
        self.header_chips = QHBoxLayout()
        self.header_chips.setSpacing(8)
        blay.addLayout(self.header_chips)
        blay.addStretch()
        return bar

    def _refresh_backend_block(self):
        prof = discord_auth.session()
        if prof:
            color = T["accent"] if prof.get("verified") else T["warning"]
            self.backend_block.set_status("CONNECTED TO BACKEND", color)
        else:
            self.backend_block.set_status("AWAITING CONNECTION", T["warning"])


    def _refresh_hw(self):
        profile = self.ctx.profile or {}
        clear_layout(self.header_chips)
        handle = state_mgr.get_handle()
        if handle:
            self.header_chips.addWidget(self._hw_chip(f"\u25cf {handle}"))
        if profile:
            self.scan_status.hide()
            self.header_chips.addWidget(self._hw_chip(
                f"Windows {profile.get('win_version', '?')} \u00b7 build {profile.get('win_build', 0)}"))
            self.header_chips.addWidget(self._hw_chip(
                "Laptop" if profile.get("laptop") else "Desktop"))
            cpu = (profile.get("cpu_name") or "")[:34]
            if cpu:
                self.header_chips.addWidget(self._hw_chip(cpu))
            gpu = " / ".join(profile.get("gpu_names", []))
            if gpu:
                self.header_chips.addWidget(self._hw_chip(gpu))
        else:
            self.scan_status.show()
        self.header_chips.addStretch()

    def _hw_chip(self, text):
        lbl = chip(text)
        fm = lbl.fontMetrics()
        lbl.setText(fm.elidedText(text, Qt.ElideRight, 300))
        lbl.setMaximumWidth(300)
        lbl.setMinimumWidth(0)
        return lbl

    # ---------------- Live telemetry bars ----------------

    def _build_telemetry_card(self):
        card = GlassCard()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel("Live Telemetry")
        title.setObjectName("GlassCardTitle")
        head.addWidget(title)
        live = QLabel("\u25cf LIVE")
        live.setStyleSheet(f"color: {T['accent']}; font-size: 10px; font-weight: 800;"
                           " letter-spacing: 1px;")
        head.addWidget(live)
        head.addStretch()
        lay.addLayout(head)

        self.cpu_row = self._metric_row(ICONS["cpu"], "CPU")
        self.gpu_row = self._metric_row(ICONS["gpu"], "GPU")
        self.ram_row = self._metric_row(ICONS["ram"], "RAM")
        for row in (self.cpu_row, self.gpu_row, self.ram_row):
            lay.addWidget(row[0])
        return card

    def _metric_row(self, icon, name):
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(IconTile(icon, T["accent"], size=26, font_scale=0.5))
        nm = QLabel(name)
        nm.setStyleSheet("font-size: 13px; font-weight: 800; letter-spacing: 1px;")
        top.addWidget(nm)
        top.addStretch()
        val = QLabel("\u2014")
        val.setMinimumWidth(64)
        val.setStyleSheet(f"font-size: 20px; font-weight: 900; color: {T['accent']};")
        top.addWidget(val)
        v.addLayout(top)
        bar = NeonBar()
        v.addWidget(bar)
        sub = QLabel("")
        sub.setObjectName("GaugeSub")
        v.addWidget(sub)
        return (wrap, val, bar, sub)

    @staticmethod
    def _update_metric(row, pct: float, sub: str, temp: float | None = None):
        _, val, bar, sub_lbl = row
        color = threshold_color(pct)
        val.setText(f"{pct:.0f}%")
        val.setStyleSheet(f"font-size: 20px; font-weight: 900; color: {color};")
        bar.set_value(pct, color)
        if temp is not None:
            sub = f"{sub}  \u00b7  {temp:.0f}\u00b0C"
        sub_lbl.setText(sub)

    # ---------------- Thermal & clock stability chart ----------------

    def _build_chart_card(self):
        card = GlassCard()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel("Thermal & Clock Stability")
        title.setObjectName("GlassCardTitle")
        head.addWidget(title)
        head.addStretch()
        self.chart_pill = TogglePill(["GPU", "CPU"], default=1)
        self.chart_pill.changed.connect(self._on_chart_mode)
        head.addWidget(self.chart_pill)
        lay.addLayout(head)
        self.latency_chart = LatencyChart()
        lay.addWidget(self.latency_chart)
        return card

    def _on_chart_mode(self, mode: str):
        self.latency_chart.set_mode(mode.lower())

    # ---------------- Rex Ultra Mode ----------------

    def _build_ultra_card(self):
        card = GlassCard()
        grid = QGridLayout(card)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        content = QWidget(card)
        clay = QVBoxLayout(content)
        clay.setContentsMargins(16, 12, 16, 12)
        clay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(IconTile("\u26a1", T["accent"], size=28, font_scale=0.45))
        title = QLabel("Rex Ultra Mode")
        title.setObjectName("GlassCardTitle")
        title.setStyleSheet("font-size: 13px; font-weight: 800; letter-spacing: 0.5px;")
        head.addWidget(title)
        head.addStretch()
        self.mode_toggle = ToggleSwitch()
        self.mode_toggle.setEnabled(False)
        self.mode_toggle.setToolTip("Coming soon")
        head.addWidget(self.mode_toggle)
        clay.addLayout(head)

        self.mode_pill = QLabel()
        self.mode_pill.setObjectName("StatusPill")
        clay.addWidget(self.mode_pill, 0, Qt.AlignLeft)

        desc = QLabel(
            "Max-performance preset: zero background CPU reserve and network "
            "packet throttling disabled. One click to engage, one click to "
            "release.")
        desc.setObjectName("CardDetail")
        desc.setWordWrap(True)
        clay.addWidget(desc)

        opt = QPushButton("Open Optimizer")
        opt.setObjectName("Primary")
        opt.clicked.connect(lambda: self.navigate("optimize"))
        clay.addWidget(opt)

        view = LinkLabel("View the tweaks  \u2192")
        view.setObjectName("LinkBtn")
        view.clicked.connect(lambda: self.navigate("tweaks"))
        clay.addWidget(view, 0, Qt.AlignLeft)

        # Locked state: blur the whole card and block interactions.
        blur = QGraphicsBlurEffect(content)
        blur.setBlurRadius(5)
        content.setGraphicsEffect(blur)
        content.setEnabled(False)

        # Overlay design: frosted emblem with the COMING SOON lock message,
        # stacked over the blurred content so it stays dead-centered.
        overlay = QFrame(card)
        overlay.setObjectName("UltraSoon")
        olay = QVBoxLayout(overlay)
        olay.setContentsMargins(18, 16, 18, 16)
        olay.setSpacing(4)
        crow = QHBoxLayout()
        crow.setSpacing(8)
        crow.addWidget(IconTile("\u26a1", T["accent"], size=22, font_scale=0.5))
        ctitle = QLabel("REX ULTRA MODE")
        ctitle.setStyleSheet(
            f"color: {T['text_dim']}; font-size: 10px; font-weight: 800;"
            "letter-spacing: 1.5px;")
        crow.addWidget(ctitle)
        crow.addStretch()
        olay.addLayout(crow)
        soon = QLabel("COMING SOON")
        soon.setStyleSheet(
            f"color: {T['accent']}; font-size: 19px; font-weight: 900;"
            "letter-spacing: 3px;")
        soon.setAlignment(Qt.AlignCenter)
        olay.addWidget(soon)
        sub = QLabel("Max-performance preset arriving in a future update.")
        sub.setStyleSheet(f"color: {T['text_faint']}; font-size: 10.5px;")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        olay.addWidget(sub)
        overlay.setStyleSheet(
            "QFrame#UltraSoon { background-color: rgba(8, 12, 18, 190);"
            " border: 1px solid rgba(0, 242, 254, 0.55);"
            " border-radius: 10px; }")

        grid.addWidget(content, 0, 0)
        grid.addWidget(overlay, 0, 0, Qt.AlignCenter)

        return card

    # ---------------- System storage ----------------

    def _build_storage_card(self):
        card = GlassCard()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("System Storage")
        title.setObjectName("GlassCardTitle")
        head.addWidget(title)
        head.addStretch()
        clean = QPushButton("Clean System Cache")
        clean.setObjectName("Secondary")
        clean.clicked.connect(self._on_clean)
        head.addWidget(clean)
        lay.addLayout(head)

        self.disk_used = QLabel("\u2014 GB of \u2014 GB Used")
        self.disk_used.setStyleSheet("font-size: 20px; font-weight: 900;")
        lay.addWidget(self.disk_used)

        self.disk_free = QLabel("")
        self.disk_free.setObjectName("GaugeSub")
        lay.addWidget(self.disk_free)

        self.disk_bar = DiskBar()
        lay.addWidget(self.disk_bar)

        legend = QHBoxLayout()
        legend.setSpacing(14)
        self.disk_legend: dict[str, QLabel] = {}
        for key, color in (("OS", T["accent"]), ("Games", T["warning"]),
                           ("Free", T["text_faint"])):
            lbl = QLabel("")
            lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 800;")
            legend.addWidget(lbl)
            self.disk_legend[key] = lbl
        legend.addStretch()
        lay.addLayout(legend)

        self.appdata_lbl = QLabel("")
        self.appdata_lbl.setObjectName("GaugeSub")
        lay.addWidget(self.appdata_lbl)
        return card

    # ---------------- Active profile ----------------

    def _build_profile_card(self):
        card = GlassCard()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(IconTile(ICONS["profiles"], T["accent"], size=30,
                                font_scale=0.5))
        title = QLabel("Active Profile")
        title.setObjectName("GlassCardTitle")
        head.addWidget(title)
        head.addStretch()
        self.profile_pill = QLabel()
        self.profile_pill.setObjectName("StatusPill")
        head.addWidget(self.profile_pill)
        lay.addLayout(head)

        self.profile_name = QLabel("\u2014")
        self.profile_name.setStyleSheet("font-size: 20px; font-weight: 900;")
        self.profile_name.setWordWrap(True)
        lay.addWidget(self.profile_name)

        self.profile_desc = QLabel("")
        self.profile_desc.setObjectName("CardDetail")
        self.profile_desc.setWordWrap(True)
        lay.addWidget(self.profile_desc)

        open_btn = QPushButton("Open Profiles")
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(lambda: self.navigate("profiles"))
        lay.addWidget(open_btn, 0, Qt.AlignLeft)
        return card

    def _refresh_profile_card(self):
        name = state_mgr.get_active_profile()
        if name:
            self.profile_name.setText(f"{name}: Engaged")
            self.profile_pill.setText("\u25cf ENGAGED")
            self.profile_pill.setStyleSheet(
                f"background-color: {T['accent']}; color: {T['accent_dark']};"
                " border-radius: 9px; padding: 3px 10px; font-size: 10.5px;"
                " font-weight: 800; letter-spacing: 0.6px;")
            self.profile_desc.setText(
                "Low-latency tuning profile is engaged. Revert it or switch "
                "profiles at any time from the Profiles page.")
        else:
            self.profile_name.setText("No profile engaged")
            self.profile_pill.setText("\u25cf STANDBY")
            self.profile_pill.setStyleSheet(
                "color: #00F2FE; background-color: rgba(0, 242, 254, 0.08);"
                " border: 1px solid rgba(0, 242, 254, 0.25);"
                " border-radius: 9px; padding: 3px 10px; font-size: 10.5px;"
                " font-weight: 500; letter-spacing: 0.6px;")
            self.profile_desc.setText(
                "Engage a game profile to auto-apply its tuning and driver "
                "settings, then watch it live from this card.")

    # ---------------- Live metrics ----------------

    def _on_metrics(self, data: dict):
        self._last = data

        freq = data.get("cpu_freq_mhz")
        freq_txt = f"{freq} MHz" if freq else "? MHz"
        self._update_metric(
            self.cpu_row, data.get("cpu_percent", 0),
            f"{freq_txt}  \u00b7  {data.get('cpu_threads', '?')} threads",
            temp=data.get("cpu_temp"))

        gpu_util = data.get("gpu_util")
        if gpu_util is None:
            self._update_metric(self.gpu_row, 0, "No GPU data available")
        else:
            name = data.get("gpu_name") or "GPU"
            mem = f"{data.get('gpu_mem_used', 0)} / {data.get('gpu_mem_total', 0)} MB"
            self._update_metric(self.gpu_row, gpu_util, f"{name}  \u00b7  {mem}",
                                temp=data.get("gpu_temp"))

        ram = data.get("ram_pct", 0)
        self._update_metric(
            self.ram_row, ram,
            f"{data.get('ram_used_gb', 0)} / {data.get('ram_total_gb', 0)} GB")

        self.latency_chart.add(data.get("cpu_temp"), data.get("gpu_temp"),
                               data.get("cpu_freq_mhz"))
        self._update_disk(data)

    def _update_disk(self, data: dict):
        used = data.get("disk_used_gb", 0)
        total = data.get("disk_total_gb", 0)
        free = data.get("disk_free_gb", 0)
        games = data.get("disk_games_gb", 0)
        appdata = data.get("disk_appdata_gb", 0)
        os_used = max(0.0, used - games)

        self.disk_used.setText(f"{used:.1f} GB of {total:.1f} GB Used")
        label = data.get("disk_label")
        self.disk_free.setText(
            f"{free:.1f} GB free" + (f"  \u00b7  {label}" if label else ""))
        self.disk_bar.set_segments(
            [("OS", os_used, T["accent"]),
             ("Games", games, T["warning"]),
             ("Free", free, T["text_faint"])],
            total)
        self.disk_legend["OS"].setText(f"OS \u00b7 {os_used:.0f} GB")
        self.disk_legend["Games"].setText(f"Games \u00b7 {games:.0f} GB")
        self.disk_legend["Free"].setText(f"Free \u00b7 {free:.0f} GB")
        if total:
            pct = appdata / total * 100.0
            self.appdata_lbl.setText(
                f"Local AppData \u00b7 {appdata:.1f} GB \u00b7 "
                f"{pct:.1f}% of this drive")

    # ---------------- Rex Ultra Mode ----------------

    def _on_mode_toggled(self, on: bool):
        state_mgr.set_ultra_mode(on)
        activity.emit("info", f"Rex Ultra Mode {'enabled' if on else 'disabled'}")
        toast(f"Rex Ultra Mode {'enabled' if on else 'disabled'}",
              "success" if on else "info", self)
        self._refresh_mode_card()

    def _refresh_mode_card(self):
        on = state_mgr.get_ultra_mode()
        self.mode_toggle.blockSignals(True)
        self.mode_toggle.setChecked(on)
        self.mode_toggle.blockSignals(False)
        if on:
            self.mode_pill.setText("\u25cf ACTIVE")
            self.mode_pill.setStyleSheet(
                f"background-color: {T['accent']}; color: {T['accent_dark']};"
                " border-radius: 9px; padding: 3px 10px; font-size: 10.5px;"
                " font-weight: 800; letter-spacing: 0.6px;")
        elif self.ctx.live_active_count() >= 10:
            self.mode_pill.setText("\u25cf CONFIGURED")
            self.mode_pill.setStyleSheet(
                "color: #00F2FE; background-color: rgba(0, 242, 254, 0.08);"
                " border: 1px solid rgba(0, 242, 254, 0.25);"
                " border-radius: 9px; padding: 3px 10px; font-size: 10.5px;"
                " font-weight: 500; letter-spacing: 0.6px;")
        else:
            self.mode_pill.setText("\u25cf INACTIVE")
            self.mode_pill.setStyleSheet(
                "color: #00F2FE; background-color: rgba(0, 242, 254, 0.08);"
                " border: 1px solid rgba(0, 242, 254, 0.25);"
                " border-radius: 9px; padding: 3px 10px; font-size: 10.5px;"
                " font-weight: 500; letter-spacing: 0.6px;")

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
