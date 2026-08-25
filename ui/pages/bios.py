"""BIOS page — quick-reference BIOS settings guide, virtualization, fast-boot."""
from __future__ import annotations

import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from config.app_config import THEME as T
from ui.widgets import PageHeader, SectionHeader, chip
from ui.monitor_widgets import GlassCard


class BIOSPage(QWidget):
    """BIOS — quick-reference settings guide, virtualization toggles, fast-boot options."""

    def __init__(self, ctx, navigate=None, parent=None):
        super().__init__(parent)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        layout.addWidget(PageHeader(
            "BIOS",
            "Quick-reference BIOS settings guide, virtualization toggles, and fast-boot options."))

        layout.addWidget(SectionHeader("Recommended BIOS Settings"))

        settings = [
            ("Virtualization (VT-x / AMD-V)", "Enabled",
             "Required for Hyper-V, WSL2, and Windows Sandbox. "
             "Look under CPU or Advanced > Processor Configuration.",
             "CPU"),
            ("XMP / EXPO Profile", "Enabled",
             "Runs RAM at its rated speed instead of the JEDEC default. "
             "Look under Memory or OC settings.",
             "Memory"),
            ("Fast Boot / Quick Boot", "Enabled",
             "Skips full POST to speed up boot times. Safe for daily use.",
             "Boot"),
            ("CSM (Compatibility Support Module)", "Disabled",
             "UEFI-only mode for Windows 11. Disable if you see CSM options.",
             "Boot"),
            ("Secure Boot", "Enabled",
             "Required for Windows 11 and anti-cheat compatibility.",
             "Security"),
            ("Resizable BAR / Smart Access Memory", "Enabled",
             "Allows CPU to access full GPU VRAM. Check GPU or Advanced settings.",
             "GPU"),
            ("Global C-State Control", "Enabled",
             "Allows CPU deep sleep states for lower idle power and temps.",
             "CPU"),
            ("Spread Spectrum", "Disabled",
             "Reduces electromagnetic interference but can cause clock instability. "
             "Disable for maximum performance.",
             "CPU"),
            ("Precision Boost Overdrive (PBO)", "Auto / Enabled",
             "AMD-only. Allows CPU to boost higher within thermal limits. "
             "Safe on modern Ryzen processors.",
             "CPU"),
            ("Intel Turbo Boost", "Enabled",
             "Intel-only. Enables automatic CPU frequency boosting under load.",
             "CPU"),
        ]

        grid = QGridLayout()
        grid.setSpacing(14)
        for i, (title, rec, desc, category) in enumerate(settings):
            card = GlassCard()
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(18, 16, 18, 16)
            card_lay.setSpacing(6)

            head = QHBoxLayout()
            head.setSpacing(10)
            t = QLabel(title)
            t.setStyleSheet(f"font-size: 14px; font-weight: 800; color: {T['text']};")
            head.addWidget(t, 1)
            head.addWidget(chip(f"Set to: {rec}", T["success"]))
            cat_badge = chip(category, T["accent"])
            head.addWidget(cat_badge)
            card_lay.addLayout(head)

            d = QLabel(desc)
            d.setWordWrap(True)
            d.setStyleSheet(f"color: {T['text_dim']}; font-size: 12.5px;")
            card_lay.addWidget(d)

            grid.addWidget(card, i // 2, i % 2)

        layout.addLayout(grid)
        layout.addStretch()

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
