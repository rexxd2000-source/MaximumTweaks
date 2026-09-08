"""Logs page: live tail of Logs/rextweaks.log."""
from __future__ import annotations

import os

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from config.app_config import LOG_FILE
from rexlog import register_ui_sink


class LogsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pos = 0
        self._sink_registered = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("Logs")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        head.addStretch()
        self.path_lbl = QLabel(str(LOG_FILE))
        self.path_lbl.setObjectName("Tag")
        btn_clear = QPushButton("Clear Logs")
        btn_clear.clicked.connect(self._clear)
        head.addWidget(self.path_lbl)
        head.addWidget(btn_clear)
        root.addLayout(head)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(20000)
        font = QFont("Consolas")
        font.setPointSize(10)
        self.view.setFont(font)
        root.addWidget(self.view, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(800)
        self.timer.timeout.connect(self._tail)
        self.timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._tail(force=True)
        if not self._sink_registered:
            register_ui_sink(self._append_live)
            self._sink_registered = True

    def _append_live(self, message):
        self.view.appendPlainText(message)

    def _tail(self, force=False):
        try:
            size = os.path.getsize(LOG_FILE)
        except OSError:
            return
        if size < self._pos:
            self._pos = 0  # log rotated
        if size == self._pos and not force:
            return
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._pos)
                chunk = fh.read()
                self._pos = fh.tell()
        except OSError:
            return
        if chunk:
            self.view.appendPlainText(chunk.rstrip("\n"))

    def _clear(self):
        self.view.clear()
