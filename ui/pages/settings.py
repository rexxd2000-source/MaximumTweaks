"""Settings page: appearance, security, data state and about."""
from __future__ import annotations

import ctypes

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import APP_NAME, APP_VERSION, ENGINE_NAME, LOG_FILE
from engine import state as state_mgr
from ui.widgets import section_label


class SettingRow(QFrame):
    def __init__(self, title, desc, widget=None):
        super().__init__()
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)
        box = QVBoxLayout()
        box.setSpacing(1)
        t = QLabel(title)
        t.setStyleSheet("font-size: 14px; font-weight: 800;")
        d = QLabel(desc)
        d.setObjectName("Tag")
        d.setWordWrap(True)
        box.addWidget(t)
        box.addWidget(d)
        lay.addLayout(box, 1)
        if widget is not None:
            lay.addWidget(widget)


class SettingsPage(QWidget):
    def __init__(self, ctx, navigate, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.navigate = navigate

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        sub = QLabel("Appearance, security and application state.")
        sub.setObjectName("PageSub")
        root.addWidget(sub)

        root.addWidget(section_label("Security"))

        admin = self._is_admin()
        btn = None
        if not admin:
            from ui.main_window import relaunch_as_admin
            btn = QPushButton("Relaunch as Admin")
            btn.clicked.connect(relaunch_as_admin)
        root.addWidget(SettingRow(
            "Administrator privileges",
            "Elevated mode lets every tweak apply, including registry and service "
            "changes. Rex Tweaks is running as "
            f"{'Administrator' if admin else 'a standard user'}.",
            btn))

        root.addWidget(section_label("Data & State"))

        btn_reset = QPushButton("Reset Applied State")
        btn_reset.clicked.connect(self._reset_applied)
        root.addWidget(SettingRow(
            "Applied tweaks",
            "Tweaks marked as applied are tracked so they can be reverted. "
            "Reset clears the tracking (settings are NOT modified).",
            btn_reset))

        btn_clear_restart = QPushButton("Clear Restart Flag")
        btn_clear_restart.clicked.connect(self._clear_restart)
        root.addWidget(SettingRow(
            "Restart required",
            "Some changes need a reboot to take effect. Once rebooted, clear "
            "this flag to mark the system healthy again.",
            btn_clear_restart))

        root.addWidget(section_label("Update"))

        btn_update = QPushButton("Check for Updates")
        btn_update.clicked.connect(self._check_updates)
        root.addWidget(SettingRow(
            "Live updates",
            f"Installed: {APP_NAME} v{APP_VERSION}. New builds are pushed to "
            "the server and applied in place with one click \u2014 no reinstall "
            "download.",
            btn_update))

        root.addWidget(section_label("About"))

        btn_logs = QPushButton("Open Logs")
        btn_logs.clicked.connect(lambda: self.navigate("logs"))
        root.addWidget(SettingRow(
            f"{APP_NAME} v{APP_VERSION} \u00b7 {ENGINE_NAME}",
            f"Log file: {LOG_FILE}",
            btn_logs))

        root.addStretch()

    @staticmethod
    def _is_admin():
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # noqa: BLE001
            return False

    def _confirm(self, title, text):
        return QMessageBox.question(
            self, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _reset_applied(self):
        if not self._confirm(
                "Reset applied state",
                "Reset the applied-tweak tracker? Applied settings will still be "
                "in effect \u2014 only the tracking is cleared."):
            return
        for tid in list(state_mgr.applied_ids()):
            state_mgr.unmark_applied(tid)
        self.ctx.note_state_change()

    def _clear_profile(self):
        state_mgr.clear_active_profile()
        self.ctx.note_state_change()

    def _clear_restart(self):
        state_mgr.clear_restart_required()
        self.ctx.note_state_change()

    def _check_updates(self):
        from ui.updater_dialog import UpdateDialog
        UpdateDialog(self).exec()
