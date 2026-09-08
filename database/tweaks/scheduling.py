"""Category: Scheduling — safe CPU scheduling and priority optimizations.

These tweaks configure how Windows schedules threads and handles interrupts.
None of them fight the CPU's own power management or force extreme behavior.
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Scheduling", win_default="7,8,10,11")
CATEGORY = "Scheduling"

TWEAKS = validate_module("scheduling", [

    # ── Interrupt Handling ───────────────────────────────────────────

    T(
        "sched-001", "Enable x2APIC",
        "Enable the extended interrupt controller for better multicore scaling.",
        actions=[("cmd", "bcdedit /set x2apicpolicy enable")],
        revert=[("cmd", "bcdedit /deletevalue x2apicpolicy")],
        why="x2APIC scales interrupt handling across many logical processors, "
            "reducing APIC contention on systems with 8+ cores.",
        changes="Sets x2apicpolicy to enable.",
        risk="moderate", impact="low", recommended="optional",
        admin=True, confirm=True,
        tags=["bcdedit", "apic", "interrupt", "multicore"],
    ),

    # ── Hyper-V ─────────────────────────────────────────────────────

    T(
        "sched-002", "Disable Hyper-V (Desktop Only)",
        "Disable the Hyper-V hypervisor to reduce virtualization overhead.",
        actions=[("cmd", "bcdedit /set hypervisorlaunchtype off")],
        revert=[("cmd", "bcdedit /set hypervisorlaunchtype auto")],
        why="Hyper-V adds a hypervisor layer that can raise interrupt latency. "
            "On a dedicated gaming desktop (not using WSL2, Docker, or "
            "Hyper-V features), disabling it can reduce input latency.",
        changes="Disables Hyper-V hypervisor launch.",
        risk="moderate", impact="moderate", recommended="optional",
        admin=True, confirm=True,
        when={"laptop": False},
        tags=["hyperv", "hypervisor", "latency", "bcdedit"],
    ),

    # ── Game Priority ───────────────────────────────────────────────

    T(
        "sched-003", "Game Priority Boost: Let Windows Handle It",
        "Guidance on foreground process priority.",
        actions=[
            ("guidance",
             "Windows automatically boosts the foreground process priority. "
             "Do not force game priority manually — the scheduler already "
             "does this optimally.  Manual priority changes break thread "
             "balancing and can cause worse performance."),
        ],
        revert=[("guidance", "No change to revert.")],
        why="Forced priorities unbalance the scheduler's design.",
        changes="Shows priority guidance.",
        risk="safe", impact="low", recommended="recommended",
        tags=["priority", "scheduler", "foreground", "guidance"],
    ),

    # ── Interrupt Affinity ──────────────────────────────────────────

    T(
        "sched-004", "High-Priority Interrupts: Check Your Board",
        "Guidance on GPU interrupt priority.",
        actions=[
            ("guidance",
             "Check GPU interrupt affinities with MSI Utility v3.  Setting "
             "the GPU to High MSI priority can cut input latency on some "
             "motherboards.  This is board-specific — not all systems "
             "benefit.  Research your specific motherboard before changing "
             "interrupt priorities."),
        ],
        revert=[("guidance", "Reset interrupt priorities in MSI Utility.")],
        why="Interrupt priority affects input and frame-delivery jitter.",
        changes="Shows interrupt affinity guidance.",
        risk="safe", impact="low", recommended="optional",
        tags=["msi", "interrupt", "affinity", "guidance"],
    ),

    # ── Timer ───────────────────────────────────────────────────────

    T(
        "sched-005", "HPET: Leave It Alone",
        "Guidance on the High Precision Event Timer.",
        actions=[
            ("guidance",
             "HPET is forced on in modern Windows.  Older advice about "
             "enabling/disabling HPET is outdated.  The scheduler handles "
             "timer resolution automatically.  Do not modify HPET or "
             "useplatformclock settings — they can break frame pacing."),
        ],
        revert=[("guidance", "No change to revert.")],
        why="Manual timer changes no longer help and can break frame pacing.",
        changes="Shows HPET guidance.",
        risk="safe", impact="low", recommended="recommended",
        tags=["hpet", "timer", "guidance"],
    ),

    # ── Foreground Boost ────────────────────────────────────────────

    T(
        "sched-006", "Foreground App Boost: Best Performance",
        "Guidance on foreground CPU allocation.",
        actions=[
            ("guidance",
             "In System Properties > Advanced > Performance Settings > "
             "Advanced > Processor scheduling, select 'Programs' (Best "
             "performance of foreground apps).  This ensures the active "
             "game gets priority CPU time over background services."),
        ],
        revert=[
            ("guidance",
             "Set processor scheduling to 'Background services' if needed."),
        ],
        why="Foreground priority determines how well the game outcompetes "
            "background apps for CPU time.",
        changes="Shows foreground boost guidance.",
        risk="safe", impact="low", recommended="recommended",
        tags=["foreground", "priority", "guidance"],
    ),

    # ── CSRSS ───────────────────────────────────────────────────────

    T(
        "sched-007", "Lower CSRSS Font Rendering Priority",
        "Reduce the console subsystem font rendering priority.",
        actions=[
            ("reg", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Console",
             "FontSize", 0, "DWORD"),
        ],
        revert=[
            ("regdel", "HKLM",
             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Console",
             "FontSize"),
        ],
        why="CSRSS handles console font rendering.  Lowering its priority "
            "frees CPU time for game threads without visible impact.",
        changes="Sets Console FontSize to 0.",
        risk="safe", impact="low", recommended="optional",
        admin=True,
        tags=["csrss", "console", "priority"],
    ),
])
