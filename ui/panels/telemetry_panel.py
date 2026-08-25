"""Right-side persistent telemetry panel — live system metrics."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QScrollArea, QVBoxLayout, QWidget,
)

from config.app_config import THEME as T
from ui.monitor_widgets import NeonBar, GlassCard, threshold_color


class TelemetryMetric(QWidget):
    """Single metric row: label + value + optional bar."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        self._label = QLabel(label)
        self._label.setStyleSheet(
            f"font-size: 10px; font-weight: 800; color: {T['text_faint']};"
            " letter-spacing: 1px; background: transparent;")
        head.addWidget(self._label)
        head.addStretch()
        self._value = QLabel("--")
        self._value.setStyleSheet(
            f"font-size: 13px; font-weight: 800; color: {T['text']};"
            " background: transparent;")
        head.addWidget(self._value)
        lay.addLayout(head)

        self.bar = NeonBar()
        self.bar.setFixedHeight(6)
        lay.addWidget(self.bar)

    def update_value(self, value: str, pct: float = 0.0, color: str = None):
        self._value.setText(value)
        self.bar.set_value(pct, color)


class TelemetryPanel(QFrame):
    """Right-side panel showing live CPU/GPU/RAM/FPS metrics."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedWidth(260)
        self.setMinimumHeight(200)
        self.setStyleSheet(
            f"#Card {{ background-color: {T['card']};"
            f" border: 1px solid {T['border']};"
            f" border-radius: 14px; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("LIVE TELEMETRY")
        title.setStyleSheet(
            f"font-size: 10px; font-weight: 800; color: {T['text_faint']};"
            " letter-spacing: 2px; background: transparent;")
        outer.addWidget(title)

        self.cpu = TelemetryMetric("CPU")
        self.gpu = TelemetryMetric("GPU")
        self.ram = TelemetryMetric("RAM")
        self.fps = TelemetryMetric("FPS")
        self.ping = TelemetryMetric("PING")
        self.latency = TelemetryMetric("LATENCY")

        for m in (self.cpu, self.gpu, self.ram, self.fps, self.ping, self.latency):
            outer.addWidget(m)

        outer.addStretch()

    def update_metrics(self, data: dict):
        """Update all metrics from a TelemetrySampler dict."""
        cpu_pct = data.get("cpu_percent", 0)
        cpu_temp = data.get("cpu_temp")
        cpu_freq = data.get("cpu_freq_mhz")
        cpu_label = f"{cpu_pct:.0f}%"
        if cpu_temp:
            cpu_label += f"  {cpu_temp:.0f}\u00b0C"
        self.cpu.update_value(cpu_label, cpu_pct, threshold_color(cpu_pct))

        gpu_util = data.get("gpu_util")
        gpu_temp = data.get("gpu_temp")
        if gpu_util is not None:
            gpu_label = f"{gpu_util}%"
            if gpu_temp:
                gpu_label += f"  {gpu_temp}\u00b0C"
            self.gpu.update_value(gpu_label, gpu_util, threshold_color(gpu_util))
        else:
            self.gpu.update_value("N/A", 0)

        ram_pct = data.get("ram_pct", 0)
        ram_used = data.get("ram_used_gb", 0)
        ram_total = data.get("ram_total_gb", 0)
        self.ram.update_value(
            f"{ram_used:.1f}/{ram_total:.1f} GB", ram_pct,
            threshold_color(ram_pct))

        # FPS / Ping / Latency are placeholders until game telemetry is active
        self.fps.update_value("--", 0)
        self.ping.update_value("-- ms", 0)
        self.latency.update_value("-- ms", 0)
