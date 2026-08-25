"""Performance baseline — captures before/after measurements.

A baseline proves whether optimization actually helped.  The engine takes
one snapshot before applying fixes and another after, then presents the
delta to the user.

Enhanced with network measurements, DPC latency, and scoring snapshots.
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
    boot_time: float = 0.0
    # Per-process
    top_cpu_process: str = ""
    top_cpu_pct: float = 0.0
    top_mem_process: str = ""
    top_mem_pct: float = 0.0


@dataclass
class NetworkSnapshot:
    """Network measurement at a point in time."""
    ping_ms: float = 0.0
    jitter_ms: float = 0.0
    loss_pct: float = 0.0
    dns_ms: float = 0.0
    gateway_ping_ms: float = 0.0


@dataclass
class DPCSnapshot:
    """DPC/ISR latency at a point in time."""
    dpc_rate_per_sec: float = 0.0
    isr_rate_per_sec: float = 0.0
    top_offender: str = ""
    top_offender_us: float = 0.0


@dataclass
class Baseline:
    before: Snapshot = field(default_factory=Snapshot)
    after: Snapshot = field(default_factory=Snapshot)
    before_network: NetworkSnapshot = field(default_factory=NetworkSnapshot)
    after_network: NetworkSnapshot = field(default_factory=NetworkSnapshot)
    before_dpc: DPCSnapshot = field(default_factory=DPCSnapshot)
    after_dpc: DPCSnapshot = field(default_factory=DPCSnapshot)

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
    def ping_delta(self) -> float:
        return round(self.after_network.ping_ms - self.before_network.ping_ms, 1)

    @property
    def jitter_delta(self) -> float:
        return round(self.after_network.jitter_ms - self.before_network.jitter_ms, 1)

    @property
    def dpc_delta(self) -> float:
        return round(self.after_dpc.dpc_rate_per_sec - self.before_dpc.dpc_rate_per_sec, 0)

    @property
    def improved(self) -> bool:
        """Any metric improved without another worsening."""
        improved = (
            self.cpu_delta < -1.0 or
            self.ram_delta < -0.5 or
            self.process_delta < -2 or
            self.dpc_delta < -50 or
            self.jitter_delta < -2.0
        )
        worsened = (
            self.cpu_delta > 5.0 or
            self.ram_delta > 3.0 or
            self.process_delta > 10
        )
        return improved and not worsened

    def summary_text(self) -> str:
        """Human-readable before/after summary."""
        parts = []

        parts.append(f"CPU: {self.before.cpu_percent}% \u2192 {self.after.cpu_percent}% "
                     f"({self.cpu_delta:+.1f}%)")
        parts.append(f"RAM: {self.before.ram_percent}% \u2192 {self.after.ram_percent}% "
                     f"({self.ram_delta:+.1f}%)")
        parts.append(f"Processes: {self.before.process_count} \u2192 {self.after.process_count} "
                     f"({self.process_delta:+d})")

        if self.before_dpc.dpc_rate_per_sec > 0 or self.after_dpc.dpc_rate_per_sec > 0:
            parts.append(f"DPC: {self.before_dpc.dpc_rate_per_sec:.0f}/s \u2192 "
                         f"{self.after_dpc.dpc_rate_per_sec:.0f}/s "
                         f"({self.dpc_delta:+.0f}/s)")

        if self.before_network.ping_ms > 0 or self.after_network.ping_ms > 0:
            parts.append(f"Ping: {self.before_network.ping_ms:.0f}ms \u2192 "
                         f"{self.after_network.ping_ms:.0f}ms "
                         f"({self.ping_delta:+.1f}ms)")
            parts.append(f"Jitter: {self.before_network.jitter_ms:.0f}ms \u2192 "
                         f"{self.after_network.jitter_ms:.0f}ms "
                         f"({self.jitter_delta:+.1f}ms)")

        return "\n".join(parts)


def capture_snapshot() -> Snapshot:
    """Take a single measurement of the system's current state."""
    snap = Snapshot()
    snap.timestamp = time.time()

    snap.cpu_percent = psutil.cpu_percent(interval=1.0)

    vm = psutil.virtual_memory()
    snap.ram_percent = vm.percent
    snap.ram_used_gb = round(vm.used / (1024**3), 2)

    try:
        dio = psutil.disk_io_counters()
        snap.disk_active_pct = 0.0
    except Exception:
        pass

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

    try:
        snap.boot_time = time.time() - psutil.boot_time()
    except Exception:
        pass

    return snap


def capture_network_snapshot() -> NetworkSnapshot:
    """Quick network measurement for before/after comparison."""
    from engine.delay_destroyer.network_measure import measure_network
    net = measure_network()
    return NetworkSnapshot(
        ping_ms=net.internet_ping_ms,
        jitter_ms=net.internet_jitter_ms,
        loss_pct=net.internet_loss_pct,
        dns_ms=net.dns_resolution_ms,
        gateway_ping_ms=net.gateway_ping_ms,
    )


def capture_dpc_snapshot() -> DPCSnapshot:
    """Quick DPC measurement for before/after comparison."""
    from engine.delay_destroyer.scanner import SystemScanner
    scan = SystemScanner()
    # Only scan DPC-relevant data
    result = scan.scan()
    snap = DPCSnapshot(
        dpc_rate_per_sec=result.ram.dpc_rate_per_sec,
        isr_rate_per_sec=result.ram.isr_rate_per_sec,
    )
    if result.ram.dpc_top_offenders:
        top = result.ram.dpc_top_offenders[0]
        snap.top_offender = top.get("name", "")
        snap.top_offender_us = top.get("latency_us", 0)
    return snap


def measure_baseline() -> Baseline:
    """Capture a before-snapshot. Call again after optimization for the after."""
    bl = Baseline()
    bl.before = capture_snapshot()
    logger.info(f"DD baseline: CPU={bl.before.cpu_percent}%, "
                f"RAM={bl.before.ram_percent}%, "
                f"procs={bl.before.process_count}")
    return bl
