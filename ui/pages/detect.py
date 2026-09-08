"""Detect page: run hardware detection and show compatibility coverage."""
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.app_config import THEME as T
from database import CATEGORIES, TWEAKS
from ui.widgets import PageHeader, SectionHeader

RISK_TO_COLOR = {
    "ready": T["green"],
    "optional": T["amber"],
    "incompatible": T["red"],
    "not_for_you": T["text_dim"],
    "warning": T["orange"],
}


class DetectWorker(QThread):
    done = Signal(dict)
    error = Signal(str)

    def run(self):
        from hardware import detect
        try:
            self.done.emit(detect())
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class DetectPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        root.addWidget(PageHeader(
            "Hardware Detection",
            "Identifies your CPU, GPU, RAM, storage, network and Windows version "
            "so only compatible tweaks are recommended."))

        bar = QHBoxLayout()
        self.btn_detect = QPushButton("Start Detection")
        self.btn_detect.setObjectName("Primary")
        self.btn_detect.clicked.connect(self.start)
        self.status = QLabel("Not detected yet.")
        self.status.setObjectName("PageSub")
        bar.addWidget(self.btn_detect)
        bar.addWidget(self.status)
        bar.addStretch()
        root.addLayout(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(4, 0, 12, 0)
        self.lay.setSpacing(16)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.ctx.profile_changed.connect(self.render)
        if self.ctx.profile:
            self.render()

    def start(self):
        if self.worker and self.worker.isRunning():
            return
        self.btn_detect.setEnabled(False)
        self.status.setText("Detecting… (takes ~10 seconds)")
        self.worker = DetectWorker(self)
        self.worker.done.connect(self._done)
        self.worker.error.connect(self._error)
        self.worker.start()

    def _done(self, profile):
        self.ctx.set_profile(profile)
        self.btn_detect.setEnabled(True)
        self.status.setText("Detection complete.")

    def _error(self, msg):
        self.btn_detect.setEnabled(True)
        self.status.setText(f"Detection failed: {msg}")
        self.status.setStyleSheet(f"color: {T['red']};")

    def render(self):
        self._clear()
        profile = self.ctx.profile
        if not profile:
            return

        self.lay.addWidget(SectionHeader("Detected Hardware"))
        card = QFrame()
        card.setObjectName("Card")
        glay = QHBoxLayout(card)
        glay.setSpacing(12)
        cols = self._fact_rows(profile)
        for i in range(0, len(cols), 4):
            pass
        left = QVBoxLayout()
        right = QVBoxLayout()
        half = (len(cols) + 1) // 2
        for idx, (k, v) in enumerate(cols):
            row = QHBoxLayout()
            kk = QLabel(k)
            kk.setObjectName("Tag")
            kk.setFixedWidth(110)
            vv = QLabel(v)
            vv.setWordWrap(True)
            vv.setStyleSheet("font-weight: 600;")
            row.addWidget(kk)
            row.addWidget(vv, 1)
            (left if idx < half else right).addLayout(row)
        glay.addLayout(left, 1)
        glay.addLayout(right, 1)
        self.lay.addWidget(card)

        self.lay.addWidget(SectionHeader("Compatibility by Category"))
        grid = QVBoxLayout()
        grid.setSpacing(10)
        counts = Counter(t["category"] for t in TWEAKS)
        for name in CATEGORIES:
            cat_tweaks = [t for t in TWEAKS if t["category"] == name]
            if not cat_tweaks:
                continue
            ready = sum(1 for t in cat_tweaks if self.ctx.state_of(t["id"]) == "ready")
            total = len(cat_tweaks)
            row = QVBoxLayout()
            row.setSpacing(3)
            head = QHBoxLayout()
            lbl = QLabel(f"{name} — {ready}/{total} compatible")
            lbl.setObjectName("Tag")
            head.addWidget(lbl)
            head.addStretch()
            row.addLayout(head)
            bar = QProgressBar()
            bar.setRange(0, total)
            bar.setValue(ready)
            bar.setTextVisible(False)
            pct = (ready / total) if total else 0
            bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: "
                f"{T['green'] if pct >= 0.7 else T['amber'] if pct >= 0.4 else T['red']}; }}")
            row.addWidget(bar)
            grid.addLayout(row)
        self.lay.addLayout(grid)

    def _fact_rows(self, p):
        disk = []
        if p.get("nvme"):
            disk.append("NVMe")
        if p.get("ssd"):
            disk.append("SSD")
        if p.get("hdd"):
            disk.append("HDD")
        gpu_names = p.get("gpu_names", [])
        gpu_parts = []
        if gpu_names:
            dedicated = p.get("gpu_dedicated", [])
            integrated = p.get("gpu_integrated", [])
            if dedicated:
                gpu_parts.append(f"Dedicated: {' / '.join(dedicated)}")
            if integrated:
                gpu_parts.append(f"Integrated: {' / '.join(integrated)}")
            if not gpu_parts:
                gpu_parts = [" / ".join(gpu_names)]
        gpu_vendors = p.get("gpu_vendors", p.get("gpu", []))
        vendor_str = ", ".join(
            {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}.get(v, v)
            for v in gpu_vendors if v != "unknown")
        vram = p.get("gpu_vram_gb", 0)
        gpu_display = " | ".join(gpu_parts) if gpu_parts else "-"
        if vendor_str:
            gpu_display += f" [{vendor_str}]"
        if vram > 0:
            gpu_display += f" · {vram} GB VRAM"
        return [
            ("CPU", f"{p.get('cpu_name','-')}"),
            ("Cores", f"{p.get('cpu_cores',0)} cores / {p.get('cpu_threads',0)} threads @ {p.get('cpu_ghz',0)} GHz"),
            ("GPU", gpu_display),
            ("RAM", f"{p.get('ram_gb',0)} GB · {p.get('ram_mtps',0)} MT/s · {p.get('ram_channels',0)} module(s)"),
            ("Storage", ", ".join(disk) if disk else "-"),
            ("Network", f"{p.get('adapter',{}).get('name','-')} · {p.get('adapter',{}).get('speed','-')}"),
            ("Display", f"{p.get('monitor_refresh',0)} Hz"),
            ("Windows", f"Windows {p.get('win_version','?')} (build {p.get('win_build',0)})"),
            ("Form factor", "Laptop" if p.get("laptop") else "Desktop"),
        ]

    def _clear(self):
        from ui.widgets import clear_layout
        clear_layout(self.lay)
