"""Category: Performance — genuine gaming / FPS performance optimizations.

Every tweak here is unique to this module (no overlap with cpu, ram, system,
network, services, or gaming modules).
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Performance", win_default="10,11")
CATEGORY = "Performance"

TWEAKS = validate_module("performance", [
    # ── Timer Resolution ───────────────────────────────────────────
    T("perf-001", "Optimize System Timer Resolution",
      "Configure Windows timer resolution behavior for lower input latency.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel",
           "GlobalTimerResolutionRequests", 1, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel",
           "GlobalTimerResolutionRequests", 0, "DWORD"),
      ],
      why="A higher timer resolution allows the system to poll input devices "
          "more frequently, reducing input latency in games.",
      changes="Enables global timer resolution requests for lower latency.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["timer", "latency", "input"]),

    # ── Game Mode ──────────────────────────────────────────────────
    T("perf-002", "Enable Game Mode",
      "Enable Windows Game Mode for better gaming performance.",
      actions=[
          ("reg", "HKCU", r"Software\Microsoft\GameBar",
           "AutoGameModeEnabled", 1, "DWORD"),
      ],
      revert=[
          ("reg", "HKCU", r"Software\Microsoft\GameBar",
           "AutoGameModeEnabled", 0, "DWORD"),
      ],
      why="Game Mode prioritizes system resources for your active game, "
          "reducing background activity that can cause stuttering.",
      changes="Enables Windows Game Mode for gaming performance.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["game", "mode", "windows"]),

    T("perf-003", "Disable Game Mode",
      "Disable Windows Game Mode if it causes issues with your system.",
      actions=[
          ("reg", "HKCU", r"Software\Microsoft\GameBar",
           "AutoGameModeEnabled", 0, "DWORD"),
      ],
      revert=[
          ("reg", "HKCU", r"Software\Microsoft\GameBar",
           "AutoGameModeEnabled", 1, "DWORD"),
      ],
      why="Some users report Game Mode causes stuttering on certain hardware. "
          "Disable it if you experience issues.",
      changes="Disables Windows Game Mode.",
      risk="safe", impact="low", recommended="optional",
      tags=["game", "mode", "windows"]),

    # ── Memory Compression ─────────────────────────────────────────
    T("perf-004", "Disable Memory Compression",
      "Disable Windows Memory Compression which can add CPU overhead.",
      actions=[
          ("cmd", "Disable-MMAgent -MemoryCompression"),
      ],
      revert=[
          ("cmd", "Enable-MMAgent -MemoryCompression"),
      ],
      why="Memory Compression uses CPU cycles to compress memory pages. "
          "On systems with enough RAM (16GB+), disabling it frees CPU for games.",
      changes="Disables Windows Memory Compression.",
      risk="low", impact="moderate", recommended="optional",
      admin=True,
      tags=["memory", "compression", "cpu"]),

    # ── Superfetch / SysMain ───────────────────────────────────────
    T("perf-005", "Disable Superfetch (SysMain)",
      "Disable Superfetch/SysMain service which can cause disk thrashing.",
      actions=[
          ("svc", "SysMain", "disabled"),
          ("svcstop", "SysMain"),
      ],
      revert=[
          ("svc", "SysMain", "manual"),
      ],
      why="Superfetch preloads frequently used apps into RAM. On SSDs with "
          "fast access times, this adds unnecessary disk I/O and CPU overhead.",
      changes="Disables Superfetch/SysMain service.",
      risk="low", impact="moderate", recommended="recommended",
      admin=True,
      tags=["superfetch", "sysmain", "memory"]),

    # ── Page Combining ─────────────────────────────────────────────
    T("perf-006", "Disable Page Combining",
      "Disable Windows page combining which can increase memory management "
      "overhead.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management",
           "DisablePageCombining", 1, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management",
           "DisablePageCombining"),
      ],
      why="Page Combining scans memory for duplicate pages and merges them. "
          "This adds CPU overhead with minimal benefit on modern systems.",
      changes="Disables Windows page combining.",
      risk="safe", impact="low", recommended="optional",
      tags=["memory", "page", "combining"]),

    # ── Fast Startup ───────────────────────────────────────────────
    T("perf-007", "Disable Fast Startup",
      "Disable Windows Fast Startup for cleaner boots.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Power",
           "HiberbootEnabled", 0, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Power",
           "HiberbootEnabled", 1, "DWORD"),
      ],
      why="Fast Startup saves a hibernation file at shutdown. Disabling it "
          "gives cleaner boots and avoids potential driver state issues.",
      changes="Disables Windows Fast Startup.",
      risk="safe", impact="low", recommended="optional",
      tags=["startup", "boot", "power"]),

    # ── Hibernation ────────────────────────────────────────────────
    T("perf-008", "Disable Hibernation",
      "Disable hibernation to free disk space and reduce overhead.",
      actions=[
          ("cmd", "powercfg /hibernate off"),
      ],
      revert=[
          ("cmd", "powercfg /hibernate on"),
      ],
      why="Hibernation creates a large hiberfil.sys file. Disabling it frees "
          "disk space and removes the overhead of managing the hibernation file.",
      changes="Disables hibernation and removes hiberfil.sys.",
      risk="low", impact="low", recommended="optional",
      admin=True,
      tags=["hibernation", "power", "disk"]),

    # ── Windows Update Throttling ──────────────────────────────────
    T("perf-009", "Throttle Windows Update During Gaming",
      "Configure Windows Update to avoid downloading during active gaming.",
      actions=[
          ("reg", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU",
           "NoAutoUpdate", 0, "DWORD"),
          ("reg", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU",
           "AUOptions", 4, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU",
           "NoAutoUpdate"),
          ("regdel", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU",
           "AUOptions"),
      ],
      why="Windows Update can download large files in the background, causing "
          "network lag and disk I/O spikes during gaming.",
      changes="Configures Windows Update to notify before downloading.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["update", "network", "background"]),

    # ── Visual Effects ─────────────────────────────────────────────
    T("perf-010", "Disable Unnecessary Visual Effects",
      "Reduce Windows visual effects for better performance.",
      actions=[
          ("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
           "VisualFXSetting", 2, "DWORD"),
      ],
      revert=[
          ("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
           "VisualFXSetting", 0, "DWORD"),
      ],
      why="Visual effects like animations and transparency consume GPU/CPU "
          "resources. Disabling them improves UI responsiveness.",
      changes="Disables unnecessary visual effects.",
      risk="safe", impact="low", recommended="optional",
      tags=["visual", "effects", "ui"]),



    # ── Notifications ──────────────────────────────────────────────
    T("perf-012", "Disable Toast Notifications",
      "Disable Windows toast notifications to avoid interruptions.",
      actions=[
          ("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\PushNotifications",
           "ToastEnabled", 0, "DWORD"),
      ],
      revert=[
          ("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\PushNotifications",
           "ToastEnabled", 1, "DWORD"),
      ],
      why="Toast notifications can appear over games, causing focus loss "
          "and interrupting gameplay.",
      changes="Disables Windows toast notifications.",
      risk="safe", impact="low", recommended="optional",
      tags=["notifications", "toast", "ui"]),

    # ── Interrupt Moderation ───────────────────────────────────────
    T("perf-013", "Disable Interrupt Moderation",
      "Disable network interrupt moderation for lower latency.",
      actions=[
          ("cmd", "netsh int tcp set global autotuninglevel=normal"),
          ("cmd", "netsh int tcp set global chimney=disabled"),
      ],
      revert=[
          ("cmd", "netsh int tcp set global autotuninglevel=normal"),
          ("cmd", "netsh int tcp set global chimney=default"),
      ],
      why="Interrupt moderation batches network interrupts to reduce CPU usage "
          "but adds latency. Disabling it improves network responsiveness.",
      changes="Disables network interrupt moderation.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["network", "interrupt", "latency"]),

    # ── GPU Scheduling ─────────────────────────────────────────────
    T("perf-015", "Enable Hardware-Accelerated GPU Scheduling",
      "Enable HAGS for better GPU performance in supported games.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
           "HwSchMode", 2, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
           "HwSchMode", 1, "DWORD"),
      ],
      why="Hardware-Accelerated GPU Scheduling allows the GPU to manage its "
          "own memory, reducing CPU overhead and improving frame rates.",
      changes="Enables Hardware-Accelerated GPU Scheduling.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["gpu", "scheduling", "hags"]),

    # ── Game DVR ───────────────────────────────────────────────────
    T("perf-016", "Disable Game DVR",
      "Disable Windows Game DVR to reduce performance overhead.",
      actions=[
          ("reg", "HKCU", r"System\GameConfigStore",
           "GameDVR_Enabled", 0, "DWORD"),
          ("reg", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\GameDVR",
           "AllowGameDVR", 0, "DWORD"),
      ],
      revert=[
          ("reg", "HKCU", r"System\GameConfigStore",
           "GameDVR_Enabled", 1, "DWORD"),
          ("regdel", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\GameDVR",
           "AllowGameDVR"),
      ],
      why="Game DVR continuously records gameplay in the background, consuming "
          "CPU, GPU, and disk resources. Disabling it improves performance.",
      changes="Disables Windows Game DVR.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["game", "dvr", "recording"]),





    # ── Interrupt Affinity ─────────────────────────────────────────
    T("perf-019", "Optimize Interrupt Affinity",
      "Configure interrupt affinity for better CPU load distribution.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\PriorityControl",
           "IRQ8Priority", 1, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", r"SYSTEM\CurrentControlSet\Control\PriorityControl",
           "IRQ8Priority"),
      ],
      why="Setting IRQ8 (real-time clock) to higher priority ensures time-critical "
          "operations get CPU attention promptly.",
      changes="Optimizes interrupt priority for lower latency.",
      risk="safe", impact="low", recommended="optional",
      tags=["interrupt", "irq", "latency"]),

    # ── MSI Mode ───────────────────────────────────────────────────
    T("perf-020", "Enable MSI Mode for GPU",
      "Enable Message Signaled Interrupts for GPU if supported.",
      actions=[
          ("guidance", "MSI mode can reduce GPU latency by allowing the GPU to "
           "use message-signaled interrupts instead of line-based interrupts. "
           "Enable this through Device Manager > Display adapter > Properties > "
           "Advanced > Interrupt Mode if available."),
      ],
      revert=[
          ("guidance", "Disable MSI mode through Device Manager if it causes issues."),
      ],
      why="MSI mode allows the GPU to communicate via memory writes instead of "
          "dedicated interrupt lines, reducing latency and improving performance.",
      changes="Provides guidance on enabling MSI mode for GPU.",
      risk="safe", impact="low", recommended="optional",
      tags=["msi", "gpu", "interrupts"]),

    # ── Turbo Boost ────────────────────────────────────────────────

    # ── FSO (Fullscreen Optimizations) ─────────────────────────────
    T("perf-023", "Disable Fullscreen Optimizations",
      "Disable Windows fullscreen optimizations for exclusive fullscreen.",
      actions=[
          ("reg", "HKCU", r"System\GameConfigStore",
           "GameDVR_FSEBehaviorMode", 2, "DWORD"),
          ("reg", "HKCU", r"System\GameConfigStore",
           "GameDVR_HonorUserFSEBehaviorMode", 1, "DWORD"),
          ("reg", "HKCU", r"System\GameConfigStore",
           "GameDVR_FSEBehavior", 2, "DWORD"),
          ("reg", "HKCU", r"System\GameConfigStore",
           "GameDVR_DXGIHonorFSEWindowsCompatible", 1, "DWORD"),
      ],
      revert=[
          ("reg", "HKCU", r"System\GameConfigStore",
           "GameDVR_FSEBehaviorMode", 0, "DWORD"),
          ("regdel", "HKCU", r"System\GameConfigStore",
           "GameDVR_HonorUserFSEBehaviorMode"),
          ("reg", "HKCU", r"System\GameConfigStore",
           "GameDVR_FSEBehavior", 0, "DWORD"),
          ("regdel", "HKCU", r"System\GameConfigStore",
           "GameDVR_DXGIHonorFSEWindowsCompatible"),
      ],
      why="Fullscreen optimizations can add input latency and reduce performance "
          "in some games. Disabling them forces exclusive fullscreen mode.",
      changes="Disables Windows fullscreen optimizations.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["fso", "fullscreen", "display"]),



    # ═══════════════════════════════════════════════════════════════
    #  NEW TWEAKS — perf-026 through perf-055
    # ═══════════════════════════════════════════════════════════════

    # ── Power Throttling ──────────────────────────────────────────
    T("perf-026", "Disable Power Throttling",
      "Disable Windows Power Throttling to prevent the OS from throttling "
      "CPU performance for background-classified threads.",
      actions=[
          ("reg", "HKLM",
           r"SYSTEM\CurrentControlSet\Control\Power\PowerThrottling",
           "PowerThrottlingOff", 1, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM",
           r"SYSTEM\CurrentControlSet\Control\Power\PowerThrottling",
           "PowerThrottlingOff"),
      ],
      why="Power Throttling can reduce CPU frequency for background processes, "
          "but may cause frame drops when the system misclassifies game threads.",
      changes="Disables Windows Power Throttling globally.",
      risk="safe", impact="moderate", recommended="recommended",
      admin=True,
      tags=["power", "throttling", "cpu"]),

    # ── Timer Coalescing ──── REMOVED (duplicate of perf-001) ──
    # ── Timer Resolution & Multimedia ──── REMOVED (duplicate of perf-001) ──

    # ── MMCSS Gaming Priority ────────────────────────────────────
    T("perf-029", "Set MMCSS Gaming Priority",
      "Configure MMCSS to give game processes highest scheduling priority.",
      actions=[
          ("reg", "HKLM",
           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Game",
           "Priority", 6, "DWORD"),
          ("reg", "HKLM",
           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Game",
           "GPU Priority", 8, "DWORD"),
          ("reg", "HKLM",
           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Game",
           "Clock Rate", 10000, "DWORD"),
          ("reg", "HKLM",
           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Game",
           "SFIO Priority", "High", "STRING"),
      ],
      revert=[
          ("regdel", "HKLM",
           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Game",
           "Priority"),
          ("regdel", "HKLM",
           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Game",
           "GPU Priority"),
          ("regdel", "HKLM",
           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Game",
           "Clock Rate"),
          ("regdel", "HKLM",
           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Game",
           "SFIO Priority"),
      ],
      why="MMCSS gives multimedia threads priority over other processes. "
          "Optimizing these values ensures games get maximum CPU and GPU "
          "scheduling priority for smooth frame delivery.",
      changes="Configures MMCSS gaming task priority for maximum performance.",
      risk="safe", impact="moderate", recommended="recommended",
      admin=True,
      tags=["mmcss", "priority", "gaming", "scheduler"]),

    # ── Dynamic Tick ──── REMOVED (duplicate of cpu-011) ──

    # ── HPET Enable ─────────────────────────────────────────────

    # ── Win32PrioritySeparation ──────────────────────────────────
    T("perf-032", "Set Win32PrioritySeparation",
      "Configure CPU thread priority separation for foreground-optimized "
      "scheduling.",
      actions=[
          ("reg", "HKLM",
           r"SYSTEM\CurrentControlSet\Control\PriorityControl",
           "Win32PrioritySeparation", 26, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM",
           r"SYSTEM\CurrentControlSet\Control\PriorityControl",
           "Win32PrioritySeparation"),
      ],
      why="Win32PrioritySeparation controls how the scheduler divides CPU time. "
          "Value 38 provides short fixed quanta with foreground boost for gaming.",
      changes="Sets Win32PrioritySeparation to 38 for foreground-optimized scheduling.",
      risk="low", impact="moderate", recommended="recommended",
      admin=True,
      tags=["priority", "scheduler", "foreground"]),

    # ── Performance Decrease Policy ──────────────────────────────
    T("perf-034", "Set Processor Performance Decrease Policy",
      "Configure aggressive processor performance decrease for faster "
      "frequency scaling under gaming loads.",
      actions=[
          ("power", "CPPERF", "2", "SCHEME_CURRENT"),
      ],
      revert=[
          ("power", "CPPERF", "0", "SCHEME_CURRENT"),
      ],
      why="Controls how quickly the CPU scales down frequency. Aggressive mode "
          "prevents unnecessary frequency drops during gaming workloads.",
      changes="Sets processor performance decrease policy to aggressive (2).",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["cpu", "power", "frequency", "scaling"]),

    # ── USB Selective Suspend ────────────────────────────────────
    T("perf-035", "Disable USB Selective Suspend",
      "Disable USB selective suspend to prevent USB device disconnections.",
      actions=[
          ("reg", "HKLM",
           r"SYSTEM\CurrentControlSet\Services\USB",
           "DisableSelectiveSuspend", 1, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM",
           r"SYSTEM\CurrentControlSet\Services\USB",
           "DisableSelectiveSuspend"),
      ],
      why="USB selective suspend can cause brief disconnections of USB devices "
          "like mice and keyboards, leading to input drops during gaming.",
      changes="Disables USB selective suspend globally.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["usb", "selective", "suspend", "input"]),

    # ── NTFS Last Access ─────────────────────────────────────────
    T("perf-036", "Optimize NTFS Last Access",
      "Disable NTFS last access timestamp updates to reduce disk I/O.",
      actions=[
          ("cmd", "fsutil behavior set disablelastaccess 1"),
      ],
      revert=[
          ("cmd", "fsutil behavior set disablelastaccess 0"),
      ],
      why="NTFS updates the last access timestamp for every file read, adding "
          "disk I/O overhead. Disabling this reduces unnecessary disk writes.",
      changes="Disables NTFS last access timestamp updates.",
      risk="low", impact="low", recommended="optional",
      admin=True,
      tags=["ntfs", "disk", "io", "timestamp"]),

    # ── TRIM ─────────────────────────────────────────────────────
    T("perf-037", "Force TRIM",
      "Ensure TRIM is always enabled for optimal SSD performance.",
      actions=[
          ("cmd", "fsutil behavior set disabledeletenotify 0"),
      ],
      revert=[
          ("cmd", "fsutil behavior set disabledeletenotify 1"),
      ],
      why="TRIM allows the SSD controller to pre-erase blocks before writes, "
          "maintaining SSD write performance over time.",
      changes="Ensures NTFS TRIM is always enabled.",
      risk="safe", impact="low", recommended="recommended",
      admin=True,
      tags=["ssd", "trim", "disk"]),

    # ── I/O Coalescing ───────────────────────────────────────────
    T("perf-038", "Disable I/O Coalescing",
      "Disable I/O coalescing in the LAN server driver for lower latency.",
      actions=[
          ("reg", "HKLM",
           r"SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters",
           "IoCoalescing", 0, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM",
           r"SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters",
           "IoCoalescing"),
      ],
      why="I/O coalescing batches disk and network I/O operations. While it "
          "improves throughput, it adds latency that can affect gaming.",
      changes="Disables I/O coalescing in LanmanServer.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["io", "coalescing", "network", "disk"]),

    # ── Service Priority ──── REMOVED (causes priority inversion) ──
    # ── Prefetch ──── REMOVED (duplicate of ram-001) ──
    # ── Superfetch (Registry) ──── REMOVED (duplicate of perf-005) ──

    # ── Memory Compression (Cmd) ─────────────────────────────────
    T("perf-042", "Disable Memory Compression (Cmd)",
      "Disable Windows Memory Compression via PowerShell to reduce CPU "
      "overhead on systems with ample RAM.",
      actions=[
          ("cmd", "Disable-MMAgent -MemoryCompression"),
      ],
      revert=[
          ("cmd", "Enable-MMAgent -MemoryCompression"),
      ],
      why="Memory Compression uses CPU cycles to compress/decompress memory "
          "pages. Disabling it frees CPU resources for gaming on systems "
          "with 16 GB+ RAM.",
      changes="Disables Windows Memory Compression via PowerShell.",
      risk="low", impact="moderate", recommended="optional",
      admin=True,
      tags=["memory", "compression", "cpu", "powershell"]),

    # ── Page Combining (Registry) ────────────────────────────────
    T("perf-043", "Disable Page Combining (Registry)",
      "Disable Windows page combining through registry to reduce memory "
      "management overhead.",
      actions=[
          ("reg", "HKLM",
           r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management",
           "DisablePageCombining", 1, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM",
           r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management",
           "DisablePageCombining"),
      ],
      why="Page Combining scans memory for duplicate pages and merges them, "
          "adding CPU overhead with minimal benefit on modern gaming systems.",
      changes="Disables Windows page combining via registry.",
      risk="safe", impact="low", recommended="optional",
      tags=["memory", "page", "combining"]),

    # ── MMCSS Network Throttling ─────────────────────────────────
    T("perf-044", "Disable MMCSS Network Throttling",
      "Disable MMCSS network throttling for maximum network throughput.",
      actions=[
          ("reg", "HKLM",
           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
           "NetworkThrottlingIndex", 0xFFFFFFFF, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM",
           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
           "NetworkThrottlingIndex"),
      ],
      why="MMCSS network throttling limits network packet processing during "
          "multimedia playback. Disabling it ensures full network speed for gaming.",
      changes="Disables MMCSS network throttling (sets index to 0xFFFFFFFF).",
      risk="safe", impact="moderate", recommended="recommended",
      admin=True,
      tags=["mmcss", "network", "throttling"]),

    # ── MMCSS SystemResponsiveness ───────────────────────────────
    T("perf-045", "Optimize MMCSS SystemResponsiveness",
      "Set MMCSS system responsiveness to minimum for gaming workloads.",
      actions=[
          ("reg", "HKLM",
           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
           "SystemResponsiveness", 10, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM",
           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
           "SystemResponsiveness"),
      ],
      why="SystemResponsiveness controls how much CPU is reserved for "
          "background tasks. Setting it to 10 reserves a small amount for "
          "system services while giving most CPU to foreground games.",
      changes="Sets MMCSS SystemResponsiveness to 10 for gaming performance.",
      risk="safe", impact="moderate", recommended="recommended",
      admin=True,
      tags=["mmcss", "responsiveness", "cpu"]),

    # ── Background Maintenance ───────────────────────────────────
    T("perf-046", "Disable Background Maintenance",
      "Disable scheduled maintenance tasks that consume disk and CPU "
      "resources during gaming sessions.",
      actions=[
          ("cmd",
           'schtasks /Change /TN "\\Microsoft\\Windows\\Maintenance\\WinSAT" /Disable'),
      ],
      revert=[
          ("cmd",
           'schtasks /Change /TN "\\Microsoft\\Windows\\Maintenance\\WinSAT" /Enable'),
      ],
      why="Windows runs scheduled maintenance tasks (disk assessment, "
          "optimization) that can cause disk I/O spikes and CPU usage "
          "during gaming.",
      changes="Disables background maintenance scheduled tasks.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["maintenance", "scheduled", "background"]),

    # ── Context Switch Rate ──── REMOVED (duplicate of perf-001) ──
    # ── Interrupt Steering ──── REMOVED (causes interrupt hotspots) ──

    # ── IRPStackSize ─────────────────────────────────────────────
    T("perf-049", "Set IRPStackSize",
      "Increase the I/O Request Packet stack size for better network "
      "throughput in LAN gaming scenarios.",
      actions=[
          ("reg", "HKLM",
           r"SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters",
           "IRPStackSize", 32, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM",
           r"SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters",
           "IRPStackSize"),
      ],
      why="IRPStackSize controls the number of stack locations for I/O request "
          "packets in the SMB server. Increasing it from the default (15) to 32 "
          "improves LAN file sharing and network game performance.",
      changes="Sets IRPStackSize to 32 for improved network throughput.",
      risk="low", impact="low", recommended="optional",
      admin=True,
      tags=["irp", "network", "lan", "smb"]),

    # ── Network Throttling ──── REMOVED (was setting default value=10) ──

    # ── Fullscreen Exclusive (DirectX) ───────────────────────────
    T("perf-051", "Enable FSE (Fullscreen Exclusive)",
      "Enable DirectX fullscreen exclusive mode for better gaming "
      "performance and lower latency.",
      actions=[
          ("reg", "HKCU",
           r"SOFTWARE\Microsoft\DirectX\UserGpuPreferences",
           "DirectXUserGlobalSettings",
           "DisableFullscreenOptimizations=1", "STRING"),
      ],
      revert=[
          ("regdel", "HKCU",
           r"SOFTWARE\Microsoft\DirectX\UserGpuPreferences",
           "DirectXUserGlobalSettings"),
      ],
      why="Fullscreen Exclusive mode bypasses the Desktop Window Manager, "
          "reducing input latency and giving the game direct control over "
          "the display output.",
      changes="Enables DirectX fullscreen exclusive mode.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["fse", "fullscreen", "directx", "display"]),

    # ── DPC Latency Logging ──── REMOVED (undocumented registry hack) ──

    # ── Non-Paged Pool ───────────────────────────────────────────
    T("perf-053", "Optimize Non-Paged Pool Size",
      "Let Windows auto-manage non-paged pool size for optimal memory "
      "allocation on gaming systems.",
      actions=[
          ("reg", "HKLM",
           r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management",
           "NonPagedPoolSize", 0, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM",
           r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management",
           "NonPagedPoolSize"),
      ],
      why="Setting NonPagedPoolSize to 0 tells Windows to auto-manage the "
          "non-paged pool, which is optimal for most gaming systems. A fixed "
          "value can waste memory or cause kernel memory pressure.",
      changes="Sets NonPagedPoolSize to 0 for automatic management.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["memory", "pool", "kernel", "npp"]),

    # ── Game DVR Recording (Policy) ──────────────────────────────
    T("perf-054", "Disable Game DVR Recording (Policy)",
      "Disable Game DVR background recording via Group Policy to free up "
      "system resources.",
      actions=[
          ("reg", "HKLM",
           r"SOFTWARE\Policies\Microsoft\Windows\GameDVR",
           "AllowGameDVR", 0, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM",
           r"SOFTWARE\Policies\Microsoft\Windows\GameDVR",
           "AllowGameDVR"),
      ],
      why="Game DVR background recording continuously captures gameplay, "
          "consuming CPU, GPU, disk, and memory resources. The Group Policy "
          "key enforces the disable system-wide.",
      changes="Disables Game DVR recording via Group Policy.",
      risk="safe", impact="moderate", recommended="recommended",
      admin=True,
      tags=["game", "dvr", "recording", "policy"]),

    # ── Thread Scheduling ────────────────────────────────────────
    T("perf-055", "Optimize Thread Scheduling",
      "Disable scheduler profiling overhead for lower context switch "
      "latency in gaming workloads.",
      actions=[
          ("reg", "HKLM",
           r"SYSTEM\CurrentControlSet\Control\PriorityControl",
           "SchedulingProfilingType", 0, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM",
           r"SYSTEM\CurrentControlSet\Control\PriorityControl",
           "SchedulingProfilingType"),
      ],
      why="Scheduler profiling adds overhead to every context switch by "
          "collecting scheduling statistics. Disabling it reduces latency "
          "in the critical thread scheduling path.",
      changes="Disables scheduler profiling overhead.",
      risk="safe", impact="low", recommended="optional",
      admin=True,
      tags=["scheduler", "thread", "profiling", "latency"]),
])
