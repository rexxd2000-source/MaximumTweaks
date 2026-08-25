"""Home page — master calibration dashboard with overview metrics."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from config.app_config import APP_NAME, APP_VERSION, THEME as T
from ui.widgets import PageHeader, StatCard, SectionHeader, chip, badge


class HomePage(QWidget):
    """Master dashboard with high-level system metrics and top recommendations."""

    def __init__(self, ctx, navigate=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._navigate = navigate

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        layout.addWidget(PageHeader(
            "Home",
            f"{APP_NAME} v{APP_VERSION} — detect, optimize, measure, revert."))

        # Quick stats row
        stats = QGridLayout()
        stats.setSpacing(12)
        stats.addWidget(StatCard("\u2699", "Tweaks Applied", "0", "total applied"), 0, 0)
        stats.addWidget(StatCard("\u26a1", "Hardware Ready", "0", "compatible tweaks"), 0, 1)
        stats.addWidget(StatCard("\u2605", "Profiles Active", "None", "no game profile"), 0, 2)
        stats.addWidget(StatCard("\u2139", "System Uptime", "--", ""), 0, 3)
        layout.addLayout(stats)

        # System overview
        layout.addWidget(SectionHeader("System Overview"))
        info_card = QFrame()
        info_card.setObjectName("Card")
        info_lay = QVBoxLayout(info_card)
        info_lay.setContentsMargins(18, 16, 18, 16)
        info_lay.setSpacing(8)

        info_label = QLabel(
            "Your system will be detected on startup. "
            "Hardware info, compatibility scores and recommendations "
            "will appear here once the scan completes.")
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {T['text_dim']}; font-size: 13px;")
        info_lay.addWidget(info_label)
        layout.addWidget(info_card)

        # Top recommendations
        layout.addWidget(SectionHeader("Top Recommendations"))
        rec_card = QFrame()
        rec_card.setObjectName("Card")
        rec_lay = QVBoxLayout(rec_card)
        rec_lay.setContentsMargins(18, 16, 18, 16)
        rec_lay.setSpacing(8)

        rec_items = [
            ("\u26a1", "Enable Hardware GPU Scheduling", "Safe", "Boosts GPU scheduling latency"),
            ("\u26a1", "Optimize TCP/IP Stack", "Safe", "Lower network latency"),
            ("\u26a1", "Disable Game DVR", "Safe", "Reclaim FPS from background recording"),
        ]
        for icon, title, risk, desc in rec_items:
            row = QHBoxLayout()
            row.setSpacing(10)
            ic = QLabel(icon)
            ic.setStyleSheet(f"font-size: 16px; color: {T['accent']}; background: transparent;")
            row.addWidget(ic)
            box = QVBoxLayout()
            box.setSpacing(1)
            t = QLabel(title)
            t.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {T['text']}; background: transparent;")
            box.addWidget(t)
            d = QLabel(desc)
            d.setStyleSheet(f"font-size: 11px; color: {T['text_dim']}; background: transparent;")
            box.addWidget(d)
            row.addLayout(box, 1)
            row.addWidget(chip(risk, T["success"]))
            rec_lay.addLayout(row)

        layout.addWidget(rec_card)
        layout.addStretch()

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
