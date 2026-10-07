"""Category: Performance — genuine gaming / FPS performance optimizations.

Every tweak here is unique to this module (no overlap with cpu, ram, system,
network, services, or gaming modules).
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Performance", win_default="10,11")
CATEGORY = "Performance"

TWEAKS = validate_module("performance", [
    # ── Timer Resolution (single optional diagnostic) ──────────────
    # Merged from perf-001 / power-017 / fpsb-018 (all three wrote the same
    # GlobalTimerResolutionRequests=1 flag) and cpu:timer_resolution (which
    # forced GlobalTimerResolution=1 + TimerResolution=5000). None of them
    # reliably "reduced input latency", so this is now one honest optional
    # card that says what the flag actually does.
    T("perf-001", "Timer Resolution Diagnostic",
      "One optional timer card. Permits applications to request a higher "
      "timer resolution; it does not force 0.5 ms. Games already request "
      "the resolution they need, so this rarely changes anything.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel",
           "GlobalTimerResolutionRequests", 1, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel",
           "GlobalTimerResolutionRequests", 0, "DWORD"),
      ],
      why="Merged four overlapping timer tweaks into this single diagnostic. "
          "The flag merely lets applications obtain finer timers on request; "
          "it never forces 0.5 ms resolution and carries no guaranteed "
          "latency benefit. Keep it optional and benchmark before/after.",
      changes="Sets GlobalTimerResolutionRequests=1 (permits high-resolution "
              "timer requests; it does not force one).",
      risk="low", impact="low", recommended="optional",
      admin=True,
      warn="Does not force a faster timer - behavior varies by CPU and "
           "Windows build, benchmark before/after.",
      tags=["timer", "resolution", "latency", "diagnostic"],
      updated="2026-09-27"),

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
      admin=True,
      tags=["update", "network", "background"]),

    # ── Visual Effects ─────────────────────────────────────────────

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

    # ── Interrupt Moderation (adapter-specific, experimental) ──────
    # Replaces the old netsh autotune/chimney pair (which never touched
    # interrupt moderation at all) and the blanket regall write: the netadp
    # engine op only touches active physical adapters that actually expose the
    # Interrupt Moderation property, using driver-valid values only.
    T("perf-013", "Disable NIC Interrupt Moderation",
      "Disables Interrupt Moderation on each active physical network "
      "adapter that exposes the setting (detect-first, revert-safe).",
      actions=[
          ("netadp", "interrupt_moderation"),
      ],
      revert=[
          ("netadp", "interrupt_moderation_revert"),
      ],
      why="Interrupt moderation batches interrupts to save CPU, adding a "
          "little latency per packet. On Realtek adapters under heavy "
          "packet load that can show as input/network jitter, but results "
          "are hardware-specific - so this is experimental and you should "
          "benchmark before/after.",
      changes="Disables Interrupt Moderation only where the adapter exposes "
              "it, with driver-valid values (global netsh tuning untouched).",
      risk="low", impact="low", recommended="experimental",
      admin=True,
      warn="Adapter-specific and experimentally beneficial - some drivers "
           "raise CPU use with moderation off; benchmark before/after.",
      tags=["network", "interrupt", "moderation", "latency", "experimental", "adapter"],
      updated="2026-09-27"),

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
      admin=True,
      tags=["interrupt", "irq", "latency"]),

    # ── MSI Mode ───────────────────────────────────────────────────

    # ── Turbo Boost ────────────────────────────────────────────────
    #  perf-026 / perf-032 / perf-044 / perf-045 removed as exact duplicates
    #  (power-021 / adv-006 / net-009 / pre-006 ship as the canonical cards);
    #  perf-030-031 / perf-033-043 / perf-046-055 remain below.
    # ═══════════════════════════════════════════════════════════════

    # ── Power Throttling ──────────────────────────────────────────

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

    # ── Performance Decrease Policy ──────────────────────────────
    T("perf-034", "Set Processor Performance Decrease Policy",
      "Configure aggressive processor performance decrease for faster "
      "frequency scaling under gaming loads.",
      actions=[
          ("power", "perf_decrease_policy", 2, "AC"),
      ],
      revert=[
          ("power", "perf_decrease_policy", 0, "AC"),
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
      admin=True,
      tags=["memory", "page", "combining"]),

    # ── MMCSS Network Throttling ─────────────────────────────────

    # ── MMCSS SystemResponsiveness ───────────────────────────────

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

    # ── Fullscreen Exclusive (DirectX) ──── MERGED INTO wgr-013 ──

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
