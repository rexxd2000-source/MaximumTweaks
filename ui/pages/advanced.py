"""Advanced page — registry editor, group policy, kernel flags, BCD."""
from __future__ import annotations

import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from config.app_config import THEME as T
from database.tweaks import TWEAKS
from ui.categories import CATEGORY_GROUPS
from ui.widgets import PageHeader, TweakCard, BatchWorker, toast, SectionHeader
from ui.monitor_widgets import GlassCard


class AdvancedPage(QWidget):
    """Advanced — registry editor, group policy, kernel flags, BCD edit options."""

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
            "Advanced",
            "Registry editor shortcuts, group policy adjustments, kernel flags, and BCD options."))

        # Quick-launch tools
        layout.addWidget(SectionHeader("Quick Launch"))
        tools_grid = QGridLayout()
        tools_grid.setSpacing(12)

        tools = [
            ("\u2699", "Registry Editor", "Open regedit.exe",
             lambda: subprocess.Popen(["regedit.exe"])),
            ("\u26cf", "Group Policy", "Open gpedit.msc",
             lambda: subprocess.Popen(["gpedit.msc"])),
            ("\u2139", "MSConfig", "Open system configuration",
             lambda: subprocess.Popen(["msconfig.exe"])),
            ("\u26cf", "Device Manager", "Open devmgmt.msc",
             lambda: subprocess.Popen(["devmgmt.msc"])),
            ("\u26a1", "PowerShell (Admin)", "Open elevated PowerShell",
             lambda: subprocess.Popen(
                 ["powershell", "-NoExit"], creationflags=0x02000000)),
            ("\u2139", "Event Viewer", "Open eventvwr.msc",
             lambda: subprocess.Popen(["eventvwr.msc"])),
        ]

        for i, (icon, title, desc, action) in enumerate(tools):
            card = GlassCard()
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(14, 12, 14, 12)
            card_lay.setSpacing(4)
            row = QHBoxLayout()
            row.setSpacing(8)
            ic = QLabel(icon)
            ic.setStyleSheet(f"font-size: 18px; color: {T['accent']}; background: transparent;")
            row.addWidget(ic)
            t = QLabel(title)
            t.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {T['text']}; background: transparent;")
            row.addWidget(t, 1)
            card_lay.addLayout(row)
            d = QLabel(desc)
            d.setStyleSheet(f"font-size: 11px; color: {T['text_dim']}; background: transparent;")
            card_lay.addWidget(d)
            card.setCursor(Qt.PointingHandCursor)
            card.mousePressEvent = lambda e, a=action: a()
            tools_grid.addWidget(card, i // 3, i % 3)

        layout.addLayout(tools_grid)

        # Advanced tweaks
        layout.addWidget(SectionHeader("Advanced Tweaks"))
        cats = set()
        for gk in ("system",):
            for db_cat in CATEGORY_GROUPS.get(gk, {}).get("db", []):
                cats.add(db_cat)
        tweaks = [t for t in TWEAKS
                  if t["category"] in ("Advanced", "Experimental", "Registry", "Scheduling")][:20]

        if tweaks:
            grid = QGridLayout()
            grid.setSpacing(12)
            for i, tweak in enumerate(tweaks):
                card = TweakCard(self.ctx, tweak)
                card.apply_requested.connect(
                    lambda tid: (BatchWorker([tid], "apply", self).start(),
                                 self.ctx.note_state_change()))
                card.revert_requested.connect(
                    lambda tid: (BatchWorker([tid], "revert", self).start(),
                                 self.ctx.note_state_change()))
                grid.addWidget(card, i // 2, i % 2)
            layout.addLayout(grid)

        layout.addStretch()

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
