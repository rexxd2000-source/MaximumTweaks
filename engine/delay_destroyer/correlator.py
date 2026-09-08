"""Delay-source correlation engine — identifies compound delay patterns.

Takes the full ScanResult and a list of Findings, then produces
CorrelatedFinding objects that represent compound delay sources
spanning multiple subsystems.

Each correlation references the appropriate tweak category rather
than duplicating fix suggestions.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

from engine.delay_destroyer.risk import Risk
from engine.delay_destroyer.scanner import ScanResult
from engine.delay_destroyer.diagnoser import Finding


def _correlation_id(prefix: str) -> str:
    raw = f"{prefix}_{time.monotonic_ns()}"
    return f"corr_{prefix}_{hashlib.md5(raw.encode()).hexdigest()[:10]}"


@dataclass
class CorrelatedFinding:
    id: str
    title: str
    description: str
    contributing_systems: list[str]
    evidence_items: list[str]
    risk: Risk
    severity: str
    impact: str
    recommendation: str
    measured: bool


class Correlator:
    """Detects compound delay sources that span multiple subsystems."""

    def correlate(
        self, scan: ScanResult, findings: list[Finding]
    ) -> list[CorrelatedFinding]:
        results: list[CorrelatedFinding] = []
        self._storage_thrashing(scan, results)
        self._dpc_cpu_contention(scan, results)
        self._input_dpc_delay(scan, results)
        self._driver_instability_delay(scan, results)
        self._memory_leak_delay(scan, results)
        self._double_gpu_overhead(scan, results)
        self._background_contention(scan, results)
        self._pending_reboot_delay(scan, results)
        self._audio_dpc_delay(scan, results)
        self._display_pipeline_stress(scan, results)
        self._memory_startup_bloat(scan, results)
        self._network_dpc_delay(scan, results)
        self._storage_driver_compound(scan, results)
        return results

    def _storage_thrashing(self, s: ScanResult, out: list[CorrelatedFinding]) -> None:
        if not (s.ram.pressure > 0.8 and s.storage.has_hdd and not s.storage.has_ssd):
            return
        out.append(CorrelatedFinding(
            id=_correlation_id("thrashing"),
            title="Storage thrashing — high RAM on HDD-only system",
            description=(
                f"Memory at {s.ram.pressure * 100:.0f}% on HDD-only storage. "
                "Each pagefile swap causes a multi-millisecond freeze. "
                "This is the single worst delay scenario for system responsiveness."
            ),
            contributing_systems=["ram", "storage"],
            evidence_items=[
                f"RAM: {s.ram.pressure * 100:.0f}% ({s.ram.used_gb}/{s.ram.total_gb}GB)",
                f"Storage: HDD only (SSD: {s.storage.has_ssd}, NVMe: {s.storage.has_nvme})",
                f"Pagefile: {s.ram.pagefile_gb}GB",
            ],
            risk=Risk.HIGH,
            severity="critical",
            impact="high",
            recommendation="Review RAM category to reduce memory pressure. Review Storage category to evaluate SSD upgrade.",
            measured=True,
        ))

    def _dpc_cpu_contention(self, s: ScanResult, out: list[CorrelatedFinding]) -> None:
        dpc_offenders = s.ram.dpc_top_offenders
        if not (len(dpc_offenders) > 2 and s.cpu.usage_percent > 50):
            return
        names = ", ".join(o.get("name", "?") for o in dpc_offenders[:5])
        out.append(CorrelatedFinding(
            id=_correlation_id("dpc_cpu"),
            title="Driver scheduling contention — DPC offenders under high CPU",
            description=(
                f"Multiple DPC offenders ({names}) active at "
                f"{s.cpu.usage_percent:.0f}% CPU. Drivers are competing "
                "for CPU time, degrading real-time responsiveness and "
                "causing micro-stutters."
            ),
            contributing_systems=["drivers", "cpu"],
            evidence_items=[
                f"DPC offenders: {len(dpc_offenders)} ({names})",
                f"CPU: {s.cpu.usage_percent:.0f}%",
            ],
            risk=Risk.HIGH,
            severity="warning",
            impact="high",
            recommendation="Review Drivers category for DPC-heavy drivers. Review CPU category for scheduling.",
            measured=False,
        ))

    def _input_dpc_delay(self, s: ScanResult, out: list[CorrelatedFinding]) -> None:
        has_input = (len(s.input.hid_driver_issues) > 0 or len(s.input.usb_driver_issues) > 0)
        if not (has_input and len(s.ram.dpc_top_offenders) > 1):
            return
        issues = s.input.hid_driver_issues + s.input.usb_driver_issues
        issues_str = "; ".join(issues[:4])
        names = ", ".join(o.get("name", "?") for o in s.ram.dpc_top_offenders[:3])
        out.append(CorrelatedFinding(
            id=_correlation_id("input_dpc"),
            title="Input delay — HID/USB issues with DPC contention",
            description=(
                f"HID/USB issues ({issues_str}) combined with DPC "
                f"offenders ({names}). Input devices may experience "
                "delayed signal delivery, increasing perceived input lag."
            ),
            contributing_systems=["input", "drivers"],
            evidence_items=[
                f"HID/USB issues: {len(issues)} ({issues_str})",
                f"DPC offenders: {len(s.ram.dpc_top_offenders)} ({names})",
            ],
            risk=Risk.MODERATE,
            severity="warning",
            impact="medium",
            recommendation="Review Input category for HID/USB issues. Review Drivers for DPC sources.",
            measured=False,
        ))

    def _driver_instability_delay(self, s: ScanResult, out: list[CorrelatedFinding]) -> None:
        if not (len(s.os.device_errors) > 0 and s.drivers.driver_resets > 0):
            return
        names = ", ".join(d.get("name", "?") for d in s.os.device_errors[:4])
        out.append(CorrelatedFinding(
            id=_correlation_id("unstable_drivers"),
            title="Unstable driver layer — device errors + driver resets",
            description=(
                f"{len(s.os.device_errors)} device error(s) and "
                f"{s.drivers.driver_resets} driver reset(s). This "
                "combination indicates a fundamentally unstable driver "
                "stack causing freezes and latency spikes."
            ),
            contributing_systems=["os", "drivers", "gpu"],
            evidence_items=[
                f"Device errors: {len(s.os.device_errors)} ({names})",
                f"Driver resets: {s.drivers.driver_resets}",
            ],
            risk=Risk.HIGH,
            severity="critical",
            impact="high",
            recommendation="Review GPU category for driver updates. Review Drivers category for problematic drivers.",
            measured=True,
        ))

    def _memory_leak_delay(self, s: ScanResult, out: list[CorrelatedFinding]) -> None:
        if not (s.os.uptime_hours > 168 and s.ram.pressure > 0.7 and s.processes.count > 100):
            return
        days = s.os.uptime_hours / 24.0
        out.append(CorrelatedFinding(
            id=_correlation_id("mem_leak"),
            title="Possible memory leak — high RAM after extended uptime",
            description=(
                f"Up {days:.1f} days with {s.ram.pressure * 100:.0f}% RAM "
                f"and {s.processes.count} processes. Long uptime + high "
                "memory is a classic leak pattern. A reboot may help."
            ),
            contributing_systems=["os", "ram", "processes"],
            evidence_items=[
                f"Uptime: {s.os.uptime_hours:.0f}h ({days:.1f} days)",
                f"RAM: {s.ram.pressure * 100:.0f}% ({s.ram.used_gb}/{s.ram.total_gb}GB)",
                f"Processes: {s.processes.count}",
            ],
            risk=Risk.MODERATE,
            severity="warning",
            impact="medium",
            recommendation="Review RAM category. Consider restarting to clear potential leaks.",
            measured=False,
        ))

    def _double_gpu_overhead(self, s: ScanResult, out: list[CorrelatedFinding]) -> None:
        if not (s.os.game_dvr_enabled and s.gpu.gfe_overlay_enabled):
            return
        out.append(CorrelatedFinding(
            id=_correlation_id("double_gpu"),
            title="Double GPU overhead — Game DVR + NVIDIA overlay",
            description=(
                "Both Game DVR and NVIDIA overlay are active. Each uses "
                "a separate GPU encoding pipeline, consuming VRAM and "
                "GPU cycles that could be allocated to rendering."
            ),
            contributing_systems=["os", "gpu"],
            evidence_items=[
                f"Game DVR: {s.os.game_dvr_enabled}",
                f"NVIDIA overlay: {s.gpu.gfe_overlay_enabled}",
                f"VRAM: {s.gpu.dedicated_vram_gb:.1f}GB dedicated",
            ],
            risk=Risk.LOW,
            severity="info",
            impact="low",
            recommendation="Review GPU category for overlay settings. Review OS category for Game DVR.",
            measured=True,
        ))

    def _background_contention(self, s: ScanResult, out: list[CorrelatedFinding]) -> None:
        if not (len(s.processes.high_cpu) > 2 and s.services.total_running > 80):
            return
        names = ", ".join(p.get("name", "?") for p in s.processes.high_cpu[:5])
        out.append(CorrelatedFinding(
            id=_correlation_id("bg_contention"),
            title="Background resource contention — high CPU processes + excessive services",
            description=(
                f"{len(s.processes.high_cpu)} processes using high CPU "
                f"({names}) with {s.services.total_running} services running. "
                "This combination steals resources from foreground apps."
            ),
            contributing_systems=["processes", "services"],
            evidence_items=[
                f"High CPU: {len(s.processes.high_cpu)} ({names})",
                f"Running services: {s.services.total_running}",
            ],
            risk=Risk.MODERATE,
            severity="info",
            impact="medium",
            recommendation="Review Services and Processes categories to reduce background load.",
            measured=True,
        ))

    def _pending_reboot_delay(self, s: ScanResult, out: list[CorrelatedFinding]) -> None:
        if not (s.os.pending_reboot and s.os.critical_events > 5):
            return
        out.append(CorrelatedFinding(
            id=_correlation_id("pending_reboot"),
            title="Pending reboot with elevated critical events",
            description=(
                f"Windows has pending updates requiring restart while "
                f"{s.os.critical_events} critical events logged. Pending "
                "reboots cause driver conflicts and accumulated instability."
            ),
            contributing_systems=["os", "drivers"],
            evidence_items=[
                f"Pending reboot: {s.os.pending_reboot}",
                f"Critical events (7-day): {s.os.critical_events}",
                f"Last update: {s.os.last_windows_update or 'unknown'}",
            ],
            risk=Risk.LOW,
            severity="info",
            impact="low",
            recommendation="Consider restarting to clear pending updates and reset driver state.",
            measured=True,
        ))

    def _audio_dpc_delay(self, s: ScanResult, out: list[CorrelatedFinding]) -> None:
        if not (len(s.ram.dpc_top_offenders) > 2 and len(s.audio.audio_issues) > 0):
            return
        names = ", ".join(o.get("name", "?") for o in s.ram.dpc_top_offenders[:3])
        issues_str = "; ".join(s.audio.audio_issues[:3])
        out.append(CorrelatedFinding(
            id=_correlation_id("audio_dpc"),
            title="Audio latency risk — DPC contention with audio driver issues",
            description=(
                f"DPC offenders ({names}) active with audio driver "
                f"issues ({issues_str}). DPC contention directly causes "
                "audio dropouts, crackling, and lip-sync drift."
            ),
            contributing_systems=["audio", "drivers"],
            evidence_items=[
                f"DPC offenders: {len(s.ram.dpc_top_offenders)} ({names})",
                f"Audio issues: {len(s.audio.audio_issues)} ({issues_str})",
            ],
            risk=Risk.MODERATE,
            severity="warning",
            impact="medium",
            recommendation="Review Drivers category for DPC sources. Review Audio category for driver issues.",
            measured=False,
        ))

    def _display_pipeline_stress(self, s: ScanResult, out: list[CorrelatedFinding]) -> None:
        if not (s.display.multi_monitor and s.display.dwm_enabled
                and (len(s.display.display_driver_errors) > 0 or s.gpu.tdr_level < 3)):
            return
        out.append(CorrelatedFinding(
            id=_correlation_id("display_stress"),
            title="Display pipeline stress — multi-monitor DWM with driver/TDR issues",
            description=(
                f"{s.display.monitor_count} monitors with DWM and TDR "
                f"level {s.gpu.tdr_level}. Multi-monitor DWM increases "
                "GPU overhead. Combined with driver errors or low TDR, "
                "the display pipeline becomes fragile."
            ),
            contributing_systems=["display", "gpu"],
            evidence_items=[
                f"Monitors: {s.display.monitor_count}",
                f"DWM: {s.display.dwm_enabled}",
                f"TDR: level={s.gpu.tdr_level}, delay={s.gpu.tdr_delay}s",
                f"Display errors: {len(s.display.display_driver_errors)}",
            ],
            risk=Risk.MODERATE,
            severity="warning",
            impact="medium",
            recommendation="Review GPU category for driver updates and TDR settings.",
            measured=False,
        ))

    def _memory_startup_bloat(self, s: ScanResult, out: list[CorrelatedFinding]) -> None:
        if not (s.ram.pressure > 0.75 and s.startup.count > 8 and s.services.total_running > 60):
            return
        out.append(CorrelatedFinding(
            id=_correlation_id("mem_startup"),
            title="Resource bloat — high memory with startup items and services",
            description=(
                f"RAM at {s.ram.pressure * 100:.0f}% with {s.startup.count} "
                f"startup items and {s.services.total_running} services. "
                "Each consumes baseline memory, increasing swap delay."
            ),
            contributing_systems=["ram", "startup", "services"],
            evidence_items=[
                f"RAM: {s.ram.pressure * 100:.0f}% ({s.ram.used_gb}/{s.ram.total_gb}GB)",
                f"Startup: {s.startup.count}",
                f"Services: {s.services.total_running}",
            ],
            risk=Risk.MODERATE,
            severity="warning",
            impact="medium",
            recommendation="Review Startup and Services categories to reduce background load.",
            measured=False,
        ))

    def _network_dpc_delay(self, s: ScanResult, out: list[CorrelatedFinding]) -> None:
        if not (len(s.ram.dpc_top_offenders) > 2 and s.network.adapter_name):
            return
        names = ", ".join(o.get("name", "?") for o in s.ram.dpc_top_offenders[:3])
        out.append(CorrelatedFinding(
            id=_correlation_id("network_dpc"),
            title="Network latency risk — DPC contention on active adapter",
            description=(
                f"DPC offenders ({names}) active with "
                f"{s.network.adapter_name} connected. DPC contention "
                "delays packet processing, increasing network latency."
            ),
            contributing_systems=["network", "drivers"],
            evidence_items=[
                f"DPC offenders: {len(s.ram.dpc_top_offenders)} ({names})",
                f"Adapter: {s.network.adapter_name} ({s.network.adapter_type})",
            ],
            risk=Risk.MODERATE,
            severity="warning",
            impact="medium",
            recommendation="Review Network category for adapter optimization. Review Drivers for DPC sources.",
            measured=False,
        ))

    def _storage_driver_compound(self, s: ScanResult, out: list[CorrelatedFinding]) -> None:
        if not (s.storage.has_hdd and len(s.os.device_errors) > 0 and s.ram.pressure > 0.6):
            return
        names = ", ".join(d.get("name", "?") for d in s.os.device_errors[:3])
        out.append(CorrelatedFinding(
            id=_correlation_id("storage_driver"),
            title="Compound storage stress — HDD with device errors and elevated RAM",
            description=(
                f"HDD with {len(s.os.device_errors)} device errors "
                f"({names}) and {s.ram.pressure * 100:.0f}% RAM. Device "
                "errors cause I/O retries, and HDD seek times combined "
                "with pagefile thrashing create severe storage delay."
            ),
            contributing_systems=["storage", "os", "ram"],
            evidence_items=[
                f"Storage: HDD (SSD: {s.storage.has_ssd})",
                f"Device errors: {len(s.os.device_errors)} ({names})",
                f"RAM: {s.ram.pressure * 100:.0f}%",
            ],
            risk=Risk.HIGH,
            severity="critical",
            impact="high",
            recommendation="Review Storage category for SSD options. Review OS category for device errors.",
            measured=True,
        ))
