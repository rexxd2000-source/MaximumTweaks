"""Backups page — registry backup, restore points, and rollback."""
from __future__ import annotations

import subprocess
import sys
import time

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from config.app_config import THEME as T
from engine import activity
from ui.widgets import PageHeader, SectionHeader, chip, toast
from ui.monitor_widgets import GlassCard


class _RestorePointWorker(QThread):
    """Create a Windows System Restore point in the background."""
    done = Signal(bool, str)

    def run(self):
        try:
            ps = (
                "Checkpoint-Computer -Description 'Maximum Tweaks Backup' "
                "-RestorePointType MODIFY_SETTINGS"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=120,
                creationflags=0x08000000)
            if r.returncode == 0:
                self.done.emit(True, "Restore point created successfully.")
            else:
                err = r.stderr.strip() or r.stdout.strip() or "Unknown error"
                self.done.emit(False, err[:200])
        except Exception as exc:
            self.done.emit(False, str(exc)[:200])


class BackupsPage(QWidget):
    """Registry backup, Windows restore point creation, and rollback."""

    def __init__(self, ctx, navigate=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._navigate = navigate
        self._worker = None

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        layout.addWidget(PageHeader(
            "Backups",
            "Registry backup, Windows restore points, and full system rollback."))

        # Action cards
        cards = QGridLayout()
        cards.setSpacing(12)

        # Restore point card
        rp_card = GlassCard()
        rp_lay = QVBoxLayout(rp_card)
        rp_lay.setContentsMargins(18, 16, 18, 16)
        rp_lay.setSpacing(10)
        rp_title = QLabel("System Restore Point")
        rp_title.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {T['text']};")
        rp_lay.addWidget(rp_title)
        rp_desc = QLabel("Create a Windows restore point before applying any tweaks. "
                         "This allows you to roll back system changes if needed.")
        rp_desc.setWordWrap(True)
        rp_desc.setStyleSheet(f"color: {T['text_dim']}; font-size: 12.5px;")
        rp_lay.addWidget(rp_desc)
        rp_btn = QPushButton("Create Restore Point")
        rp_btn.setObjectName("Primary")
        rp_btn.setMinimumHeight(38)
        rp_btn.clicked.connect(self._create_restore_point)
        rp_lay.addWidget(rp_btn)
        cards.addWidget(rp_card, 0, 0)

        # Registry backup card
        reg_card = GlassCard()
        reg_lay = QVBoxLayout(reg_card)
        reg_lay.setContentsMargins(18, 16, 18, 16)
        reg_lay.setSpacing(10)
        reg_title = QLabel("Registry Backup")
        reg_title.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {T['text']};")
        reg_lay.addWidget(reg_title)
        reg_desc = QLabel("Export the current registry state to a file. "
                          "Maximum Tweaks tracks applied tweaks for per-tweak revert.")
        reg_desc.setWordWrap(True)
        reg_desc.setStyleSheet(f"color: {T['text_dim']}; font-size: 12.5px;")
        reg_lay.addWidget(reg_desc)
        reg_btn = QPushButton("Backup Registry")
        reg_btn.setObjectName("Primary")
        reg_btn.setMinimumHeight(38)
        reg_btn.clicked.connect(self._backup_registry)
        reg_lay.addWidget(reg_btn)
        cards.addWidget(reg_card, 0, 1)

        # Full rollback card
        rb_card = GlassCard()
        rb_lay = QVBoxLayout(rb_card)
        rb_lay.setContentsMargins(18, 16, 18, 16)
        rb_lay.setSpacing(10)
        rb_title = QLabel("Full System Rollback")
        rb_title.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {T['text']};")
        rb_lay.addWidget(rb_title)
        rb_desc = QLabel("Revert all Maximum Tweaks changes at once. "
                         "This uses the built-in per-tweak revert system.")
        rb_desc.setWordWrap(True)
        rb_desc.setStyleSheet(f"color: {T['text_dim']}; font-size: 12.5px;")
        rb_lay.addWidget(rb_desc)
        rb_btn = QPushButton("Revert All Tweaks")
        rb_btn.setObjectName("Secondary")
        rb_btn.setMinimumHeight(38)
        rb_btn.setStyleSheet(
            f"QPushButton {{ background-color: {T['card']}; color: {T['danger']};"
            f" border: 1px solid {T['danger']}; border-radius: 10px;"
            f" padding: 8px 16px; font-weight: 700; }}"
            f"QPushButton:hover {{ background-color: rgba(248, 121, 121, 0.1); }}")
        rb_btn.clicked.connect(self._revert_all)
        rb_lay.addWidget(rb_btn)
        cards.addWidget(rb_card, 0, 2)

        layout.addLayout(cards)
        layout.addStretch()

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _create_restore_point(self):
        if self._worker and self._worker.isRunning():
            toast("Already creating a restore point...", "info", self)
            return
        self._worker = _RestorePointWorker(self)
        self._worker.done.connect(self._on_restore_point_done)
        self._worker.start()
        toast("Creating restore point...", "info", self)

    def _on_restore_point_done(self, ok, msg):
        if ok:
            toast("Restore point created!", "success", self)
            activity.emit("success", "System restore point created")
        else:
            toast(f"Failed: {msg}", "error", self)
            activity.emit("error", f"Restore point failed: {msg}")

    def _backup_registry(self):
        try:
            from config.app_config import DIRS
            backup_dir = DIRS["backups"]
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            out = backup_dir / f"registry_{ts}.reg"
            subprocess.run(
                ["reg", "export", "HKCU", str(out), "/y"],
                capture_output=True, timeout=60,
                creationflags=0x08000000)
            toast(f"Registry backed up to {out.name}", "success", self)
            activity.emit("success", f"Registry exported: {out.name}")
        except Exception as exc:
            toast(f"Backup failed: {exc}", "error", self)

    def _revert_all(self):
        from ui.widgets import ProgressDialog
        from database import TWEAKS
        applied = [t["id"] for t in TWEAKS if t["id"] in self.ctx.applied_ids()]
        if not applied:
            toast("No tweaks to revert.", "info", self)
            return
        ProgressDialog(self, applied, mode="revert").exec()
        self.ctx.note_state_change()
