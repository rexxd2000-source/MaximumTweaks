"""Delay-focused diagnostic brain — identifies hidden sources of system delay.

Every finding answers three questions:
  1. What is causing delay?
  2. What is the measured evidence?
  3. Where should the user go to fix it?

No placebo tweaks. No duplicate cross-category recommendations.
Each finding references the appropriate tweak category rather than
suggesting its own fixes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine.delay_destroyer.risk import Risk
from engine.delay_destroyer.scanner import ScanResult


@dataclass
class Finding:
    """A single diagnosed delay source with evidence."""
    id: str
    title: str
    description: str
    evidence: str
    risk: Risk
    category: str
    severity: str = "info"
    impact: str = "low"
    is_measured: bool = True


class Diagnoser:
    """Analyzes scan results and identifies actual delay sources."""

    def diagnose(self, scan: ScanResult) -> list[Finding]:
        findings: list[Finding] = []
        self._cpu_responsiveness(scan, findings)
        self._memory_delay(scan, findings)
        self._dpc_isr_latency(scan, findings)
        self._driver_delay(scan, findings)
        self._input_delay(scan, findings)
        self._storage_delay(scan, findings)
        self._display_delay(scan, findings)
        self._network_delay(scan, findings)
        self._background_contention(scan, findings)
        self._windows_delay(scan, findings)
        self._cross_system_delays(scan, findings)
        return findings

    # ------------------------------------------------------------------
    # 1. CPU Responsiveness
    # ------------------------------------------------------------------

    def _cpu_responsiveness(self, s: ScanResult, f: list[Finding]) -> None:
        c = s.cpu

        # Power saver = severe CPU throttle
        is_power_saver = "a1841308" in c.power_plan_guid.lower()
        if is_power_saver:
            f.append(Finding(
                id="delay_cpu_power_saver",
                title="CPU responsiveness severely limited — Power Saver plan active",
                description=(
                    "The Power Saver plan caps CPU frequency and disables "
                    "turbo boost. This is the most restrictive power "
                    "configuration and directly causes sluggish application "
                    "response, slow program launches, and input lag."
                ),
                evidence=(
                    f"Power plan: {c.power_plan_name} ({c.power_plan_guid}), "
                    f"Boost mode: {c.boost_mode}"
                ),
                risk=Risk.MODERATE,
                category="cpu",
                severity="critical",
                impact="high",
                is_measured=True,
            ))

        # Boost disabled (but not on Power Saver, which already covers this)
        if c.boost_mode == 0 and not is_power_saver:
            f.append(Finding(
                id="delay_cpu_boost_disabled",
                title="CPU turbo boost is disabled — reduced single-thread responsiveness",
                description=(
                    "CPU turbo boost allows the processor to exceed its base "
                    "clock under load. With it disabled, the CPU cannot reach "
                    "its maximum single-threaded speed, directly impacting "
                    "application responsiveness and game frame rates."
                ),
                evidence=f"Boost mode: disabled ({c.boost_mode}), Power plan: {c.power_plan_name}",
                risk=Risk.LOW,
                category="cpu",
                severity="warning",
                impact="high",
                is_measured=True,
            ))

        # Thermal throttling
        if c.temp_celsius > 90:
            f.append(Finding(
                id="delay_cpu_thermal",
                title="CPU thermal throttling — clock speeds actively reduced",
                description=(
                    f"CPU temperature is {c.temp_celsius:.0f}\u00b0C. The CPU "
                    "is almost certainly reducing clock speeds to prevent "
                    "damage, causing severe and sustained responsiveness loss."
                ),
                evidence=f"Temperature: {c.temp_celsius:.1f}\u00b0C (throttle threshold: ~90\u00b0C)",
                risk=Risk.MODERATE,
                category="cpu",
                severity="critical",
                impact="high",
                is_measured=True,
            ))
        elif c.temp_celsius > 80:
            f.append(Finding(
                id="delay_cpu_warm",
                title="CPU running warm — boost headroom reduced",
                description=(
                    f"CPU temperature is {c.temp_celsius:.0f}\u00b0C. Sustained "
                    "high temperatures reduce turbo boost headroom and may "
                    "cause intermittent slowdowns under peak load."
                ),
                evidence=f"Temperature: {c.temp_celsius:.1f}\u00b0C (warning: 80\u00b0C)",
                risk=Risk.LOW,
                category="cpu",
                severity="warning",
                impact="medium",
                is_measured=True,
            ))

        # MMCSS not running — multimedia thread scheduling
        if not c.mmcss_running:
            f.append(Finding(
                id="delay_mmcss_missing",
                title="MMCSS not running — multimedia threads may be starved",
                description=(
                    "The Multimedia Class Scheduler Service (MMCSS) "
                    "prioritizes multimedia workloads. Without it, audio "
                    "and video threads compete equally with background "
                    "tasks, causing audio pops and frame pacing issues."
                ),
                evidence="MMCSS service: not running",
                risk=Risk.LOW,
                category="cpu",
                severity="info",
                impact="medium",
                is_measured=True,
            ))

    # ------------------------------------------------------------------
    # 2. Memory Pressure Delay
    # ------------------------------------------------------------------

    def _memory_delay(self, s: ScanResult, f: list[Finding]) -> None:
        rm = s.ram

        if rm.pressure > 0.85:
            f.append(Finding(
                id="delay_ram_pressure",
                title="High memory pressure — system swapping aggressively",
                description=(
                    f"System using {rm.used_gb}GB of {rm.total_gb}GB "
                    f"({rm.pressure * 100:.0f}%). When RAM fills, Windows "
                    "swaps to the pagefile. Each swap operation causes a "
                    "delay spike that makes the entire system feel sluggish."
                ),
                evidence=(
                    f"RAM: {rm.used_gb}/{rm.total_gb}GB "
                    f"({rm.pressure * 100:.0f}% pressure)"
                ),
                risk=Risk.MODERATE,
                category="ram",
                severity="warning",
                impact="high",
                is_measured=True,
            ))
        elif rm.pressure > 0.70 and rm.total_gb < 16:
            f.append(Finding(
                id="delay_ram_low_total",
                title="Memory pressure on limited RAM — swap likely",
                description=(
                    f"System has {rm.total_gb}GB RAM at "
                    f"{rm.pressure * 100:.0f}% usage. On systems with less "
                    "than 16GB, moderate pressure causes frequent pagefile "
                    "access, adding latency to every application."
                ),
                evidence=(
                    f"RAM: {rm.used_gb}/{rm.total_gb}GB "
                    f"({rm.pressure * 100:.0f}%, {rm.total_gb}GB total)"
                ),
                risk=Risk.LOW,
                category="ram",
                severity="info",
                impact="medium",
                is_measured=True,
            ))

        # Manual pagefile on low RAM
        if not rm.pagefile_auto and rm.total_gb < 32:
            f.append(Finding(
                id="delay_manual_pagefile",
                title="Pagefile manually configured — may cause OOM delays",
                description=(
                    "The pagefile is set to a fixed size instead of automatic. "
                    "On a system with less than 32GB RAM, an undersized "
                    "fixed pagefile causes out-of-memory pauses and "
                    "application crashes."
                ),
                evidence=f"Pagefile auto: disabled, total RAM: {rm.total_gb}GB",
                risk=Risk.LOW,
                category="ram",
                severity="info",
                impact="low",
                is_measured=True,
            ))

    # ------------------------------------------------------------------
    # 3. DPC/ISR Latency
    # ------------------------------------------------------------------

    def _dpc_isr_latency(self, s: ScanResult, f: list[Finding]) -> None:
        rm = s.ram

        if rm.dpc_latency_us > 500:
            offender_names = ", ".join(
                o.get("name", "?") for o in rm.dpc_top_offenders[:3])
            f.append(Finding(
                id="delay_dpc_high",
                title="DPC latency elevated — driver blocking the CPU",
                description=(
                    f"DPC rate: {rm.dpc_latency_us:.0f}/s. A driver is "
                    "spending excessive time in kernel mode, preventing "
                    "the CPU from handling real-time tasks. This directly "
                    "causes audio dropouts, input lag, and frame stutters."
                ),
                evidence=(
                    f"DPC rate: {rm.dpc_latency_us:.0f}/s, "
                    f"top offenders: {offender_names}"
                ),
                risk=Risk.HIGH,
                category="drivers",
                severity="warning",
                impact="high",
                is_measured=True,
            ))

        if rm.isr_latency_us > 500:
            f.append(Finding(
                id="delay_isr_high",
                title="ISR latency elevated — hardware interrupts consuming CPU",
                description=(
                    f"ISR rate: {rm.isr_latency_us:.0f}/s. Hardware "
                    "interrupts are consuming excessive CPU time, preventing "
                    "the system from responding to user input and application "
                    "requests in a timely manner."
                ),
                evidence=f"ISR rate: {rm.isr_latency_us:.0f}/s",
                risk=Risk.HIGH,
                category="drivers",
                severity="warning",
                impact="high",
                is_measured=True,
            ))

    # ------------------------------------------------------------------
    # 4. Driver Delay
    # ------------------------------------------------------------------

    def _driver_delay(self, s: ScanResult, f: list[Finding]) -> None:
        d = s.drivers

        if d.audio_driver_issues:
            issues_str = "; ".join(d.audio_driver_issues)
            f.append(Finding(
                id="delay_audio_driver",
                title="Audio driver issues — potential DPC latency source",
                description=(
                    f"Audio devices with problems: {issues_str}. Audio "
                    "driver issues are a common source of DPC latency "
                    "spikes that freeze the entire system for hundreds "
                    "of milliseconds."
                ),
                evidence=f"Audio issues: {issues_str}",
                risk=Risk.MODERATE,
                category="audio",
                severity="warning",
                impact="medium",
                is_measured=True,
            ))

        if d.display_driver_issues:
            issues_str = "; ".join(d.display_driver_issues)
            f.append(Finding(
                id="delay_display_driver",
                title="Display driver issues — frame drops and freezes",
                description=(
                    f"Display devices with problems: {issues_str}. Display "
                    "driver instability causes visual glitches, frame drops, "
                    "and potential system freezes."
                ),
                evidence=f"Display issues: {issues_str}",
                risk=Risk.MODERATE,
                category="gpu",
                severity="warning",
                impact="high",
                is_measured=True,
            ))

        if d.driver_resets > 0:
            f.append(Finding(
                id="delay_driver_resets",
                title=f"{d.driver_resets} GPU driver resets — TDR events causing freezes",
                description=(
                    f"{d.driver_resets} driver resets (TDR events) detected. "
                    "Each reset causes a momentary freeze and black screen, "
                    "and indicates GPU driver instability that disrupts the "
                    "entire display pipeline."
                ),
                evidence=f"Driver resets (event 4101/4116): {d.driver_resets}",
                risk=Risk.MODERATE,
                category="gpu",
                severity="warning",
                impact="high",
                is_measured=True,
            ))

    # ------------------------------------------------------------------
    # 5. Input Delay
    # ------------------------------------------------------------------

    def _input_delay(self, s: ScanResult, f: list[Finding]) -> None:
        inp = s.input

        if inp.hid_driver_issues:
            issues_str = "; ".join(inp.hid_driver_issues)
            f.append(Finding(
                id="delay_hid_issues",
                title="HID driver issues — input devices may be lagging",
                description=(
                    f"HID devices with problems: {issues_str}. HID driver "
                    "issues cause input devices to exhibit erratic behavior "
                    "or elevated latency between physical input and screen "
                    "response."
                ),
                evidence=f"HID issues: {issues_str}",
                risk=Risk.MODERATE,
                category="input",
                severity="warning",
                impact="medium",
                is_measured=True,
            ))

        if inp.usb_driver_issues:
            issues_str = "; ".join(inp.usb_driver_issues)
            f.append(Finding(
                id="delay_usb_issues",
                title="USB controller issues — all peripherals affected",
                description=(
                    f"USB controllers with problems: {issues_str}. USB "
                    "driver issues affect all connected peripherals, "
                    "causing intermittent disconnections and input lag."
                ),
                evidence=f"USB issues: {issues_str}",
                risk=Risk.MODERATE,
                category="input",
                severity="warning",
                impact="medium",
                is_measured=True,
            ))

    # ------------------------------------------------------------------
    # 6. Storage Delay
    # ------------------------------------------------------------------

    def _storage_delay(self, s: ScanResult, f: list[Finding]) -> None:
        st = s.storage

        if st.has_hdd and not st.has_ssd and not st.has_nvme:
            f.append(Finding(
                id="delay_hdd_only",
                title="HDD-only system — storage is the primary delay source",
                description=(
                    "No SSD detected. Mechanical hard drives are the single "
                    "biggest source of system delay. Windows boot, application "
                    "launch, file operations, and pagefile access are all "
                    "dramatically slower on HDD."
                ),
                evidence="Storage: HDD only (no SSD or NVMe detected)",
                risk=Risk.LOW,
                category="storage",
                severity="warning",
                impact="high",
                is_measured=True,
            ))

        if st.avg_disk_queue_length > 2.0:
            f.append(Finding(
                id="delay_disk_queue",
                title="Disk queue congested — I/O requests stalling",
                description=(
                    f"Average disk queue length: {st.avg_disk_queue_length:.1f}. "
                    "The disk cannot keep up with I/O requests, causing "
                    "every file operation to stall and starving applications "
                    "of data."
                ),
                evidence=f"Avg disk queue: {st.avg_disk_queue_length:.1f}",
                risk=Risk.MODERATE,
                category="storage",
                severity="warning",
                impact="high",
                is_measured=True,
            ))

    # ------------------------------------------------------------------
    # 7. Display / DWM Delay
    # ------------------------------------------------------------------

    def _display_delay(self, s: ScanResult, f: list[Finding]) -> None:
        d = s.display
        g = s.gpu

        # GPU overlay overhead
        if g.gfe_overlay_enabled:
            f.append(Finding(
                id="delay_nvidia_overlay",
                title="NVIDIA overlay active — GPU encoding overhead",
                description=(
                    "The NVIDIA overlay runs a GPU encoding pipeline in the "
                    "background, consuming VRAM and GPU cycles. This adds "
                    "micro-stutters and input lag, especially in GPU-bound "
                    "scenes."
                ),
                evidence="GFE overlay: enabled",
                risk=Risk.LOW,
                category="gpu",
                severity="info",
                impact="medium",
                is_measured=True,
            ))

        # HAGS disabled
        if not g.hardware_gpu_scheduling and g.dedicated:
            f.append(Finding(
                id="delay_hags_disabled",
                title="HAGS disabled — CPU handling GPU scheduling",
                description=(
                    "Hardware-accelerated GPU scheduling lets the GPU manage "
                    "its own task queue. With it disabled, the CPU handles "
                    "GPU scheduling, adding driver overhead and reducing "
                    "frame pacing smoothness."
                ),
                evidence=f"HwSchMode: {'enabled' if g.hardware_gpu_scheduling else 'disabled'}",
                risk=Risk.MODERATE,
                category="gpu",
                severity="info",
                impact="medium",
                is_measured=True,
            ))

        # TDR modified
        if g.tdr_level != 3:
            f.append(Finding(
                id="delay_tdr_modified",
                title="TDR settings modified — driver recovery may cause delays",
                description=(
                    f"TDR level is {g.tdr_level} (default: 3). Modified TDR "
                    "settings can cause driver crashes to go unhandled or "
                    "trigger unnecessary resets, both creating display "
                    "interruptions and latency spikes."
                ),
                evidence=f"TdrLevel={g.tdr_level}, TdrDelay={g.tdr_delay}s",
                risk=Risk.MODERATE,
                category="gpu",
                severity="warning",
                impact="medium",
                is_measured=True,
            ))

        # Multi-monitor with driver errors
        if d.multi_monitor and d.display_driver_errors:
            errors_str = "; ".join(d.display_driver_errors[:3])
            f.append(Finding(
                id="delay_multi_monitor_errors",
                title="Multi-monitor with driver errors — display pipeline stressed",
                description=(
                    f"{d.monitor_count} monitors with driver errors: "
                    f"{errors_str}. Multi-monitor increases GPU and driver "
                    "load; combined with errors, this causes frame pacing "
                    "issues and visual artifacts."
                ),
                evidence=f"Monitors: {d.monitor_count}, errors: {errors_str}",
                risk=Risk.MODERATE,
                category="display",
                severity="warning",
                impact="medium",
                is_measured=True,
            ))

    # ------------------------------------------------------------------
    # 8. Network Delay
    # ------------------------------------------------------------------

    def _network_delay(self, s: ScanResult, f: list[Finding]) -> None:
        net = s.network

        if not net.nagle_disabled and net.adapter_type != "unknown":
            f.append(Finding(
                id="delay_nagle",
                title="Nagle algorithm adding network latency",
                description=(
                    "Nagle's algorithm batches small network packets, "
                    "adding 200-400ms of latency to real-time game server "
                    "communication and online interactions."
                ),
                evidence="TcpNoDelay: not set (Nagle active)",
                risk=Risk.LOW,
                category="network",
                severity="info",
                impact="medium",
                is_measured=True,
            ))

    # ------------------------------------------------------------------
    # 9. Background Contention
    # ------------------------------------------------------------------

    def _background_contention(self, s: ScanResult, f: list[Finding]) -> None:
        p = s.processes
        st = s.startup
        svc = s.services

        if p.high_cpu:
            names = [f"{x['name']} ({x['cpu']}%)" for x in p.high_cpu[:3]]
            f.append(Finding(
                id="delay_bg_cpu",
                title=f"{len(p.high_cpu)} processes competing for CPU time",
                description=(
                    f"High CPU consumers: {', '.join(names)}. These "
                    "background processes steal CPU time from foreground "
                    "applications, causing stuttering and input lag."
                ),
                evidence=f"High CPU: {', '.join(names)}",
                risk=Risk.LOW,
                category="processes",
                severity="warning",
                impact="high",
                is_measured=True,
            ))

        if p.high_memory:
            names = [f"{x['name']} ({x['mem_pct']}%)" for x in p.high_memory[:3]]
            f.append(Finding(
                id="delay_bg_mem",
                title=f"{len(p.high_memory)} processes consuming significant memory",
                description=(
                    f"High memory consumers: {', '.join(names)}. These "
                    "processes contribute to memory pressure, increasing "
                    "swap activity and system-wide latency."
                ),
                evidence=f"High memory: {', '.join(names)}",
                risk=Risk.LOW,
                category="processes",
                severity="info",
                impact="medium",
                is_measured=True,
            ))

        if st.count > 8:
            high_str = ", ".join(st.high_impact[:5]) if st.high_impact else "none"
            f.append(Finding(
                id="delay_startup_bloat",
                title=f"{st.count} startup items extending boot and consuming RAM",
                description=(
                    f"{st.count} programs launch at startup. Each competes "
                    "for CPU, RAM, and disk I/O during login, extending boot "
                    "time and leaving resident processes consuming resources "
                    f"throughout the session. High-impact: {high_str}."
                ),
                evidence=f"Startup: {st.count}, high-impact: {high_str}",
                risk=Risk.LOW,
                category="startup",
                severity="info",
                impact="medium",
                is_measured=True,
            ))

        if svc.unnecessary_running:
            running_str = ", ".join(svc.unnecessary_running[:6])
            f.append(Finding(
                id="delay_unnecessary_services",
                title=f"{len(svc.unnecessary_running)} unnecessary services running",
                description=(
                    f"Services that are safe to disable are still running: "
                    f"{running_str}. These consume CPU cycles, memory, and "
                    "disk I/O for functionality you likely do not need."
                ),
                evidence=f"Running: {running_str}",
                risk=Risk.LOW,
                category="services",
                severity="info",
                impact="medium",
                is_measured=True,
            ))

    # ------------------------------------------------------------------
    # 10. Windows Responsiveness
    # ------------------------------------------------------------------

    def _windows_delay(self, s: ScanResult, f: list[Finding]) -> None:
        o = s.os

        if o.game_dvr_enabled:
            f.append(Finding(
                id="delay_game_dvr",
                title="Game DVR recording in background — GPU and disk overhead",
                description=(
                    "Game DVR continuously records gameplay using GPU "
                    "encoding and disk I/O, even when you are not actively "
                    "recording. This consumes GPU cycles and adds disk "
                    "throughput pressure."
                ),
                evidence="GameDVR_Enabled: 1",
                risk=Risk.LOW,
                category="gaming",
                severity="info",
                impact="medium",
                is_measured=True,
            ))

        if o.uptime_hours > 168:
            days = o.uptime_hours / 24
            f.append(Finding(
                id="delay_long_uptime",
                title=f"System up {days:.1f} days — memory leaks and driver degradation",
                description=(
                    f"Uptime of {o.uptime_hours:.0f} hours ({days:.1f} days). "
                    "Extended uptime leads to memory leaks, driver state "
                    "degradation, and accumulated temporary files that "
                    "increase system latency over time."
                ),
                evidence=f"Uptime: {o.uptime_hours:.0f}h ({days:.1f} days)",
                risk=Risk.LOW,
                category="os",
                severity="info",
                impact="low",
                is_measured=True,
            ))

        if o.critical_events > 0:
            f.append(Finding(
                id="delay_critical_events",
                title=f"{o.critical_events} critical events — system instability",
                description=(
                    "Critical events (kernel crashes, driver failures) "
                    "indicate underlying instability that causes freezes "
                    "and performance degradation."
                ),
                evidence=f"Critical events (7-day): {o.critical_events}",
                risk=Risk.MODERATE,
                category="os",
                severity="warning",
                impact="high",
                is_measured=True,
            ))

        if o.device_errors:
            names = ", ".join(d.get("name", "?") for d in o.device_errors[:3])
            f.append(Finding(
                id="delay_device_errors",
                title="Device errors — hardware/driver malfunction",
                description=(
                    f"Devices with errors: {names}. Devices in error state "
                    "cause resource conflicts and driver instability."
                ),
                evidence=f"Device errors: {names}",
                risk=Risk.MODERATE,
                category="os",
                severity="warning",
                impact="medium",
                is_measured=True,
            ))

        if o.pending_reboot:
            f.append(Finding(
                id="delay_pending_reboot",
                title="Pending reboot — updates may not be fully active",
                description=(
                    "Windows has pending updates requiring restart. Pending "
                    "reboots can cause driver conflicts and prevent new "
                    "optimizations from taking effect."
                ),
                evidence="RebootPending: present",
                risk=Risk.LOW,
                category="os",
                severity="info",
                impact="low",
                is_measured=True,
            ))

    # ------------------------------------------------------------------
    # 11. Cross-system delay correlations
    # ------------------------------------------------------------------

    def _cross_system_delays(self, s: ScanResult, f: list[Finding]) -> None:
        """Detect compound delay sources spanning multiple subsystems."""

        # Storage thrashing: high RAM + HDD
        if (s.ram.pressure > 0.85 and s.storage.has_hdd
                and not s.storage.has_ssd and not s.storage.has_nvme):
            f.append(Finding(
                id="delay_thrashing",
                title="Storage thrashing — high RAM on HDD-only system",
                description=(
                    f"Memory at {s.ram.pressure * 100:.0f}% on HDD-only "
                    "storage. When RAM fills, Windows swaps to disk. On "
                    "a mechanical drive, each swap causes a multi-millisecond "
                    "freeze. This is the single worst delay scenario."
                ),
                evidence=(
                    f"RAM: {s.ram.pressure * 100:.0f}%, "
                    "Storage: HDD only"
                ),
                risk=Risk.HIGH,
                category="storage",
                severity="critical",
                impact="high",
                is_measured=True,
            ))

        # DPC + high CPU = driver scheduling contention
        dpc_offenders = s.ram.dpc_top_offenders or s.drivers.dpc_offenders
        if dpc_offenders and s.cpu.usage_percent > 50:
            names = ", ".join(
                o.get("name", "?") for o in dpc_offenders[:3])
            f.append(Finding(
                id="delay_dpc_cpu_contention",
                title="Driver scheduling contention — DPC + high CPU",
                description=(
                    f"DPC offenders ({names}) active with "
                    f"{s.cpu.usage_percent:.0f}% CPU. Drivers are "
                    "contending for CPU time, degrading real-time "
                    "responsiveness."
                ),
                evidence=(
                    f"DPC offenders: {names}, "
                    f"CPU: {s.cpu.usage_percent:.0f}%"
                ),
                risk=Risk.MODERATE,
                category="drivers",
                severity="warning",
                impact="high",
                is_measured=False,
            ))

        # HID/USB + DPC = input delay
        has_input_issues = (s.input.hid_driver_issues or s.input.usb_driver_issues)
        dpc_elevated = s.ram.dpc_latency_us > 500
        if has_input_issues and dpc_elevated:
            f.append(Finding(
                id="delay_input_dpc",
                title="Input delay — HID/USB issues with DPC contention",
                description=(
                    "HID or USB driver issues combined with elevated DPC "
                    "latency. Input devices may be experiencing delayed "
                    "signal delivery."
                ),
                evidence=(
                    f"HID/USB issues: {len(s.input.hid_driver_issues) + len(s.input.usb_driver_issues)}, "
                    f"DPC: {s.ram.dpc_latency_us:.0f}/s"
                ),
                risk=Risk.MODERATE,
                category="input",
                severity="warning",
                impact="medium",
                is_measured=False,
            ))

        # Game DVR + NVIDIA overlay = double GPU overhead
        if s.os.game_dvr_enabled and s.gpu.gfe_overlay_enabled:
            f.append(Finding(
                id="delay_double_gpu",
                title="Double GPU overhead — Game DVR + NVIDIA overlay",
                description=(
                    "Both Game DVR and NVIDIA overlay are active. Each "
                    "uses a separate GPU encoding pipeline, consuming "
                    "significant GPU resources."
                ),
                evidence="Game DVR: enabled, NVIDIA overlay: enabled",
                risk=Risk.LOW,
                category="gpu",
                severity="info",
                impact="medium",
                is_measured=True,
            ))

        # Power saver + boost disabled = double CPU throttle
        is_ps = "a1841308" in s.cpu.power_plan_guid.lower()
        if is_ps and s.cpu.boost_mode == 0:
            f.append(Finding(
                id="delay_double_throttle",
                title="Double CPU throttle — Power Saver + boost disabled",
                description=(
                    "Both Power Saver and CPU turbo boost are disabled. "
                    "The CPU is running at minimum performance — the most "
                    "restrictive configuration possible."
                ),
                evidence=(
                    f"Power plan: Power Saver, "
                    f"Boost: disabled ({s.cpu.boost_mode})"
                ),
                risk=Risk.MODERATE,
                category="cpu",
                severity="warning",
                impact="high",
                is_measured=False,
            ))

        # Startup bloat + high memory
        if s.startup.count > 8 and s.ram.pressure > 0.75:
            f.append(Finding(
                id="delay_startup_memory",
                title="Startup bloat compounding memory pressure",
                description=(
                    f"{s.startup.count} startup items with "
                    f"{s.ram.pressure * 100:.0f}% memory. Startup programs "
                    "remain resident, directly contributing to swap delay."
                ),
                evidence=(
                    f"Startup: {s.startup.count}, "
                    f"RAM: {s.ram.pressure * 100:.0f}%"
                ),
                risk=Risk.LOW,
                category="startup",
                severity="info",
                impact="medium",
                is_measured=False,
            ))

        # Long uptime + high memory = possible leak
        if s.os.uptime_hours > 168 and s.ram.pressure > 0.75:
            f.append(Finding(
                id="delay_memory_leak",
                title="Possible memory leak — high RAM after extended uptime",
                description=(
                    f"Up {s.os.uptime_hours / 24:.1f} days with "
                    f"{s.ram.pressure * 100:.0f}% RAM. Long uptime + high "
                    "memory is a classic leak pattern. A reboot may help."
                ),
                evidence=(
                    f"Uptime: {s.os.uptime_hours:.0f}h, "
                    f"RAM: {s.ram.pressure * 100:.0f}%"
                ),
                risk=Risk.LOW,
                category="os",
                severity="info",
                impact="medium",
                is_measured=False,
            ))

        # Unstable driver layer
        if s.os.device_errors and s.drivers.driver_resets > 0:
            f.append(Finding(
                id="delay_unstable_drivers",
                title="Unstable driver layer — device errors + driver resets",
                description=(
                    f"{len(s.os.device_errors)} device error(s) and "
                    f"{s.drivers.driver_resets} driver reset(s). This "
                    "indicates a fundamentally unstable driver stack."
                ),
                evidence=(
                    f"Device errors: {len(s.os.device_errors)}, "
                    f"Resets: {s.drivers.driver_resets}"
                ),
                risk=Risk.HIGH,
                category="drivers",
                severity="warning",
                impact="high",
                is_measured=False,
            ))

        # Multi-monitor + driver errors
        if s.display.multi_monitor and s.display.display_driver_errors:
            errors_str = "; ".join(s.display.display_driver_errors[:3])
            f.append(Finding(
                id="delay_display_stress",
                title="Display pipeline stress — multi-monitor + driver errors",
                description=(
                    f"{s.display.monitor_count} monitors with driver errors: "
                    f"{errors_str}. Multi-monitor increases GPU load, "
                    "amplifying driver instability."
                ),
                evidence=(
                    f"Monitors: {s.display.monitor_count}, "
                    f"Errors: {errors_str}"
                ),
                risk=Risk.MODERATE,
                category="display",
                severity="warning",
                impact="medium",
                is_measured=False,
            ))
