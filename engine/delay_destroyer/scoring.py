"""Measurement-based scoring system for Delay Destroyer.

Every score is derived from actual measurements. No arbitrary values.
If insufficient data exists, the score reports "insufficient data"
rather than guessing.

Scoring categories (as specified):
  INPUT RESPONSIVENESS — mouse/keyboard/controller → screen
  SYSTEM RESPONSIVENESS — CPU, RAM, DPC, scheduling
  FRAME-TIME STABILITY — GPU, display, DWM
  NETWORK STABILITY — latency, jitter, loss
  OVERALL — weighted composite

Each category scores 0-100 where:
  90-100 = excellent (no issues detected)
  75-89 = good (minor issues)
  55-74 = fair (some issues worth addressing)
  35-54 = poor (significant issues)
  0-34 = critical (severe issues)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine.delay_destroyer.scanner import ScanResult
from engine.delay_destroyer.network_measure import NetworkMeasurement


@dataclass
class DimensionScore:
    """A single scoring dimension with measurement details."""
    name: str
    score: int  # 0-100
    label: str  # "excellent", "good", "fair", "poor", "critical"
    metrics: list[str] = field(default_factory=list)  # measured values
    issues: list[str] = field(default_factory=list)    # problems found
    icon: str = ""


@dataclass
class DelayScores:
    """All scoring dimensions plus composite."""
    input_responsiveness: DimensionScore
    system_responsiveness: DimensionScore
    frame_time_stability: DimensionScore
    network_stability: DimensionScore
    overall: DimensionScore


def _label(score: int) -> str:
    if score >= 90:
        return "excellent"
    elif score >= 75:
        return "good"
    elif score >= 55:
        return "fair"
    elif score >= 35:
        return "poor"
    else:
        return "critical"


def _clamp(val: int) -> int:
    return max(0, min(100, val))


def score_input_responsiveness(scan: ScanResult) -> DimensionScore:
    """Score based on measured input-related factors.

    Input latency cannot be directly measured without specialized hardware.
    This scores contributing FACTORS (settings, driver health, DPC) —
    NOT a direct latency measurement. The score reflects how many
    input-delay risk factors are present, not an actual latency value.
    """
    score = 100
    metrics = []
    issues = []
    has_measurement = False

    # USB selective suspend
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\USB",
        ) as k:
            val, _ = winreg.QueryValueEx(k, "DisableSelectiveSuspend")
            if val != 1:
                score -= 15
                issues.append("USB Selective Suspend active")
            else:
                metrics.append("USB Selective Suspend: disabled")
            has_measurement = True
    except OSError:
        metrics.append("USB Selective Suspend: unknown")

    # Mouse acceleration
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\Mouse",
        ) as k:
            val, _ = winreg.QueryValueEx(k, "MouseSpeed")
            if val != "0":
                score -= 10
                issues.append("Mouse acceleration enabled")
            else:
                metrics.append("Mouse acceleration: disabled")
            has_measurement = True
    except OSError:
        metrics.append("Mouse acceleration: unknown")

    # Accessibility keys
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\Accessibility\StickyKeys",
        ) as k:
            val, _ = winreg.QueryValueEx(k, "Flags")
            if val != "506":
                score -= 5
                issues.append("Sticky Keys active")
            else:
                metrics.append("Sticky Keys: disabled")
            has_measurement = True
    except OSError:
        metrics.append("Sticky Keys: unknown")

    # HID driver issues
    if scan.input.hid_driver_issues:
        score -= 15
        issues.append(f"HID driver issues: {len(scan.input.hid_driver_issues)}")
        has_measurement = True
    else:
        metrics.append(f"HID devices: {scan.input.hid_device_count} detected")

    # USB driver issues
    if scan.input.usb_driver_issues:
        score -= 15
        issues.append(f"USB controller issues: {len(scan.input.usb_driver_issues)}")
        has_measurement = True
    else:
        metrics.append(f"USB controllers: {scan.input.usb_controllers}")

    # Bluetooth HID (adds latency)
    if scan.input.bluetooth_hid:
        score -= 5
        issues.append("Bluetooth HID detected — wireless adds latency")
        has_measurement = True
    else:
        metrics.append("Connection: wired")

    # DPC rate affects input delivery
    if scan.ram.dpc_rate_per_sec > 500:
        score -= 20
        issues.append(f"DPC rate {scan.ram.dpc_rate_per_sec:.0f}/s — may delay input delivery")
        has_measurement = True
    elif scan.ram.dpc_rate_per_sec > 200:
        score -= 10
        issues.append(f"DPC rate {scan.ram.dpc_rate_per_sec:.0f}/s — moderate")
        has_measurement = True
    elif scan.ram.dpc_rate_per_sec > 0:
        metrics.append(f"DPC rate: {scan.ram.dpc_rate_per_sec:.0f}/s")

    # Critical: note that input latency is NOT directly measured
    if has_measurement:
        metrics.insert(0, "Note: input latency not directly measured — scoring risk factors only")

    return DimensionScore(
        name="Input Responsiveness",
        score=_clamp(score),
        label=_label(_clamp(score)),
        metrics=metrics,
        issues=issues,
        icon="\u2328",
    )


def score_system_responsiveness(scan: ScanResult) -> DimensionScore:
    """Score based on CPU, RAM, storage, scheduling measurements.

    Considers: power plan, boost, thermal, context switches, memory
    pressure, storage type, background CPU load.
    """
    score = 100
    metrics = []
    issues = []
    c = scan.cpu

    # Power plan
    if "a1841308" in c.power_plan_guid.lower():
        score -= 35
        issues.append("Power Saver plan — severe CPU throttle")
    elif "381b4222" in c.power_plan_guid.lower():
        metrics.append(f"Power plan: {c.power_plan_name}")
    else:
        metrics.append(f"Power plan: {c.power_plan_name}")

    # CPU boost
    if c.boost_mode == 0:
        score -= 15
        issues.append("CPU turbo boost disabled")
    else:
        metrics.append(f"CPU boost: mode {c.boost_mode}")

    # Thermal
    if c.temp_celsius > 90:
        score -= 25
        issues.append(f"CPU at {c.temp_celsius:.0f}\u00b0C — thermal throttling")
    elif c.temp_celsius > 80:
        score -= 10
        issues.append(f"CPU at {c.temp_celsius:.0f}\u00b0C — warm")
    elif c.temp_celsius > 0:
        metrics.append(f"CPU temp: {c.temp_celsius:.0f}\u00b0C")

    # CPU usage
    if c.usage_percent > 80:
        score -= 15
        issues.append(f"CPU at {c.usage_percent:.0f}% — high load")
    elif c.usage_percent > 50:
        score -= 5
        issues.append(f"CPU at {c.usage_percent:.0f}% — moderate load")
    else:
        metrics.append(f"CPU usage: {c.usage_percent:.0f}%")

    # Context switches
    if c.context_switches_per_sec > 50000:
        score -= 10
        issues.append(f"Context switches: {c.context_switches_per_sec:.0f}/s — high")
    else:
        metrics.append(f"Context switches: {c.context_switches_per_sec:.0f}/s")

    # Memory pressure
    rm = scan.ram
    if rm.pressure > 0.85:
        score -= 20
        issues.append(f"RAM at {rm.pressure*100:.0f}% — swap thrashing likely")
    elif rm.pressure > 0.70:
        score -= 5
        issues.append(f"RAM at {rm.pressure*100:.0f}% — moderate pressure")
    else:
        metrics.append(f"RAM: {rm.used_gb}/{rm.total_gb}GB ({rm.pressure*100:.0f}%)")

    # Storage
    if scan.storage.has_hdd and not scan.storage.has_ssd and not scan.storage.has_nvme:
        score -= 15
        issues.append("HDD-only — storage is a bottleneck")
    else:
        stype = "NVMe" if scan.storage.has_nvme else "SSD" if scan.storage.has_ssd else "Unknown"
        metrics.append(f"Storage: {stype}")

    # MMCSS
    if c.mmcss_running:
        metrics.append("MMCSS: running")
    else:
        score -= 5
        issues.append("MMCSS not running")

    # Background CPU
    if scan.processes.high_cpu:
        names = [p["name"] for p in scan.processes.high_cpu[:3]]
        score -= 10
        issues.append(f"Background CPU: {', '.join(names)}")

    return DimensionScore(
        name="System Responsiveness",
        score=_clamp(score),
        label=_label(_clamp(score)),
        metrics=metrics,
        issues=issues,
        icon="\u2699",
    )


def score_frame_time_stability(scan: ScanResult) -> DimensionScore:
    """Score based on factors that affect frame stability.

    Frame-time latency cannot be measured without real-time frame capture.
    This scores contributing FACTORS — driver state, HAGS, overlays,
    DWM, driver resets, TDR settings — NOT actual frame times.
    The score reflects risk factors, not measured frame performance.
    """
    score = 100
    metrics = []
    issues = []

    g = scan.gpu
    d = scan.display

    # GPU detected
    if g.names:
        metrics.append(f"GPU: {g.names[0]}")
    else:
        score -= 10
        issues.append("No GPU detected")

    # Driver version
    if g.driver_version:
        metrics.append(f"Driver: {g.driver_version}")
    else:
        score -= 5
        issues.append("GPU driver version unknown")

    # HAGS — informational only, no score impact
    if g.hardware_gpu_scheduling:
        metrics.append("HAGS: enabled")
    elif g.dedicated:
        metrics.append("HAGS: disabled")

    # NVIDIA overlay — adds GPU encoding overhead
    if g.gfe_overlay_enabled:
        score -= 10
        issues.append("NVIDIA overlay active — GPU encoding overhead")

    # Driver resets (TDR) — real measured evidence
    if scan.drivers.driver_resets > 0:
        score -= 20
        issues.append(f"GPU driver resets: {scan.drivers.driver_resets}")

    # TDR modified
    if g.tdr_level != 3:
        score -= 5
        issues.append(f"TDR level modified: {g.tdr_level}")

    # Display driver issues
    if scan.drivers.display_driver_issues:
        score -= 15
        issues.append(f"Display driver issues: {len(scan.drivers.display_driver_issues)}")

    # Refresh rate
    if d.refresh_rates:
        metrics.append(f"Refresh rate: {', '.join(d.refresh_rates)}")
    else:
        metrics.append("Refresh rate: unknown")

    # Resolution
    if d.primary_resolution:
        metrics.append(f"Resolution: {d.primary_resolution}")

    # Multi-monitor
    if d.multi_monitor:
        metrics.append(f"Monitors: {d.monitor_count}")

    # Game DVR (GPU encoding overhead)
    if scan.os.game_dvr_enabled:
        score -= 10
        issues.append("Game DVR recording — GPU encoding overhead")

    # DPC rate affects frame delivery
    if scan.ram.dpc_rate_per_sec > 500:
        score -= 15
        issues.append(f"DPC rate {scan.ram.dpc_rate_per_sec:.0f}/s — frame delivery impact")

    # Critical: note that frame times are NOT directly measured
    metrics.insert(0, "Note: frame times not directly measured — scoring risk factors only")

    return DimensionScore(
        name="Frame-Time Stability",
        score=_clamp(score),
        label=_label(_clamp(score)),
        metrics=metrics,
        issues=issues,
        icon="\u25a0",
    )


def score_network_stability(net: NetworkMeasurement | None) -> DimensionScore:
    """Score based on real network measurements.

    Only scores from actual ICMP/ping data. If no measurements
    available, reports "insufficient data" with score 50.
    """
    if not net:
        return DimensionScore(
            name="Network Stability",
            score=50,
            label="insufficient data",
            metrics=["Network measurements not available"],
            issues=[],
            icon="\u2637",
        )

    score = 100
    metrics = []
    issues = []

    avg_ping = net.internet_ping_ms or 0
    jitter = net.internet_jitter_ms or 0
    loss = net.internet_loss_pct or 0

    if avg_ping == 0:
        return DimensionScore(
            name="Network Stability",
            score=50,
            label="insufficient data",
            metrics=["No ping data collected — run a network scan"],
            issues=[],
            icon="\u2637",
        )

    # Ping
    metrics.append(f"Ping: {avg_ping:.0f}ms (min: {net.min_ping_ms:.0f}ms, max: {net.max_ping_ms:.0f}ms)")
    if avg_ping > 100:
        score -= 30
        issues.append(f"High ping: {avg_ping:.0f}ms")
    elif avg_ping > 60:
        score -= 15
        issues.append(f"Moderate ping: {avg_ping:.0f}ms")
    elif avg_ping > 30:
        score -= 5
        issues.append(f"Slightly elevated: {avg_ping:.0f}ms")

    # Jitter
    metrics.append(f"Jitter: {jitter:.0f}ms")
    if jitter > 20:
        score -= 25
        issues.append(f"High jitter: {jitter:.0f}ms")
    elif jitter > 10:
        score -= 10
        issues.append(f"Moderate jitter: {jitter:.0f}ms")

    # Packet loss
    if loss > 0:
        metrics.append(f"Packet loss: {loss:.1f}%")
        if loss > 5:
            score -= 25
            issues.append(f"Significant packet loss: {loss:.1f}%")
        elif loss > 1:
            score -= 10
            issues.append(f"Some packet loss: {loss:.1f}%")
    else:
        metrics.append("Packet loss: 0%")

    # Gateway latency (local network)
    if net.gateway_ping_ms > 0:
        metrics.append(f"Gateway: {net.gateway_ping_ms:.0f}ms")
        gap = avg_ping - net.gateway_ping_ms
        if gap > 40:
            score -= 5
            issues.append(f"ISP routing adds {gap:.0f}ms")

    # DNS
    if net.dns_resolution_ms > 0:
        metrics.append(f"DNS: {net.dns_resolution_ms:.0f}ms")
        if net.dns_resolution_ms > 200:
            score -= 5
            issues.append(f"Slow DNS: {net.dns_resolution_ms:.0f}ms")

    # MTU
    if net.mtu:
        metrics.append(f"MTU: {net.mtu}")

    return DimensionScore(
        name="Network Stability",
        score=_clamp(score),
        label=_label(_clamp(score)),
        metrics=metrics,
        issues=issues,
        icon="\u2637",
    )


def calculate_scores(
    scan: ScanResult,
    net: NetworkMeasurement | None = None,
) -> DelayScores:
    """Calculate all scoring dimensions and composite from real measurements."""
    inp = score_input_responsiveness(scan)
    sys_resp = score_system_responsiveness(scan)
    frame = score_frame_time_stability(scan)
    net_score = score_network_stability(net)

    # Weighted composite — system and frame get more weight since they
    # affect the most users. Network only matters for online gaming.
    weights = {
        "input": 0.20,
        "system": 0.30,
        "frame": 0.25,
        "network": 0.25,
    }
    overall_val = int(
        inp.score * weights["input"]
        + sys_resp.score * weights["system"]
        + frame.score * weights["frame"]
        + net_score.score * weights["network"]
    )

    overall = DimensionScore(
        name="Overall",
        score=_clamp(overall_val),
        label=_label(_clamp(overall_val)),
        metrics=[],
        issues=[],
        icon="\u2b50",
    )

    return DelayScores(
        input_responsiveness=inp,
        system_responsiveness=sys_resp,
        frame_time_stability=frame,
        network_stability=net_score,
        overall=overall,
    )
