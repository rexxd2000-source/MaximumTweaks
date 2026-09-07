"""Category: Game Process — process-aware CPU tweaks for running games.

These are the CPU spec PART 2 features.  They are NOT registry tweaks: every
op goes through the shared Game Process Manager
(:mod:`engine.game_process_manager`), which opens the game with minimum
rights, detects current state first, applies only what is needed, refuses to
touch protected/anti-cheat processes, and snapshots the original values so
Revert restores them exactly.

Apply runs against whichever supported game processes are running right now.
If no game is running, the op is skipped and the card reports why, so
re-apply after launching the game.
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Game Process", win_default="10,11")
CATEGORY = "Game Process"

TWEAKS = validate_module("game_process", [
    T("gproc-001", "Disable Game Efficiency Mode",
      "Removes EcoQoS execution-speed throttling from the running game "
      "process (High QoS). Windows-only for Efficiency Mode behavior.",
      actions=[("process", "high_qos")],
      revert=[("process", "high_qos_revert")],
      why="Windows can apply execution-speed throttling (EcoQoS) to a game "
          "even when it is the foreground app, capping its CPU throughput. "
          "This disables that throttling for the game process only.",
      changes="Sets ProcessPowerThrottling execution-speed state off "
              "(High QoS / Efficiency Mode disabled) on the running game.",
      risk="low", impact="moderate", recommended="optional",
      warn="Applies only to a currently running supported game. Protected or "
           "anti-cheat processes are skipped — never bypassed.",
      added="2026-09-07",
      tags=["efficiency", "ecoqos", "power", "qos", "throttling"]),

    T("gproc-002", "Restore Game CPU Sets",
      "Detects an explicit per-game CPU Set restriction and clears it so "
      "Windows scheduling becomes unrestricted again.",
      actions=[("process", "clear_cpu_sets")],
      revert=[("process", "clear_cpu_sets_revert")],
      why="Some optimizers pin games to a subset of CPU Sets (e.g. P-core "
          "only). If such a restriction exists, clearing it returns the game "
          "to the Windows-default scheduler behavior. No fixed mask is ever "
          "written.",
      changes="Clears the explicit default CPU Set assignment on the running "
              "game, if one is set.",
      risk="low", impact="low", recommended="optional",
      warn="Reports 'No explicit CPU Set restriction' when none exists — "
           "nothing is forced.",
      added="2026-09-07",
      tags=["cpu", "sets", "affinity", "scheduler"]),

    T("gproc-003", "Normalize Game Memory Priority",
      "Restores a game that another optimizer set to a low memory priority "
      "back to Windows Normal (5).",
      actions=[("process", "memory_normal")],
      revert=[("process", "memory_normal_revert")],
      why="The documented process memory priorities are 1 (Very Low) to 5 "
          "(Normal). A game pushed below Normal can get its working set "
          "trimmed aggressively; this only ever raises a low value back "
          "to 5 and never above it.",
      changes="Sets process memory priority to Normal (5) on the running "
              "game if it is below 5.",
      risk="low", impact="low", recommended="optional",
      warn="Never uses undocumented values above Normal.",
      added="2026-09-07",
      tags=["memory", "priority", "working", "set"]),

    T("gproc-004", "Game CPU Priority",
      "Lets a running supported game use the Windows 'Above Normal' CPU "
      "scheduling priority class.",
      actions=[("process", "priority_above_normal")],
      revert=[("process", "priority_above_normal_revert")],
      why="Above Normal schedules the game's threads ahead of standard "
          "processes without starving background system work. The original "
          "priority class is saved and restored on revert.",
      changes="Sets the running game's priority class to Above Normal.",
      risk="moderate", impact="moderate", recommended="optional", confirm=True,
      warn="Optional tuning — High and Realtime are never used automatically. "
           "Protected processes are skipped.",
      added="2026-09-07",
      tags=["priority", "scheduler", "cpu"]),
])