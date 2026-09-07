"""Category: CPU — the CPU & Scheduling tweak set, verbatim.

These are exactly the tweaks defined by the Reaper Performance Suite
"CPU & Scheduling" group (verified against the installed exe).  Ids,
names, descriptions, registry/powercfg/bcdedit commands and warnings are
reproduced as-is.  Nothing has been added beyond this set.
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
_KERNEL = r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel"
_POWER_THROTTLING = r"SYSTEM\CurrentControlSet\Control\Power\PowerThrottling"

TWEAKS = validate_module("cpu", [

    # ── 1) Foreground Priority Boost ────────────────────────────────

    T(
        "process_priority", "Foreground Priority Boost",
        "Increases foreground process priority boost for smoother gaming.",
        actions=[
            ("reg", "HKLM", _PRIORITY_CONTROL,
             "Win32PrioritySeparation", 26, "DWORD"),
        ],
        revert=[
            ("regdel", "HKLM", _PRIORITY_CONTROL, "Win32PrioritySeparation"),
        ],
        why="Raises the foreground boost so the active game gets more CPU "
            "time relative to background processes.",
        changes="Sets Win32PrioritySeparation to 26.",
        risk="low", impact="moderate", recommended="recommended",
        admin=True, confirm=True,
        sub_category="gaming",
        tags=["priority", "foreground", "scheduler", "restart"],
    ),

    # ── 2) MMCSS Game Priority Boost ────────────────────────────────

    T(
        "mmcss_game_priority", "MMCSS Game Priority Boost",
        "Raises the multimedia scheduler's CPU/GPU priority for the "
        "foreground game task.",
        actions=[
            ("reg", "HKLM", _GAMES_TASKS, "GPU Priority", 8, "DWORD"),
            ("reg", "HKLM", _GAMES_TASKS, "Priority", 6, "DWORD"),
            ("reg", "HKLM", _GAMES_TASKS, "Scheduling Category", "High", "STRING"),
        ],
        revert=[
            ("regdel", "HKLM", _GAMES_TASKS, "GPU Priority"),
            ("reg", "HKLM", _GAMES_TASKS, "Priority", 2, "DWORD"),
            ("reg", "HKLM", _GAMES_TASKS, "Scheduling Category", "Medium", "STRING"),
        ],
        why="The MMCSS Games task class controls how the multimedia "
            "scheduler prioritizes the foreground game's threads.",
        changes="Sets the Games task to GPU Priority 8, Priority 6, High.",
        risk="low", impact="high", recommended="recommended",
        admin=True, confirm=True,
        sub_category="gaming",
        tags=["mmcss", "games", "priority", "scheduler", "restart"],
    ),

    # ── 3) CPU Core Parking Disable ─────────────────────────────────

    T(
        "core_parking_disable", "CPU Core Parking Disable",
        "Keeps all CPU cores active instead of letting Windows park "
        "idle cores under light load.",
        actions=[
            ("cmd", "powercfg /setacvalueindex scheme_current sub_processor "
                    "0cc5b647-c1df-4637-891a-dec35c318583 100"),
            ("cmd", "powercfg /setactive scheme_current"),
        ],
        revert=[
            ("cmd", "powercfg /setacvalueindex scheme_current sub_processor "
                    "0cc5b647-c1df-4637-891a-dec35c318583 0"),
            ("cmd", "powercfg /setactive scheme_current"),
        ],
        why="Prevents Windows from parking cores under light load so all "
            "logical processors stay ready to take threads. Does not modify "
            "the core-parking maximum cap.",
        changes="Sets the core-parking min cores value to 100 on AC.",
        risk="advanced", impact="moderate", recommended="advanced",
        admin=True, confirm=True,
        warn="Aggressive — can raise idle power draw and temperatures. "
             "Lets Windows/firmware manage topology by default instead.",
        sub_category="advanced",
        tags=["core", "parking", "power", "powercfg"],
    ),

    # ── 4) Timer Resolution ─────────────────────────────────────────

    T(
        "timer_resolution", "Timer Resolution",
        "Sets system timer to 0.5ms for reduced input lag and smoother "
        "frame pacing.",
        actions=[
            ("reg", "HKLM", _KERNEL, "GlobalTimerResolution", 1, "DWORD"),
            ("reg", "HKLM", _KERNEL, "TimerResolution", 5000, "DWORD"),
        ],
        revert=[
            ("regdel", "HKLM", _KERNEL, "GlobalTimerResolution"),
            ("regdel", "HKLM", _KERNEL, "TimerResolution"),
        ],
        why="A faster global timer resolution lets games and input be "
            "serviced on a tighter schedule, cutting input lag.",
        changes="Sets GlobalTimerResolution=1 and TimerResolution=5000.",
        risk="low", impact="high", recommended="experimental",
        admin=True, confirm=True,
        warn="Timer resolution behaviors vary by CPU and Windows config — "
             "benchmark before/after.",
        sub_category="gaming",
        tags=["timer", "resolution", "latency", "experimental"],
    ),

    # ── 5) Disable Power Throttling ─────────────────────────────────

    T(
        "power_throttling_off", "Disable Power Throttling",
        "Stops Windows power-throttling eligible background processes.",
        actions=[
            ("reg", "HKLM", _POWER_THROTTLING, "PowerThrottlingOff", 1, "DWORD"),
        ],
        revert=[
            ("reg", "HKLM", _POWER_THROTTLING, "PowerThrottlingOff", 0, "DWORD"),
        ],
        why="Prevents Windows from duty-cycling background threads to "
            "save energy, avoiding micro-stutter in games.",
        changes="Sets PowerThrottlingOff to 1.",
        risk="advanced", impact="moderate", recommended="advanced",
        admin=True, confirm=True,
        sub_category="advanced",
        tags=["throttling", "power", "background"],
    ),

    # ── 6) Disable Processor Idle States ────────────────────────────

    T(
        "processor_idle_disable", "Disable Processor Idle States",
        "Aggressive desktop-only tuning; prevents the active AC power "
        "plan from entering processor idle states.",
        actions=[
            ("cmd", "powercfg /setacvalueindex scheme_current sub_processor "
                    "5d76a2ca-e8c0-402f-a133-2158492d58ad 0"),
            ("cmd", "powercfg /setactive scheme_current"),
        ],
        revert=[
            ("cmd", "powercfg /setacvalueindex scheme_current sub_processor "
                    "5d76a2ca-e8c0-402f-a133-2158492d58ad 1"),
            ("cmd", "powercfg /setactive scheme_current"),
        ],
        why="Keeps the CPU out of idle processor states so wake-up latency "
            "from idle is removed while the AC plan is active.",
        changes="Sets the processor-idle-disable value to 0 on AC.",
        risk="advanced", impact="high", recommended="experimental",
        admin=True, confirm=True,
        warn="Very aggressive — can raise idle temps/power draw substantially.",
        when={"laptop": False},
        sub_category="advanced",
        tags=["idle", "cstate", "power", "powercfg", "experimental"],
    ),

    # ── 7) Foreground CPU Scheduling Profile ────────────────────────

    T(
        "foreground_priority", "Foreground CPU Scheduling Profile",
        "Tunes Win32 foreground scheduling toward games/interactive "
        "workloads.",
        actions=[
            ("reg", "HKLM", _PRIORITY_CONTROL,
             "Win32PrioritySeparation", 26, "DWORD"),
        ],
        revert=[
            ("regdel", "HKLM", _PRIORITY_CONTROL, "Win32PrioritySeparation"),
        ],
        why="Biases the Windows scheduler's foreground boost toward "
            "interactive workloads.",
        changes="Sets Win32PrioritySeparation to 26.",
        risk="advanced", impact="high", recommended="advanced",
        admin=True, confirm=True,
        sub_category="advanced",
        tags=["priority", "foreground", "scheduler", "restart"],
    ),

    # ── 8) Game Process Priority Policy ────────────────────────────

    T(
        "game_process_priority", "Game Process Priority Policy",
        "Enables the Windows multimedia \"Games\" task profile for "
        "foreground-oriented scheduling.",
        actions=[
            ("reg", "HKLM", _GAMES_TASKS, "GPU Priority", 8, "DWORD"),
            ("reg", "HKLM", _GAMES_TASKS, "Priority", 6, "DWORD"),
            ("reg", "HKLM", _GAMES_TASKS, "Scheduling Category", "High", "STRING"),
        ],
        revert=[
            ("regdel", "HKLM", _GAMES_TASKS, "GPU Priority"),
            ("reg", "HKLM", _GAMES_TASKS, "Priority", 2, "DWORD"),
            ("reg", "HKLM", _GAMES_TASKS, "Scheduling Category", "Medium", "STRING"),
        ],
        why="Activates the multimedia scheduler's Games task profile so "
            "game threads are scheduled with foreground preference.",
        changes="Sets the Games task to GPU Priority 8, Priority 6, High.",
        risk="advanced", impact="high", recommended="advanced",
        admin=True, confirm=True,
        sub_category="advanced",
        tags=["mmcss", "games", "priority", "scheduler", "restart"],
    ),
])