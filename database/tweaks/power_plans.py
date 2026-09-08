"""Category: Power Plans — MAXimum Premium Power Plan."""
from __future__ import annotations

from ._base import make_T, validate_module, plan_guid

T = make_T("Power Plans", win_default="7,8,10,11")
CATEGORY = "Power Plans"

# Deterministic GUID the MAXimum Premium Power Plan is created under.
MAX_PLAN_NAME = "MAXimum Premium Power Plan"
MAX_PLAN_GUID = plan_guid(MAX_PLAN_NAME)

TWEAKS = validate_module("power_plans", [
    T("pp-013", "MAXimum Premium Power Plan",
      "Create and activate the MAXimum Premium Power Plan — a properly optimized "
      "gaming power plan that improves performance consistency without forcing "
      "100% CPU usage or aggressive clock-locking.",
      actions=[
          # 1. Create the plan from High Performance base.
          ("powerscheme", "create",
           "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
           MAX_PLAN_NAME),

          # ── Processor (AC / DC) ──────────────────────────────────
          # Max 100% allows full boost when needed; min 5% allows idle savings.
          ("power", "processor_max", 100, "AC"),
          ("power", "processor_max", 90, "DC"),
          ("power", "processor_min", 5, "AC"),
          ("power", "processor_min", 5, "DC"),

          # Boost mode: 0 = Disabled (let Windows manage boost naturally)
          # Setting aggressive (2) causes thermal throttling and FPS drops.
          ("power", "boost_mode", 0, "AC"),
          ("power", "boost_mode", 0, "DC"),

          # Performance thresholds: moderate values.
          ("power", "perf_increase_threshold", 30, "AC"),
          ("power", "perf_increase_threshold", 50, "DC"),
          ("power", "perf_decrease_threshold", 10, "AC"),
          ("power", "perf_decrease_threshold", 20, "DC"),

          # Policy: 1 = Ideal (default Windows behavior — balanced ramp).
          ("power", "perf_increase_policy", 1, "AC"),
          ("power", "perf_increase_policy", 1, "DC"),
          ("power", "perf_decrease_policy", 1, "AC"),
          ("power", "perf_decrease_policy", 1, "DC"),

          # Boost policy ceiling: 100% AC, 60% DC.
          ("power", "boost_policy", 100, "AC"),
          ("power", "boost_policy", 60, "DC"),

          # EPP: 40 = balanced performance/efficiency (not 0 which forces max).
          ("power", "epp", 40, "AC"),
          ("power", "epp", 80, "DC"),

          # Idle: allow idle states.
          ("power", "idle_disable", 0, "AC"),
          ("power", "idle_disable", 0, "DC"),

          # Time check: moderate (10 AC, 20 DC).
          ("power", "time_check", 10, "AC"),
          ("power", "time_check", 20, "DC"),

          # ── Display / Storage / USB ──────────────────────────────
          ("power", "adaptive_brightness", 0, "AC"),
          ("power", "adaptive_brightness", 0, "DC"),

          ("power", "display_timeout", 0, "AC"),
          ("power", "display_timeout", 300, "DC"),

          ("power", "hdd_timeout", 0, "AC"),
          ("power", "hdd_timeout", 600, "DC"),

          ("power", "usb_selective", 0, "AC"),
          ("power", "usb_selective", 1, "DC"),

          # ── Sleep / Hibernate / Lid ──────────────────────────────
          ("power", "sleep_timeout", 0, "AC"),
          ("power", "sleep_timeout", 1200, "DC"),

          ("power", "hibernate_timeout", 0, "AC"),
          ("power", "hibernate_timeout", 0, "DC"),

          ("power", "lid_action", 0, "AC"),
          ("power", "lid_action", 1, "DC"),
      ],
      revert=[
          ("powerscheme", "setactive",
           "381b4222-f694-41f0-9685-ff5bb260df2e"),  # Balanced
          ("powerscheme", "delete", MAX_PLAN_GUID),
      ],
      why="A purpose-built gaming power plan optimized for consistent frame times. "
          "Unlike aggressive plans that force 100% CPU and aggressive boost policies "
          "causing thermal throttling and FPS drops, this plan uses moderate settings "
          "that allow the CPU to boost when needed while maintaining thermal headroom. "
          "Boost mode is left at default (Windows-managed) instead of forced Aggressive. "
          "Performance policies use Ideal (not Rocket) to prevent aggressive package-wide "
          "ramping. EPP is set to 40 (not 0) to maintain efficiency headroom on hybrid CPUs. "
          "Proper AC/DC differentiation ensures laptop battery life isn't sacrificed.",
      changes="Installs and activates the MAXimum Premium Power Plan.",
      risk="safe", impact="high", recommended="recommended",
      admin=True,
      tags=["power", "plan", "premium", "gaming", "performance"]),
])
