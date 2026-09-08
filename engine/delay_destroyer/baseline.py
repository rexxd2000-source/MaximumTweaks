"""Performance baseline — captures before/after measurements.

A baseline proves whether optimization actually helped.  The engine takes
one snapshot before applying fixes and another after, then presents the
delta to the user.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import psutil

from rexlog import logger


@dataclass
class Snapshot:
    """Single point-in-time system measurement."""
    timestamp: float = 0.0
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    ram_used_gb: float = 0.0
    disk_active_pct: float = 0.0
    process_count: int = 0
    boot_time: float = 0.0  # seconds since last boot
    # Per-process
    top_cpu_process: str = ""
    top_cpu_pct: float = 0.0
    top_mem_process: str = ""
    top_mem_pct: float = 0.0


@dataclass
class Baseline:
    before: Snapshot = field(default_factory=Snapshot)
    after: Snapshot = field(default_factory=Snapshot)

    @property
    def cpu_delta(self) -> float:
        return round(self.after.cpu_percent - self.before.cpu_percent, 1)

    @property
    def ram_delta(self) -> float:
        return round(self.after.ram_percent - self.before.ram_percent, 1)

    @property
    def process_delta(self) -> int:
        return self.after.process_count - self.before.process_count

    @property
    def improved(self) -> bool:
        """Any metric improved without another worsening."""
        improved = (
            self.cpu_delta < -1.0 or
            self.ram_delta < -0.5 or
            self.process_delta < -2
        )
        worsened = (
            self.cpu_delta > 5.0 or
            self.ram_delta > 3.0 or
            self.process_delta > 10
        )
        return improved and not worsened


def capture_snapshot() -> Snapshot:
    """Take a single measurement of the system's current state."""
    snap = Snapshot()
    snap.timestamp = time.time()

    # CPU — sample over 1 second for accuracy
    snap.cpu_percent = psutil.cpu_percent(interval=1.0)

    # RAM
    vm = psutil.virtual_memory()
    snap.ram_percent = vm.percent
    snap.ram_used_gb = round(vm.used / (1024**3), 2)

    # Disk activity
    try:
        dio = psutil.disk_io_counters()
        # Percentage is approximate: active / total
        snap.disk_active_pct = 0.0  # psutil doesn't give a direct %; set to 0
    except Exception:
        pass

    # Process count + top consumers
    snap.process_count = 0
    top_cpu = ("", 0.0)
    top_mem = ("", 0.0)
    for p in psutil.process_iter(["name", "cpu_percent", "memory_percent", "status"]):
        try:
            info = p.info
            if info["status"] != "running":
                continue
            snap.process_count += 1
            cpu = info.get("cpu_percent", 0) or 0
            mem = info.get("memory_percent", 0) or 0
            if cpu > top_cpu[1]:
                top_cpu = (info["name"], cpu)
            if mem > top_mem[1]:
                top_mem = (info["name"], mem)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    snap.top_cpu_process = top_cpu[0]
    snap.top_cpu_pct = top_cpu[1]
    snap.top_mem_process = top_mem[0]
    snap.top_mem_pct = top_mem[1]

    # Boot time
    try:
        snap.boot_time = time.time() - psutil.boot_time()
    except Exception:
        pass

    return snap


def measure_baseline() -> Baseline:
    """Capture a before-snapshot. Call again after optimization for the after."""
    bl = Baseline()
    bl.before = capture_snapshot()
    logger.info(f"DD baseline: CPU={bl.before.cpu_percent}%, "
                f"RAM={bl.before.ram_percent}%, "
                f"procs={bl.before.process_count}")
    return bl
