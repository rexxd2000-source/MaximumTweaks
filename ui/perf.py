"""Live performance sampling for the dashboard (CPU / RAM / GPU / uptime)."""
from __future__ import annotations

import subprocess
import time

from PySide6.QtCore import QThread, Signal

import psutil

INTERVAL_S = 3.0


def _sample() -> dict:
    data = {"cpu_percent": 0.0, "cpu_freq_mhz": None, "cpu_temp": None,
            "ram_used_gb": 0.0, "ram_total_gb": 0.0, "ram_avail_gb": 0.0,
            "ram_pct": 0.0, "uptime_s": 0.0,
            "gpu_name": None, "gpu_util": None, "gpu_mem_used": None,
            "gpu_mem_total": None, "gpu_temp": None}
    try:
        data["cpu_percent"] = float(psutil.cpu_percent(None) or 0.0)
        try:
            freq = psutil.cpu_freq()
            data["cpu_freq_mhz"] = int(freq.current) if freq else None
        except Exception:  # noqa: BLE001
            pass
        data["cpu_temp"] = _cpu_temp()
        try:
            vm = psutil.virtual_memory()
            data["ram_used_gb"] = round(vm.used / 2**30, 1)
            data["ram_total_gb"] = round(vm.total / 2**30, 1)
            data["ram_avail_gb"] = round(vm.available / 2**30, 1)
            data["ram_pct"] = float(vm.percent)
        except Exception:  # noqa: BLE001
            pass
        data["uptime_s"] = time.time() - psutil.boot_time()
    except Exception:  # noqa: BLE001
        pass

    gpu = _gpu_sample()
    if gpu:
        data.update(gpu)
    return data


def _cpu_temp() -> float | None:
    """Best-effort CPU temperature via psutil (usually empty on Windows)."""
    try:
        temps = psutil.sensors_temperatures()
        for name in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            for entry in temps.get(name, []) or []:
                if entry.current:
                    return float(entry.current)
        for entries in temps.values():
            for entry in entries or []:
                if entry.current:
                    return float(entry.current)
    except Exception:  # noqa: BLE001
        pass
    return None


def _gpu_sample() -> dict | None:
    """Query the primary NVIDIA GPU via nvidia-smi when available."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,"
             "temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2.5)
        line = out.stdout.strip().splitlines()
        if not line:
            return None
        parts = [p.strip() for p in line[0].split(",")]
        if len(parts) < 5:
            return None
        name, util, mem_used, mem_total, temp = parts
        return {
            "gpu_name": name,
            "gpu_util": int(util),
            "gpu_mem_used": int(mem_used),
            "gpu_mem_total": int(mem_total),
            "gpu_temp": int(temp),
        }
    except Exception:  # noqa: BLE001
        return None


def uptime_str(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def usage_color(pct: float) -> str:
    from config.app_config import THEME as TT
    if pct >= 85:
        return TT["danger"]
    if pct >= 60:
        return TT["warning"]
    return TT["success"]


class PerfSampler(QThread):
    """Samples live system stats on a background thread and emits them."""

    stats = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = False

    def run(self):
        try:
            psutil.cpu_percent(interval=0.1)  # prime the first reading
        except Exception:  # noqa: BLE001
            pass
        while not self._stop:
            data = _sample()
            self.stats.emit(data)
            for _ in range(int(INTERVAL_S * 10)):
                if self._stop:
                    return
                time.sleep(0.1)

    def stop(self):
        self._stop = True
