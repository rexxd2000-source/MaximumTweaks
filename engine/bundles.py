"""One-click optimize presets.

Each preset references tweak IDs from the database. Unknown IDs are dropped
with a warning so a stale preset can never crash the app.
"""
from __future__ import annotations

from database import BY_ID
from rexlog import logger

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
        "power-001",   # High Performance plan
        "power-004",   # Sleep never
        "power-005",   # Display 15 min
        "game-001",    # Game Mode
        "game-002",    # Game Bar off
        "game-003",    # Background recording off
        "win-006",     # Visual effects: best performance
        "reg-001",     # Foreground lock timeout
        "il-001",      # Mouse acceleration off
        "cpu-013",     # MMCSS gaming priority
        "audio-003",   # Audio MMCSS task
        "eth-002",     # TCP ack frequency
        "eth-003",     # Nagle off
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
        "savings off, core parking disabled, aggressive CPU boost, input "
        "responsiveness and DVR fully off. For esports titles."
    ),
    "risk": "low",
    "tweaks": BALANCED["tweaks"] + [
        "power-002",   # USB selective suspend off
        "power-003",   # PCIe ASPM off
        "power-009",   # Min processor state 20%
        "sched-001",   # Core parking off
        "cpu-005",     # Performance boost mode aggressive
        "cpu-002",     # Win32 priority separation (low)
        "reg-002",     # Active window tracking timeout 0
        "reg-003",     # Menu show delay 0
        "il-002",      # Mouse threshold 0
        "il-005",      # Game DVR off
        "kbd-001",     # Key repeat delay zero
        "game-004",    # Fullscreen optimizations off
        "net-010",     # TCP window scaling
        "net-011",     # TCP ECN
    ],
}

MAXIMUM = {
    "id": "maximum",
    "name": "Maximum",
    "tagline": "Advanced tuning — read first",
    "description": (
        "Aggressive debloating and advanced latency settings. Disables "
        "telemetry, diagnostics and unused services, turns off CPU mitigations "
        "and memory compression, and trims storage. Security and stability "
        "trade-offs apply. Best paired with a restore point."
    ),
    "risk": "moderate",
    "tweaks": COMPETITIVE["tweaks"] + [
        "sched-003",   # Processor sleep states off
        "sched-006",   # Hyper-V off
        "sched-007",   # VBS off
        "adv-006",     # Processor scheduling to programs
        "adv-012",     # Memory compression off
        "ram-006",     # I/O page lock limit
        "cpu-003",     # Favor foreground (low)
        "sys-018",     # Spectre/Meltdown mitigations off
        "stor-003",    # Last access timestamps off
        "stor-002",    # 8.3 short names off
        "svc-003",     # DiagTrack off
        "svc-004",     # WER off
        "tel-001",     # Telemetry: security
        "db-003",      # OneDrive sync off
        "db-002",      # Startup apps cleanup
        "bg-001",      # Background apps off
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
