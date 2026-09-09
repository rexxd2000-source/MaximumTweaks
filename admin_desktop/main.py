"""Maximum Tweaks Admin - native red/black desktop panel for license keys.

Sign in with the operator ADMIN_TOKEN; the app exchanges it for the server's
HttpOnly session cookie and then manages licenses entirely through the hosted
backend (stats / generate / search / revoke / unrevoke / unbind).

Run from source:   python -m admin_desktop.main        (repo root)
Run from folder:   python main.py
Built EXE:         build.ps1  ->  dist\\MaximumTweaksAdmin.exe
"""
from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QSettings, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QStatusBar, QAbstractItemView, QHeaderView,
)

from .api import AdminClient, ApiError, mask_device
from .theme import RED_BLACK, BASE_RED_QSS, repolish

APP_NAME = "Maximum Tweaks Admin"
DEFAULT_URL = "https://maximumtweaks.onrender.com"

T = RED_BLACK


def _status_color(status: str) -> str:
    return {
        "active": "#FF6B70",
        "unused": T["text_faint"],
        "expired": "#FFCB7A",
        "revoked": "#8F7A7A",
    }.get(status, T["text_dim"])


# ---------------------------------------------------------------------------
# Background task plumbing (network calls never block the UI thread)
# ---------------------------------------------------------------------------

class _Signals(QObject):
    finished = Signal(object, object)   # (result, error)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self._fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            self.signals.finished.emit(self._fn(), None)
        except ApiError as e:
            self.signals.finished.emit(None, e)
        except Exception as e:  # noqa: BLE001 - surface anything unexpected
            self.signals.finished.emit(None, ApiError(str(e)))


class TaskHost(QObject):
    """Owner object that keeps a reference to the last task so it is not
    garbage-collected mid-flight."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._active = []

    def run(self, fn: Callable[[], object],
            on_done: Callable[[object | None, ApiError | None], None]) -> None:
        task = _Task(fn)
        task.signals.finished.connect(on_done)
        task.signals.finished.connect(lambda *_: self._purge(task))
        self._active.append(task)
        self._pool.start(task)

    def _purge(self, task) -> None:
        try:
            if task in self._active:
                self._active.remove(task)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} - Sign in")
        self.setModal(True)
        self.setMinimumWidth(420)

        settings = QSettings("MaximumTweaks", "Admin")
        self.url = QLineEdit(settings.value("server_url", DEFAULT_URL))
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("ADMIN_TOKEN")
        self.remember = QCheckBox("Remember this server URL on this PC")

        self.done_label = QLabel("Sign in with your operator token to manage licenses.")
        self.done_label.setObjectName("CardSub")
        self.done_label.setWordWrap(True)

        sign_btn = QPushButton("Sign in")
        sign_btn.setObjectName("Primary")
        sign_btn.clicked.connect(self.start_login)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("Ghost")
        cancel_btn.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(12)
        title = QLabel(APP_NAME)
        title.setObjectName("LoginTitle")
        title.setStyleSheet(
            f"font-size:20px;font-weight:800;color:{T['text']};letter-spacing:0.5px;")
        layout.addWidget(title)
        layout.addWidget(self.done_label)
        layout.addSpacing(6)
        layout.addWidget(QLabel("License server"))
        layout.addWidget(self.url)
        layout.addWidget(QLabel("Admin token"))
        layout.addWidget(self.token)
        layout.addWidget(self.remember)
        layout.addSpacing(8)
        btns = QHBoxLayout()
        btns.addWidget(cancel_btn)
        btns.addStretch(1)
        btns.addWidget(sign_btn)
        layout.addLayout(btns)

        self.client = None
        self.sign_btn = sign_btn

    def start_login(self) -> None:
        url = self.url.text().strip().rstrip("/") or DEFAULT_URL
        token = self.token.text().strip()
        if not token:
            self.done_label.setText("Please paste your ADMIN_TOKEN.")
            self.done_label.setStyleSheet(f"color:{T['warning']};")
            return
        self.sign_btn.setEnabled(False)
        self.done_label.setText("Signing in…")
        self.done_label.setStyleSheet(f"color:{T['text_dim']};")
        client = AdminClient(url)

        host = TaskHost(self)
        self._host = host

        def task():
            client.login(token)
            return client.me()

        def done(result, error):
            self.sign_btn.setEnabled(True)
            if error is not None:
                self.done_label.setText(f"Sign in failed: {error.message}"
                                        + (" (check the server URL)" if error.status == 0 else ""))
                self.done_label.setStyleSheet(f"color:{T['danger']};")
                return
            self.client = client
            if self.remember.isChecked():
                QSettings("MaximumTweaks", "Admin").setValue("server_url", url)
            self.accept()

        host.run(task, done)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class ToastLabel(QLabel):
    """The status bar slot that flashes current state with a color."""

    def show(self, text: str, color: str = T["text_dim"]) -> None:
        self.setText(text)
        self.setStyleSheet(f"color:{color};")


class AdminMainWindow(QMainWindow):
    def __init__(self, client: AdminClient):
        super().__init__()
        self.client = client
        self.host = TaskHost(self)
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)

        app = QApplication.instance()
        font = app.font()
        font.setPointSize(10)
        app.setFont(font)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 18, 20, 14)
        body_layout.setSpacing(16)
        body_layout.addLayout(self._build_stats_row())
        body_layout.addWidget(self._build_body(), 1)
        root.addWidget(body, 1)
        self._build_status_bar()

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(350)
        self.search_timer.timeout.connect(self.refresh_licenses)

        self.refresh_all()

    # -- header -----------------------------------------------------------
    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Header")
        bar.setFixedHeight(62)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(22, 10, 22, 10)

        brand = QLabel("MAXIMUM TWEAKS  ADMIN")
        brand.setObjectName("BrandMark")
        sub = QLabel("LICENSE CONTROL PANEL  •  RED / BLACK")
        sub.setObjectName("BrandSub")
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(brand)
        col.addWidget(sub)

        self.pill = QLabel("server: online")
        self.pill.setObjectName("ServerPill")
        self.pill.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        refresh = QPushButton("↻ Refresh")
        refresh.setObjectName("Secondary")
        refresh.clicked.connect(self.refresh_all)
        signout = QPushButton("Sign out")
        signout.setObjectName("Primary")
        signout.setMinimumHeight(34)
        signout.clicked.connect(self.sign_out)

        lay.addLayout(col)
        lay.addStretch(1)
        lay.addWidget(self.pill)
        lay.addSpacing(8)
        lay.addWidget(refresh)
        lay.addWidget(signout)
        return bar

    # -- stats ------------------------------------------------------------
    def _build_stats_row(self):
        self.stat_cards = {}
        grid = QHBoxLayout()
        grid.setSpacing(12)
        labels = [("total", "TOTAL"), ("unused", "UNUSED"), ("active", "ACTIVE"),
                  ("expired", "EXPIRED"), ("revoked", "REVOKED")]
        for key, text in labels:
            card = QFrame()
            card.setObjectName("StatCard" if key != "active" else "StatCard#stat-active")
            col = QVBoxLayout(card)
            col.setContentsMargins(16, 12, 16, 12)
            col.setSpacing(2)
            value = QLabel("—")
            value.setObjectName("StatValue")
            value.setAlignment(Qt.AlignmentFlag.AlignLeft)
            name = QLabel(text)
            name.setObjectName("StatLabel")
            col.addWidget(name)
            col.addWidget(value)
            self.stat_cards[key] = value
            grid.addWidget(card, 1)
        return grid

    # -- body -------------------------------------------------------------
    def _build_body(self) -> QWidget:
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_generate_panel())
        split.addWidget(self._build_licenses_panel())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([380, 760])
        return split

    def _build_generate_panel(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        card.setMinimumWidth(360)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        title = QLabel("Generate keys")
        title.setObjectName("CardTitle")
        sub = QLabel("Duration lives only in the DB record — keys never encode it.")
        sub.setObjectName("CardSub")
        sub.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(6)

        lay.addWidget(QLabel("Count"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 500)
        self.count_spin.setValue(1)

        lay.addWidget(QLabel("Prefix"))
        self.prefix_edit = QLineEdit("MAX")
        self.prefix_edit.setMaxLength(4)
        self.prefix_edit.setPlaceholderText("MAX / REX / MTW")

        lay.addWidget(QLabel("Duration"))
        self.duration_combo = QComboBox()
        self.duration_combo.addItem("Lifetime", "lifetime")
        self.duration_combo.addItem("1 month", "1m")
        self.duration_combo.addItem("6 months", "6m")

        lay.addWidget(QLabel("Customer"))
        self.customer_edit = QLineEdit()
        self.customer_edit.setPlaceholderText("optional buyer name")

        lay.addWidget(QLabel("Note"))
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("optional note")

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setObjectName("Primary")
        self.generate_btn.clicked.connect(self.generate_keys)

        self.results = QListWidget()
        self.results.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        pill = QLabel("Result keys")
        pill.setObjectName("CardSub")

        self.copy_btn = QPushButton("Copy selected key")
        self.copy_btn.setObjectName("Chip")
        self.copy_btn.clicked.connect(self.copy_selected_result)
        self.copy_all_btn = QPushButton("Copy all")
        self.copy_all_btn.setObjectName("Chip")
        self.copy_all_btn.clicked.connect(self.copy_all_results)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.copy_all_btn)
        row.addWidget(self.copy_btn)

        lay.addWidget(self.count_spin)
        lay.addWidget(self.prefix_edit)
        lay.addWidget(self.duration_combo)
        lay.addWidget(self.customer_edit)
        lay.addWidget(self.note_edit)
        lay.addWidget(self.generate_btn)
        lay.addSpacing(8)
        lay.addWidget(pill)
        lay.addWidget(self.results, 1)
        lay.addLayout(row)
        return card

    def _build_licenses_panel(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Licenses")
        title.setObjectName("CardTitle")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search key / customer / note…")
        self.search_edit.textChanged.connect(self._on_search_changed)
        self.status_combo = QComboBox()
        for label, value in (("All", ""), ("Unused", "unused"), ("Active", "active"),
                             ("Expired", "expired"), ("Revoked", "revoked")):
            self.status_combo.addItem(label, value)
        self.status_combo.currentIndexChanged.connect(self.refresh_licenses)
        head.addWidget(title)
        head.addSpacing(12)
        head.addWidget(self.search_edit, 1)
        head.addWidget(self.status_combo)
        lay.addLayout(head)

        table = QTableWidget(0, 7)
        table.setObjectName("LicenseTable")
        table.setHorizontalHeaderLabels(
            ["Key", "Status", "Plan", "Customer", "Expires (UTC)", "Device", "Activated (UTC)"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(1, 86)
        table.setColumnWidth(2, 84)
        table.setColumnWidth(3, 110)
        table.setColumnWidth(4, 128)
        table.setColumnWidth(5, 150)
        table.setColumnWidth(6, 128)
        table.doubleClicked.connect(self.copy_selected_license)
        self.table = table

        actions = QHBoxLayout()
        copy_k = QPushButton("Copy key")
        copy_k.setObjectName("Secondary")
        copy_k.clicked.connect(self.copy_selected_license)
        revoke_btn = QPushButton("Revoke selected")
        revoke_btn.setObjectName("DangerGhost")
        revoke_btn.clicked.connect(lambda: self.revoke_selected(revoke=True))
        restore_btn = QPushButton("Un-revoke")
        restore_btn.setObjectName("Secondary")
        restore_btn.clicked.connect(lambda: self.revoke_selected(revoke=False))
        unbind_btn = QPushButton("Unbind (PC change)")
        unbind_btn.setObjectName("Secondary")
        unbind_btn.clicked.connect(self.unbind_selected)
        refresh = QPushButton("↻")
        refresh.setObjectName("Secondary")
        refresh.clicked.connect(self.refresh_licenses)
        actions.addWidget(copy_k)
        actions.addSpacing(6)
        actions.addWidget(revoke_btn)
        actions.addWidget(restore_btn)
        actions.addWidget(unbind_btn)
        actions.addStretch(1)
        actions.addWidget(refresh)

        lay.addWidget(table, 1)
        lay.addLayout(actions)
        return card

    def _build_status_bar(self) -> None:
        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        self.status_bar.setStyleSheet(
            f"background-color:{T['bg_alt']};border-top:1px solid {T['border']};color:{T['text_dim']};")
        self.toast = ToastLabel("Ready")
        self.status_bar.addWidget(self.toast)
        self.setStatusBar(self.status_bar)

    # -- helpers ----------------------------------------------------------
    def toast_msg(self, text: str, color: str = T["text_dim"]) -> None:
        self.toast.show(text, color)

    def _on_search_changed(self) -> None:
        self.search_timer.start()

    # -- data -------------------------------------------------------------
    def refresh_all(self) -> None:
        self.refresh_stats()
        self.refresh_licenses()

    def refresh_stats(self) -> None:
        def task():
            return self.client.stats().get("stats", {})

        def done(res, error):
            if error is not None:
                self._handle_error(error)
                return
            s = res or {}
            by = s.get("by_status", {})
            self.stat_cards["total"].setText(str(s.get("total", "—")))
            self.stat_cards["unused"].setText(str(by.get("unused", 0)))
            self.stat_cards["active"].setText(str(by.get("active", 0)))
            self.stat_cards["expired"].setText(str(by.get("expired", 0)))
            self.stat_cards["revoked"].setText(str(by.get("revoked", 0)))

        self.host.run(task, done)

    def refresh_licenses(self) -> None:
        status = self.status_combo.currentData()
        query = self.search_edit.text().strip()

        def task():
            if query and len(query) >= 3:
                return self.client.search(query)
            return self.client.licenses(status)

        def done(res, error):
            if error is not None:
                self._handle_error(error)
                return
            self.populate_table(res or [])

        self.host.run(task, done)

    def populate_table(self, rows: list[dict]) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            key_item = QTableWidgetItem(r.get("license_key", ""))
            key_item.setFont(self._mono_font())
            status = r.get("status", "")
            status_item = QTableWidgetItem(status)
            status_item.setForeground(self._color(_status_color(status)))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            plan_item = QTableWidgetItem((r.get("plan") or "") or "lifetime")
            cust_item = QTableWidgetItem(r.get("customer") or "")
            exp_item = QTableWidgetItem(r.get("expires_at") or "lifetime")
            exp_item.setForeground(self._color(
                T["warning"] if r.get("status") == "expired" else T["text_dim"]))
            dev_item = QTableWidgetItem(mask_device(r.get("device_id")))
            act_item = QTableWidgetItem(r.get("activated_at") or "")
            act_item.setForeground(self._color(T["text_faint"]))

            for col, item in enumerate((key_item, status_item, plan_item,
                                        cust_item, exp_item, dev_item, act_item)):
                self.table.setItem(i, col, item)
            self.table.setItem(i, 0, key_item)
        self.table.setSortingEnabled(True)
        self.pill.setText("server: online")
        self.pill.setStyleSheet(
            f"background-color:{T['card']};border:1px solid {T['border']};"
            f"border-radius:100px;padding:5px 12px;color:{T['text_dim']};font-size:11px;"
            f"font-family:'JetBrains Mono','Cascadia Mono',monospace;")

    def _mono_font(self):
        from PySide6.QtGui import QFont
        f = QFont("Courier New")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPointSize(10)
        return f

    def _color(self, hex_str: str):
        from PySide6.QtGui import QColor
        return QColor(hex_str)

    # -- actions ----------------------------------------------------------
    def generate_keys(self) -> None:
        duration = self.duration_combo.currentData()
        count = self.count_spin.value()
        self.generate_btn.setEnabled(False)
        self.toast_msg("Generating…")

        def task():
            return self.client.generate(
                count=count, prefix=self.prefix_edit.text().strip(),
                duration=duration, customer=self.customer_edit.text().strip(),
                note=self.note_edit.text().strip())

        def done(res, error):
            self.generate_btn.setEnabled(True)
            if error is not None:
                self._handle_error(error)
                return
            keys = (res or {}).get("keys", [])
            self.results.clear()
            for k in keys:
                self.results.addItem(k)
            self.toast_msg(f"Created {len(keys)} key(s). Copy them now.",
                           T["text"])
            self.refresh_stats()
            self.refresh_licenses()

        self.host.run(task, done)

    def copy_selected_result(self) -> None:
        items = self.results.selectedItems()
        if not items:
            self.toast_msg("Select a generated key first.")
            return
        QApplication.clipboard().setText(items[0].text())
        self.toast_msg("Key copied to clipboard.", T["text"])

    def copy_all_results(self) -> None:
        keys = [self.results.item(i).text() for i in range(self.results.count())]
        if not keys:
            self.toast_msg("No generated keys to copy.")
            return
        QApplication.clipboard().setText("\n".join(keys))
        self.toast_msg(f"Copied {len(keys)} key(s) to clipboard.", T["text"])

    def selected_license_key(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).text()

    def copy_selected_license(self, *_):
        key = self.selected_license_key()
        if not key:
            self.toast_msg("Select a license row first.")
            return
        QApplication.clipboard().setText(key)
        self.toast_msg("Key copied to clipboard.", T["text"])

    def revoke_selected(self, revoke: bool) -> None:
        key = self.selected_license_key()
        if not key:
            self.toast_msg("Select a license row first.")
            return
        action = "revoke" if revoke else "un-revoke"
        if revoke and QMessageBox.question(
                self, "Revoke license",
                f"Revoke {key}?\nThe customer will not be able to activate it.") \
                != QMessageBox.StandardButton.Yes:
            return

        def task():
            return (self.client.revoke(key, "revoked from desktop admin")
                    if revoke else self.client.unrevoke(key))

        def done(res, error):
            if error is not None:
                self._handle_error(error)
                return
            self.toast_msg(f"{key}\n{action}d.", T["text"])
            self.refresh_all()

        self.host.run(task, done)

    def unbind_selected(self) -> None:
        key = self.selected_license_key()
        if not key:
            self.toast_msg("Select a license row first.")
            return
        if QMessageBox.question(
                self, "Unbind license",
                f"Unbind {key}?\nThe customer can activate it on a different PC.") \
                != QMessageBox.StandardButton.Yes:
            return

        def task():
            return self.client.unbind(key)

        def done(res, error):
            if error is not None:
                self._handle_error(error)
                return
            self.toast_msg(f"{key}\nunbound (ready for a new PC).", T["text"])
            self.refresh_all()

        self.host.run(task, done)

    def sign_out(self) -> None:
        def task():
            self.client.logout()
            return None

        def done(res, error):
            self.close()

        self.host.run(task, done)

    def _handle_error(self, error: ApiError) -> None:
        self.pill.setText("server: error")
        self.pill.setStyleSheet(
            f"background-color:{T['card']};border:1px solid {T['danger']};"
            f"border-radius:100px;padding:5px 12px;color:{T['danger']};font-size:11px;"
            f"font-family:'JetBrains Mono','Cascadia Mono',monospace;")
        if error.status == 401:
            QMessageBox.warning(
                self, "Session expired",
                "This session has expired. Sign in again to continue.")
            return
        self.toast_msg(error.message, T["danger"])


# ---------------------------------------------------------------------------

def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(BASE_RED_QSS)

    login = LoginDialog()
    if login.exec() != QDialog.DialogCode.Accepted:
        return 0
    window = AdminMainWindow(login.client)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())