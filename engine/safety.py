"""Apply-time safety gate.

Every apply path — UI toggles, Apply All, presets, the optimizer dialog and
the CLI — must pass through :func:`preflight` before a tweak is executed. The
UI filters by compatibility *before* building a batch, but this module is the
hard guarantee at the engine layer: no caller can silently apply a tweak that
is blocked by validation, targets the wrong Windows version, needs undisclosed
hardware, or conflicts with a tweak that is already applied.

Codes returned to callers (so the UI can render a specific badge/message):

  info_only          guidance tweak — nothing to execute
  status_blocked     INVALID / PLACEBO / OUTDATED / CONFLICTING validation status
  admin              requires elevation and the app is not elevated
  win_version        tweak supports a different Windows version
  incompatible       detected hardware fails a ``when`` condition
  no_profile         hardware-gated tweak but hardware was never detected
  conflict_active    a conflicting tweak is currently applied (force-able)
"""
from __future__ import annotations

from database.validation import BLOCKED_STATUSES

# CONFLICTING is a runtime concern, not a hard block: it only means *another
# tweak in the database* writes the same setting with a different target. It is
# dangerous only while that counterpart is actually applied, which the
# conflict-active guard below enforces. Blocking here would permanently disable
# a tweak (e.g. Click Timing) even when its counterpart was never applied.
_HARD_BLOCK_STATUSES = BLOCKED_STATUSES - {"CONFLICTING"}

from . import state as state_mgr
from .recommender import _effective_win_version, evaluate, has_hardware_gates, windows_versions


def _deny(result: dict, code: str, reason: str) -> dict:
    result["allowed"] = False
    result["code"] = code
    result["reason"] = reason
    return result


def preflight(tweak: dict, profile: dict | None = None,
              mode: str = "apply", force: bool = False) -> dict:
    """Decide whether a tweak may be executed right now.

    Returns {"allowed": bool, "code": str|None, "reason": str,
             "conflicts": [tweak_ids]}. ``force`` bypasses only the
    conflict-active guard (for a UI "apply anyway?" confirmation); status,
    Windows-version, admin and hardware checks always hold.
    """
    result: dict = {"allowed": True, "code": None, "reason": "", "conflicts": []}
    tid = tweak["id"]

    if mode == "revert":
        # Revert always restores — never blocked by status or hardware. Only a
        # guidance tweak has nothing to revert.
        if tweak.get("guidance"):
            return _deny(result, "info_only", "Informational guide — nothing to revert.")
        return result

    if tweak.get("guidance"):
        return _deny(result, "info_only", "Informational guide — nothing to apply.")

    status = tweak.get("status", "UNKNOWN")
    if status in _HARD_BLOCK_STATUSES:
        note = tweak.get("validation_note") or "not safe to auto-apply"
        return _deny(result, "status_blocked",
                     f"Blocked by validation status {status.lower()}: {note}")

    if tweak.get("admin"):
        from database.executor import _is_admin  # deferred: avoids import cycle
        if not _is_admin():
            return _deny(
                result, "admin",
                "Requires administrator privileges — relaunch the app as administrator.")

    # Windows version gating (works without a profile via cheap OS detection).
    win = _effective_win_version(profile or {})
    if win is not None:
        supported = windows_versions(tweak)
        if supported and win not in supported:
            return _deny(
                result, "win_version",
                f"Designed for Windows {'/'.join(sorted(supported))}; "
                f"this PC runs Windows {win}.")
        when_wins = (tweak.get("when") or {}).get("win_versions")
        if when_wins and win not in set(when_wins):
            return _deny(
                result, "win_version",
                f"Requires Windows {'/'.join(when_wins)}; this PC runs Windows {win}.")

    # Hardware compatibility. A hardware-gated tweak with no detected profile
    # is never applied blindly — skip it and ask the user to run detection.
    if has_hardware_gates(tweak):
        if not profile:
            return _deny(
                result, "no_profile",
                "Hardware not detected yet — run Hardware Detection first so "
                "this tweak is never applied blindly.")
        ev = evaluate(tweak, profile)
        if ev["state"] == "incompatible":
            reasons = "; ".join(ev["reasons"]) or "not compatible with this PC"
            return _deny(result, "incompatible",
                         f"Not compatible with this PC: {reasons}")

    # Conflict guard: applying this tweak while a conflicting one is already
    # applied would silently overwrite the other change.
    conflicts = tweak.get("conflicts") or []
    applied = state_mgr.applied_ids()
    active_conflicts = [c["with"] for c in conflicts if c["with"] in applied]
    if active_conflicts and not force:
        result["conflicts"] = active_conflicts
        return _deny(
            result, "conflict_active",
            "Conflicts with an applied tweak: " + ", ".join(active_conflicts)
            + ". Applying both would fight over the same setting.")

    return result
