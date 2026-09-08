"""Game Profiles page — split-pane master-detail with scanning overlay,
profile presets, live tuning dashboard, and changes preview.

Left panel (~35%): scrollable list of premium game cards.
Right panel (~65%): full-featured game inspector with hero banner,
preset bar, fine-tuning grid, NvAPI flags accordion, and apply/reset.
"""
from __future__ import annotations

import ctypes

from PySide6.QtCore import Qt, QThread, Signal, QPropertyAnimation, QEasingCurve, QRectF
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.app_config import THEME as T
from engine import nvprofiles
from engine import state as state_mgr
from ui.categories import GAME_PROFILE_IDS
from ui.premium_widgets import (
    AnimatedToast,
    ChangesPreviewDialog,
    GameListItem,
    GlassCheckbox,
    GlassComboBox,
    LoadingCard,
    NvapiFlagsAccordion,
    ProfilePresetBar,
    ResolutionPicker,
    SystemInfoBadge,
    _draw_game_icon,
    toast,
)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _form_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color: {T['text_faint']}; font-size: 10px; font-weight: 700;"
        "letter-spacing: 1px; padding-bottom: 2px; background: transparent; border: none;")
    return lbl


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color: {T['text_faint']}; font-size: 10px; font-weight: 700;"
        "letter-spacing: 1.5px; padding: 4px 0; background: transparent; border: none;")
    return lbl


# ──────────────────────────────────────────────────────────────
# Worker threads
# ──────────────────────────────────────────────────────────────

class InstalledWorker(QThread):
    done = Signal(dict)
    error = Signal(str)

    def run(self):
        from engine import game_detector
        try:
            self.done.emit(game_detector.detect_games())
        except Exception as exc:
            self.error.emit(str(exc))


class ProfileWorker(QThread):
    done = Signal(str, dict)
    error = Signal(str, str)

    def __init__(self, game_id: str, mode: str, config_values: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self.game_id = game_id
        self.mode = mode
        self.config_values = config_values or {}

    def run(self):
        try:
            from engine import game_config
            if self.mode == "apply":
                nv_report = nvprofiles.apply_profile(self.game_id)
                game_report = game_config.write_game_config(
                    self.game_id, self.config_values)
                combined = {**nv_report}
                combined["game_config"] = game_report
                self.done.emit(self.game_id, combined)
            elif self.mode == "apply_recommended":
                recommended = game_config.read_game_config(self.game_id)
                nv_report = nvprofiles.apply_profile(self.game_id)
                game_report = game_config.write_game_config(
                    self.game_id, recommended)
                combined = {**nv_report}
                combined["game_config"] = game_report
                combined["recommended_applied"] = True
                self.done.emit(self.game_id, combined)
            else:
                report = nvprofiles.reset_profile(self.game_id)
                self.done.emit(self.game_id, report)
        except Exception as exc:
            self.error.emit(self.game_id, str(exc))


# ──────────────────────────────────────────────────────────────
# Right panel: premium game inspector / configurator
# ──────────────────────────────────────────────────────────────

class GameInspector(QFrame):
    """Premium inspector with hero banner, preset bar, fine-tuning grid."""

    apply_clicked = Signal(str, dict)
    reset_clicked = Signal(str)
    recommended_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._game_id: str | None = None
        self._form_widgets: dict[str, QWidget] = {}
        self._banner_opacity = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Hero Banner (painted). ──
        self._banner = QWidget()
        self._banner.setFixedHeight(140)
        self._banner.setStyleSheet("background: transparent;")
        root.addWidget(self._banner)

        # ── Content. ──
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(24, 0, 24, 16)
        cl.setSpacing(12)

        # Header row.
        header = QHBoxLayout()
        header.setSpacing(12)
        self._game_icon = QLabel()
        self._game_icon.setFixedSize(48, 48)
        self._game_icon.setStyleSheet("background: transparent; border: none;")
        header.addWidget(self._game_icon)

        hb = QVBoxLayout()
        hb.setSpacing(2)
        self.title_lbl = QLabel("Select a Game")
        self.title_lbl.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {T['text']}; background: transparent; border: none;")
        self.publisher_lbl = QLabel("")
        self.publisher_lbl.setStyleSheet(f"font-size: 12px; color: {T['text_dim']}; background: transparent; border: none;")
        hb.addWidget(self.title_lbl)
        hb.addWidget(self.publisher_lbl)
        header.addLayout(hb, 1)

        self._sys_badge = SystemInfoBadge()
        header.addWidget(self._sys_badge, 0, Qt.AlignTop)
        cl.addLayout(header)

        # Status banner.
        self.status_frame = QFrame()
        self.status_frame.setObjectName("Card")
        self.status_frame.setStyleSheet(f"background-color: rgba(0, 242, 254, 0.06); border: 1px solid rgba(0, 242, 254, 0.18); border-radius: 10px;")
        sf_lay = QHBoxLayout(self.status_frame)
        sf_lay.setContentsMargins(14, 10, 14, 10)
        self.status_icon = QLabel("\u2713")
        self.status_icon.setStyleSheet(f"color: {T['success']}; font-size: 16px; font-weight: 800; background: transparent; border: none;")
        sf_lay.addWidget(self.status_icon)
        self.status_msg = QLabel("Select a game from the list to configure its profile.")
        self.status_msg.setStyleSheet(f"color: {T['text_dim']}; font-size: 12px; background: transparent; border: none;")
        self.status_msg.setWordWrap(True)
        sf_lay.addWidget(self.status_msg, 1)
        cl.addWidget(self.status_frame)

        # Preset bar.
        self._preset_bar = ProfilePresetBar()
        self._preset_bar.preset_changed.connect(self._on_preset_changed)
        cl.addWidget(self._preset_bar)

        # Action buttons.
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_apply = QPushButton("Apply Profile")
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._on_apply)
        btns.addWidget(self.btn_apply)

        self.btn_view = QPushButton("View Driver & File Edits")
        self.btn_view.setObjectName("Ghost")
        self.btn_view.setEnabled(False)
        self.btn_view.clicked.connect(self._on_view_changes)
        btns.addWidget(self.btn_view)

        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setObjectName("Danger")
        self.btn_reset.setEnabled(False)
        self.btn_reset.clicked.connect(self._on_reset)
        btns.addWidget(self.btn_reset)

        btns.addStretch()
        cl.addLayout(btns)

        # Divider.
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background-color: {T['border']};")
        cl.addWidget(div)

        # Settings scroll area.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        self.settings_container = QWidget()
        self.settings_container.setStyleSheet("background: transparent;")
        self.settings_layout = QVBoxLayout(self.settings_container)
        self.settings_layout.setContentsMargins(0, 0, 0, 0)
        self.settings_layout.setSpacing(16)
        self.settings_layout.addStretch()
        scroll.setWidget(self.settings_container)
        cl.addWidget(scroll, 1)

        root.addWidget(content)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._game_id and self._banner_opacity > 0:
            p.setOpacity(self._banner_opacity * 0.12)
            _draw_game_icon(p, QRectF(self._banner.rect()), self._game_id, 140)
        p.end()
        super().paintEvent(event)

    def _update_banner(self, game_id):
        anim = QPropertyAnimation(self, b"bannerOpacity")
        anim.setDuration(400)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(self._banner_opacity)
        anim.setEndValue(1.0 if game_id else 0.0)
        anim.start()
        self._banner_anim = anim

    def _get_banner_opacity(self):
        return self._banner_opacity

    def _set_banner_opacity(self, val):
        self._banner_opacity = val
        self.update()

    bannerOpacity = property(_get_banner_opacity, _set_banner_opacity)

    # ── public interface ──

    def set_game(self, game_id, nv_applied=False, nv_profile=None,
                 installed=False, enabled=True):
        self._game_id = game_id

        try:
            from engine import nvprofile as nv_mod
            gpu = nv_mod.Nvapi().gpu_names() if nv_mod.Nvapi.available() else []
            self._sys_badge.set_info(gpu_name=gpu[0] if gpu else "", nvapi_ready=nv_mod.Nvapi.available())
        except Exception:
            self._sys_badge.set_info(nvapi_ready=False)

        if game_id is None:
            self.title_lbl.setText("Select a Game")
            self.publisher_lbl.setText("")
            self.btn_apply.setEnabled(False)
            self.btn_view.setEnabled(False)
            self.btn_reset.setEnabled(False)
            self.status_msg.setText("Select a game from the list to configure its profile.")
            self.status_icon.setText("\u25cb")
            self.status_icon.setStyleSheet(f"color: {T['text_faint']}; font-size: 16px; font-weight: 800; background: transparent; border: none;")
            self.status_frame.setStyleSheet(f"background-color: transparent; border: 1px solid {T['border']}; border-radius: 10px;")
            self._update_banner(None)
            self._clear_form()
            return

        meta = nvprofiles.GAMES.get(game_id, {})
        name = meta.get("name", game_id)
        cands = meta.get("profile_candidates", [])
        publisher = cands[0] if cands else ""

        self.title_lbl.setText(name)
        self.publisher_lbl.setText(publisher)
        self._update_banner(game_id)
        self._build_form(game_id)

        can_configure = game_id in ("gp-001",)
        if nv_applied:
            self.status_msg.setText(f"Profile active on \u201c{nv_profile}\u201d. Fine-tune and apply again, or reset.")
            self.status_icon.setText("\u2713")
            self.status_icon.setStyleSheet(f"color: {T['success']}; font-size: 16px; font-weight: 800; background: transparent; border: none;")
            self.status_frame.setStyleSheet(f"background-color: rgba(0, 242, 254, 0.06); border: 1px solid rgba(0, 242, 254, 0.18); border-radius: 10px;")
        elif installed and can_configure:
            self.status_msg.setText("Ready to configure \u2014 Fine-tune this profile before applying.")
            self.status_icon.setText("\u25cb")
            self.status_icon.setStyleSheet(f"color: {T['accent']}; font-size: 16px; font-weight: 800; background: transparent; border: none;")
            self.status_frame.setStyleSheet(f"background-color: rgba(0, 242, 254, 0.04); border: 1px solid rgba(0, 242, 254, 0.12); border-radius: 10px;")
        elif installed:
            self.status_msg.setText("Game detected \u2014 NVIDIA driver settings available.")
            self.status_icon.setText("\u25cb")
            self.status_icon.setStyleSheet(f"color: {T['accent']}; font-size: 16px; font-weight: 800; background: transparent; border: none;")
            self.status_frame.setStyleSheet(f"background-color: rgba(0, 242, 254, 0.04); border: 1px solid rgba(0, 242, 254, 0.12); border-radius: 10px;")
        else:
            self.status_msg.setText("Game not detected \u2014 install it for full profile support.")
            self.status_icon.setText("\u26a0")
            self.status_icon.setStyleSheet(f"color: {T['warning']}; font-size: 16px; font-weight: 800; background: transparent; border: none;")
            self.status_frame.setStyleSheet(f"background-color: rgba(240, 181, 77, 0.06); border: 1px solid rgba(240, 181, 77, 0.15); border-radius: 10px;")

        has_config = game_id in ("gp-001",)
        self.btn_apply.setEnabled(enabled and installed)
        self.btn_view.setEnabled(enabled and installed)
        self.btn_reset.setEnabled(enabled and nv_applied)

    def _on_preset_changed(self, preset: str):
        if preset == "max_perf":
            if hasattr(self, '_res_picker'):
                self._res_picker._w_combo.setCurrentIndex(0)
            for key in ("fps_limit", "rendering_mode", "reflex"):
                if key in self._form_widgets:
                    w = self._form_widgets[key]
                    if hasattr(w, 'setCurrentText'):
                        defaults = {"fps_limit": "240", "rendering_mode": "Performance Mode", "reflex": "On + Boost"}
                        if key in defaults:
                            w.setCurrentText(defaults[key])
        elif preset == "balanced":
            if hasattr(self, '_res_picker'):
                self._res_picker._w_combo.setCurrentIndex(0)
            for key in ("fps_limit", "rendering_mode", "reflex"):
                if key in self._form_widgets:
                    w = self._form_widgets[key]
                    if hasattr(w, 'setCurrentText'):
                        defaults = {"fps_limit": "240", "rendering_mode": "DirectX 12", "reflex": "On"}
                        if key in defaults:
                            w.setCurrentText(defaults[key])

    # ── form building ──

    def _clear_form(self):
        while self.settings_layout.count():
            item = self.settings_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
        self._form_widgets.clear()

    def _build_form(self, game_id: str):
        self._clear_form()

        from engine import game_config
        cfg_cls = game_config.get_config(game_id)
        if cfg_cls is not None:
            current = cfg_cls.read()
        else:
            current = {}

        sec = self._add_section("Resolution")
        self._res_picker = ResolutionPicker(current.get("resolution_w", "1920"), current.get("resolution_h", "1080"))
        sec.addWidget(self._res_picker)

        sec2 = self._add_section("Core Settings")
        self._add_combo(sec2, "FPS Limit", ["Uncapped", "60", "120", "144", "165", "240", "360"],
                        current.get("fps_limit", "Uncapped"), "fps_limit")
        self._add_combo(sec2, "Rendering Mode",
                        ["Performance Mode", "DirectX 11", "DirectX 12"],
                        current.get("rendering_mode", "Performance Mode"), "rendering_mode")

        grid = QHBoxLayout()
        grid.setSpacing(12)
        aq_col = QVBoxLayout()
        self._add_combo(aq_col, "Audio Quality", ["Low", "Medium", "High"],
                        current.get("audio_quality", "High"), "audio_quality")
        grid.addLayout(aq_col)
        ref_col = QVBoxLayout()
        self._add_combo(ref_col, "Reflex Low Latency", ["Off", "On", "On + Boost"],
                        current.get("reflex", "Off"), "reflex")
        grid.addLayout(ref_col)
        grid.addStretch()
        sec2.addLayout(grid)

        sec3 = self._add_section("System Flags")
        self._add_checkbox(sec3, "Disable Fullscreen Optimizations (Win32 Override)",
                           current.get("fullscreen_opts", False), "fullscreen_opts")
        self._add_checkbox(sec3, "Run Executable as Administrator",
                           current.get("run_admin", False), "run_admin")
        self._add_checkbox(sec3, "Disable Windows Game Bar Telemetry", False, "gamebar_disable")

        self._nvapi_accordion = NvapiFlagsAccordion()
        self.settings_layout.addWidget(self._nvapi_accordion)
        self.settings_layout.addStretch()

    def _build_nvapi_only_form(self, game_id: str):
        self._clear_form()

        sec = self._add_section("Resolution")
        self._res_picker = ResolutionPicker("1920", "1080")
        sec.addWidget(self._res_picker)

        sec2 = self._add_section("Core Settings")
        self._add_combo(sec2, "FPS Limit", ["Uncapped", "60", "120", "144", "165", "240", "360"],
                        "Uncapped", "fps_limit")
        self._add_combo(sec2, "Rendering Mode",
                        ["Performance Mode", "DirectX 11", "DirectX 12"],
                        "Performance Mode", "rendering_mode")

        grid = QHBoxLayout()
        grid.setSpacing(12)
        aq_col = QVBoxLayout()
        self._add_combo(aq_col, "Audio Quality", ["Low", "Medium", "High"],
                        "High", "audio_quality")
        grid.addLayout(aq_col)
        ref_col = QVBoxLayout()
        self._add_combo(ref_col, "Reflex Low Latency", ["Off", "On", "On + Boost"],
                        "Off", "reflex")
        grid.addLayout(ref_col)
        grid.addStretch()
        sec2.addLayout(grid)

        sec3 = self._add_section("System Flags")
        self._add_checkbox(sec3, "Disable Fullscreen Optimizations (Win32 Override)",
                           False, "fullscreen_opts")
        self._add_checkbox(sec3, "Run Executable as Administrator",
                           False, "run_admin")
        self._add_checkbox(sec3, "Disable Windows Game Bar Telemetry", False, "gamebar_disable")

        from database import BY_ID
        tweak = BY_ID.get(game_id)
        if tweak:
            desc = QLabel(tweak.get("desc", ""))
            desc.setStyleSheet(f"color: {T['text_dim']}; font-size: 12px; background: transparent; border: none;")
            desc.setWordWrap(True)
            self.settings_layout.addWidget(desc)

        self._nvapi_accordion = NvapiFlagsAccordion()
        self.settings_layout.addWidget(self._nvapi_accordion)
        self.settings_layout.addStretch()

    def _add_section(self, title: str) -> QVBoxLayout:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(_section_label(title))
        self.settings_layout.addWidget(wrap)
        return lay

    def _add_combo(self, container, label, options, current, key):
        container.addWidget(_form_label(label))
        combo = GlassComboBox(options)
        if current in options:
            combo.setCurrentText(current)
        combo.currentTextChanged.connect(lambda _, k=key: self._emit_changed(k))
        self._form_widgets[key] = combo
        container.addWidget(combo)

    def _add_checkbox(self, container, label, checked, key):
        cb = GlassCheckbox(label, checked)
        cb.toggled.connect(lambda _, k=key: self._emit_changed(k))
        self._form_widgets[key] = cb
        container.addWidget(cb)

    def _emit_changed(self, key):
        pass

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def get_settings(self) -> dict:
        result = {}
        if hasattr(self, '_res_picker'):
            w, h = self._res_picker.get_values()
            result["resolution_w"] = w
            result["resolution_h"] = h
        for key, widget in self._form_widgets.items():
            if hasattr(widget, 'currentText'):
                result[key] = widget.currentText()
            elif hasattr(widget, 'isChecked'):
                result[key] = widget.isChecked()
        return result

    def _on_apply(self):
        if self._game_id:
            self.apply_clicked.emit(self._game_id, self.get_settings())

    def _on_view_changes(self):
        if self._game_id:
            dlg = ChangesPreviewDialog(self._game_id, self.get_settings(), self)
            dlg.exec()

    def _on_reset(self):
        if self._game_id:
            self.reset_clicked.emit(self._game_id)


# ──────────────────────────────────────────────────────────────
# Main page
# ──────────────────────────────────────────────────────────────

class ProfilesPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.workers: dict[str, ProfileWorker] = {}
        self.scan_worker: InstalledWorker | None = None
        self._gpu: list[str] = []
        self._selected_game: str | None = None
        self._installed: dict[str, bool] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        from ui.widgets import PageHeader
        root.addWidget(PageHeader(
            "Game Profiles",
            "Manage game-specific optimizations and performance settings"))

        # Toolbar.
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.btn_scan = QPushButton("Rescan Installed")
        self.btn_scan.setObjectName("Ghost")
        self.btn_scan.clicked.connect(self.scan_installed)
        bar.addWidget(self.btn_scan)
        self.scan_status = QLabel("Scanning for installed games\u2026")
        self.scan_status.setStyleSheet(f"color: {T['text_dim']}; background: transparent; border: none;")
        bar.addWidget(self.scan_status)
        bar.addStretch()
        self.gpu_lbl = QLabel("")
        self.gpu_lbl.setStyleSheet(f"color: {T['text_dim']}; font-size: 11px; background: transparent; border: none;")
        bar.addWidget(self.gpu_lbl)
        from ui.widgets import badge
        bar.addWidget(badge("ADMIN", T["accent"], filled=True) if is_admin() else badge("NOT ADMIN", T["warning"]))
        root.addLayout(bar)

        # Split pane — fixed left, flex right.
        split = QHBoxLayout()
        split.setSpacing(12)

        left = QFrame()
        left.setObjectName("Card")
        left.setFixedWidth(320)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(8, 8, 8, 8)
        left_lay.setSpacing(4)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setStyleSheet("background: transparent; border: none;")
        self.game_list = QWidget()
        self.game_list.setStyleSheet("background: transparent;")
        self.game_list_lay = QVBoxLayout(self.game_list)
        self.game_list_lay.setContentsMargins(4, 4, 4, 4)
        self.game_list_lay.setSpacing(4)
        self.game_list_lay.addStretch()
        left_scroll.setWidget(self.game_list)
        left_lay.addWidget(left_scroll)
        split.addWidget(left)

        self.inspector = GameInspector()
        self.inspector.apply_clicked.connect(self._apply)
        self.inspector.reset_clicked.connect(self._reset)
        self.inspector.recommended_clicked.connect(self._apply_recommended)
        split.addWidget(self.inspector, 1)

        root.addLayout(split, 1)

        # Build game list.
        self.game_items: dict[str, GameListItem] = {}
        for game_id in GAME_PROFILE_IDS:
            if game_id not in nvprofiles.GAMES:
                continue
            item = GameListItem(game_id)
            item.clicked.connect(self._select_game)
            self.game_items[game_id] = item
            self.game_list_lay.insertWidget(self.game_list_lay.count() - 1, item)

        # Loading card.
        self._loading_card = LoadingCard(self)
        self._loading_card.loading_complete.connect(self._on_loading_complete)

        self.ctx.state_changed.connect(self.refresh)
        self.refresh()
        self.scan_installed()

    # ── loading card ──

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loading_card.isVisible():
            self._loading_card.setGeometry(self.rect())
            self._loading_card.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_loading_card'):
            self._loading_card.setGeometry(self.rect())

    def _on_loading_complete(self):
        first = next(
            (gid for gid in GAME_PROFILE_IDS if self._installed.get(gid)), None)
        if first and not self._selected_game:
            self._select_game(first)

    # ── game selection ──

    def _select_game(self, game_id: str):
        if self._selected_game and self._selected_game in self.game_items:
            self.game_items[self._selected_game].set_selected(False)
        self._selected_game = game_id
        if game_id in self.game_items:
            self.game_items[game_id].set_selected(True)
        snap = state_mgr.get_nv_profile_snapshot(game_id)
        self.inspector.set_game(
            game_id,
            nv_applied=snap is not None,
            nv_profile=(snap or {}).get("profile"),
            installed=self._installed.get(game_id, False),
            enabled=nvprofiles.driver_available())

    # ── refresh / scan ──

    def refresh(self):
        available = nvprofiles.driver_available()
        if not self._gpu:
            self._gpu = nvprofiles.gpu_names()
        self.gpu_lbl.setText(" \u00b7 ".join(self._gpu) if self._gpu else "")

        for game_id, item in self.game_items.items():
            if self.workers.get(game_id):
                continue
            snap = state_mgr.get_nv_profile_snapshot(game_id)
            item.set_applied(snap is not None)
            item.set_installed(self._installed.get(game_id, False))

        if self._selected_game:
            snap = state_mgr.get_nv_profile_snapshot(self._selected_game)
            self.inspector.set_game(
                self._selected_game,
                nv_applied=snap is not None,
                nv_profile=(snap or {}).get("profile"),
                installed=self._installed.get(self._selected_game, False),
                enabled=available)

    def scan_installed(self):
        if self.scan_worker and self.scan_worker.isRunning():
            return
        self.btn_scan.setEnabled(False)
        self.scan_status.setText("Scanning for installed games\u2026")
        self.scan_worker = InstalledWorker(self)
        self.scan_worker.done.connect(self._scan_done)
        self.scan_worker.error.connect(self._scan_error)
        self.scan_worker.start()

    def _scan_done(self, found: dict):
        self.btn_scan.setEnabled(True)
        self._installed = found
        n = sum(1 for g in self.game_items if found.get(g))
        self.scan_status.setText(f"{n} of {len(self.game_items)} games found on disk.")
        for game_id, item in self.game_items.items():
            item.set_installed(bool(found.get(game_id)))
        self.scan_worker = None
        if self._selected_game:
            snap = state_mgr.get_nv_profile_snapshot(self._selected_game)
            self.inspector.set_game(
                self._selected_game,
                nv_applied=snap is not None,
                nv_profile=(snap or {}).get("profile"),
                installed=found.get(self._selected_game, False),
                enabled=nvprofiles.driver_available())
        elif not self._selected_game:
            first_installed = next(
                (gid for gid in GAME_PROFILE_IDS if found.get(gid)), None)
            if first_installed:
                self._select_game(first_installed)

    def _scan_error(self, msg: str):
        self.btn_scan.setEnabled(True)
        self.scan_status.setText(f"Scan failed: {msg}")
        self.scan_status.setStyleSheet(f"color: {T['danger']};")
        self.scan_worker = None

    # ── apply / reset ──

    def _apply(self, game_id: str, config_values: dict):
        if self.workers.get(game_id):
            return
        worker = ProfileWorker(game_id, "apply", config_values, self)
        self.workers[game_id] = worker
        worker.done.connect(self._op_done)
        worker.error.connect(self._op_error)
        worker.finished.connect(lambda gid=game_id: self._op_finished(gid))
        worker.start()

    def _apply_recommended(self, game_id: str):
        if self.workers.get(game_id):
            return
        worker = ProfileWorker(game_id, "apply_recommended", parent=self)
        self.workers[game_id] = worker
        worker.done.connect(self._op_done)
        worker.error.connect(self._op_error)
        worker.finished.connect(lambda gid=game_id: self._op_finished(gid))
        worker.start()

    def _reset(self, game_id: str):
        if self.workers.get(game_id):
            return
        worker = ProfileWorker(game_id, "reset", parent=self)
        self.workers[game_id] = worker
        worker.done.connect(self._op_done)
        worker.error.connect(self._op_error)
        worker.finished.connect(lambda gid=game_id: self._op_finished(gid))
        worker.start()

    def _op_done(self, game_id: str, report: dict):
        n = len(report.get("applied", []))
        created = " (new driver profile created)" if report.get("created") else ""
        game_cfg = report.get("game_config", {})
        cfg_n = len(game_cfg.get("applied", []))
        game_name = report.get("game", game_id)
        msg = f"{game_name} Competitive Profile Successfully Applied!"
        if n:
            msg += f" \u2014 {n} driver settings"
        if cfg_n:
            msg += f", {cfg_n} game settings"
        msg += created
        toast(msg, "success", self)
        self.ctx.note_state_change()

    def _op_error(self, game_id: str, msg: str):
        if game_id in self.game_items:
            snap = state_mgr.get_nv_profile_snapshot(game_id)
            self.game_items[game_id].set_applied(snap is not None)
        lower = msg.lower()
        if "admin" in lower or "elevat" in lower or "access" in lower or "0x" in msg:
            toast(f"Apply failed \u2014 needs elevated (admin) run: {msg}", "error", self)
        else:
            toast(f"Failed: {msg}", "error", self)
        self.ctx.note_state_change()

    def _op_finished(self, game_id: str):
        self.workers.pop(game_id, None)
        self.refresh()
