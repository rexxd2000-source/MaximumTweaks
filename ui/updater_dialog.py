"""Update UI — Check for Updates button, download progress and relaunch.

Runs the updater's network/disk work on a QThread so the UI never blocks,
shows a small modal with progress while downloading, and offers an immediate
restart once the new build is staged.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from config.app_config import APP_NAME, APP_VERSION, UPDATE_EXE_NAME
from rexlog import logger


class FetchWorker(QThread):
    """Check for an update in the background."""

    done = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._err = ""

    def run(self):
        from engine import updater
        import traceback
        try:
            result = updater.fetch_update()
        except updater.UpdaterError as exc:
            self._err = str(exc)
            logger.info(f"updater: check failed: {exc}")
            result = None
        except Exception:  # noqa: BLE001
            self._err = traceback.format_exc().splitlines()[-1]
            logger.warn(f"updater: unexpected check error: {self._err}")
            result = None
        self.done.emit({"info": result, "error": self._err})


class DownloadWorker(QThread):
    """Download the staged update; reports 0..1 progress."""

    progress = Signal(float)
    done = Signal(object, str)  # new_exe path or None, error message

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._err = ""
        self._dest = None

    def _progress(self, frac):
        self.progress.emit(frac)

    def run(self):
        from engine import updater
        try:
            self._dest = updater.download(self._url, progress_cb=self._progress)
        except updater.UpdaterError as exc:
            self._err = str(exc)
        except Exception as exc:  # noqa: BLE001
            self._err = str(exc)
            logger.warn(f"updater: download error: {exc}")
        self.done.emit(self._dest, self._err)


class UpdateDialog(QDialog):
    """Check for updates, download with progress, install + restart."""

    def __init__(self, parent=None, check_on_open: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Update")
        self.setModal(True)
        self.resize(430, 250)
        self._worker = None
        self._info = None
        self._new_exe = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        title = QLabel("Update")
        title.setStyleSheet("font-size: 20px; font-weight: 900;")
        lay.addWidget(title)

        self.msg = QLabel(f"{APP_NAME} v{APP_VERSION} is the installed build.")
        self.msg.setObjectName("PageSub")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.hide()
        lay.addWidget(self.progress)

        row = QHBoxLayout()
        row.addStretch()
        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("Ghost")
        self.close_btn.clicked.connect(self.reject)
        row.addWidget(self.close_btn)
        self.primary = QPushButton("Check for Updates")
        self.primary.setObjectName("Primary")
        self.primary.clicked.connect(self._check)
        row.addWidget(self.primary)
        lay.addLayout(row)

        if check_on_open:
            self._check()

    # ---------------- actions ----------------

    def _check(self):
        self._set_busy(True, "Checking for updates\u2026")
        self.primary.setText("Checking\u2026")
        self.primary.setEnabled(False)
        self.worker = FetchWorker(self)
        self.worker.done.connect(self._on_checked)
        self.worker.start()

    def _on_checked(self, payload):
        info = payload.get("info")
        error = payload.get("error")
        self._set_busy(False, "")
        self.primary.setEnabled(True)
        self.primary.setText("Check for Updates")
        if error:
            self.msg.setText(f"Could not check for updates.\n{error}")
            return
        if info is None:
            self.msg.setText(
                f"You're up to date \u2014 {APP_NAME} v{APP_VERSION} is the "
                "latest release.")
            return
        self._info = info
        ver = info["version"]
        notes = (info.get("notes") or "").strip()
        text = (f"Update available: v{ver} \u2192 press Download & Install to "
                f"get it.")
        if notes:
            text += f"\n\nWhat's new:\n{notes[:500]}"
        self.msg.setText(text)
        self.primary.setText("Download & Install")
        self.primary.clicked.disconnect(self._check)
        self.primary.clicked.connect(self._download)

    def _download(self):
        if self._info is None:
            return
        self._set_busy(True, "Downloading update\u2026")
        self.progress.show()
        self.progress.setValue(0)
        self.primary.setEnabled(False)
        self.worker = DownloadWorker(self._info["url"], self)
        self.worker.progress.connect(
            lambda f: self.progress.setValue(int(f * 100)))
        self.worker.done.connect(self._on_downloaded)
        self.worker.start()

    def _on_downloaded(self, new_exe, error):
        self._set_busy(False, "")
        self.progress.hide()
        self.primary.setEnabled(True)
        if error or new_exe is None:
            self.msg.setText(f"Download failed.\n{error or 'unknown error'}")
            self.primary.setText("Retry")
            self.primary.clicked.disconnect(self._download)
            self.primary.clicked.connect(self._check)
            return
        self._new_exe = new_exe
        self.msg.setText(
            "Update downloaded. Restart now to apply it \u2014 the app will "
            "close, swap in the new build and relaunch itself.")
        self.primary.setText("Restart & Update")
        self.primary.clicked.disconnect(self._download)
        self.primary.clicked.connect(self._install)

    def _install(self):
        from engine import updater
        try:
            updater.install_and_restart(self._new_exe)
        except updater.UpdaterError as exc:
            self.msg.setText(f"Could not install the update.\n{exc}")
            self.primary.setText("Retry")
            self.primary.clicked.disconnect(self._install)
            self.primary.clicked.connect(self._check)
            return
        logger.info("updater: quitting to apply update")
        # Ensure state files are flushed, then terminate.
        if hasattr(self.parentWidget(), "close"):
            self.parentWidget().close()
        os._exit(0)

    # ---------------- helpers ----------------

    def _set_busy(self, busy: bool, text: str):
        if text:
            self.msg.setText(text)
        self.close_btn.setEnabled(not busy)