"""Fixes page — automated troubleshooters (SFC, DISM, DLL, WU, drivers)."""
from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QProgressBar, QScrollArea, QVBoxLayout, QWidget,
)

from config.app_config import THEME as T
from engine import activity
from ui.widgets import PageHeader, SectionHeader, toast
from ui.monitor_widgets import GlassCard


class _FixWorker(QThread):
    """Run a system fix command in the background."""
    progress = Signal(str)
    done = Signal(bool, str)

    def __init__(self, command: list[str], label: str, parent=None):
        super().__init__(parent)
        self.command = command
        self.label = label

    def run(self):
        try:
            self.progress.emit(f"Running {self.label}...")
            r = subprocess.run(
                self.command, capture_output=True, text=True, timeout=600,
                creationflags=0x08000000)
            output = (r.stdout + "\n" + r.stderr).strip()
            if r.returncode == 0:
                self.done.emit(True, f"{self.label} completed successfully.\n{output[-500:]}")
            else:
                self.done.emit(False, f"{self.label} returned code {r.returncode}.\n{output[-500:]}")
        except subprocess.TimeoutExpired:
            self.done.emit(False, f"{self.label} timed out after 10 minutes.")
        except Exception as exc:
            self.done.emit(False, f"{self.label} failed: {exc}")


class FixCard(QFrame):
    """Card for a single system fix action with progress output."""

    def __init__(self, icon, title, desc, command, label, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._worker = None
        self._command = command
        self._label = label
        self.setStyleSheet(
            f"#Card {{ background-color: {T['card']};"
            f" border: 1px solid {T['border']};"
            f" border-radius: 14px; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        ic = QLabel(icon)
        ic.setStyleSheet(f"font-size: 20px; color: {T['accent']}; background: transparent;")
        head.addWidget(ic)
        box = QVBoxLayout()
        box.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {T['text']}; background: transparent;")
        box.addWidget(t)
        d = QLabel(desc)
        d.setStyleSheet(f"font-size: 12px; color: {T['text_dim']}; background: transparent;")
        d.setWordWrap(True)
        box.addWidget(d)
        head.addLayout(box, 1)
        lay.addLayout(head)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setFixedHeight(4)
        self._bar.setVisible(False)
        lay.addWidget(self._bar)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumHeight(100)
        self._output.setVisible(False)
        self._output.setStyleSheet(
            f"background-color: {T['bg_alt']}; border: 1px solid {T['border']};"
            " border-radius: 8px; font-size: 11px; color: {T['text_dim']}; padding: 8px;")
        lay.addWidget(self._output)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn = QPushButton(f"Run {label}")
        self._btn.setObjectName("Primary")
        self._btn.setMinimumHeight(34)
        self._btn.clicked.connect(self._run)
        btn_row.addWidget(self._btn)
        lay.addLayout(btn_row)

    def _run(self):
        if self._worker and self._worker.isRunning():
            return
        self._bar.setVisible(True)
        self._output.setVisible(True)
        self._output.clear()
        self._btn.setEnabled(False)
        self._btn.setText("Running...")

        self._worker = _FixWorker(self._command, self._label, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, msg):
        self._output.appendPlainText(msg)

    def _on_done(self, ok, msg):
        self._bar.setVisible(False)
        self._btn.setEnabled(True)
        self._btn.setText(f"Run {self._label}")
        self._output.appendPlainText(msg)
        if ok:
            toast(f"{self._label} completed!", "success", self)
            activity.emit("success", f"{self._label} completed")
        else:
            toast(f"{self._label} failed.", "error", self)
            activity.emit("error", f"{self._label} failed: {msg[:100]}")


class FixesPage(QWidget):
    """Automated troubleshooters — DLL repairs, SFC/DISM, Windows Update, drivers."""

    def __init__(self, ctx, navigate=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        layout.addWidget(PageHeader(
            "Fixes",
            "Automated troubleshooters — SFC, DISM, Windows Update repair, and driver fixes."))

        cards = QGridLayout()
        cards.setSpacing(14)

        fixes = [
            FixCard(
                "\u26cf", "System File Checker",
                "Scan and repair corrupted Windows system files.",
                ["sfc", "/scannow"], "SFC"),
            FixCard(
                "\u2699", "DISM Repair",
                "Repair the Windows component store and system image.",
                ["dism", "/online", "/cleanup-image", "/restorehealth"], "DISM"),
            FixCard(
                "\u2139", "Windows Update Fix",
                "Reset Windows Update components and services.",
                ["powershell", "-NoProfile", "-Command",
                 "Stop-Service wuauserv,bits; "
                 "Remove-Item -Recurse -Force $env:SystemRoot\\SoftwareDistribution -ErrorAction SilentlyContinue; "
                 "Start-Service wuauserv,bits"], "WU Reset"),
            FixCard(
                "\u26cf", "Check Disk",
                "Scan the system drive for filesystem errors.",
                ["chkdsk", "C:", "/f", "/r"], "CHKDSK"),
            FixCard(
                "\u2139", "DISM Component Cleanup",
                "Clean up superseded components to free disk space.",
                ["dism", "/online", "/cleanup-image", "/startcomponentcleanup"],
                "DISM Cleanup"),
            FixCard(
                "\u26a1", "DLL Repair",
                "Re-register common DirectX and Visual C++ DLLs.",
                ["powershell", "-NoProfile", "-Command",
                 "Get-ChildItem 'C:\\Windows\\System32\\d3d*.dll' | "
                 "ForEach-Object { regsvr32 /s $_.FullName }"], "DLL Re-register"),
        ]

        for i, card in enumerate(fixes):
            cards.addWidget(card, i // 2, i % 2)

        layout.addLayout(cards)
        layout.addStretch()

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
