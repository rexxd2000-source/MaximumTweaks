"""Apply/revert tweaks in a batch with progress callbacks (UI-friendly)."""
from __future__ import annotations

from typing import Callable

from database import BY_ID
from database.executor import apply_tweak
from rexlog import logger

from . import activity, state as state_mgr
from . import state_checker

ProgressCb = Callable[[int, int, str, bool, str], None]  # done,total,id,ok,detail


def run(ids: list[str], mode: str = "apply", progress: ProgressCb | None = None) -> dict:
    """Apply or revert each tweak id.

    Returns {"applied": [...ids...], "results": {id: (ok, details)}}.
    """
    applied, results = [], {}
    total = len(ids)
    for idx, tid in enumerate(ids, start=1):
        tweak = BY_ID.get(tid)
        if tweak is None:
            results[tid] = (False, [("", False, "unknown tweak id")])
            activity.emit("error", f"Unknown tweak id {tid}")
            if progress:
                progress(idx, total, tid, False, "unknown tweak id")
            continue

        ok, details = apply_tweak(tid, mode=mode)
        summary = _summarize(details)
        results[tid] = (ok, details)

        # Post-apply verification against the live system: a tweak is only
        # recorded as applied when the measured state matches (or the tweak
        # cannot be measured at all). Execution success alone is not proof.
        #
        # The scan/audit that ran before this batch populated the checker's
        # process-global cache with PRE-apply reads, so drop it before the
        # verify or every reg/power/svc value written just now reads stale.
        state_checker.invalidate_cache()
        live = None
        verified = None
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
        logger.info(
            f"{mode} {tid} ({tweak['name']}) -> ok={ok} verified={verified} "
            f"live={live} {summary}")

        if ok and mode == "apply" and verified is not False:
            state_mgr.unmark_disabled(tid)
            state_mgr.mark_applied(tid)
            applied.append(tid)
            activity.emit("success",
                          f"{tweak['name']} applied (verified)" if verified
                          else f"{tweak['name']} applied (not measurable)")
            if "reboot" in (tweak.get("tags") or []):
                state_mgr.set_restart_required(True)
                activity.emit("restart", "Restart required to finalize changes")
        elif ok and mode == "revert" and verified is not False:
            state_mgr.unmark_applied(tid)
            state_mgr.mark_disabled(tid)
            activity.emit("info",
                          f"{tweak['name']} reverted (verified)" if verified
                          else f"{tweak['name']} reverted (not measurable)")
        elif ok and verified is False:
            activity.emit(
                "error",
                f"{tweak['name']} did not verify after {mode} "
                f"(live state = {live}) - not recorded as applied")
        else:
            activity.emit("error", f"{tweak['name']} failed — {summary}")

        if progress:
            progress(idx, total, tid, ok, summary)
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
