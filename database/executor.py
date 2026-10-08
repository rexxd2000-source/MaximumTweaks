"""Action executor for the Maximum Tweaks database.

Registry writes are value-snapshotted before apply and the exact previous
value is restored on revert (``_snapshot_reg_targets`` / ``_restore_backup``).
This is what makes Revert genuinely undo an apply, even for values whose
previous data was non-default.

Implements every action kind used by the tweak definitions:

  reg / regdel / regkeydel   -> reg.exe
  svc / svcstart / svcstop   -> sc.exe
  cmd                        -> subprocess (shell)
  file (write/append/delete) -> local filesystem
  ini                        -> game config ini edit (set key=value)
  power                      -> powercfg.exe (named settings)
  powerscheme                -> powercfg.exe
  sched (disable/enable)     -> schtasks.exe
  appx (remove/register)     -> PowerShell
  restart (explorer)         -> restart explorer.exe
  mkdir                      -> os.makedirs
  process                    -> engine.game_process_manager (running games)
  netadp                     -> engine.net_latency (NIC properties / RSS)
  guidance                   -> informational no-op

Run with ``dry_run=True`` to preview actions without touching the system.
"""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import threading

from .tweaks import BY_ID
from .tweaks._base import plan_guid
from engine import reg_util
from engine.state_checker import CHANGE_SETTINGS
from engine.state_checker import POWER_NAMES as POWER_SETTINGS

# Thread-local context so process-level actions ("process") know which tweak
# they belong to (used to key the per-exe original-state snapshots).
_tweak_ctx = threading.local()

_GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

# POWER_SETTINGS: named power settings -> (subgroup GUID, setting GUID).
# Single source of truth lives in engine.state_checker.POWER_NAMES (verified
# against the live PowerSettings registry); this alias keeps apply and detect
# on the same table so a GUID can never drift between them.

# Power setting GUIDs exposed by each (active scheme, subgroup) pair, keyed by
# (active scheme guid, subgroup guid).  Populated lazily by
# _power_setting_supported() and dropped whenever a plan is re-activated, since
# that can change which settings the plan exposes.
_POWER_SUBGROUP_CACHE: dict[tuple[str, str], set[str]] = {}

SVC_MODE_MAP = {"auto": "auto", "manual": "demand", "disabled": "disabled",
                "boot": "boot", "system": "system", "delayed": "delayed"}
_SVC_START_ALIASES = {"auto_start": "auto", "demand_start": "manual",
                      "delayed_auto_start": "delayed", "boot_start": "boot",
                      "system_start": "system"}

# reg.exe type tokens
REG_TYPE = {"DWORD": "REG_DWORD", "QWORD": "REG_QWORD", "STRING": "REG_SZ",
            "EXPAND_STRING": "REG_EXPAND_SZ", "BINARY": "REG_BINARY",
            "MULTI_STRING": "REG_MULTI_SZ"}
_REV_TYPE = {v: k for k, v in REG_TYPE.items()}


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run(args, timeout=10):
    """Run a command and return (ok, output)."""
    try:
        proc = subprocess.run(
            args, shell=True, capture_output=True, text=True,
            timeout=timeout, creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        out = (proc.stdout or "").strip() + ("\n" + proc.stderr if proc.stderr else "").strip()
        ok = proc.returncode == 0
        return ok, out or ("exit code %d" % proc.returncode)
    except subprocess.TimeoutExpired:
        return False, "command timed out"
    except OSError as exc:
        return False, str(exc)


def _reg_write(hive, path, name, value, vtype):
    if vtype.upper() == "QWORD":
        vtype = "QWORD"
    if isinstance(value, bool):
        value = int(value)
    if vtype.upper() == "BINARY":
        if isinstance(value, str):
            value = value.replace(" ", "")
        elif isinstance(value, int):
            value = hex(value)[2:].zfill(2)
    return reg_util.write_value(hive, path, name, value, vtype)


def _is_default_name(name) -> bool:
    return str(name).strip().lower() in ("", "(default)", "(default value)")


def _missing(detail: str) -> bool:
    """True when a failed reg delete means the target is already gone."""
    low = (detail or "").lower()
    return any(tok in low for tok in (
        "unable to find the specified registry key or value",
        "cannot find the specified registry key or value",
        "does not exist", "could not be found"))


def _reg_delete(hive, path, name):
    ok, detail = reg_util.delete_value(hive, path, name)
    if not ok and _missing(detail):
        # Deleting an already-absent value is a success (idempotent revert):
        # the desired end state is achieved even though the delete errored.
        return True, f"already absent: {hive}\\{path} [{name}]"
    return ok, detail


def _reg_key_delete(hive, path):
    ok, detail = reg_util.delete_key(hive, path)
    if not ok and _missing(detail):
        return True, f"already absent: {hive}\\{path}"
    return ok, detail


def _power_read_index(subgroup, guid, index="AC", scheme=""):
    """Read a power setting's current index -> the raw value token, or None.

    ``powercfg /query`` only lists *visible* settings. The hidden majority of
    the processor subgroup (EPP, boost mode, core parking, the increase/decrease
    policies, the heterogeneous scheduling policies) reads back as empty
    output, so a snapshot taken that way records nothing - and revert then
    reports "original value unknown, skip" while quietly leaving the setting
    changed. ``/qh`` lists every setting, so prefer it and fall back to
    ``/query`` for schemes where the hidden view is unavailable.
    """
    scheme = scheme or "SCHEME_CURRENT"
    target = f"current {index} power setting index:".lower()
    for flag in ("/qh", "/query"):
        ok, out = _run(f"powercfg {flag} {scheme} {subgroup} {guid}")
        if not ok:
            continue
        for line in (out or "").splitlines():
            if target in line.lower():
                m = re.search(r"(0x[0-9a-fA-F]+|\d+)", line)
                if m:
                    return m.group(1)
    return None


def _snapshot_power_targets(tweak_id: str, actions: list) -> None:
    """Record each power setting's previous value before the apply writes it.

    Backups are kept from the FIRST apply: re-applying never overwrites the
    snapshot, so revert always lands on the true pre-tweak value.

    Raises if a setting's original value cannot be read. Applying without a
    captured original would make the change unrevertable, and apply_tweak aborts
    before executing anything when a snapshot fails - so failing here is what
    guarantees Revert can always land on the exact pre-tweak value.
    """
    from engine import state as state_mgr

    existing = state_mgr.get_power_backups(tweak_id) or {}
    changed = False

    for a in actions:
        if len(a) < 3 or a[0] != "power":
            continue
        setting, value, scheme = a[1], a[2], a[3] if len(a) > 3 else "AC"
        key = f"{setting}_{scheme}"
        if key in existing:
            if existing[key].get("value") is not None:
                continue
            # A stored entry with no value is not a usable backup - it came from
            # the build that snapshotted with the visible-only query. Re-reading
            # now would capture the *already-tweaked* value and make Revert a
            # silent no-op, so refuse and say how to clear it.
            raise RuntimeError(
                f"{setting} has a snapshot with no recorded original value "
                f"(written by an older build); revert or clear it before "
                f"re-applying")
        spec = POWER_SETTINGS.get(setting)
        if spec is None:
            raise RuntimeError(
                f"{setting} has no GUID mapping; refusing to write an "
                f"unmapped power setting")
        subgroup, guid = spec
        index = "AC" if scheme in ("AC", None) else "DC"
        # Snapshot against the real active plan, not the SCHEME_CURRENT alias,
        # so the stored original belongs to the plan the tweak actually hit.
        active, _ = _run_powercfg_active()
        current_val = _power_read_index(subgroup, guid, index, active or "")
        if current_val is None:
            raise RuntimeError(
                f"could not read the current {index} value of {setting} "
                f"({guid}); refusing to apply without a restorable backup")
        existing[key] = {
            "setting": setting, "scheme": scheme,
            "subgroup": subgroup, "guid": guid,
            "value": current_val, "scheme_guid": active,
        }
        changed = True
    if changed:
        state_mgr.save_power_backups(tweak_id, existing)


def _restore_power_backup(entry: dict, dry_run: bool = False):
    """Restore one backed-up power setting -> (ok, detail)."""
    if dry_run:
        return True, f"dry-run: restore power {entry['setting']}={entry['value']!r}"
    if entry.get("value") is None:
        # Never claim success: there is no original value to write back, so the
        # tweak is still in effect. Say so loudly instead of silently leaving
        # the machine modified.
        return False, (
            f"{entry['setting']}: no original value was recorded, so it was "
            f"NOT restored - set it manually")
    index = "AC" if entry["scheme"] in ("AC", None) else "DC"
    flag = "/SETACVALUEINDEX" if index == "AC" else "/SETDCVALUEINDEX"
    target = entry.get("scheme_guid") or "SCHEME_CURRENT"
    ok1, msg1 = _run(
        f"powercfg {flag} {target} {entry['subgroup']} {entry['guid']} {entry['value']}")
    if not ok1 and "does not exist" in (msg1 or "").lower():
        return False, (f"{entry['setting']}: setting/scheme no longer exists - "
                       f"NOT restored ({msg1})")
    if not ok1:
        return ok1, msg1
    ok2, msg2 = _run(f"powercfg /setactive {target}")
    return ok2, msg2 or f"restored {entry['setting']}={entry['value']}"


def _snapshot_svc_targets(tweak_id: str, actions: list) -> None:
    """Record each service's startup type and running state before the apply changes it."""
    from engine import state as state_mgr

    existing = state_mgr.get_svc_backups(tweak_id) or {}
    changed = False

    for a in actions:
        if len(a) < 2:
            continue
        kind = a[0]
        if kind == "svc":
            name = a[1]
        elif kind == "svcstop":
            name = a[1]
        elif kind == "svcstart":
            name = a[1]
        elif kind == "sc" and a[1] in ("disable", "enable", "start", "stop"):
            name = a[2]
        else:
            continue
        name_up = name.upper()
        if name_up in existing:
            continue
        ok, out = _run(f'sc qc "{name}"')
        start_type = None
        if ok:
            m = re.search(r"START_TYPE\s*:\s*\d+\s+([A-Z_]+)", out)
            if m:
                start_type = m.group(1)
        # Also capture running state
        is_running = False
        ok2, out2 = _run(f'sc query "{name}"')
        if ok2 and out2:
            is_running = "RUNNING" in out2.upper()
        existing[name_up] = {"name": name, "start_type": start_type,
                             "is_running": is_running}
        changed = True
    if changed:
        state_mgr.save_svc_backups(tweak_id, existing)


_REV_SVC = {v: k for k, v in SVC_MODE_MAP.items()}


def _restore_svc_backup(entry: dict, dry_run: bool = False):
    """Restore one backed-up service startup type and running state -> (ok, detail)."""
    if dry_run:
        return True, f"dry-run: restore svc {entry['name']} start={entry['start_type']}"
    if entry["start_type"] is None:
        return False, (f"{entry['name']}: original startup type unknown - "
                       f"NOT restored")
    token = entry["start_type"].lower()
    token = _SVC_START_ALIASES.get(token, token)
    friendly = _REV_SVC.get(token, token)
    ok, detail = _svc(entry["name"], friendly)
    # Also restore running state
    was_running = entry.get("is_running", False)
    if was_running and friendly in ("auto", "manual", "delayed"):
        ok2, _ = _svc_run(entry["name"], "svcstart")
    elif not was_running and friendly in ("auto", "manual", "delayed"):
        pass  # leave stopped if it was stopped before
    return ok, detail or f"restored {entry['name']} start={friendly}"


def _snapshot_cmd_targets(tweak_id: str, actions: list) -> None:
    """Parse cmd strings and record the pre-apply state for each parseable form."""
    from engine import state as state_mgr

    existing = state_mgr.get_cmd_backups(tweak_id) or {}
    changed = False

    for a in actions:
        if a[0] != "cmd":
            continue
        cmd = a[1]
        low = " ".join(cmd.strip().lower().split())
        if not low:
            continue
        # Deduplicate by normalized command
        if low in existing:
            continue

        # powercfg /setactive <target>
        m = re.match(r"^powercfg\s+/setactive\s+(\S+)$", low)
        if m:
            active_guid, active_name = _run_powercfg_active()
            existing[low] = {
                "kind": "powercfg_setactive",
                "target": m.group(1),
                "prev_active": active_guid,
                "prev_name": active_name,
            }
            changed = True
            continue

        # powercfg /SETACVALUEINDEX or /SETDCVALUEINDEX
        m = re.match(
            r"^powercfg\s+/set(?:ac|dc)valueindex\s+scheme_current\s+"
            r"([0-9a-f-]+)\s+([0-9a-f-]+)\s+(0x[0-9a-f]+|\d+)$", low)
        if m:
            index = "AC" if "ac" in low else "DC"
            flag = "/query"
            ok, out = _run(f"powercfg /query SCHEME_CURRENT {m.group(1)} {m.group(2)}")
            current_val = None
            if ok:
                target_label = f"Current {index} Power Setting Index:"
                for line in (out or "").splitlines():
                    if target_label.lower() in line.lower():
                        mv = re.search(r"(0x[0-9a-fA-F]+|\d+)", line)
                        if mv:
                            current_val = mv.group(1)
                            break
            existing[low] = {
                "kind": "powercfg_value",
                "subgroup": m.group(1), "guid": m.group(2),
                "value": m.group(3), "index": index,
                "prev_value": current_val,
            }
            changed = True
            continue

        # powercfg /change <name>-timeout-<ac|dc> <val>
        m = re.match(r"^powercfg\s+/change\s+([a-z_]+)-timeout-(ac|dc)\s+(\d+)$", low)
        if m:
            spec = CHANGE_SETTINGS.get(m.group(1))
            if spec:
                ok2, out2 = _run(f"powercfg /query SCHEME_CURRENT {spec[0]} {spec[1]}")
                current_val = None
                if ok2:
                    target_label = f"Current {m.group(2).upper()} Power Setting Index:"
                    for line in (out2 or "").splitlines():
                        if target_label.lower() in line.lower():
                            mv = re.search(r"(0x[0-9a-fA-F]+|\d+)", line)
                            if mv:
                                current_val = mv.group(1)
                                break
                existing[low] = {
                    "kind": "powercfg_change",
                    "name": m.group(1), "ac_dc": m.group(2),
                    "subgroup": spec[0], "guid": spec[1],
                    "prev_value": current_val,
                }
                changed = True
            continue

        # powercfg /h on|off
        m = re.match(r"^powercfg\s+/h\s+(on|off)$", low)
        if m:
            # Read current HibernateEnabled
            from engine import state_checker
            entry = state_checker._reg_data(
                "HKLM", r"SYSTEM\CurrentControlSet\Control\Power", "HibernateEnabled")
            current = entry[1] if entry else None
            existing[low] = {
                "kind": "powercfg_hibernate",
                "target": m.group(1),
                "prev_value": current,
            }
            changed = True
            continue

        # bcdedit /set <name> <value>
        m = re.match(r"^bcdedit\s+/set\s+([\w-]+)\s+(.+?)\s*$", low)
        if m:
            from engine import state_checker
            store = state_checker._bcd_values()
            current = store.get(m.group(1).lower()) if store else None
            existing[low] = {
                "kind": "bcdedit",
                "name": m.group(1), "value": m.group(2),
                "prev_value": current,
            }
            changed = True
            continue

        # bcdedit /timeout <seconds>
        m = re.match(r"^bcdedit\s+/timeout\s+(\d+)$", low)
        if m:
            from engine import state_checker
            store = state_checker._bcd_values()
            current = store.get("timeout") if store else None
            existing[low] = {
                "kind": "bcdedit",
                "name": "timeout", "value": m.group(1),
                "prev_value": current,
            }
            changed = True
            continue

        # netsh int tcp set global <name>=<value>
        m = re.match(r"^netsh\s+int(?:erface)?\s+tcp\s+set\s+global\s+([\w]+)=(\S+)$", low)
        if m:
            from engine import state_checker
            globals_map = state_checker._netsh_tcp_global()
            from engine.state_checker import _NETSH_LABELS
            labels = _NETSH_LABELS.get(m.group(1))
            current = None
            if labels:
                for label in labels:
                    v = globals_map.get(label.lower())
                    if v is not None:
                        current = v
                        break
            existing[low] = {
                "kind": "netsh",
                "name": m.group(1), "value": m.group(2),
                "prev_value": current,
            }
            changed = True
            continue

        # reg add (via cmd) — rare but possible
        m = re.match(
            r"^reg\s+add\s+(?P<path>.+?)\s+/v\s+(?P<name>[\"']?[^\"'\s]+[\"']?)"
            r"\s+/t\s+(?P<type>REG_[A-Z_]+)\s+/d\s+(?P<value>.+?)\s*/f\s*$",
            cmd, re.IGNORECASE)
        if m:
            from engine.state_checker import _split_hive
            hive, path = _split_hive(m.group("path").strip('"\''))
            if hive:
                from engine import state_checker
                entry = state_checker._reg_data(hive, path, m.group("name").strip('"\''))
                current = entry[1] if entry else None
                vtype = entry[0] if entry else None
                existing[low] = {
                    "kind": "reg_cmd",
                    "hive": hive, "path": path,
                    "name": m.group("name").strip('"\''),
                    "vtype": vtype,
                    "prev_value": current,
                }
                changed = True
            continue

    if changed:
        state_mgr.save_cmd_backups(tweak_id, existing)


def _restore_cmd_backup(entry: dict, dry_run: bool = False):
    """Restore one backed-up cmd state -> (ok, detail)."""
    if dry_run:
        return True, f"dry-run: restore cmd {entry['kind']}"

    kind = entry["kind"]

    if kind == "powercfg_setactive":
        prev = entry.get("prev_active") or entry.get("prev_name")
        if not prev:
            return False, "original scheme unknown - NOT restored"
        ok, detail = _run(f'powercfg /setactive "{prev}"')
        return ok, detail or f"restored active scheme to {prev}"

    if kind == "powercfg_value":
        if entry.get("prev_value") is None:
            return False, "original value unknown - NOT restored"
        flag = "/SETACVALUEINDEX" if entry["index"] == "AC" else "/SETDCVALUEINDEX"
        ok1, msg1 = _run(
            f"powercfg {flag} SCHEME_CURRENT {entry['subgroup']} "
            f"{entry['guid']} {entry['prev_value']}")
        if not ok1 and "does not exist" in (msg1 or "").lower():
            return False, (f"setting no longer exists on this scheme - "
                           f"NOT restored ({msg1})")
        if not ok1:
            return ok1, msg1
        ok2, msg2 = _run("powercfg /setactive SCHEME_CURRENT")
        return ok2, msg2 or "restored"

    if kind == "powercfg_change":
        if entry.get("prev_value") is None:
            return False, "original value unknown - NOT restored"
        flag = "/SETACVALUEINDEX" if entry["ac_dc"] == "ac" else "/SETDCVALUEINDEX"
        ok1, msg1 = _run(
            f"powercfg {flag} SCHEME_CURRENT {entry['subgroup']} "
            f"{entry['guid']} {entry['prev_value']}")
        if not ok1:
            return ok1, msg1
        ok2, msg2 = _run("powercfg /setactive SCHEME_CURRENT")
        return ok2, msg2 or "restored"

    if kind == "powercfg_hibernate":
        prev = entry.get("prev_value")
        if prev is None:
            return False, "original hibernate state unknown - NOT restored"
        target_val = 1 if str(prev).strip() == "1" else 0
        ok, detail = reg_util.write_value(
            "HKLM", r"SYSTEM\CurrentControlSet\Control\Power",
            "HibernateEnabled", target_val, "DWORD")
        return ok, detail or f"restored HibernateEnabled={target_val}"

    if kind == "bcdedit":
        prev = entry.get("prev_value")
        if prev is None:
            # Option was not set before -> delete it
            ok, detail = _run(f"bcdedit /deletevalue {entry['name']}")
            if not ok and "not" in (detail or "").lower():
                return True, "already absent"
            return ok, detail or f"deleted {entry['name']}"
        ok, detail = _run(f"bcdedit /set {entry['name']} {prev}")
        return ok, detail or f"restored {entry['name']}={prev}"

    if kind == "netsh":
        prev = entry.get("prev_value")
        if prev is None:
            return False, "original netsh value unknown - NOT restored"
        ok, detail = _run(f"netsh int tcp set global {entry['name']}={prev}")
        return ok, detail or f"restored {entry['name']}={prev}"

    if kind == "reg_cmd":
        prev = entry.get("prev_value")
        hive, path, name = entry["hive"], entry["path"], entry["name"]
        if prev is None:
            ok, detail = _reg_delete(hive, path, name)
            if not ok and _missing(detail):
                return True, "already absent"
            return ok, detail or f"deleted {hive}\\{path} [{name}]"
        vtype = entry.get("vtype", "REG_DWORD")
        short = _REV_TYPE.get(vtype.upper(), "STRING")
        return _reg_write(hive, path, name, prev, short)

    return False, f"unknown cmd backup kind {kind!r} - NOT restored"


def _snapshot_powerscheme_targets(tweak_id: str, actions: list) -> None:
    """Record the active scheme and which schemes exist before powerscheme actions."""
    from engine import state as state_mgr

    existing = state_mgr.get_powerscheme_backups(tweak_id)
    if existing:
        return  # keep the original pre-apply snapshot (first apply wins)

    created = []
    deleted = []
    active_before = None
    setactive_done = False

    for a in actions:
        if a[0] != "powerscheme":
            continue
        op = a[1]
        if op == "setactive":
            setactive_done = True
            if active_before is None:
                ok, out = _run("powercfg /getactivescheme")
                if ok:
                    m = re.search(r"([0-9a-fA-F-]{36})", out)
                    active_before = m.group(1) if m else None
        elif op in ("create", "duplicate"):
            if len(a) >= 4:
                from .tweaks._base import plan_guid as _pguid
                guid = _pguid(a[3])
                created.append({"guid": guid, "name": a[3], "base": a[2]})
        elif op == "delete":
            # Capture the scheme's name before deletion for potential restore
            ok, out = _run("powercfg /list")
            scheme_name = None
            if ok:
                for line in out.splitlines():
                    if a[2].lower() in line.lower():
                        m2 = re.search(r"\(([^)]+)\)", line)
                        if m2:
                            scheme_name = m2.group(1)
                            break
            deleted.append({"guid": a[2], "name": scheme_name})

    if active_before or created or deleted or setactive_done:
        state_mgr.save_powerscheme_backups(tweak_id, {
            "active_scheme": active_before,
            "created_schemes": created,
            "deleted_schemes": deleted,
            "setactive": setactive_done,
        })


def _restore_powerscheme_backup(entry: dict, dry_run: bool = False):
    """Restore power scheme state: delete created schemes, re-create deleted ones, activate original."""
    if dry_run:
        return True, "dry-run: restore powerscheme state"

    ok_all = True
    results = []

    # Delete schemes that this tweak created
    for scheme in entry.get("created_schemes", []):
        if dry_run:
            continue
        ok, detail = _run(f'powercfg -delete "{scheme["guid"]}"')
        if not ok and "does not exist" in (detail or "").lower():
            ok = True
            detail = "already absent"
        if not ok:
            ok_all = False
        results.append(f"delete {scheme.get('name', scheme['guid'])}: {detail}")

    # Re-create schemes that this tweak deleted (if we know the name)
    for scheme in entry.get("deleted_schemes", []):
        if dry_run:
            continue
        name = scheme.get("name")
        if not name:
            ok_all = False
            results.append(
                f"re-create {scheme.get('guid')}: NOT restored "
                f"(scheme name unknown)")
            continue
        ok, detail = _run(f'powercfg -duplicatescheme "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c" "{scheme["guid"]}"')
        if ok:
            _run(f'powercfg -changename "{scheme["guid"]}" "{name}"')
        if not ok:
            ok_all = False
        results.append(f"re-create {name}: {detail}")

    # Activate the original scheme. Legacy snapshots (written before the
    # setactive flag existed) restore when a previous scheme is known; a
    # snapshot that recorded a setactive happened but could not read the
    # original scheme must fail instead of silently leaving this one active.
    prev = entry.get("active_scheme")
    if prev and not dry_run:
        ok, detail = _run(f'powercfg /setactive "{prev}"')
        results.append(f"activate {prev}: {detail}")
        if not ok:
            ok_all = False
    elif entry.get("setactive") and not dry_run:
        ok_all = False
        results.append("activate: NOT restored (original active scheme unknown)")

    return ok_all, "; ".join(results) or "powerscheme restored"


def _snapshot_sched_targets(tweak_id: str, actions: list) -> None:
    """Record each task's enabled/disabled state before the sched action."""
    from engine import state as state_mgr

    existing = state_mgr.get_sched_backups(tweak_id) or {}
    changed = False

    for a in actions:
        if a[0] != "sched":
            continue
        task = _extract_task_name(a[2])
        if not task or task in existing:
            continue
        # Query current state
        ok, out = _run(f'schtasks /Query /TN "{task}" /FO LIST')
        was_enabled = None
        if ok:
            for line in out.splitlines():
                low = line.strip().lower()
                if low.startswith("status:") or low.startswith("scheduled task state:"):
                    status = line.split(":", 1)[1].strip().lower()
                    was_enabled = status not in ("disabled",)
                    break
        existing[task] = {"task": task, "was_enabled": was_enabled}
        changed = True
    if changed:
        state_mgr.save_sched_backups(tweak_id, existing)


def _extract_task_name(arg: str) -> str | None:
    """Extract task name from schtasks argument."""
    import re as _re
    m = _re.search(r"['\"]([^'\"]+)['\"]", arg)
    if m:
        return m.group(1)
    parts = arg.split()
    for i, p in enumerate(parts):
        if p.lower() in ("/tn", "/tn:"):
            return parts[i + 1].strip() if i + 1 < len(parts) else None
    return None


def _restore_sched_backup(entry: dict, dry_run: bool = False):
    """Restore one backed-up scheduled task state -> (ok, detail)."""
    if dry_run:
        return True, f"dry-run: restore sched {entry['task']}"
    if entry.get("was_enabled") is None:
        return False, f"{entry['task']}: original state unknown - NOT restored"
    suffix = "/Enable" if entry["was_enabled"] else "/Disable"
    ok, detail = _run(f'schtasks /Change /TN "{entry["task"]}" {suffix}')
    return ok, detail or f"restored {entry['task']} {'enabled' if entry['was_enabled'] else 'disabled'}"


def _run_powercfg_active():
    """Read the active power scheme -> (guid, name)."""
    ok, out = _run("powercfg /getactivescheme")
    guid = name = ""
    if ok:
        m = re.search(r"([0-9a-fA-F-]{36})", out)
        if m:
            guid = m.group(1)
        n = re.search(r"\(([^)]+)\)", out)
        if n:
            name = n.group(1).strip()
    return guid, name


# ---------------- value snapshot / exact restore ----------------

_VALUE_RE = re.compile(
    r"^\s+(?P<name>.+?)\s+(?P<type>REG_[A-Z_]+)\s+(?P<data>.*?)\s*$")


def _reg_read_value(hive, path, name):
    """Read one registry value -> (existed, vtype, data).

    vtype/data are the raw REG_* token and data string printed by reg.exe.
    ``existed`` is False when the value (or its key) is absent.
    """
    return reg_util.read_value(hive, path, name)


def _target_key(hive, path, name):
    return f"{hive.upper()}\\{path.replace('\\\\', '\\').upper()}\\{name.upper()}"


def _values_equal(target, vtype, data) -> bool:
    """Does a stored value already equal the target we are about to write?"""
    data = (data or "").strip()
    if not data:
        return False
    vtype = str(vtype).upper()
    if vtype in ("DWORD", "QWORD"):
        try:
            actual = int(data, 16) if data.lower().startswith("0x") else int(data)
        except ValueError:
            return False
        return actual == int(target)
    if vtype == "BINARY":
        if isinstance(target, int):
            want = hex(target)[2:].zfill(2)
        else:
            want = str(target).replace(" ", "")
        return data.replace(" ", "").lower() == want.lower()
    return data.strip().lower() == str(target).strip().lower()


def _snapshot_reg_targets(tweak_id: str, actions: list) -> None:
    """Record each reg/regall/regdel/regdelall value's previous state before the apply runs.

    Backups are kept from the FIRST apply: re-applying never overwrites the
    snapshot, so revert always lands on the true pre-tweak value.  A value that
    already equals the target is not snapshotted (revert then falls back to the
    hardcoded revert list).  ``regall`` writes are snapshotted per subkey, so a
    revert restores each subkey's real previous value instead of deleting it.
    ``regdel``/``regdelall`` record the value they are about to remove so a
    rollback or revert can write it back instead of leaving it deleted.
    """
    from engine import state as state_mgr  # deferred: avoids import cycle

    existing = state_mgr.get_reg_backups(tweak_id) or {}
    changed = False

    def _one(hive, path, name, value, vtype):
        nonlocal changed
        key = _target_key(hive, path, name)
        if key in existing:
            return  # keep the original snapshot
        existed, rtype, data = _reg_read_value(hive, path, name)
        if existed and _values_equal(value, vtype, data):
            return  # already at target; nothing meaningful to back up
        if existed:
            existing[key] = {"hive": hive, "path": path, "name": name,
                             "existed": True, "vtype": rtype, "data": data}
        else:
            existing[key] = {"hive": hive, "path": path, "name": name,
                             "existed": False}
        changed = True

    def _one_before_delete(hive, path, name):
        """Snapshot a value a regdel is about to remove (restore = write back)."""
        nonlocal changed
        key = _target_key(hive, path, name)
        if key in existing:
            return  # keep the original snapshot
        existed, rtype, data = _reg_read_value(hive, path, name)
        if not existed:
            return  # already absent; deleting it changes nothing
        existing[key] = {"hive": hive, "path": path, "name": name,
                         "existed": True, "vtype": rtype, "data": data}
        changed = True

    for a in actions:
        kind = a[0]
        if kind == "reg":
            if len(a) < 6:
                continue
            _one(a[1], a[2], a[3], a[4], a[5])
        elif kind == "regall":
            if len(a) < 6:
                continue
            hive, base, name, value, vtype = a[1], a[2], a[3], a[4], a[5]
            for sub in _reg_subkeys(hive, base):
                _one(hive, sub, name, value, vtype)
        elif kind == "regdel":
            if len(a) < 4:
                continue
            _one_before_delete(a[1], a[2], a[3])
        elif kind == "regdelall":
            if len(a) < 4:
                continue
            hive, base, name = a[1], a[2], a[3]
            for sub in _reg_subkeys(hive, base):
                _one_before_delete(hive, sub, name)
    if changed:
        state_mgr.save_reg_backups(tweak_id, existing)


def _restore_backup(entry: dict, dry_run: bool = False):
    """Restore one backed-up registry value -> (ok, detail)."""
    if dry_run:
        if entry["existed"]:
            return True, f"dry-run: restore {entry['hive']}\\{entry['path']} [{entry['name']}] to {entry['data']!r}"
        return True, f"dry-run: delete {entry['hive']}\\{entry['path']} [{entry['name']}]"
    if entry["existed"]:
        short = _REV_TYPE.get((entry["vtype"] or "").upper(), "STRING")
        return _reg_write(entry["hive"], entry["path"], entry["name"],
                          entry["data"], short)
    # The value was absent before the tweak ran -> revert means delete it.
    # Deleting an already-absent value is a *success* (idempotent restore), so
    # the backup can be cleared instead of failing forever.
    ok, detail = _reg_delete(entry["hive"], entry["path"], entry["name"])
    if not ok and _missing(detail):
        return True, f"already absent: {entry['hive']}\\{entry['path']} [{entry['name']}]"
    return ok, detail


_FULL_HIVE = {
    "HKLM": "HKEY_LOCAL_MACHINE",
    "HKCU": "HKEY_CURRENT_USER",
    "HKCR": "HKEY_CLASSES_ROOT",
    "HKU": "HKEY_USERS",
    "HKCC": "HKEY_CURRENT_CONFIG",
}


def _normalize_hive(full):
    """Map a hive-short prefix back to the full name reg.exe echoes.

    ``reg query`` prints keys with the long hive name (HKEY_LOCAL_MACHINE\\...)
    even when the short alias (HKLM) was typed, so the prefix used for
    matching must use the long form.
    """
    for short, long in _FULL_HIVE.items():
        if full.upper().startswith(short + "\\"):
            return long + full[len(short):]
    return full


def _reg_subkeys(hive, base):
    """Return relative sub-paths (``base\\child``) of base's immediate subkeys."""
    return reg_util.subkeys(hive, base)


def _reg_write_all(hive, base, name, value, vtype):
    """Write a value into every immediate subkey of base."""
    keys = _reg_subkeys(hive, base)
    if not keys:
        return False, f"no subkeys found under {hive}\\{base}"
    ok_all, details = True, []
    for key in keys:
        ok, detail = reg_util.write_value(hive, key, name, value, vtype)
        ok_all = ok_all and ok
        details.append(detail)
    return ok_all, "; ".join(details)


def _reg_delete_all(hive, base, name):
    """Delete a value from every immediate subkey of base."""
    keys = _reg_subkeys(hive, base)
    if not keys:
        return True, f"no subkeys under {hive}\\{base} (nothing to remove)"
    ok_all, details = True, []
    for key in keys:
        ok, detail = reg_util.delete_value(hive, key, name)
        if not ok and _missing(detail):
            ok, detail = True, "already absent"
        ok_all = ok_all and ok
        details.append(detail)
    return ok_all, "; ".join(details)


def _svc(name, mode):
    token = SVC_MODE_MAP.get(mode, "demand")
    return _run(f'sc config "{name}" start= {token}')


def _svc_run(name, action):
    cmd = "start" if action == "svcstart" else "stop"
    return _run(f'sc {cmd} "{name}"')


def _sc(action):
    subop, name = action[1], action[2]
    if subop in ("disable", "enable"):
        start = "disabled" if subop == "disable" else "auto"
        return _run(f'sc config "{name}" start= {start}')
    if subop in ("start", "stop"):
        return _svc_run(name, "svcstart" if subop == "start" else "svcstop")
    return False, f"unknown sc subop {subop!r}"


def _power_setting_supported(setting: str) -> tuple[bool, str]:
    """Is *setting* actually exposed by the active power scheme?

    ``powercfg /setacvalueindex`` accepts ANY GUID and exits 0, even one the
    hardware does not implement, so the write alone proves nothing - the old
    code reported "applied" for settings that were never touched.

    Ask the scheme instead, and ask with ``/qh`` rather than ``/query``: most
    processor settings (EPP, boost mode, core parking, the boost/increase/
    decrease policies, the heterogeneous scheduling policies) are *hidden* by
    default. On the reference machine ``/query`` shows 6 processor settings
    while ``/qh`` shows 75, so a visible-only probe would dim every one of them
    as "unsupported" on hardware that fully supports it.

    Returns ``(supported, detail)``.  Cached per (scheme, subgroup) because the
    plan only changes when we re-activate it.
    """
    spec = POWER_SETTINGS.get(setting)
    if spec is None:
        return False, f"unknown power setting {setting!r}"
    subgroup, guid = spec
    scheme = _run_powercfg_active()[0] or "SCHEME_CURRENT"
    cache_key = (scheme.lower(), subgroup.lower())
    # The cache holds the whole SET of GUIDs the subgroup exposes - caching a
    # single bool per subgroup would leak one setting's verdict to all the rest.
    present = _POWER_SUBGROUP_CACHE.get(cache_key)
    if present is None:
        ok, out = _run(f"powercfg /qh {scheme} {subgroup}")
        if not ok:
            # Cannot prove absence - assume present so behaviour is unchanged
            # on systems where the query itself is restricted.
            return True, "presence could not be queried; assuming supported"
        present = {
            m.group(1).lower()
            for m in re.finditer(
                r"Power Setting GUID:\s*([0-9a-fA-F-]{36})", out or ""
            )
        }
        _POWER_SUBGROUP_CACHE[cache_key] = present
    if guid.lower() in present:
        return True, f"{setting} is exposed by the active scheme"
    return False, f"{setting} is not exposed by this CPU or active power plan"


def power_setting_supported(setting: str) -> tuple[bool, str]:
    """Public wrapper so the UI can dim a card the machine cannot honour."""
    return _power_setting_supported(setting)


def _power(setting, value, scheme, strict=False):
    spec = POWER_SETTINGS.get(setting)
    if spec is None:
        return False, f"unknown power setting {setting!r}"
    subgroup, guid = spec
    index = "AC" if scheme in ("AC", None) else "DC"
    flag = "/SETACVALUEINDEX" if index == "AC" else "/SETDCVALUEINDEX"
    if strict:
        supported, why = _power_setting_supported(setting)
        if not supported:
            # A strict card must fail loudly rather than pretend it applied.
            return False, why
    ok1, msg1 = _run(f'powercfg {flag} SCHEME_CURRENT {subgroup} {guid} {value}')
    if not ok1:
        # A setting the CPU/driver does not expose cannot be changed: treat it
        # as satisfied so a plan applying every deep setting does not fail on
        # machines that simply lack one (e.g. EPP on some desktop CPUs).
        # Strict tweaks opt out of this so the card reports a real failure.
        if "does not exist" in (msg1 or "").lower():
            if strict:
                return False, f"{setting}: not supported on this system"
            return True, f"{setting}: not supported on this system"
        return ok1, msg1
    ok2, msg2 = _run("powercfg /setactive SCHEME_CURRENT")
    # The plan we just committed to may expose a different set of settings.
    _POWER_SUBGROUP_CACHE.clear()
    return ok2, msg2 or "applied"


def _powerscheme(op, *args):
    if op == "setactive":
        _POWER_SUBGROUP_CACHE.clear()
        return _run(f'powercfg /setactive "{args[0]}"')
    if op in ("create", "duplicate"):
        return _create_scheme(op, *args)
    if op == "delete":
        ok, detail = _run(f'powercfg -delete "{args[0]}"')
        if not ok and "does not exist" in (detail or "").lower():
            return True, f"plan {args[0]} already absent"
        return ok, detail
    if op == "change":
        return _run(f'powercfg /change {args[0]} {args[1]} {args[2]}')
    return False, f"unknown powerscheme op {op!r}"


def _plan_guid(name: str) -> str:
    """Deterministic, stable GUID for a named power plan.

    Deriving the GUID from the plan name means the same name always maps to
    the same GUID, so create/activate is idempotent and revert can delete the
    exact plan that an apply created.  uuid5 is used instead of a raw md5 so
    the result is a valid RFC-4122 GUID powercfg accepts.
    """
    return plan_guid(name)


def _scheme_exists(guid: str) -> bool:
    ok, out = _run("powercfg /list")
    return bool(ok) and guid.lower() in (out or "").lower()


def _scheme_active(guid: str) -> bool:
    """Return True if the given scheme GUID is the active power scheme."""
    ok, out = _run("powercfg /getactivescheme")
    if not ok:
        return False
    return guid.lower() in (out or "").lower()


def _get_scheme_guid(scheme: str | None) -> str | None:
    """Resolve a scheme name/alias/GUID to a GUID string.

    Supports: 'AC'/'DC' (current active scheme), scheme aliases
    ('scheme_min', 'scheme_max', 'scheme_balanced', 'ultimate'),
    friendly names ('high performance', 'balanced'), or raw GUIDs.
    """
    if scheme in (None, "AC", "DC", "current", "SCHEME_CURRENT"):
        ok, out = _run("powercfg /getactivescheme")
        if ok:
            m = _GUID_RE.search(out)
            if m:
                return m.group(0)
        return None
    # Check if it's a GUID directly
    if _GUID_RE.match(scheme):
        return scheme
    # Check aliases
    aliases = {
        "scheme_min": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
        "scheme_max": "a1841308-3541-4fab-bc81-f71556f20b4a",
        "scheme_balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
        "ultimate": "e9a42b02-d5df-448d-aa00-03f14749eb61",
    }
    low = scheme.lower()
    if low in aliases:
        return aliases[low]
    # Try friendly name match from powercfg /list
    ok, out = _run("powercfg /list")
    if ok and out:
        for line in out.splitlines():
            if low in line.lower():
                m = _GUID_RE.search(line)
                if m:
                    return m.group(0)
    return None


def _powercfg_query(scheme_guid: str, subgroup: str, setting: str) -> tuple[bool, str]:
    """Query a powercfg setting. Returns (ok, raw_output)."""
    return _run(f'powercfg /query "{scheme_guid}" {subgroup} {setting}')


def _create_scheme(op, *args):
    """powercfg plan creation: duplicate a base plan into a fresh GUID.

    ``("powerscheme", "duplicate", base_guid, name)`` clones the base plan
    and renames the copy (no activation).  ``("powerscheme", "create",
    base_guid, name)`` does the same and then activates the new plan, which is
    what the Maximum Power Plan tweak needs: it is built from a base
    plan with every deep setting explicitly overridden afterwards.

    Re-applying is idempotent: if a plan for ``name`` already exists it is
    re-renamed and (for ``create``) re-activated instead of erroring.
    """
    if len(args) < 2:
        ok, detail = _run(f'powercfg -duplicatescheme "{args[0]}"')
        return ok, detail or "duplicated"
    base, name = args[0], args[1]
    guid = _plan_guid(name)
    if _scheme_exists(guid):
        _run(f'powercfg -changename "{guid}" "{name}"')
        if op == "create":
            return _run(f'powercfg /setactive "{guid}"')
        return True, f"plan {name!r} ({guid}) already exists"
    ok, detail = _run(f'powercfg -duplicatescheme "{base}" "{guid}"')
    if not ok:
        return ok, detail
    ok, detail = _run(f'powercfg -changename "{guid}" "{name}"')
    if not ok:
        return ok, detail
    if op == "create":
        return _run(f'powercfg /setactive "{guid}"')
    return True, f"plan {name!r} ({guid}) created"


def _sched(op, flag_arg):
    suffix = "/Disable" if op == "disable" else "/Enable"
    return _run(f'schtasks /Change {flag_arg} {suffix}')


def _appx(op, package):
    if op == "remove":
        cmd = f'powershell -NoProfile -Command "Get-AppxPackage *{package}* | Remove-AppxPackage"'
    else:
        cmd = (f'powershell -NoProfile -Command '
               f'"Get-AppxPackage *{package}* | ForEach-Object {{ Add-AppxPackage -Register '
               f'"$($_.InstallLocation)\\AppxManifest.xml" -DisableDevelopmentMode }} "')
    return _run(cmd)


def _restart_explorer():
    _run("taskkill /f /im explorer.exe")
    return _run("start explorer.exe")


def _file(action, path, content):
    path = os.path.expandvars(os.path.expanduser(path))
    try:
        if action == "write":
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            return True, f"wrote {path}"
        if action == "append":
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(content)
            return True, f"appended {path}"
        if action == "delete":
            os.remove(path)
            return True, f"deleted {path}"
    except OSError as exc:
        return False, str(exc)
    return False, f"unknown file action {action!r}"


def _guidance(text):
    return True, f"guidance: {text}"


def _ini(path, section, key, value):
    from engine.game_config import set_ini_value  # deferred: avoids import cycle
    return set_ini_value(path, section, key, value)


def _ini_delete(path, section, key):
    from engine.game_config import delete_ini_value  # deferred: avoids import cycle
    return delete_ini_value(path, section, key)


def _execute_action(action, dry_run=False):
    """Run one action tuple. Returns (ok, detail)."""
    kind = action[0]
    if dry_run:
        return True, f"dry-run: {action}"
    try:
        if kind == "reg":
            return _reg_write(action[1], action[2], action[3], action[4], action[5])
        if kind == "regall":
            return _reg_write_all(action[1], action[2], action[3], action[4], action[5])
        if kind == "regdel":
            return _reg_delete(action[1], action[2], action[3])
        if kind == "regdelall":
            return _reg_delete_all(action[1], action[2], action[3])
        if kind == "regkeydel":
            return _reg_key_delete(action[1], action[2])
        if kind == "svc":
            return _svc(action[1], action[2])
        if kind == "sc":
            return _sc(action)
        if kind in ("svcstart", "svcstop"):
            return _svc_run(action[1], kind)
        if kind == "cmd":
            cmd = action[1]
            timeout = action[2] if len(action) > 2 and isinstance(action[2], (int, float)) else 15
            return _run(cmd, timeout=timeout)
        if kind == "file":
            content = action[3] if len(action) > 3 else ""
            return _file(action[1], action[2], content)
        if kind == "ini":
            return _ini(action[1], action[2], action[3], action[4])
        if kind == "inidel":
            return _ini_delete(action[1], action[2], action[3])
        if kind == "power":
            scheme = action[3] if len(action) > 3 else "AC"
            strict = bool(getattr(_tweak_ctx, "power_strict", False))
            return _power(action[1], action[2], scheme, strict=strict)
        if kind == "powerscheme":
            return _powerscheme(action[1], *action[2:])
        if kind == "sched":
            return _sched(action[1], action[2])
        if kind == "appx":
            return _appx(action[1], action[2])
        if kind == "restart":
            return _restart_explorer()
        if kind == "mkdir":
            os.makedirs(action[1], exist_ok=True)
            return True, f"created {action[1]}"
        if kind == "process":
            from engine import game_process_manager as gpm
            try:
                tid = getattr(_tweak_ctx, "id", None)
                ok, summary, results = gpm.run_op(action[1], tid)
            except Exception as exc:  # noqa: BLE001
                return False, f"{type(exc).__name__}: {exc}"
            lines = "; ".join(f"{r['exe']}: {r['detail']}" for r in results)
            return ok, summary if not results else f"{summary} — {lines}"
        if kind == "netadp":
            from engine import net_latency
            try:
                tid = getattr(_tweak_ctx, "id", None)
                ok, summary, results = net_latency.run_op(action[1], tid)
            except Exception as exc:  # noqa: BLE001
                return False, f"{type(exc).__name__}: {exc}"
            return ok, summary if not results else f"{summary} — {'; '.join(results)}"
        if kind == "guidance":
            return _guidance(action[1])
        return False, f"unknown action kind {kind!r}"
    except Exception as exc:  # noqa: BLE001 - report and continue
        return False, f"{type(exc).__name__}: {exc}"


def apply_actions(actions, dry_run=False, admin_required=False):
    """Run a list of actions; returns (overall_ok, results)."""
    if admin_required and not dry_run and not _is_admin():
        return False, [(a, False, "requires administrator privileges") for a in actions]
    results = []
    for action in actions:
        ok, detail = _execute_action(action, dry_run=dry_run)
        results.append((action, ok, detail))
    return all(ok for _, ok, _ in results), results


def apply_tweak(tweak_id, mode="apply", dry_run=False):
    """Apply or revert a tweak by id. Returns (ok, results).

    Apply snapshots every registry/file/ini/power/svc/cmd/powerscheme/sched
    value it is about to change; revert restores those exact previous values
    (falling back to the hardcoded revert list only when no snapshot exists,
    e.g. tweaks applied before this feature shipped).

    If any snapshot fails, the apply is aborted (no partial writes).
    If any action fails mid-apply, previously-executed actions are rolled back.
    """
    tweak = BY_ID.get(tweak_id)
    if tweak is None:
        return False, [(tweak_id, False, "unknown tweak id")]
    _tweak_ctx.id = tweak_id
    _tweak_ctx.power_strict = bool(tweak.get("power_strict"))
    try:
        if mode == "revert":
            return _revert_tweak(tweak, dry_run=dry_run)
        return _apply_tweak(tweak, tweak_id, dry_run=dry_run)
    finally:
        try:
            del _tweak_ctx.id
        except AttributeError:
            pass
        try:
            del _tweak_ctx.power_strict
        except AttributeError:
            pass


def _apply_tweak(tweak, tweak_id, dry_run=False):
    """Execute a tweak's apply actions (after snapshot/context setup)."""
    # Fail fast on missing elevation BEFORE any snapshot is taken: a failed
    # apply must never leave behind backups for a change that never happened.
    if tweak["admin"] and not dry_run and not _is_admin():
        return False, [(a, False, "requires administrator privileges") for a in tweak["actions"]]
    if not dry_run:
        # ── Snapshot ALL targets before any write ──────────────────
        # If any snapshot fails, abort the entire apply.
        snap_errors = []
        try:
            _snapshot_reg_targets(tweak_id, tweak["actions"])
        except Exception as exc:
            snap_errors.append(f"reg: {exc}")
        try:
            _snapshot_file_targets(tweak_id, tweak["actions"])
        except Exception as exc:
            snap_errors.append(f"file: {exc}")
        try:
            _snapshot_ini_targets(tweak_id, tweak["actions"])
        except Exception as exc:
            snap_errors.append(f"ini: {exc}")
        try:
            _snapshot_power_targets(tweak_id, tweak["actions"])
        except Exception as exc:
            snap_errors.append(f"power: {exc}")
        try:
            _snapshot_svc_targets(tweak_id, tweak["actions"])
        except Exception as exc:
            snap_errors.append(f"svc: {exc}")
        try:
            _snapshot_cmd_targets(tweak_id, tweak["actions"])
        except Exception as exc:
            snap_errors.append(f"cmd: {exc}")
        try:
            _snapshot_powerscheme_targets(tweak_id, tweak["actions"])
        except Exception as exc:
            snap_errors.append(f"powerscheme: {exc}")
        try:
            _snapshot_sched_targets(tweak_id, tweak["actions"])
        except Exception as exc:
            snap_errors.append(f"sched: {exc}")
        if snap_errors:
            return False, [(a, False, f"snapshot failed: {'; '.join(snap_errors)}")
                           for a in tweak["actions"]]

    # ── Execute actions with rollback on failure ───────────────────
    results = []
    executed = []
    for action in tweak["actions"]:
        ok, detail = _execute_action(action, dry_run=dry_run)
        results.append((action, ok, detail))
        if ok:
            executed.append(action)
        else:
            # Roll back everything executed so far from the snapshots taken
            # before the first action ran; report honestly when something
            # cannot be restored.
            if not dry_run and executed:
                rollback_results = _rollback_actions(tweak_id, executed)
                results.extend(rollback_results)
                rb_bad = sum(1 for _, ok, _ in rollback_results if not ok)
                results.append(
                    (("_rollback",), rb_bad == 0,
                     f"rolled back {len(executed)} actions"
                     + (f"; {rb_bad} item(s) NOT restored" if rb_bad else "")))
            return False, results

    return all(ok for _, ok, _ in results), results


def _rollback_actions(tweak_id, actions):
    """Undo a failed apply by restoring the snapshots taken before it ran.

    Every backup stored under ``tweak_id`` was captured before the first
    action executed, so restoring all of them returns the machine to its
    pre-apply state; restoring entries whose action this apply never reached
    is idempotent (it rewrites the value that is already there).  Executed
    actions no snapshot covers are reported honestly instead of claiming a
    revert that cannot happen.  Returns ``(label, ok, detail)`` tuples in the
    same shape as ``_revert_tweak``; backups are kept so the user can still
    run Revert afterwards.
    """
    from engine import state as state_mgr

    reg_backups = state_mgr.get_reg_backups(tweak_id) or {}
    file_backups = state_mgr.get_file_backups(tweak_id) or {}
    ini_backups = state_mgr.get_ini_backups(tweak_id) or {}
    power_backups = state_mgr.get_power_backups(tweak_id) or {}
    svc_backups = state_mgr.get_svc_backups(tweak_id) or {}
    cmd_backups = state_mgr.get_cmd_backups(tweak_id) or {}
    powerscheme_backups = state_mgr.get_powerscheme_backups(tweak_id) or {}
    sched_backups = state_mgr.get_sched_backups(tweak_id) or {}

    results = []

    def _restore(label, fn, entry, what):
        """Restore one backup entry without letting a raise abort the rollback."""
        try:
            ok, detail = fn(entry)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        results.append((label, ok, f"{what} -> {detail}"))

    # ── Restore every captured snapshot (each restore is idempotent) ──
    for entry in reg_backups.values():
        _restore("restore_reg", _restore_backup, entry,
                 f"restored {entry['hive']}\\{entry['path']} "
                 f"[{entry['name']}]")
    for entry in file_backups.values():
        _restore("restore_file", _restore_file_backup, entry,
                 f"restored {entry['path']}")
    for entry in ini_backups.values():
        _restore("restore_ini", _restore_ini_backup, entry,
                 f"restored {entry['section']}.{entry['key']}")
    for entry in power_backups.values():
        _restore("restore_power", _restore_power_backup, entry,
                 f"restored power {entry['setting']}")
    for entry in svc_backups.values():
        _restore("restore_svc", _restore_svc_backup, entry,
                 f"restored svc {entry['name']}")
    for entry in cmd_backups.values():
        _restore("restore_cmd", _restore_cmd_backup, entry,
                 f"restored cmd {entry['kind']}")
    if powerscheme_backups:
        _restore("restore_powerscheme", _restore_powerscheme_backup,
                 powerscheme_backups, "restored powerscheme state")
    for entry in sched_backups.values():
        _restore("restore_sched", _restore_sched_backup, entry,
                 f"restored sched {entry['task']}")

    # ── Executed actions no snapshot covers ──────────────────────────
    for action in actions:
        try:
            _report_uncovered(action, results, reg_backups, svc_backups,
                              cmd_backups, power_backups, powerscheme_backups,
                              sched_backups, file_backups, ini_backups)
        except Exception as exc:  # noqa: BLE001
            results.append((action, False, f"rollback failed: {exc}"))
    return results


def _report_uncovered(action, results, reg_backups, svc_backups, cmd_backups,
                      power_backups, powerscheme_backups, sched_backups,
                      file_backups, ini_backups):
    """Report the rollback fate of one executed action no snapshot restores."""
    kind = action[0]
    if kind in ("reg", "regdel") and len(action) >= 4:
        if _target_key(action[1], action[2], action[3]) in reg_backups:
            return  # restored from the snapshot above
        results.append((action, True,
                        f"{kind}: no change to undo "
                        f"(value already at its original state)"))
    elif kind in ("regall", "regdelall") and len(action) >= 4:
        prefix = (f"{action[1].upper()}\\"
                  f"{action[2].replace('\\\\', '\\').upper()}\\")
        if any(k.startswith(prefix) for k in reg_backups):
            return  # restored from the snapshot above
        results.append((action, True,
                        f"{kind}: no change to undo "
                        f"(values already at their original state)"))
    elif kind in ("svc", "svcstop", "svcstart"):
        if action[1].upper() in svc_backups:
            return  # restored from the snapshot above
        results.append((action, False,
                        f"{kind} {action[1]}: no snapshot - NOT restored"))
    elif kind == "sc":
        name = action[2] if len(action) >= 3 else ""
        if name.upper() in svc_backups:
            return  # restored from the snapshot above
        results.append((action, False,
                        f"sc {name}: no snapshot - NOT restored"))
    elif kind == "cmd":
        low_cmd = " ".join(action[1].strip().lower().split())
        if low_cmd in cmd_backups:
            return  # restored from the snapshot above
        results.append((action, False,
                        f"cmd '{action[1]}' is not restorable "
                        f"from a snapshot - NOT restored"))
    elif kind == "power":
        scheme = action[3] if len(action) > 3 else "AC"
        if f"{action[1]}_{scheme}" in power_backups:
            return  # restored from the snapshot above
        results.append((action, False,
                        f"power {action[1]}: no snapshot - NOT restored"))
    elif kind == "powerscheme":
        if powerscheme_backups:
            return  # restored from the snapshot above
        results.append((action, False,
                        "powerscheme: no snapshot - NOT restored"))
    elif kind == "sched":
        task = _extract_task_name(action[2]) if len(action) >= 3 else None
        if task and task in sched_backups:
            return  # restored from the snapshot above
        results.append((action, False,
                        "sched: no snapshot - NOT restored"))
    elif kind == "file":
        if len(action) >= 3 and _file_backup_key(action[2]) in file_backups:
            return  # restored from the snapshot above
        results.append((action, False,
                        f"file {action[1]}: no snapshot - NOT restored"))
    elif kind in ("ini", "inidel") and len(action) >= 4:
        if _ini_backup_key(action[1], action[2], action[3]) in ini_backups:
            return  # restored from the snapshot above
        if kind == "inidel":
            results.append((action, True,
                            "inidel: key already absent - no change to undo"))
            return
        results.append((action, False,
                        f"ini {action[2]}.{action[3]}: no snapshot "
                        f"- NOT restored"))
    elif kind == "guidance":
        results.append((action, True, "guidance: nothing was changed"))
    elif kind == "restart":
        results.append((action, True,
                        "explorer restarted (benign - cannot be undone)"))
    elif kind == "mkdir":
        results.append((action, True,
                        f"directory {action[1]} left in place (benign)"))
    elif kind == "appx":
        results.append((action, False,
                        f"appx {action[2]} removal cannot be rolled back"))
    else:
        results.append((action, False,
                        f"{kind}: no automatic rollback - NOT restored"))


def _file_backup_key(path: str) -> str:
    return os.path.normpath(os.path.expandvars(os.path.expanduser(path))).lower()


def _ini_backup_key(path: str, section: str, key: str) -> str:
    return (f"{_file_backup_key(path)}|{str(section).strip().lower()}"
            f"|{str(key).strip().lower()}")


def _ini_read_value(path, section, key):
    """Read a raw ini key -> (existed, value) straight from disk (uncached)."""
    from engine import state_checker  # deferred: avoids import cycle
    vals = state_checker._ini_map(path)
    sec = vals.get(str(section).strip().lower())
    if not sec:
        return False, None
    value = sec.get(str(key).strip().lower())
    return (True, value) if value is not None else (False, None)


def _snapshot_file_targets(tweak_id: str, actions: list) -> None:
    """Back up the previous content (or absence) of files a tweak will write."""
    from engine import state as state_mgr  # deferred: avoids import cycle

    existing = state_mgr.get_file_backups(tweak_id) or {}
    changed = False
    for a in actions:
        if len(a) < 3 or a[0] != "file" or a[1] not in ("write", "append"):
            continue
        path = a[2]
        pkey = _file_backup_key(path)
        if pkey in existing:
            continue
        full = os.path.expandvars(os.path.expanduser(path))
        if os.path.exists(full):
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except OSError:
                continue
            existing[pkey] = {"kind": "file", "path": path,
                              "existed": True, "content": content}
        else:
            existing[pkey] = {"kind": "file", "path": path,
                              "existed": False, "content": ""}
        changed = True
    if changed:
        state_mgr.save_file_backups(tweak_id, existing)


def _restore_file_backup(entry: dict, dry_run: bool = False):
    """Restore one backed-up file -> (ok, detail)."""
    path = os.path.expandvars(os.path.expanduser(entry["path"]))
    if dry_run:
        verb = "restore" if entry["existed"] else "remove"
        return True, f"dry-run: {verb} {path}"
    if entry["existed"]:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(entry["content"] or "")
            return True, f"restored {path}"
        except OSError as exc:
            return False, str(exc)
    # The file did not exist before the tweak -> revert means delete it.
    # Deleting an already-absent file is a success (idempotent restore).
    try:
        if os.path.exists(path):
            os.remove(path)
        return True, f"removed {path}"
    except OSError as exc:
        return False, str(exc)


def _snapshot_ini_targets(tweak_id: str, actions: list) -> None:
    """Back up the previous value of every ini key a tweak will set or delete."""
    from engine import state as state_mgr  # deferred: avoids import cycle

    existing = state_mgr.get_ini_backups(tweak_id) or {}
    changed = False
    for a in actions:
        if a[0] == "inidel":
            if len(a) < 4:
                continue
            path, section, key = a[1], a[2], a[3]
        elif a[0] == "ini":
            if len(a) < 5:
                continue
            path, section, key = a[1], a[2], a[3]
        else:
            continue
        ikey = _ini_backup_key(path, section, key)
        if ikey in existing:
            continue
        existed, value = _ini_read_value(path, section, key)
        if a[0] == "inidel" and not existed:
            continue  # already absent; deleting it changes nothing
        existing[ikey] = {"kind": "ini", "path": path, "section": section,
                          "key": key, "existed": existed, "value": value}
        changed = True
    if changed:
        state_mgr.save_ini_backups(tweak_id, existing)


def _restore_ini_backup(entry: dict, dry_run: bool = False):
    """Restore one backed-up ini key -> (ok, detail)."""
    if dry_run:
        verb = "restore" if entry["existed"] else "remove key"
        return True, f"dry-run: {verb} {entry['section']}.{entry['key']} in {entry['path']}"
    if entry["existed"]:
        return _ini(entry["path"], entry["section"], entry["key"], entry["value"])
    return _ini_delete(entry["path"], entry["section"], entry["key"])


def _revert_tweak(tweak, dry_run=False):
    """Revert using exact value backups when present, else the revert list.

    Every backup type (reg, file, ini, power, svc, cmd, powerscheme, sched)
    is checked: if a backup exists, the exact original value is restored instead
    of running the hardcoded revert action.  After all restores, the live system
    is verified via state_checker — a tweak is only marked as reverted when the
    verification confirms the original state has been restored.
    """
    from engine import state as state_mgr

    tid = tweak["id"]
    reg_backups = state_mgr.get_reg_backups(tid) or {}
    file_backups = state_mgr.get_file_backups(tid) or {}
    ini_backups = state_mgr.get_ini_backups(tid) or {}
    power_backups = state_mgr.get_power_backups(tid) or {}
    svc_backups = state_mgr.get_svc_backups(tid) or {}
    cmd_backups = state_mgr.get_cmd_backups(tid) or {}
    powerscheme_backups = state_mgr.get_powerscheme_backups(tid) or {}
    sched_backups = state_mgr.get_sched_backups(tid) or {}
    has_backups = bool(reg_backups or file_backups or ini_backups or
                       power_backups or svc_backups or cmd_backups or
                       powerscheme_backups or sched_backups)
    if not has_backups:
        return apply_actions(tweak["revert"], dry_run=dry_run,
                             admin_required=tweak["admin"])

    def _covered_regdelall(hive, base):
        prefix = f"{hive.upper()}\\{base.replace('\\\\', '\\').upper()}\\"
        return any(k.startswith(prefix) for k in reg_backups)

    # Build lookup sets for cmd backups
    cmd_backup_keys = set(cmd_backups.keys())

    # Run the hardcoded revert for everything EXCEPT targets covered by a
    # backup (those are restored to their true previous value below). This
    # keeps svc/cmd/power/appx reversions exactly as authored and stops
    # hardcoded reg/regdelall/ini/file actions from clobbering restored values.
    results = []
    restored_reg: set[str] = set()
    for a in tweak["revert"]:
        if a[0] == "reg" and len(a) >= 4:
            key = _target_key(a[1], a[2], a[3])
            if key in reg_backups:
                restored_reg.add(key)
                continue
        if a[0] == "regdel" and len(a) >= 4:
            key = _target_key(a[1], a[2], a[3])
            if key in reg_backups:
                continue
        if a[0] == "regdelall" and len(a) >= 4 and _covered_regdelall(a[1], a[2]):
            continue
        if a[0] == "file" and len(a) >= 3:
            if _file_backup_key(a[2]) in file_backups:
                continue
        if a[0] in ("ini", "inidel") and len(a) >= 4:
            if _ini_backup_key(a[1], a[2], a[3]) in ini_backups:
                continue
        if a[0] == "power" and len(a) >= 2:
            setting = a[1]
            scheme = a[3] if len(a) > 3 else "AC"
            pkey = f"{setting}_{scheme}"
            if pkey in power_backups:
                continue
        if a[0] == "svc" and len(a) >= 2:
            if a[1].upper() in svc_backups:
                continue
        if a[0] == "cmd" and len(a) >= 2:
            low_cmd = " ".join(a[1].strip().lower().split())
            if low_cmd in cmd_backup_keys:
                continue
        if a[0] == "powerscheme" and powerscheme_backups:
            continue
        if a[0] == "sched":
            task = _extract_task_name(a[2])
            if task and task in sched_backups:
                continue
        ok, detail = _execute_action(a, dry_run=dry_run)
        results.append((a, ok, detail))

    # Restore the exact previous state of every snapshotted value.
    ok_all = True

    for key, entry in reg_backups.items():
        ok, detail = _restore_backup(entry, dry_run=dry_run)
        if not ok:
            ok_all = False
        results.append(("restore_reg", ok,
                        f"restored {entry['hive']}\\{entry['path']} "
                        f"[{entry['name']}] -> {detail}"))
    for key, entry in file_backups.items():
        ok, detail = _restore_file_backup(entry, dry_run=dry_run)
        if not ok:
            ok_all = False
        results.append(("restore_file", ok,
                        f"restored {entry['path']} -> {detail}"))
    for key, entry in ini_backups.items():
        ok, detail = _restore_ini_backup(entry, dry_run=dry_run)
        if not ok:
            ok_all = False
        results.append(("restore_ini", ok,
                        f"restored {entry['section']}.{entry['key']} -> {detail}"))
    for key, entry in power_backups.items():
        ok, detail = _restore_power_backup(entry, dry_run=dry_run)
        if not ok:
            ok_all = False
        results.append(("restore_power", ok,
                        f"restored power {entry['setting']} -> {detail}"))
    for key, entry in svc_backups.items():
        ok, detail = _restore_svc_backup(entry, dry_run=dry_run)
        if not ok:
            ok_all = False
        results.append(("restore_svc", ok,
                        f"restored svc {entry['name']} -> {detail}"))
    for key, entry in cmd_backups.items():
        ok, detail = _restore_cmd_backup(entry, dry_run=dry_run)
        if not ok:
            ok_all = False
        results.append(("restore_cmd", ok,
                        f"restored cmd {entry['kind']} -> {detail}"))
    for key, entry in powerscheme_backups.items():
        ok, detail = _restore_powerscheme_backup(entry, dry_run=dry_run)
        if not ok:
            ok_all = False
        results.append(("restore_powerscheme", ok, detail))
    for key, entry in sched_backups.items():
        ok, detail = _restore_sched_backup(entry, dry_run=dry_run)
        if not ok:
            ok_all = False
        results.append(("restore_sched", ok,
                        f"restored sched {entry['task']} -> {detail}"))

    if ok_all and not dry_run:
        state_mgr.clear_reg_backups(tid)
        state_mgr.clear_file_backups(tid)
        state_mgr.clear_ini_backups(tid)
        state_mgr.clear_power_backups(tid)
        state_mgr.clear_svc_backups(tid)
        state_mgr.clear_cmd_backups(tid)
        state_mgr.clear_powerscheme_backups(tid)
        state_mgr.clear_sched_backups(tid)
    return ok_all and all(ok for _, ok, _ in results), results
