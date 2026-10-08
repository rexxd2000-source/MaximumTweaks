"""Category: FPS Boost — proven system-level tweaks that measurably increase
frame rates and reduce input latency across all GPU vendors.

Every tweak here has a documented benchmark or well-known mechanism.  None
overlap with Performance, CPU, Power, Gaming, NVIDIA, AMD, or Intel modules.
"""
from __future__ import annotations

from ._base import make_T, validate_module, plan_guid

T = make_T("FPS Boost", win_default="10,11")

CATEGORY = "FPS Boost"

# Deterministic GUID the Maximum Power Plan is created under (shared with the
# Power Plans module so both tweaks target the same plan).
MAX_PLAN_NAME = "Maximum Power Plan"
MAX_PLAN_GUID = plan_guid(MAX_PLAN_NAME)

WARNING_VBS = (
    "This disables Virtualization-Based Security which is a Windows security "
    "feature.  Disabling it measurably improves FPS (2-15% in many titles) but "
    "reduces protection against kernel-level attacks.  Only do this on a "
    "gaming-only machine that does not handle sensitive data."
)

WARNING_SPECTRE = (
    "This disables CPU vulnerability mitigations (Spectre/Meltdown).  The "
    "performance gain is real (1-8% depending on workload) but it reduces "
    "protection against speculative execution attacks.  Only use this on a "
    "dedicated gaming machine."
)

TWEAKS = validate_module("fps_boost", [

    # ── VBS / HVCI ──────────────────────────────────────────────────
    T(
        "fpsb-001", "Disable Virtualization-Based Security (VBS)",
        "Disables VBS and HVCI to recover 2-15% FPS lost to virtualization overhead.",
        actions=[
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\DeviceGuard",
             "EnableVirtualizationBasedSecurity", 0, "DWORD"),
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\DeviceGuard",
             "RequirePlatformSecurityFeatures", 0, "DWORD"),
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios"
             r"\HypervisorEnforcedCodeIntegrity",
             "Enabled", 0, "DWORD"),
        ],
        revert=[
            ("regdel", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\DeviceGuard",
             "EnableVirtualizationBasedSecurity"),
            ("regdel", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\DeviceGuard",
             "RequirePlatformSecurityFeatures"),
            ("regdel", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios"
             r"\HypervisorEnforcedCodeIntegrity",
             "Enabled"),
        ],
        why="VBS/HVCI run a hypervisor layer that traps memory operations. "
            "This adds measurable overhead to every CPU instruction, directly "
            "reducing frame rates by 2-15% in GPU-bound and CPU-bound titles.",
        changes="Disables VBS and HVCI (requires reboot).",
        risk="moderate", impact="extreme", recommended="optional",
        admin=True, confirm=True, warn=WARNING_VBS,
        win="10,11",
        tags=["vbs", "hvci", "hypervisor", "security", "fps"],
    ),

    # ── GPU Power Management (vendor guidance) ────────────────────
    # Replaces the old hard-coded PerfLevelSrc / PowerMizerLevel registry
    # writes: the \\\\0000 display-adapter instance is not reliable across
    # PCs, and the undocumented writes are driver-version dependent (a known
    # source of GPU clock collapse). Now guides toward the NVIDIA Control
    # Panel profile instead.

    # ── Nagle's Algorithm ───────────────────────────────────────────
    T(
        "fpsb-005", "Disable Nagle's Algorithm (Network Latency)",
        "Disables TCP packet batching for lower network latency in online games.",
        actions=[
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
             "TcpAckFrequency", 1, "DWORD"),
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
             "TCPNoDelay", 1, "DWORD"),
        ],
        revert=[
            ("regdel", "HKLM",
             r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
             "TcpAckFrequency"),
            ("regdel", "HKLM",
             r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
             "TCPNoDelay"),
        ],
        why="Nagle's algorithm batches small TCP packets to improve "
            "throughput but adds latency.  Online games send many small "
            "packets (position updates, inputs) where latency matters "
            "more than throughput.",
        changes="Disables TCP packet batching for lower latency.",
        risk="safe", impact="moderate", recommended="recommended",
        admin=True,
        tags=["network", "tcp", "nagle", "latency", "online"],
    ),

    # ── Background Apps ─────────────────────────────────────────────

    # ── Windows Spotlight ───────────────────────────────────────────
    T(
        "fpsb-008", "Disable Windows Spotlight",
        "Turns off the Windows lock screen Spotlight feature that downloads images.",
        actions=[
            ("reg", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion"
             r"\ContentDeliveryManager",
             "RotatingLockScreenEnabled", 0, "DWORD"),
            ("reg", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion"
             r"\ContentDeliveryManager",
             "RotatingLockScreenOverlayEnabled", 0, "DWORD"),
        ],
        revert=[
            ("regdel", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion"
             r"\ContentDeliveryManager",
             "RotatingLockScreenEnabled"),
            ("regdel", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion"
             r"\ContentDeliveryManager",
             "RotatingLockScreenOverlayEnabled"),
        ],
        why="Windows Spotlight periodically downloads new lock screen "
            "images and runs background tasks.  Disabling it removes "
            "unexpected disk and network activity.",
        changes="Disables Windows Spotlight lock screen.",
        risk="safe", impact="very low", recommended="optional",
        tags=["spotlight", "lockscreen", "background", "network"],
    ),

    # ── Windows Tips ────────────────────────────────────────────────
    T(
        "fpsb-009", "Disable Windows Tips and Suggestions",
        "Turns off Windows promotional tips and suggestion notifications.",
        actions=[
            ("reg", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion"
             r"\ContentDeliveryManager",
             "SoftLandingEnabled", 0, "DWORD"),
            ("reg", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion"
             r"\ContentDeliveryManager",
             "SubscribedContent-338389Enabled", 0, "DWORD"),
        ],
        revert=[
            ("regdel", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion"
             r"\ContentDeliveryManager",
             "SoftLandingEnabled"),
            ("regdel", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion"
             r"\ContentDeliveryManager",
             "SubscribedContent-338389Enabled"),
        ],
        why="Windows Tips run as background processes and can pop up "
            "over games, causing focus loss and resource usage.",
        changes="Disables Windows tips and suggestions.",
        risk="safe", impact="very low", recommended="optional",
        tags=["tips", "notifications", "background"],
    ),

    # ── Activity History ────────────────────────────────────────────
    T(
        "fpsb-010", "Disable Activity History",
        "Turns off Windows activity tracking to free background CPU and disk I/O.",
        actions=[
            ("reg", "HKLM",
             r"SOFTWARE\Policies\Microsoft\Windows\System",
             "EnableActivityFeed", 0, "DWORD"),
            ("reg", "HKLM",
             r"SOFTWARE\Policies\Microsoft\Windows\System",
             "PublishUserActivities", 0, "DWORD"),
            ("reg", "HKLM",
             r"SOFTWARE\Policies\Microsoft\Windows\System",
             "UploadUserActivities", 0, "DWORD"),
        ],
        revert=[
            ("regdel", "HKLM",
             r"SOFTWARE\Policies\Microsoft\Windows\System",
             "EnableActivityFeed"),
            ("regdel", "HKLM",
             r"SOFTWARE\Policies\Microsoft\Windows\System",
             "PublishUserActivities"),
            ("regdel", "HKLM",
             r"SOFTWARE\Policies\Microsoft\Windows\System",
             "UploadUserActivities"),
        ],
        why="Activity History tracks app usage and syncs it to the cloud. "
            "It runs periodic background writes that cause disk I/O spikes.",
        changes="Disables activity history tracking and upload.",
        risk="safe", impact="very low", recommended="optional",
        admin=True,
        tags=["activity", "history", "telemetry", "background"],
    ),

    # ── Maximum Power Plan ──────────────────────────────────────────

    # ── Spectre/Meltdown Mitigations ─────────────────────────────────
    T(
        "fpsb-012", "Disable Spectre/Meltdown Mitigations",
        "Disables CPU vulnerability mitigations for 1-8% FPS improvement.",
        actions=[
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Session Manager"
             r"\Memory Management",
             "FeatureSettingsOverride", 3, "DWORD"),
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Session Manager"
             r"\Memory Management",
             "FeatureSettingsOverrideMask", 3, "DWORD"),
        ],
        revert=[
            ("regdel", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Session Manager"
             r"\Memory Management",
             "FeatureSettingsOverride"),
            ("regdel", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Session Manager"
             r"\Memory Management",
             "FeatureSettingsOverrideMask"),
        ],
        why="CPU vulnerability mitigations (Spectre Variant 2 and Meltdown) "
            "add overhead to every system call and memory access.  Disabling "
            "them recovers 1-8% performance depending on workload.",
        changes="Disables Spectre and Meltdown mitigations (requires reboot).",
        risk="moderate", impact="high", recommended="optional",
        admin=True, confirm=True, warn=WARNING_SPECTRE,
        win="10,11",
        tags=["spectre", "meltdown", "mitigation", "security", "cpu"],
    ),

    # ── System Responsiveness ───────────────────────────────────────

    # ── Game Mode ───────────────────────────────────────────────────

    # ── Timer Resolution ──── REMOVED (fpsb-018 wrote the same
    # GlobalTimerResolutionRequests=1 flag as perf-001/power-017; merged into
    # perf-001 "Timer Resolution Diagnostic".)

    # ── PCIe ASPM ───────────────────────────────────────────────────
    T(
        "fpsb-021", "Disable PCIe ASPM",
        "Disables PCI Express Active State Power Management for maximum GPU/SSD bandwidth.",
        actions=[
            ("cmd",
             "powercfg /SETACVALUEINDEX SCHEME_CURRENT"
             " 501a4d13-42af-4429-9fd1-a8218c268e20"
             " ee12f906-d277-404b-b6da-e5fa1a576df5 0"),
            ("cmd", "powercfg /setactive SCHEME_CURRENT"),
        ],
        revert=[
            ("cmd",
             "powercfg /SETACVALUEINDEX SCHEME_CURRENT"
             " 501a4d13-42af-4429-9fd1-a8218c268e20"
             " ee12f906-d277-404b-b6da-e5fa1a576df5 3"),
            ("cmd", "powercfg /setactive SCHEME_CURRENT"),
        ],
        why="PCIe ASPM puts GPU and NVMe links into low-power states "
            "during idle, adding wake latency on the next access.  "
            "Disabling it keeps the link at full bandwidth.",
        changes="Disables PCIe Link State Power Management.",
        risk="safe", impact="low", recommended="recommended",
        admin=True,
        tags=["pcie", "aspm", "gpu", "nvme", "latency"],
    ),

    # ── Disable Telemetry ───────────────────────────────────────────

    # ── Disable Notifications ───────────────────────────────────────

    # ── Resizable BAR ───────────────────────────────────────────────
    T(
        "fpsb-026", "Resizable BAR Review",
        "Checks whether Resizable BAR / Above-4G decoding is available and explains how to enable it safely in BIOS.",
        actions=[
            ("cmd", 'powershell -NoProfile -Command "try { Get-PnpDevice -PresentOnly -Class Display | ForEach-Object { Write-Output (\'GPU: \' + $_.FriendlyName); $d = Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName \'DEVPKEY_Device_ReportedDeviceIds\' -ErrorAction Stop; if ($d) { Write-Output (\'ReportedDeviceIds: \' + ($d.Data -join \', \')) } } } catch { Write-Output (\'No ReBAR device-id data returned: \' + $_.Exception.Message) } exit 0"',
             30),
            ("guidance", "Resizable BAR is a BIOS/firmware feature: enable 'Above 4G Decoding' and 'Resizable BAR' in the motherboard BIOS, then confirm in the GPU vendor software. There is NO supported Windows registry switch for it, so this app does not emulate one."),
        ],
        revert=[
            ("guidance", "Disable Resizable BAR in the BIOS."),
        ],
        why="ReBAR lets the CPU address the full GPU VRAM. It is a hardware "
            "platform feature; a fake registry value cannot enable it.",
        changes="Reviews Resizable BAR support and BIOS instructions.",
        risk="safe", impact="moderate", recommended="optional",
        updated="2026-09-27",
        tags=["rebar", "bios", "vram", "above4g"],
    ),

])
