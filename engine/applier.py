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

import re
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
        dry_run: bool = False,
        cancel_check=None) -> dict:
    """Apply or revert each tweak id.

    Args:
        ids:      tweak ids to process, in order.
        mode:     "apply" or "revert".
        progress: optional callback ``(done, total, tid, ok, summary)``.
        profile:  detected hardware profile for compatibility gating.
        force:    bypass the conflict-active guard (user confirmed "apply anyway").
        dry_run:  preview only — execute nothing, record nothing.
        cancel_check: optional callable returning True to abort the batch.

    Returns:
        {"applied": [ids recorded as applied],
         "results": {id: {"ok", "status", "detail", "verified", "live",
                           "code", "actions"}}}
    """
    applied: list[str] = []
    results: dict = {}
    total = len(ids)
    for idx, tid in enumerate(ids, start=1):
        # Cooperative cancellation: check before each tweak.
        if cancel_check and cancel_check():
            activity.emit("warning", "Batch cancelled by user")
            logger.info(f"{mode} batch cancelled at {idx}/{total}")
            break

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

        # Snapshot backups before execute (for revert verification after).
        pre_backups = {}
        if mode == "revert" and not dry_run:
            pre_backups = _collect_backups(tid)

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
        elif ok and mode == "revert":
            # ── Post-revert verification ──────────────────────────
            # After a revert, verify that the live system now matches the
            # original backup values (if any were captured).  A revert is
            # only reported as "reverted" when verification confirms the
            # original state has been restored.
            revert_verified = _verify_revert(tid, tweak, pre_backups)
            if revert_verified is True:
                state_mgr.unmark_applied(tid)
                state_mgr.mark_disabled(tid)
                status = "reverted"
                results[tid]["status"] = status
                results[tid]["verified"] = True
                results[tid]["live"] = live
                activity.emit("info", f"{tweak['name']} reverted (verified)")
            elif revert_verified is False:
                # Execution succeeded but the restored state does not match
                # the original backups — the revert did not fully take effect.
                state_mgr.unmark_applied(tid)
                state_mgr.mark_disabled(tid)
                status = "reverted_unverified"
                results[tid]["status"] = status
                results[tid]["verified"] = False
                results[tid]["live"] = live
                activity.emit(
                    "error",
                    f"{tweak['name']} revert did not verify — "
                    f"original state may not have been restored")
            elif verified is not False:
                # No backups to compare (tweak applied before this feature
                # shipped) and state_checker says the tweak is inactive.
                state_mgr.unmark_applied(tid)
                state_mgr.mark_disabled(tid)
                status = "reverted"
                results[tid]["status"] = status
                results[tid]["verified"] = verified
                results[tid]["live"] = live
                activity.emit(
                    "info",
                    f"{tweak['name']} reverted (verified)" if verified
                    else f"{tweak['name']} reverted (not verifiable)")
            else:
                results[tid]["status"] = "failed"
                activity.emit("error", f"{tweak['name']} revert failed")
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


# ---------------------------------------------------------------------------
# Post-revert verification helpers
# ---------------------------------------------------------------------------

def _collect_backups(tid: str) -> dict:
    """Collect all live backups for a tweak before execute (for post-revert check)."""
    return {
        "reg": state_mgr.get_reg_backups(tid) or {},
        "file": state_mgr.get_file_backups(tid) or {},
        "ini": state_mgr.get_ini_backups(tid) or {},
        "power": state_mgr.get_power_backups(tid) or {},
        "svc": state_mgr.get_svc_backups(tid) or {},
        "cmd": state_mgr.get_cmd_backups(tid) or {},
        "powerscheme": state_mgr.get_powerscheme_backups(tid) or {},
        "sched": state_mgr.get_sched_backups(tid) or {},
    }


def _verify_revert(tid: str, tweak: dict, pre_backups: dict) -> bool | None:
    """Verify that a revert restored the original state.

    Returns:
        True  — verification passed (original state restored or no backups)
        False — verification failed (restored state does not match backups)
        None  — not verifiable (no backups and state_checker says None)
    """
    if not any(pre_backups.values()):
        return None  # no backups captured (pre-feature tweak)

    state_checker.invalidate_cache()
    all_ok = True
    any_checked = False

    # Verify registry backups
    for key, entry in pre_backups.get("reg", {}).items():
        ok = _verify_reg_backup(entry)
        if ok is not None:
            any_checked = True
            if not ok:
                all_ok = False

    # Verify file backups
    for key, entry in pre_backups.get("file", {}).items():
        ok = _verify_file_backup(entry)
        if ok is not None:
            any_checked = True
            if not ok:
                all_ok = False

    # Verify ini backups
    for key, entry in pre_backups.get("ini", {}).items():
        ok = _verify_ini_backup(entry)
        if ok is not None:
            any_checked = True
            if not ok:
                all_ok = False

    # Verify power backups
    for key, entry in pre_backups.get("power", {}).items():
        ok = _verify_power_backup(entry)
        if ok is not None:
            any_checked = True
            if not ok:
                all_ok = False

    # Verify svc backups
    for key, entry in pre_backups.get("svc", {}).items():
        ok = _verify_svc_backup(entry)
        if ok is not None:
            any_checked = True
            if not ok:
                all_ok = False

    # Verify cmd backups (powercfg, bcdedit, reg add/delete)
    for key, entry in pre_backups.get("cmd", {}).items():
        ok = _verify_cmd_backup(entry)
        if ok is not None:
            any_checked = True
            if not ok:
                all_ok = False

    # Verify powerscheme backups
    for key, entry in pre_backups.get("powerscheme", {}).items():
        ok = _verify_powerscheme_backup(entry)
        if ok is not None:
            any_checked = True
            if not ok:
                all_ok = False

    # Verify sched backups
    for key, entry in pre_backups.get("sched", {}).items():
        ok = _verify_sched_backup(entry)
        if ok is not None:
            any_checked = True
            if not ok:
                all_ok = False

    if not any_checked:
        return None  # nothing was verifiable
    return all_ok


def _verify_reg_backup(entry: dict) -> bool | None:
    """Check if a registry value now matches its backup."""
    hive, path, name, expected_data = (
        entry["hive"], entry["path"], entry["name"], entry["data"])
    from . import state_checker
    # If backup was "missing", verify value is absent
    if entry.get("missing"):
        current = state_checker._reg_data(hive, path, name)
        if current is not None:  # value exists — bad
            return False
        return True  # value absent — good
    # If backup existed, verify value matches
    current = state_checker._reg_data(hive, path, name)
    if current is None:
        return False  # value missing — bad
    current_type, current_data = current
    return current_data.strip('"') == expected_data.strip('"')


def _verify_file_backup(entry: dict) -> bool | None:
    """Check if a file now matches its backup."""
    path = entry["path"]
    import os
    existed = entry.get("existed", True)
    if not existed:
        return not os.path.exists(path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return content == entry.get("content", "")
    except (OSError, FileNotFoundError):
        return False


def _verify_ini_backup(entry: dict) -> bool | None:
    """Check if an INI value now matches its backup."""
    from configparser import ConfigParser
    cp = ConfigParser()
    try:
        cp.read(entry["path"], encoding="utf-8")
        current = cp.get(entry["section"], entry["key"], fallback=None)
        return current == entry["value"]
    except Exception:
        return None


def _verify_power_backup(entry: dict) -> bool | None:
    """Check if a power setting now matches its backup."""
    from database.executor import _get_scheme_guid, _powercfg_query
    scheme_guid = _get_scheme_guid(entry.get("scheme"))
    if not scheme_guid:
        return None
    _, raw = _powercfg_query(scheme_guid, entry["subgroup"], entry["setting"])
    m = re.search(r"Current Power Setting Index:\s*0x([0-9a-fA-F]+)", raw)
    if not m:
        return None
    current_val = int(m.group(1), 16)
    return str(current_val) == entry["data"]


def _verify_svc_backup(entry: dict) -> bool | None:
    """Check if a service startup type now matches its backup."""
    from . import state_checker
    current = state_checker._svc_start_type(entry["name"])
    if current is None:
        return None
    # entry["start_type"] is like "DEMAND_START", "DISABLED", etc.
    return current.upper() == entry["start_type"].upper()


def _verify_cmd_backup(entry: dict) -> bool | None:
    """Verify a cmd-based backup against the live system."""
    from . import state_checker
    from database.executor import _run_powercfg_active, _powercfg_query, _run
    kind = entry.get("kind", "")
    try:
        if kind == "powercfg_setactive":
            prev = entry.get("prev_active")
            if not prev:
                return None
            guid, _ = state_checker._active_scheme()
            return prev.lower() in (guid or "")

        if kind == "powercfg_value":
            prev = entry.get("prev_value")
            if prev is None:
                return None
            scheme_guid = state_checker._active_scheme()[0]
            if not scheme_guid:
                return None
            _, raw = _powercfg_query(scheme_guid, entry.get("subgroup", ""),
                                     entry.get("guid", ""))
            m = re.search(r"Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)",
                          raw or "")
            if not m:
                return None
            current = int(m.group(1), 16)
            return str(current) == str(prev).strip()

        if kind == "powercfg_change":
            prev = entry.get("prev_value")
            if prev is None:
                return None
            scheme_guid = state_checker._active_scheme()[0]
            if not scheme_guid:
                return None
            _, raw = _powercfg_query(scheme_guid, entry.get("subgroup", ""),
                                     entry.get("guid", ""))
            ac_dc = entry.get("ac_dc", "ac").upper()
            label = f"Current {ac_dc} Power Setting Index:"
            for line in (raw or "").splitlines():
                if label.lower() in line.lower():
                    mv = re.search(r"0x([0-9a-fA-F]+)", line)
                    if mv:
                        return str(int(mv.group(1), 16)) == str(prev).strip()
            return None

        if kind == "powercfg_hibernate":
            prev = entry.get("prev_value")
            if prev is None:
                return None
            current = state_checker._reg_data(
                "HKLM", r"SYSTEM\CurrentControlSet\Control\Power", "HibernateEnabled")
            if current is None:
                return None
            return str(current[1]).strip() == str(prev).strip()

        if kind == "bcdedit":
            prev = entry.get("prev_value")
            store = state_checker._bcd_values()
            current = store.get(entry["name"].lower()) if store else None
            if prev is None:
                return current is None
            return str(current).strip() == str(prev).strip()

        if kind == "netsh":
            prev = entry.get("prev_value")
            if prev is None:
                return None
            globals_map = state_checker._netsh_tcp_global()
            from engine.state_checker import _NETSH_LABELS
            labels = _NETSH_LABELS.get(entry["name"])
            if not labels:
                return None
            for label in labels:
                v = globals_map.get(label.lower())
                if v is not None:
                    return v.strip() == str(prev).strip()
            return None

        if kind == "reg_cmd":
            prev = entry.get("prev_value")
            current = state_checker._reg_data(entry["hive"], entry["path"], entry["name"])
            if prev is None:
                return current is None
            if current is None:
                return False
            return str(current[1]).strip() == str(prev).strip()
    except Exception:
        return None
    return None


def _verify_powerscheme_backup(entry: dict) -> bool | None:
    """Check if a power scheme state matches its backup."""
    from database.executor import _scheme_exists, _scheme_active
    if entry["action"] == "present":
        if entry.get("deleted"):
            return not _scheme_exists(entry["guid"])
        return _scheme_exists(entry["guid"])
    elif entry["action"] == "active":
        return _scheme_active(entry["guid"])
    return None


def _verify_sched_backup(entry: dict) -> bool | None:
    """Check if a scheduled task state matches its backup."""
    from . import state_checker
    task = entry.get("task", "")
    status = state_checker._sched_status(task)
    if status is None:
        return None
    if entry.get("disabled"):
        return "Disabled" in status
    if entry.get("enabled"):
        return "Ready" in status or "Running" in status
    return None


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
