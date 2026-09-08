"""Category: Power Plans — Maximum Power Plan."""
from __future__ import annotations

from ._base import make_T, validate_module, plan_guid

T = make_T("Power Plans", win_default="7,8,10,11")
CATEGORY = "Power Plans"

# Deterministic GUID the Maximum Power Plan is created under.
MAX_PLAN_NAME = "Maximum Power Plan"
MAX_PLAN_GUID = plan_guid(MAX_PLAN_NAME)

TWEAKS = validate_module("power_plans", [
    T("pp-013", "Maximum Power Plan",
      "Create and activate the Maximum Power Plan — a maximum-performance "
      "gaming power plan that locks the processor to 100% and minimizes "
      "throttling for consistent frame times.",
      actions=[
          # 1. Create the plan from High Performance base.
          ("powerscheme", "create",
           "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
           MAX_PLAN_NAME),

          # ── Processor (AC / DC) ──────────────────────────────────
          # Lock min & max processor state to 100% for maximum sustained clocks.
          ("power", "processor_min", 100, "AC"),
          ("power", "processor_min", 100, "DC"),
          ("power", "processor_max", 100, "AC"),
          ("power", "processor_max", 100, "DC"),

          # Performance thresholds: ramp up quickly, scale down slowly.
          ("power", "perf_increase_threshold", 10, "AC"),
          ("power", "perf_increase_threshold", 30, "DC"),
          ("power", "perf_decrease_threshold", 10, "AC"),
          ("power", "perf_decrease_threshold", 10, "DC"),

          # No processor frequency cap (0 = uncapped).
          ("power", "proc_freq_max", 0, "AC"),
          ("power", "proc_freq_max", 0, "DC"),

          # System cooling policy: Active AC (fan-based), Passive DC.
          ("power", "sys_cooling_pol", 1, "AC"),
          ("power", "sys_cooling_pol", 0, "DC"),

          # ── Display / Storage / PCIe ─────────────────────────────
          ("power", "adaptive_brightness", 0, "AC"),
          ("power", "adaptive_brightness", 0, "DC"),
          ("power", "display_brightness", 100, "AC"),
          ("power", "display_brightness", 75, "DC"),
          ("power", "display_brightness_dim", 50, "AC"),
          ("power", "display_brightness_dim", 50, "DC"),
          ("power", "display_timeout", 0, "AC"),
          ("power", "display_timeout", 0, "DC"),
          ("power", "hdd_timeout", 0, "AC"),
          ("power", "hdd_timeout", 0, "DC"),
          ("power", "pcie_aspm", 0, "AC"),
          ("power", "pcie_aspm", 0, "DC"),

          # ── Sleep / Hibernate / Wake ─────────────────────────────
          ("power", "away_mode", 1, "AC"),
          ("power", "away_mode", 0, "DC"),
          ("power", "sleep_timeout", 0, "AC"),
          ("power", "sleep_timeout", 600, "DC"),
          ("power", "hybrid_sleep", 0, "AC"),
          ("power", "hybrid_sleep", 0, "DC"),
          ("power", "hibernate_timeout", 0, "AC"),
          ("power", "hibernate_timeout", 0, "DC"),
          ("power", "wake_timers", 0, "AC"),
          ("power", "wake_timers", 0, "DC"),
      ],
      revert=[
          ("powerscheme", "setactive",
           "381b4222-f694-41f0-9685-ff5bb260df2e"),  # Balanced
          ("powerscheme", "delete", MAX_PLAN_GUID),
      ],
      why="A maximum-performance gaming power plan that locks the processor to "
          "100% min/max state, ramps performance up aggressively (10% increase "
          "threshold) and scales down slowly (10% decrease threshold), disables "
          "PCIe link-state power management, sets adaptive brightness off, and "
          "keeps the display, storage, and system from idling to sleep on AC. "
          "Based on the Reaper Power Plan spec, which is installed under the "
          "name 'Maximum Power Plan'.",
      changes="Installs and activates the Maximum Power Plan.",
      risk="safe", impact="high", recommended="recommended",
      admin=True,
      tags=["power", "plan", "maximum", "gaming", "performance"]),
])
