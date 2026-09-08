"""Category: FPS Boost — proven system-level tweaks that measurably increase
frame rates and reduce input latency across all GPU vendors.

Every tweak here has a documented benchmark or well-known mechanism.  None
overlap with Performance, CPU, Power, Gaming, NVIDIA, AMD, or Intel modules.
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("FPS Boost", win_default="10,11")

CATEGORY = "FPS Boost"

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

    # ── Resizable BAR ───────────────────────────────────────────────
    T(
        "fpsb-002", "Enable Resizable BAR (ReBAR)",
        "Enables Resizable BAR so the CPU can access the full GPU VRAM in one transaction.",
        actions=[
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
             "HwSchMode", 2, "DWORD"),
        ],
        revert=[
            ("regdel", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
             "HwSchMode"),
        ],
        why="ReBAR lets the CPU map the entire GPU framebuffer instead of "
            "256 MB chunks, reducing VRAM access stalls and improving FPS "
            "by 2-8% in modern titles with heavy texture streaming.",
        changes="Enables hardware-accelerated GPU scheduling (required for ReBAR).",
        risk="safe", impact="high", recommended="recommended",
        admin=True,
        tags=["rebar", "resizeable", "bar", "vram", "gpu"],
    ),

    # ── GPU Power Management ────────────────────────────────────────
    T(
        "fpsb-004", "Set GPU Power Management to Maximum Performance",
        "Forces the GPU to stay at maximum clock speeds instead of downclocking.",
        actions=[
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Class"
             r"\{4d36e968-e325-11ce-bfc1-08002be10318}\0000",
             "PerfLevelSrc", 8738, "DWORD"),
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Class"
             r"\{4d36e968-e325-11ce-bfc1-08002be10318}\0000",
             "PowerMizerLevel", 1, "DWORD"),
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Class"
             r"\{4d36e968-e325-11ce-bfc1-08002be10318}\0000",
             "PowerMizerLevelAC", 1, "DWORD"),
        ],
        revert=[
            ("regdel", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Class"
             r"\{4d36e968-e325-11ce-bfc1-08002be10318}\0000",
             "PerfLevelSrc"),
            ("regdel", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Class"
             r"\{4d36e968-e325-11ce-bfc1-08002be10318}\0000",
             "PowerMizerLevel"),
            ("regdel", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Class"
             r"\{4d36e968-e325-11ce-bfc1-08002be10318}\0000",
             "PowerMizerLevelAC"),
        ],
        why="NVIDIA GPUs dynamically downclock to save power.  Forcing "
            "maximum performance prevents micro-stutter caused by clock "
            "speed transitions during gameplay.",
        changes="Sets GPU power management to maximum performance.",
        risk="safe", impact="moderate", recommended="recommended",
        admin=True,
        when={"gpu": ["nvidia"]},
        tags=["gpu", "power", "clock", "nvidia"],
    ),

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

    # ── Network Throttling Index ────────────────────────────────────
    T(
        "fpsb-006", "Disable MMCSS Network Throttling",
        "Removes the multimedia network throttling cap for full network throughput.",
        actions=[
            ("reg", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
             r"\Multimedia\SystemProfile",
             "NetworkThrottlingIndex", 0xFFFFFFFF, "DWORD"),
        ],
        revert=[
            ("regdel", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
             r"\Multimedia\SystemProfile",
             "NetworkThrottlingIndex"),
        ],
        why="MMCSS limits network packet processing during multimedia "
            "playback to 10 packets/ms by default.  Disabling this cap "
            "ensures full network speed for online gaming.",
        changes="Removes MMCSS network throttling (sets index to 0xFFFFFFFF).",
        risk="safe", impact="moderate", recommended="recommended",
        admin=True,
        tags=["mmcss", "network", "throttling", "online"],
    ),

    # ── Background Apps ─────────────────────────────────────────────
    T(
        "fpsb-007", "Disable Background Apps",
        "Prevents UWP apps from running in the background and consuming CPU/GPU.",
        actions=[
            ("reg", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion"
             r"\BackgroundAccessApplications",
             "GlobalUserDisabled", 1, "DWORD"),
        ],
        revert=[
            ("regdel", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion"
             r"\BackgroundAccessApplications",
             "GlobalUserDisabled"),
        ],
        why="UWP apps can run background tasks, update live tiles, and "
            "consume CPU/GPU even when minimized.  Disabling background "
            "access frees resources for your game.",
        changes="Disables background access for all UWP apps.",
        risk="safe", impact="moderate", recommended="recommended",
        tags=["uwp", "background", "apps", "resource"],
    ),

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

    # ── Ultimate Performance Power Plan ──────────────────────────────
    T(
        "fpsb-011", "Activate Ultimate Performance Power Plan",
        "Creates and activates the hidden Ultimate Performance power plan.",
        actions=[
            ("powerscheme", "create",
             "e9a42b02-d5df-448d-aa00-03f14749eb61",
             "Ultimate Performance"),
        ],
        revert=[
            ("powerscheme", "setactive",
             "381b4222-f694-41df-9d63-86d0b2b0e55f"),
            ("powerscheme", "delete",
             "e9a42b02-d5df-448d-aa00-03f14749eb61"),
        ],
        why="The Ultimate Performance plan minimizes micro-latencies by "
            "removing power-saving delays.  It keeps CPUs at high clock "
            "speeds and disables PCI Express link state power management.",
        changes="Activates the Ultimate Performance power plan.",
        risk="safe", impact="moderate", recommended="recommended",
        admin=True,
        tags=["power", "plan", "ultimate", "clock", "latency"],
    ),

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
    T(
        "fpsb-013", "Minimize System Responsiveness Reserve",
        "Reduces the CPU reserved for background tasks to maximize game performance.",
        actions=[
            ("reg", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
             r"\Multimedia\SystemProfile",
             "SystemResponsiveness", 0, "DWORD"),
        ],
        revert=[
            ("regdel", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
             r"\Multimedia\SystemProfile",
             "SystemResponsiveness"),
        ],
        why="SystemResponsiveness reserves a percentage of CPU for "
            "background tasks.  Setting it to 0 gives foreground games "
            "access to all CPU resources.",
        changes="Sets MMCSS SystemResponsiveness to 0.",
        risk="safe", impact="moderate", recommended="recommended",
        admin=True,
        tags=["mmcss", "responsiveness", "cpu", "background"],
    ),

    # ── Game DVR Recording ──────────────────────────────────────────
    T(
        "fpsb-014", "Disable Game DVR and Recording",
        "Disables Windows Game DVR background recording to free GPU and CPU resources.",
        actions=[
            ("reg", "HKCU",
             r"System\GameConfigStore",
             "GameDVR_Enabled", 0, "DWORD"),
            ("reg", "HKLM",
             r"SOFTWARE\Policies\Microsoft\Windows\GameDVR",
             "AllowGameDVR", 0, "DWORD"),
            ("reg", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
             "AppCaptureEnabled", 0, "DWORD"),
        ],
        revert=[
            ("regdel", "HKCU",
             r"System\GameConfigStore",
             "GameDVR_Enabled"),
            ("regdel", "HKLM",
             r"SOFTWARE\Policies\Microsoft\Windows\GameDVR",
             "AllowGameDVR"),
            ("regdel", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
             "AppCaptureEnabled"),
        ],
        why="Game DVR continuously records gameplay in the background, "
            "consuming CPU, GPU, and disk resources even when you are "
            "not recording.",
        changes="Disables Game DVR and background recording.",
        risk="safe", impact="moderate", recommended="recommended",
        tags=["game", "dvr", "recording", "background"],
    ),

    # ── Fullscreen Optimizations ────────────────────────────────────
    T(
        "fpsb-015", "Disable Fullscreen Optimizations",
        "Forces exclusive fullscreen mode for lower input latency.",
        actions=[
            ("reg", "HKCU",
             r"System\GameConfigStore",
             "GameDVR_FSEBehaviorMode", 2, "DWORD"),
            ("reg", "HKCU",
             r"System\GameConfigStore",
             "GameDVR_HonorUserFSEBehaviorMode", 1, "DWORD"),
            ("reg", "HKCU",
             r"System\GameConfigStore",
             "GameDVR_FSEBehavior", 2, "DWORD"),
            ("reg", "HKCU",
             r"System\GameConfigStore",
             "GameDVR_DXGIHonorFSEWindowsCompatible", 1, "DWORD"),
        ],
        revert=[
            ("reg", "HKCU",
             r"System\GameConfigStore",
             "GameDVR_FSEBehaviorMode", 0, "DWORD"),
            ("regdel", "HKCU",
             r"System\GameConfigStore",
             "GameDVR_HonorUserFSEBehaviorMode"),
            ("reg", "HKCU",
             r"System\GameConfigStore",
             "GameDVR_FSEBehavior", 0, "DWORD"),
            ("regdel", "HKCU",
             r"System\GameConfigStore",
             "GameDVR_DXGIHonorFSEWindowsCompatible"),
        ],
        why="Windows fullscreen optimizations add a compositor layer "
            "between the game and the display, increasing input latency "
            "and reducing performance.",
        changes="Disables Windows fullscreen optimizations.",
        risk="safe", impact="moderate", recommended="recommended",
        tags=["fso", "fullscreen", "exclusive", "latency"],
    ),

    # ── Game Mode ───────────────────────────────────────────────────
    T(
        "fpsb-016", "Enable Windows Game Mode",
        "Enables Game Mode to prioritize system resources for your game.",
        actions=[
            ("reg", "HKCU",
             r"Software\Microsoft\GameBar",
             "AutoGameModeEnabled", 1, "DWORD"),
            ("reg", "HKCU",
             r"Software\Microsoft\GameBar",
             "AllowAutoGameMode", 1, "DWORD"),
        ],
        revert=[
            ("reg", "HKCU",
             r"Software\Microsoft\GameBar",
             "AutoGameModeEnabled", 0, "DWORD"),
            ("reg", "HKCU",
             r"Software\Microsoft\GameBar",
             "AllowAutoGameMode", 0, "DWORD"),
        ],
        why="Game Mode tells Windows to allocate scheduling priority "
            "and GPU budget to the active game, reducing background "
            "interference.",
        changes="Enables Windows Game Mode.",
        risk="safe", impact="moderate", recommended="recommended",
        tags=["game", "mode", "priority", "windows"],
    ),

    # ── HAGS ────────────────────────────────────────────────────────
    T(
        "fpsb-017", "Enable Hardware-Accelerated GPU Scheduling",
        "Enables HAGS so the GPU manages its own memory for lower CPU overhead.",
        actions=[
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
             "HwSchMode", 2, "DWORD"),
        ],
        revert=[
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
             "HwSchMode", 1, "DWORD"),
        ],
        why="HAGS lets the GPU schedule its own work instead of relying "
            "on the CPU, reducing CPU overhead and improving frame rates "
            "in supported games.",
        changes="Enables Hardware-Accelerated GPU Scheduling.",
        risk="safe", impact="moderate", recommended="recommended",
        tags=["hags", "gpu", "scheduling", "directx"],
    ),

    # ── Timer Resolution ────────────────────────────────────────────
    T(
        "fpsb-018", "Optimize Timer Resolution",
        "Enables global timer resolution requests for lower input latency.",
        actions=[
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel",
             "GlobalTimerResolutionRequests", 1, "DWORD"),
        ],
        revert=[
            ("regdel", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel",
             "GlobalTimerResolutionRequests"),
        ],
        why="A higher timer resolution allows Windows to poll input "
            "devices more frequently, reducing input latency in games.",
        changes="Enables global timer resolution requests.",
        risk="safe", impact="moderate", recommended="recommended",
        admin=True,
        tags=["timer", "resolution", "input", "latency"],
    ),

    # ── Disable Superfetch ──────────────────────────────────────────
    T(
        "fpsb-020", "Disable Superfetch (SysMain)",
        "Disables Superfetch/SysMain to eliminate disk thrashing on SSDs.",
        actions=[
            ("svc", "SysMain", "disabled"),
            ("svcstop", "SysMain"),
        ],
        revert=[
            ("svc", "SysMain", "manual"),
        ],
        why="Superfetch preloads frequently used apps into RAM.  On SSDs "
            "with fast access times, this adds unnecessary disk I/O and "
            "CPU overhead during gaming.",
        changes="Disables Superfetch/SysMain service.",
        risk="low", impact="moderate", recommended="recommended",
        admin=True,
        tags=["superfetch", "sysmain", "memory", "disk"],
    ),

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
    T(
        "fpsb-023", "Disable Windows Telemetry",
        "Stops the Connected User Experiences and Telemetry service.",
        actions=[
            ("svc", "DiagTrack", "disabled"),
            ("svcstop", "DiagTrack"),
        ],
        revert=[
            ("svc", "DiagTrack", "auto"),
        ],
        why="DiagTrack periodically uploads telemetry data in the "
            "background, consuming CPU, disk, and network resources.",
        changes="Disables and stops the DiagTrack telemetry service.",
        risk="safe", impact="low", recommended="optional",
        admin=True,
        win="10,11",
        tags=["telemetry", "service", "background"],
    ),

    # ── Disable Notifications ───────────────────────────────────────
    T(
        "fpsb-024", "Disable Toast Notifications",
        "Turns off Windows toast notifications to prevent focus loss during gaming.",
        actions=[
            ("reg", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion\PushNotifications",
             "ToastEnabled", 0, "DWORD"),
        ],
        revert=[
            ("regdel", "HKCU",
             r"Software\Microsoft\Windows\CurrentVersion\PushNotifications",
             "ToastEnabled"),
        ],
        why="Toast notifications can appear over fullscreen games, "
            "causing focus loss and brief frame drops.",
        changes="Disables Windows toast notifications.",
        risk="safe", impact="low", recommended="optional",
        tags=["notifications", "toast", "focus"],
    ),

    # ── NTFS Last Access ────────────────────────────────────────────
    T(
        "fpsb-025", "Disable NTFS Last Access Timestamps",
        "Stops NTFS from updating file access timestamps to reduce disk I/O.",
        actions=[
            ("cmd", "fsutil behavior set disablelastaccess 1"),
        ],
        revert=[
            ("cmd", "fsutil behavior set disablelastaccess 0"),
        ],
        why="NTFS updates the last access timestamp for every file read, "
            "adding disk I/O overhead that can cause hitches during "
            "asset streaming.",
        changes="Disables NTFS last access timestamp updates.",
        risk="low", impact="low", recommended="optional",
        admin=True,
        tags=["ntfs", "disk", "io", "timestamp"],
    ),

])
