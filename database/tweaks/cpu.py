"""Category: CPU — safe, hardware-aware processor optimizations.

Every tweak in this module is designed to work WITH the CPU's own dynamic
power management, not against it.  Modern AMD Precision Boost and Intel
Speed Shift already handle clock scaling, idle states, and boost behavior
far better than any static registry tweak.

These optimizations focus on:
  - Configuring Windows to get out of the CPU's way
  - Reducing background CPU overhead (services, telemetry)
  - Optimizing MMCSS scheduling for games
  - Appropriate power-plan settings per form factor (desktop/laptop)
  - Proper AC vs battery behavior

Nothing here forces a permanent clock speed, disables C-states, or fights
the CPU's own boost algorithm.
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("CPU", win_default="7,8,10,11")

CATEGORY = "CPU"

# ── Shared warnings ──────────────────────────────────────────────────
_CPU_SAFE_WARN = (
    "This tweak adjusts standard Windows power-management settings.  "
    "It does not override your CPU's own boost or idle behavior — it "
    "simply configures how Windows interacts with the processor.  "
    "All changes are reversible."
)

# ── Universal tweaks (all CPUs, desktop + laptop) ────────────────────

TWEAKS = validate_module("cpu", [

    # ── Power State (AC) ────────────────────────────────────────────

    T(
        "cpu-001", "Processor Minimum State 5% (AC)",
        "Set the minimum processor performance state to 5% on AC power.",
        actions=[("power", "processor_min", 5, "AC")],
        revert=[("power", "processor_min", 100, "AC")],
        why="A low minimum state lets the CPU idle at deep C-states when "
            "not under load, reducing heat and power draw.  The OS boosts "
            "to higher P-states on demand anyway, so there is no performance "
            "loss during gaming.",
        changes="Sets minimum processor state to 5% on AC.",
        risk="safe", impact="low", recommended="recommended",
        admin=True, confirm=True, warn=_CPU_SAFE_WARN,
        tags=["power", "idle", "ac", "processor"],
    ),

    T(
        "cpu-002", "Processor Maximum State 100% (AC)",
        "Allow the CPU to reach its full boost frequency on AC power.",
        actions=[("power", "processor_max", 100, "AC")],
        revert=[("power", "processor_max", 100, "AC")],
        why="Ensures the CPU is not artificially capped below its maximum "
            "boost clock during gaming.  The default is often already 100%, "
            "but some OEM power plans lower this.",
        changes="Sets maximum processor state to 100% on AC.",
        risk="safe", impact="moderate", recommended="recommended",
        admin=True, confirm=True, warn=_CPU_SAFE_WARN,
        tags=["power", "boost", "ac", "processor"],
    ),

    T(
        "cpu-003", "Active Cooling Policy (AC)",
        "Ramp up the fan before the CPU throttles on AC power.",
        actions=[
            ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR COOLINGPOLICY 1"),
            ("cmd", "powercfg /setactive SCHEME_CURRENT"),
        ],
        revert=[
            ("cmd", "powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR COOLINGPOLICY 0"),
            ("cmd", "powercfg /setactive SCHEME_CURRENT"),
        ],
        why="Active cooling increases fan speed under load instead of "
            "letting the CPU down-clock first.  This keeps boost clocks "
            "active longer during sustained gaming.",
        changes="Sets cooling policy to Active on AC.",
        risk="safe", impact="moderate", recommended="recommended",
        admin=True, confirm=True, warn=_CPU_SAFE_WARN,
        tags=["cooling", "fan", "thermal", "ac"],
    ),

    # ── Power State (Battery) ───────────────────────────────────────

    T(
        "cpu-004", "Processor Maximum State 80% (Battery)",
        "Cap the CPU at 80% on battery to extend play time.",
        actions=[("power", "processor_max", 80, "DC")],
        revert=[("power", "processor_max", 100, "DC")],
        why="On battery, capping the CPU slightly below maximum extends "
            "session time with minimal gaming impact.  Most games are "
            "GPU-bound, not CPU-bound.",
        changes="Sets maximum processor state to 80% on battery.",
        risk="safe", impact="low", recommended="optional",
        admin=True, confirm=True, warn=_CPU_SAFE_WARN,
        when={"laptop": True},
        tags=["power", "battery", "processor"],
    ),

    T(
        "cpu-005", "Passive Cooling Policy (Battery)",
        "Throttle the CPU before spinning the fan on battery.",
        actions=[
            ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR COOLINGPOLICY 0"),
            ("cmd", "powercfg /setactive SCHEME_CURRENT"),
        ],
        revert=[
            ("cmd", "powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_PROCESSOR COOLINGPOLICY 1"),
            ("cmd", "powercfg /setactive SCHEME_CURRENT"),
        ],
        why="Passive cooling saves battery and reduces noise when unplugged "
             "by throttling the CPU before ramping the fan.",
        changes="Sets cooling policy to Passive on battery.",
        risk="safe", impact="low", recommended="optional",
        admin=True, confirm=True, warn=_CPU_SAFE_WARN,
        when={"laptop": True},
        tags=["cooling", "fan", "thermal", "battery"],
    ),

    # ── Power Throttling ────────────────────────────────────────────

    T(
        "cpu-006", "Disable Windows Power Throttling",
        "Prevent Windows from duty-cycling background threads to save energy.",
        actions=[
            ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power\PowerThrottling",
             "PowerThrottlingOff", 1, "DWORD"),
        ],
        revert=[
            ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power\PowerThrottling",
             "PowerThrottlingOff", 0, "DWORD"),
        ],
        why="Power Throttling can duty-cycle game-related background threads "
            "(Discord, streaming software, overlays) causing micro-stutters. "
            "Disabling it on AC keeps all foreground work at full speed.",
        changes="Sets PowerThrottlingOff=1.",
        risk="low", impact="moderate", recommended="recommended",
        admin=True, confirm=True, warn=_CPU_SAFE_WARN,
        when={"laptop": False},
        tags=["throttling", "background", "power"],
    ),

    # ── MMCSS Scheduling ────────────────────────────────────────────

    T(
        "cpu-007", "MMCSS Gaming Class Optimization",
        "Configure the Multimedia Class Scheduler for optimal game thread scheduling.",
        actions=[
            ("reg", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
             "SystemResponsiveness", 10, "DWORD"),
            ("reg", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
             "NetworkThrottlingIndex", 0xffffffff, "DWORD"),
            ("reg", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games",
             "GPU Priority", 8, "DWORD"),
            ("reg", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games",
             "Priority", 6, "DWORD"),
            ("reg", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games",
             "Scheduling Category", "High", "STRING"),
        ],
        revert=[
            ("reg", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
             "SystemResponsiveness", 20, "DWORD"),
            ("reg", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
             "NetworkThrottlingIndex", 10, "DWORD"),
            ("regdel", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games",
             "GPU Priority"),
            ("regdel", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games",
             "Priority"),
            ("regdel", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games",
             "Scheduling Category"),
        ],
        why="MMCSS reserves CPU time for multimedia threads.  The default "
            "SystemResponsiveness of 20% reserves too much for background "
            "tasks.  Lowering it to 10% and boosting the Games class gives "
            "game threads higher scheduling priority.",
        changes="Sets SystemResponsiveness=10, Games class to High priority.",
        risk="low", impact="high", recommended="recommended",
        admin=True, confirm=True, warn=_CPU_SAFE_WARN,
        tags=["mmcss", "scheduler", "games", "priority"],
    ),

    T(
        "cpu-008", "MMCSS Latency Class Optimization",
        "Boost the Latency class for lower input latency.",
        actions=[
            ("reg", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Latency",
             "Priority", 6, "DWORD"),
            ("reg", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Latency",
             "Scheduling Category", "High", "STRING"),
        ],
        revert=[
            ("regdel", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Latency",
             "Priority"),
            ("regdel", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Latency",
             "Scheduling Category"),
        ],
        why="The MMCSS Latency class is used by audio engines and input "
            "devices.  Boosting its priority ensures low-latency audio and "
            "input processing during gaming.",
        changes="Sets Latency class to High priority.",
        risk="low", impact="moderate", recommended="recommended",
        admin=True, confirm=True, warn=_CPU_SAFE_WARN,
        tags=["mmcss", "latency", "input", "priority"],
    ),

    T(
        "cpu-009", "MMCSS Games I/O Priority",
        "Boost game file-read priority to reduce streaming stutter.",
        actions=[
            ("reg", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games",
             "SFIO Priority", "High", "STRING"),
        ],
        revert=[
            ("regdel", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games",
             "SFIO Priority"),
        ],
        why="A higher SFIO Priority lets game file reads bypass the disk "
            "scheduler's background queue, smoothing level loads and asset "
            "streaming in open-world games.",
        changes="Sets Games SFIO Priority to High.",
        risk="low", impact="moderate", recommended="recommended",
        admin=True, confirm=True, warn=_CPU_SAFE_WARN,
        tags=["mmcss", "games", "io", "disk"],
    ),

    # ── Background Services ─────────────────────────────────────────

    T(
        "cpu-010", "Disable Telemetry Service",
        "Disable the Connected User Experiences and Telemetry service.",
        actions=[("svc", "DiagTrack", "disabled"), ("svcstop", "DiagTrack")],
        revert=[("svc", "DiagTrack", "auto"), ("svcstart", "DiagTrack")],
        why="DiagTrack periodically uploads telemetry data in the background, "
            "consuming CPU cycles and disk I/O.  Disabling it frees resources "
            "for active applications.",
        changes="Disables and stops DiagTrack.",
        risk="safe", impact="low", recommended="recommended",
        admin=True,
        win="10,11",
        tags=["service", "telemetry", "background"],
    ),

    T(
        "cpu-011", "Disable Windows Search Indexer",
        "Disable the Windows Search indexing service.",
        actions=[("svc", "WSearch", "disabled"), ("svcstop", "WSearch")],
        revert=[("svc", "WSearch", "delayed"), ("svcstart", "WSearch")],
        why="The indexer periodically rescans files, consuming CPU and disk "
            "bandwidth.  Disabling it keeps resources available for gaming. "
            "Note: Windows search results will no longer be indexed.",
        changes="Disables and stops WSearch.",
        risk="safe", impact="low", recommended="optional",
        admin=True,
        tags=["service", "search", "indexer", "background"],
    ),

    T(
        "cpu-012", "Disable Program Compatibility Assistant",
        "Disable the PCA service that monitors application launches.",
        actions=[("svc", "PcaSvc", "disabled"), ("svcstop", "PcaSvc")],
        revert=[("svc", "PcaSvc", "auto"), ("svcstart", "PcaSvc")],
        why="PcaSvc hooks process starts to detect compatibility issues. "
            "On a gaming system this is unnecessary overhead.",
        changes="Disables and stops PcaSvc.",
        risk="low", impact="low", recommended="optional",
        admin=True,
        tags=["service", "compatibility", "background"],
    ),

    T(
        "cpu-013", "Disable Error Reporting Service",
        "Disable Windows Error Reporting to stop background crash processing.",
        actions=[("svc", "WerSvc", "disabled"), ("svcstop", "WerSvc")],
        revert=[("svc", "WerSvc", "manual"), ("svcstart", "WerSvc")],
        why="WerSvc spins up to capture and upload crash data, causing "
            "bursts of CPU and disk activity.  Disabling it removes that "
            "overhead.",
        changes="Disables and stops WerSvc.",
        risk="safe", impact="low", recommended="optional",
        admin=True,
        tags=["service", "error", "reporting", "background"],
    ),

    T(
        "cpu-014", "Disable WAP Push Service",
        "Disable the Device Management WAP Push background worker.",
        actions=[("svc", "dmwappushservice", "disabled"), ("svcstop", "dmwappushservice")],
        revert=[("svc", "dmwappushservice", "auto"), ("svcstart", "dmwappushservice")],
        why="dmwappushservice listens for WAP push notifications on every "
            "boot.  On a desktop gaming system this is unnecessary.",
        changes="Disables and stops dmwappushservice.",
        risk="safe", impact="low", recommended="optional",
        admin=True,
        win="10,11",
        tags=["service", "wap", "background"],
    ),

    # ── System Policies ─────────────────────────────────────────────

    T(
        "cpu-015", "Device Idle Policy: Performance",
        "Favor performance over power saving for device idle throttling.",
        actions=[
            ("reg", "HKLM",
             r"SOFTWARE\Policies\Microsoft\Windows\Power\DeviceIdlePolicy",
             "Performance", 1, "DWORD"),
        ],
        revert=[
            ("reg", "HKLM",
             r"SOFTWARE\Policies\Microsoft\Windows\Power\DeviceIdlePolicy",
             "Performance", 0, "DWORD"),
        ],
        why="Device idle throttling can slow I/O responses for storage and "
            "peripherals.  A performance policy keeps devices responsive.",
        changes="Sets DeviceIdlePolicy Performance=1.",
        risk="low", impact="moderate", recommended="optional",
        admin=True,
        tags=["idle", "device", "power"],
    ),

    T(
        "cpu-016", "Disable Away Mode",
        "Turn off Windows Away Mode to prevent unexpected throttling.",
        actions=[
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Session Manager\Power",
             "AwayModeEnabled", 0, "DWORD"),
        ],
        revert=[
            ("reg", "HKLM",
             r"SYSTEM\CurrentControlSet\Control\Session Manager\Power",
             "AwayModeEnabled", 1, "DWORD"),
        ],
        why="Away Mode can dim the display and throttle background work "
            "even when the PC is actively in use, causing performance dips.",
        changes="Sets AwayModeEnabled=0.",
        risk="safe", impact="low", recommended="recommended",
        admin=True,
        tags=["away", "power", "background"],
    ),

    # ── Guidance (no changes, just advice) ──────────────────────────

    T(
        "cpu-017", "CPU Boost Behavior: Let Windows Decide",
        "Guidance on processor boost behavior.",
        actions=[
            ("guidance",
             "Modern CPUs (AMD Precision Boost, Intel Turbo Boost / Speed "
             "Shift) dynamically manage their own clock speeds based on "
             "thermal headroom, power limits, and workload.  Letting "
             "Windows manage boost (default Balanced plan) gives the best "
             "balance of performance and thermals.  Forcing maximum boost "
             "permanently causes thermal throttling and WORSE sustained "
             "performance.  Keep boost enabled and let the CPU manage it."),
        ],
        revert=[("guidance", "No change to revert.")],
        why="CPU boost is managed by hardware-level algorithms that respond "
            "in microseconds.  No Windows setting can improve on this.",
        changes="Shows boost behavior guidance.",
        risk="safe", impact="low", recommended="recommended",
        tags=["boost", "guidance", "power"],
    ),

    T(
        "cpu-018", "CPU Idle States: Leave Them Alone",
        "Guidance on C-states and idle behavior.",
        actions=[
            ("guidance",
             "C-states (idle states) let the CPU save power and reduce heat "
             "when not under load.  Disabling C-states forces the CPU to "
             "run at full power even when idle, generating excess heat that "
             "causes thermal throttling during gaming.  The CPU wakes from "
             "C-states in microseconds — too fast to affect FPS.  Leave "
             "C-states enabled and let the CPU manage them."),
        ],
        revert=[("guidance", "No change to revert.")],
        why="Disabling C-states is one of the most common causes of FPS "
            "drops in optimization tools.  The CPU needs idle time to cool "
            "between boost bursts.",
        changes="Shows C-state guidance.",
        risk="safe", impact="low", recommended="recommended",
        tags=["cstate", "idle", "guidance", "power"],
    ),

    T(
        "cpu-019", "CPU Clock Speed: Don't Force It",
        "Guidance on processor frequency management.",
        actions=[
            ("guidance",
             "Locking the CPU to a fixed frequency prevents it from boosting "
             "higher when needed and idling lower when not.  This wastes "
             "power, generates heat, and reduces peak performance.  Modern "
             "CPUs boost well above their base clock — let them.  The "
             "only safe frequency setting is ensuring the maximum state "
             "is 100% on AC power."),
        ],
        revert=[("guidance", "No change to revert.")],
        why="Forced clock speeds fight the CPU's own power management and "
            "cause more harm than good.",
        changes="Shows clock speed guidance.",
        risk="safe", impact="low", recommended="recommended",
        tags=["clock", "frequency", "guidance"],
    ),
])
