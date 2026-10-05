"""Category: CPU — scheduling tweaks plus a hardware-filtered power card set.

Two groups live here:

1. Scheduling tweaks (registry), shared by every CPU.
2. Power-management cards (``power`` actions) that are filtered by the manual
   CPU-family pick in the CPU page.  Untagged cards are *shared* and show for
   every family; cards carrying ``when.cpu_family`` only show for the families
   they list, so an AMD-only control can never be offered on an Intel chip.

Every power card sets ``power_strict=True``.  That makes the executor verify
the target GUID is actually exposed by the active power plan before writing,
and fail loudly when it is not, instead of reporting a successful change that
never happened.  A card can therefore dim to "unsupported here" rather than
claim to have applied.
"""

from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("CPU", win_default="7,8,10,11")

CATEGORY = "CPU"

# ── Shared registry paths ───────────────────────────────────────────────
_PRIORITY_CONTROL = r"SYSTEM\CurrentControlSet\Control\PriorityControl"
_GAMES_TASKS = (
    r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia"
    r"\SystemProfile\Tasks\Games"
)

# ── CPU family tags used by when.cpu_family ─────────────────────────────
AMD_ALL = ("amd_am4", "amd_am4_x3d", "amd_am5", "amd_am5_x3d")
INTEL_LEGACY = ("intel_legacy",)
INTEL_HYBRID = ("intel_hybrid", "intel_core_ultra")

_PLAN_CONFLICT = (
    "The Maximum Power Plan pins this value itself, so re-activating that plan "
    "will silently undo this card. Change one or the other, not both."
)

TWEAKS = validate_module("cpu", [

    # ── 1) Foreground Priority Boost ────────────────────────────────────
    # Sole owner of Win32PrioritySeparation for this category.  The former
    # "foreground_priority" card wrote the identical value and was removed.

    T(
        "process_priority", "Foreground Priority Boost",
        "Gives the foreground app more CPU share than background services "
        "when both want the processor.",
        actions=[
            ("reg", "HKLM", _PRIORITY_CONTROL, "Win32PrioritySeparation", 26, "DWORD"),
        ],
        revert=[("regdel", "HKLM", _PRIORITY_CONTROL, "Win32PrioritySeparation")],
        sub_category="gaming",
        risk="low", impact="moderate", recommended="recommended",
        admin=True,
        when={"cpu_vendor": ["amd", "intel"]},
        why="26 favours foreground work over background services during contention.",
        changes="HKLM\\...\\PriorityControl\\Win32PrioritySeparation = 26",
    ),

    # ── 2) MMCSS Game Priority ──────────────────────────────────────────
    # Sole owner of the MMCSS Games task for this category.  The former
    # "game_process_priority" card wrote the identical value and was removed.

    T(
        "mmcss_game_priority", "MMCSS Game Priority",
        "Marks the game as a high-priority Multimedia Class Scheduler task "
        "so audio and video threads get dedicated CPU time.",
        actions=[
            ("reg", "HKLM", _GAMES_TASKS, "GPU Priority", 8, "DWORD"),
            ("reg", "HKLM", _GAMES_TASKS, "Priority", 6, "DWORD"),
            ("reg", "HKLM", _GAMES_TASKS, "Scheduling Category", "High", "STRING"),
        ],
        revert=[
            ("regdel", "HKLM", _GAMES_TASKS, "GPU Priority"),
            ("regdel", "HKLM", _GAMES_TASKS, "Priority"),
            ("regdel", "HKLM", _GAMES_TASKS, "Scheduling Category"),
        ],
        sub_category="gaming",
        risk="low", impact="moderate", recommended="recommended",
        admin=True,
        why="MMCSS 'Games' category reserves throughput for multimedia threads.",
        changes="HKLM\\...\\Multimedia\\SystemProfile\\Tasks\\Games",
    ),

    # ── 3) Shared power cards (every family) ────────────────────────────

    T(
        "cpu_max_state_100", "Maximum Processor State",
        "Lets the processor use its full advertised frequency instead of being "
        "held below the maximum by the power plan.",
        actions=[("power", "processor_max", 100, "AC")],
        revert=[("power", "processor_max", 0, "AC")],
        sub_category="power",
        risk="low", impact="low", recommended="recommended",
        admin=True, power_strict=True,
        why="AC-only: 100 leaves the hardware frequency ceiling in charge.",
        changes="Processor power management / Maximum processor state = 100% (AC)",
    ),

    T(
        "cpu_min_state_100", "Minimum Processor State",
        "Holds cores at full clock while the system is busy, trading idle "
        "power and heat for a floor under clock speed.",
        actions=[("power", "processor_min", 100, "AC")],
        revert=[("power", "processor_min", 5, "AC")],
        sub_category="power",
        risk="advanced", impact="moderate", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        why="A 100% floor removes downclocking entirely while work is queued.",
        changes="Processor power management / Minimum processor state = 100% (AC)",
    ),

    T(
        "cpu_epp_performance", "Energy Performance Preference",
        "Biases the hardware scheduler toward performance over energy saving "
        "when it picks between equally valid cores.",
        actions=[("power", "epp", 0, "AC")],
        revert=[("power", "epp", 50, "AC")],
        sub_category="power",
        risk="advanced", impact="moderate", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        why="A 0 bias tells the scheduler not to conserve energy on its own.",
        changes="Processor power management / Energy performance preference = 0 (AC)",
    ),

    T(
        "cpu_boost_mode_aggressive", "Processor Boost Mode",
        "Sets the hardware turbo behaviour to aggressive, letting the chip "
        "exceed its sustained base clock for short bursts.",
        actions=[("power", "boost_mode", 2, "AC")],
        revert=[("power", "boost_mode", 1, "AC")],
        sub_category="power",
        risk="advanced", impact="moderate", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        # 0 Disabled, 1 Enabled, 2 Aggressive, 3 Efficient Enabled,
        # 4 Efficient Aggressive, 5/6 ...At Guaranteed.
        why="Aggressive mode raises the turbo time/thermal budget, not the cap.",
        changes="Processor power management / Processor performance boost mode = 2 (AC)",
    ),

    T(
        "cpu_idle_disable", "Disable Processor Idle States",
        "Stops the processor dropping into its low-power C-states, keeping "
        "cores clocked up at the cost of idle power and heat.",
        actions=[("power", "idle_disable", 1, "AC")],
        revert=[("power", "idle_disable", 0, "AC")],
        sub_category="power",
        risk="advanced", impact="moderate", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        # This is an enum: 0 = Enable idle, 1 = Disable idle. The retired card
        # wrote 0 while claiming to disable idle states, i.e. the exact
        # opposite of what it promised.
        why="A hidden setting; enum 1 is Disable idle, 0 is Enable idle.",
        changes="Processor power management / Processor idle disable = Disable idle (AC)",
        updated="2026-09-29",
    ),

    # ── 3b) Intel hybrid (P-core / E-core) scheduling ───────────────────
    # Only offered on hybrid families. SchedulingPolicy is the OS-level
    # constraint on where long-running threads are placed; Automatic (5) is
    # what the OS picks by default, so both cards revert to it.

    T(
        "cpu_hybrid_sched_performant", "Heterogeneous Scheduling (Performance)",
        "Tells Windows to place long-running threads on the performance cores "
        "rather than letting it choose between P-cores and E-cores.",
        actions=[("power", "sched_policy", 1, "AC")],
        revert=[("power", "sched_policy", 5, "AC")],
        sub_category="power",
        risk="advanced", impact="moderate", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        when={"cpu_family": list(INTEL_HYBRID)},
        why="0 All, 1 Performant, 2 Prefer performant, 3 Efficient, "
            "4 Prefer efficient, 5 Automatic. Reverting to 5 returns the "
            "decision to the OS.",
        changes="Processor power management / Heterogeneous thread scheduling policy = 1 (AC)",
        added="2026-09-29",
    ),

    T(
        "cpu_hybrid_short_sched_performant", "Short-Thread Scheduling (Performance)",
        "Applies the same performance-core preference to short-running "
        "threads, which the long-thread policy deliberately leaves alone.",
        actions=[("power", "short_sched_policy", 1, "AC")],
        revert=[("power", "short_sched_policy", 2, "AC")],
        sub_category="power",
        risk="advanced", impact="moderate", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        when={"cpu_family": list(INTEL_HYBRID)},
        why="This is a separate policy from the long-thread one; forcing both "
            "to performance cores is what removes the hybrid scheduler's "
            "ability to spread work.",
        changes="Processor power management / Heterogeneous short running thread scheduling policy = 1 (AC)",
        added="2026-09-29",
    ),

    # ── 4) AMD-only power cards ─────────────────────────────────────────
    # Core parking is never offered on Intel, which is why the old universal
    # "core_parking_disable" card was removed rather than filtered.

    T(
        "cpu_amd_unpark_all", "Minimum Unparked Cores (100%)",
        "Asks the scheduler to keep every core out of the parked state, so "
        "spreading work does not stall on a waking core.",
        actions=[("power", "parking_min", 100, "AC")],
        revert=[("power", "parking_min", 0, "AC")],
        sub_category="power",
        risk="advanced", impact="moderate", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        when={"cpu_family": list(AMD_ALL)},
        why="Higher minimums keep more cores ready; the setting is a request, "
            "not a guarantee, and may be ignored by the driver.",
        changes="Processor power management / Minimum unparked cores = 100% (AC)",
    ),

    T(
        "cpu_amd_increase_policy", "Performance Increase Policy (AMD)",
        "Chooses which hardware performance boost signal is allowed to raise "
        "the clock, instead of letting the CPU decide.",
        actions=[("power", "perf_increase_policy", 3, "AC")],
        revert=[("power", "perf_increase_policy", 2, "AC")],
        sub_category="power",
        risk="advanced", impact="low", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        when={"cpu_family": list(AMD_ALL)},
        # 0 Ideal, 1 Single, 2 Rocket, 3 IdealAggressive. The active Maximum
        # Power Plan already sits on 2, so 3 is the first index that changes
        # anything - proposing 2 would be a guaranteed no-op there.
        why="3 is IdealAggressive; the default plan value is 2 (Rocket).",
        changes="Processor power management / Performance increase policy = 3 (AC)",
        updated="2026-09-29",
    ),

    T(
        "cpu_amd_decrease_policy", "Performance Decrease Policy (AMD)",
        "Chooses which signal is allowed to drop the clock back down, which "
        "changes how quickly the chip settles after a burst.",
        actions=[("power", "perf_decrease_policy", 2, "AC")],
        revert=[("power", "perf_decrease_policy", 1, "AC")],
        sub_category="power",
        risk="advanced", impact="low", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        when={"cpu_family": list(AMD_ALL)},
        # 0 Ideal, 1 Single, 2 Rocket. The active plan already sits on 1.
        why="2 (Rocket) lets the clock drop fastest once work subsides.",
        changes="Processor power management / Performance decrease policy = 2 (AC)",
        updated="2026-09-29",
    ),

    T(
        "cpu_amd_increase_threshold", "Performance Increase Threshold (AMD)",
        "How far utilisation must fall before the clock steps down.  A low "
        "value makes the boost policy respond sooner.",
        actions=[("power", "perf_increase_threshold", 10, "AC")],
        revert=[("power", "perf_increase_threshold", 10, "AC")],
        sub_category="power",
        risk="advanced", impact="low", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        when={"cpu_family": list(AMD_ALL)},
        why="Expressed as a percentage; the active plan already sets 10 on "
            "this machine, so this card is a no-op until that changes.",
        changes="Processor power management / Performance increase threshold = 10% (AC)",
    ),

    T(
        "cpu_amd_decrease_threshold", "Performance Decrease Threshold (AMD)",
        "How far utilisation must rise before the clock steps up.  A low "
        "value makes the boost policy respond sooner.",
        actions=[("power", "perf_decrease_threshold", 10, "AC")],
        revert=[("power", "perf_decrease_threshold", 10, "AC")],
        sub_category="power",
        risk="advanced", impact="low", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        when={"cpu_family": list(AMD_ALL)},
        why="Expressed as a percentage; the active plan already sets 10 on "
            "this machine, so this card is a no-op until that changes.",
        changes="Processor power management / Performance decrease threshold = 10% (AC)",
    ),

    # ── 5) Intel legacy (non-hybrid) power cards ────────────────────────
    # No parking control here: the old universal parking card was removed
    # because parking is an AMD-side behaviour, not an Intel one.

    T(
        "cpu_intel_increase_policy", "Performance Increase Policy (Intel)",
        "Chooses which hardware performance boost signal is allowed to raise "
        "the clock, instead of letting the CPU decide.",
        actions=[("power", "perf_increase_policy", 3, "AC")],
        revert=[("power", "perf_increase_policy", 2, "AC")],
        sub_category="power",
        risk="advanced", impact="low", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        when={"cpu_family": list(INTEL_LEGACY)},
        why="3 is IdealAggressive; the default plan value is 2 (Rocket).",
        changes="Processor power management / Performance increase policy = 3 (AC)",
        updated="2026-09-29",
    ),

    T(
        "cpu_intel_decrease_policy", "Performance Decrease Policy (Intel)",
        "Chooses which signal is allowed to drop the clock back down, which "
        "changes how quickly the chip settles after a burst.",
        actions=[("power", "perf_decrease_policy", 2, "AC")],
        revert=[("power", "perf_decrease_policy", 1, "AC")],
        sub_category="power",
        risk="advanced", impact="low", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        when={"cpu_family": list(INTEL_LEGACY)},
        why="2 (Rocket) lets the clock drop fastest once work subsides.",
        changes="Processor power management / Performance decrease policy = 2 (AC)",
        updated="2026-09-29",
    ),

    T(
        "cpu_intel_increase_threshold", "Performance Increase Threshold (Intel)",
        "How far utilisation must fall before the clock steps down.  A low "
        "value makes the boost policy respond sooner.",
        actions=[("power", "perf_increase_threshold", 10, "AC")],
        revert=[("power", "perf_increase_threshold", 10, "AC")],
        sub_category="power",
        risk="advanced", impact="low", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        when={"cpu_family": list(INTEL_LEGACY)},
        why="Expressed as a percentage; the active plan already sets 10 on "
            "this machine, so this card is a no-op until that changes.",
        changes="Processor power management / Performance increase threshold = 10% (AC)",
    ),

    T(
        "cpu_intel_decrease_threshold", "Performance Decrease Threshold (Intel)",
        "How far utilisation must rise before the clock steps up.  A low "
        "value makes the boost policy respond sooner.",
        actions=[("power", "perf_decrease_threshold", 10, "AC")],
        revert=[("power", "perf_decrease_threshold", 10, "AC")],
        sub_category="power",
        risk="advanced", impact="low", recommended="optional",
        admin=True, power_strict=True, warn=_PLAN_CONFLICT,
        when={"cpu_family": list(INTEL_LEGACY)},
        why="Expressed as a percentage; the active plan already sets 10 on "
            "this machine, so this card is a no-op until that changes.",
        changes="Processor power management / Performance decrease threshold = 10% (AC)",
    ),

])
