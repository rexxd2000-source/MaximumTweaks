"""One-click optimize presets.

Each preset references tweak IDs from the database. Unknown IDs are dropped
with a warning so a stale preset can never crash the app.
"""
from __future__ import annotations

from database import BY_ID
from maxlog import logger

BALANCED = {
    "id": "balanced",
    "name": "Balanced",
    "tagline": "Safe everyday performance",
    "description": (
        "Recommended for most systems. High-performance power plan, Game Mode, "
        "performance visual effects, zero-input-lag mouse, MMCSS multimedia "
        "priority and smart startup cleanup. Nothing destructive."
    ),
    "risk": "safe",
    "tweaks": [
        "pp-013",      # Maximum Power Plan
        "power-004",   # Sleep never
        "power-005",   # Display 15 min
        "game-001",    # Game Mode
        "game-003",    # Game DVR / Game Bar / capture off
        "win-006",     # Visual effects: best performance
        "reg-001",     # Foreground lock timeout
        "mouse-001",   # Mouse acceleration off
        "mmcss_game_priority",  # MMCSS gaming priority
        "audio-003",   # Audio MMCSS task
        "dd-013",      # TCP ack frequency
        "dd-014",      # Nagle off
        "net-009",     # Network throttling off
        "bg-009",      # Tips & suggestions off
    ],
}

COMPETITIVE = {
    "id": "competitive",
    "name": "Competitive",
    "tagline": "Minimum input latency",
    "description": (
        "Everything Balanced does plus latency-first tuning: USB & PCIe power "
        "savings off, aggressive CPU boost, input responsiveness and the "
        "Game DVR/Game Bar stack off. For esports titles."
    ),
    "risk": "low",
    "tweaks": BALANCED["tweaks"] + [
        "power-002",   # USB selective suspend off
        "power-003",   # PCIe ASPM off
        "power-009",   # Min processor state 20%
        "perf-034",    # Processor performance decrease policy
        "perf-032",    # Win32 priority separation
        "reg-002",     # Active window tracking timeout 0
        "reg-003",     # Menu show delay 0
        "kbd-001",     # Key repeat delay zero
        "net-010",     # TCP window scaling
        "net-004",     # TCP ECN
    ],
}

MAXIMUM = {
    "id": "maximum",
    "name": "Maximum",
    "tagline": "Advanced tuning — read first",
    "description": (
        "Aggressive debloating and advanced latency settings. Disables "
        "telemetry, diagnostics and unused services, disables memory "
        "compression, and trims storage. Security and stability trade-offs "
        "apply. Best paired with a restore point."
    ),
    "risk": "moderate",
    "tweaks": COMPETITIVE["tweaks"] + [
        "exp-003",     # Hypervisor off (bcdedit)
        "fpsb-001",    # VBS off
        "adv-006",     # Processor scheduling to programs
        "perf-004",    # Memory compression off
        "ram-058",     # I/O page lock limit
        "stor-016",    # Last access timestamps off
        "stor-002",    # 8.3 short names off
        "ram-030",     # Telemetry service off
        "sys-004",     # WER off
        "tel-001",     # Telemetry: security
        "db-003",      # OneDrive sync off
        "db-002",      # Startup apps cleanup
        "fpsb-007",    # Background apps off
        "win-018",     # Delivery optimization off
        "win-012",     # Advertising ID off
        "rep-008",     # Create a System Restore Point
    ],
}

BUNDLES = {b["id"]: b for b in (BALANCED, COMPETITIVE, MAXIMUM)}


def resolve_bundle(bundle_id: str) -> dict:
    """Return a validated copy of the bundle (unknown tweak ids dropped)."""
    bundle = dict(BUNDLES[bundle_id])
    valid, dropped = [], []
    for tid in bundle["tweaks"]:
        (valid if tid in BY_ID else dropped).append(tid)
    if dropped:
        logger.warn(f"bundle {bundle_id}: dropped unknown tweaks {dropped}")
    bundle["tweaks"] = valid
    return bundle
