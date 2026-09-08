"""Apply/revert tweaks in a batch with progress callbacks (UI-friendly).

Every tweak passes :func:`engine.safety.preflight` before execution, so a
batch assembled anywhere (toggles, Apply All, presets, optimizer dialog, CLI)
can never silently apply a tweak that is blocked by validation status, targets
the wrong Windows version, requires undetected hardware, or conflicts with an
applied tweak.

Verification after execution is honest: a tweak is only recorded as applied
when the live system actually matches its target. ``verified is None``
(unmeasurable actions like one-shot commands) is recorded but reported as
"applied but not verifiable" — never as verified. ``verified is False``
(written but the system does not match) is recorded as *not* applied so the
UI never claims a change that did not take effect.
"""
from __future__ import annotations

from typing import Callable

from database import BY_ID
from database.executor import apply_tweak
from rexlog import logger

from . import activity, state as state_mgr
from . import state_checker
from .safety import preflight

ProgressCb = Callable[[int, int, str, bool, str], None]  # done,total,id,ok,summary


def run(ids: list[str], mode: str = "apply",
        progress: ProgressCb | None = None,
        profile: dict | None = None,
        force: bool = False,
        dry_run: bool = False) -> dict:
    """Apply or revert each tweak id.

    Args:
        ids:      tweak ids to process, in order.
        mode:     "apply" or "revert".
        progress: optional callback ``(done, total, tid, ok, summary)``.
        profile:  detected hardware profile for compatibility gating.
        force:    bypass the conflict-active guard (user confirmed "apply anyway").
        dry_run:  preview only — execute nothing, record nothing.

    Returns:
        {"applied": [ids recorded as applied],
         "results": {id: {"ok", "status", "detail", "verified", "live",
                           "code", "actions"}}}

        ``ok`` is True when the operations executed successfully (or the tweak
        was blocked with a clean reason in ``code``). ``status`` is one of:
        applied / applied_unverified / reverted / reverted_unverified /
        unverified (executed but the live system does not match) /
        failed / blocked.
    """
    applied: list[str] = []
    results: dict = {}
    total = len(ids)
    for idx, tid in enumerate(ids, start=1):
        tweak = BY_ID.get(tid)
        if tweak is None:
            results[tid] = {"ok": False, "status": "failed",
                            "detail": "unknown tweak id", "verified": None,
                            "live": None, "code": None, "actions": []}
            activity.emit("error", f"Unknown tweak id {tid}")
            if progress:
                progress(idx, total, tid, False, "unknown tweak id")
            continue

        # Safety gate first — never execute a blocked tweak.
        if mode == "apply":
            pf = preflight(tweak, profile=profile, mode="apply", force=force)
            if not pf["allowed"]:
                results[tid] = {"ok": False, "status": "blocked",
                                "detail": pf["reason"], "verified": None,
                                "live": None, "code": pf["code"],
                                "actions": []}
                activity.emit("warning", f"{tweak['name']} blocked: {pf['reason']}")
                logger.info(f"apply {tid} BLOCKED ({pf['code']}): {pf['reason']}")
                if progress:
                    progress(idx, total, tid, False, pf["reason"])
                continue

        # Execute — one unexpected crash must never abort the whole batch.
        try:
            ok, details = apply_tweak(tid, mode=mode, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{mode} {tid}: unexpected exception: {exc}")
            ok, details = False, [((tweak["actions"] or [("",)])[0], False,
                                   f"{type(exc).__name__}: {exc}")]
        summary = _summarize(details)
        results[tid] = {"ok": bool(ok), "status": "failed", "detail": summary,
                        "verified": None, "live": None, "code": None,
                        "actions": details}

        # Dry-run: nothing was written, so there is nothing to verify or record.
        if dry_run:
            if ok:
                results[tid]["status"] = "dry_run"
                if progress:
                    progress(idx, total, tid, True, "dry-run: " + summary)
                continue
            results[tid]["status"] = "failed"
            activity.emit("error", f"{tweak['name']} dry-run failed — {summary}")
            if progress:
                progress(idx, total, tid, False, summary)
            continue

        # Post-apply verification against the live system: a tweak is only
        # recorded as applied when the measured state matches. Execution
        # success alone is not proof. The pre-batch audit populated the
        # checker's process-global cache with PRE-apply reads, so drop it
        # before the verify or every reg/power/svc value just written is stale.
        state_checker.invalidate_cache()
        verified = None
        live = None
        if ok:
            try:
                live = state_checker.check_tweak(tweak)
            except Exception as exc:  # noqa: BLE001
                logger.warn(f"verify {tid}: state check failed: {exc}")
                live = None
            if live is None:
                verified = None  # not measurable (guidance / opaque action)
            else:
                verified = (live is True) if mode == "apply" else (live is False)

        if ok and mode == "apply" and verified is not False:
            state_mgr.unmark_disabled(tid)
            state_mgr.mark_applied(tid)
            applied.append(tid)
            status = "applied" if verified else "applied_unverified"
            results[tid]["status"] = status
            results[tid]["verified"] = verified
            results[tid]["live"] = live
            activity.emit(
                "success",
                f"{tweak['name']} applied (verified)" if verified
                else f"{tweak['name']} applied (not verifiable)")
        elif ok and mode == "revert" and verified is not False:
            state_mgr.unmark_applied(tid)
            state_mgr.mark_disabled(tid)
            status = "reverted" if verified else "reverted_unverified"
            results[tid]["status"] = status
            results[tid]["verified"] = verified
            results[tid]["live"] = live
            activity.emit(
                "info",
                f"{tweak['name']} reverted (verified)" if verified
                else f"{tweak['name']} reverted (not verifiable)")
        elif ok and verified is False:
            # Executed but the live system does not match the target: the
            # change did not take effect (or was immediately reverted by the OS).
            # Never record it as applied.
            results[tid]["status"] = "unverified"
            results[tid]["verified"] = False
            results[tid]["live"] = live
            activity.emit(
                "error",
                f"{tweak['name']} did not verify after {mode} "
                f"(live state = {live}) — not recorded as applied")
        else:
            results[tid]["status"] = "failed"
            activity.emit("error", f"{tweak['name']} failed — {summary}")

        # Keep the restart-required flag in sync: set when any applied tweak
        # needs a reboot, cleared when the last one is reverted.
        if ok and "reboot" in (tweak.get("tags") or []):
            state_mgr.recompute_restart_required()
            if mode == "apply" and verified is not False:
                activity.emit("restart", "Restart required to finalize changes")

        logger.info(
            f"{mode} {tid} ({tweak['name']}) -> ok={ok} verified={verified} "
            f"status={results[tid]['status']} live={live} {summary}")

        if progress:
            progress(idx, total, tid, bool(ok), summary)
    return {"applied": applied, "results": results}


def _summarize(details) -> str:
    """Collapse the action results into a short human string."""
    parts = []
    for action, ok, detail in details:
        if isinstance(action, dict):
            name = action.get("name", "action")
        elif isinstance(action, (list, tuple)):
            name = action[0]
        else:
            name = str(action)
        parts.append(f"{name}={'ok' if ok else 'FAIL'}")
    return ", ".join(parts) or "no actions"
