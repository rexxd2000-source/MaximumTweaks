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

from config.app_config import (
    APP_NAME,
    APP_VERSION,
    ENGINE_NAME,
    LOG_FILE,
    THEME as T,
    current_windows_user,
)
from engine import license as license_mgr
from engine import state as state_mgr
from ui.license import LicenseAccountCard, deactivate, relock
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
        self._license_worker = None
        self._busy = False
        self._signout_btn = None
        self._signout_row = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        welcome = QLabel(f"Welcome, {current_windows_user()}")
        welcome.setStyleSheet(
            f"font-size: 15px; font-weight: 700; color: {T['accent']};")
        root.addWidget(welcome)
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
            "changes. Maximum Tweaks is running as "
            f"{'Administrator' if admin else 'a standard user'}.",
            btn))

        self._license_card = LicenseAccountCard(self.ctx)
        self._license_card.activate_requested.connect(
            lambda: relock(self.window()))
        root.addWidget(self._license_card)

        self._signout_btn = QPushButton("Sign Out")
        self._signout_btn.setObjectName("Danger")
        self._signout_btn.clicked.connect(lambda: deactivate(self.ctx, self))
        self._signout_row = SettingRow(
            "License account",
            "Sign out on this device, clear the local session and lock the app. "
            "You can reactivate at any time with your license key.",
            self._signout_btn)
        root.addWidget(self._signout_row)
        self._refresh_signout()
        self.ctx.license_changed.connect(self._refresh_signout)

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

    def set_busy(self, busy: bool):
        self._busy = busy
        if self._signout_btn is not None:
            self._signout_btn.setEnabled(not busy)
            self._signout_btn.setText("Signing out\u2026" if busy else "Sign Out")

    def _refresh_signout(self):
        if self._signout_row is None:
            return
        authorized = bool(license_mgr.session() and license_mgr.is_authorized())
        self._signout_row.setVisible(authorized)
        if self._signout_btn is not None:
            self._signout_btn.setEnabled(authorized and not self._busy)

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
