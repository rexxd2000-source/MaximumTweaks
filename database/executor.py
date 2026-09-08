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
  guidance                   -> informational no-op

Run with ``dry_run=True`` to preview actions without touching the system.
"""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys

from .tweaks import BY_ID

# named power settings -> (subgroup GUID, setting GUID) for powercfg
POWER_SETTINGS = {
    "adaptive_brightness": (
        "7516b95f-f776-4464-8c53-06167f40cc99",          # Display subgroup
        "fbd9aa66-9553-4097-ba44-ed6e9d65eab8",          # Adaptive display brightness
    ),
    "usb_selective": (
        "2a737441-1930-4402-8d77-b2bebba308a3",          # USB settings subgroup
        "48e6b7a6-50f5-4782-a5d4-53bb8f07e226",          # USB selective suspend
    ),
    # Processor subgroup (54533251-82be-4824-96c1-47b60b740d00)
    "processor_max": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "bc5038f7-23e0-4960-96da-33abaf5935ec",
    ),
    "processor_min": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "893dee8e-2bef-41e0-89c6-b55d0929964c",
    ),
    "boost_mode": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "be337238-0d82-4146-a960-4f3749d470c7",
    ),
    "perf_increase_threshold": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "06cadf0e-64ed-448a-8927-ce7bf90eb35d",
    ),
    "perf_decrease_threshold": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "12a0ab44-fe28-4fa9-b3fb-4b64a26f8725",
    ),
    "idle_disable": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "5d76a2ca-e8c0-402f-a133-2158312c3406",
    ),
    "time_check": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "18a7d39f-c168-4f6f-b3c4-bbf17f66a4c9",
    ),
    "parking_min": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "0cc5b647-c1df-4637-891a-dec35c318583",
    ),
    "parking_max": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "ea062031-0e34-4ff1-9b6d-eb1059334028",
    ),
    # Power policy subgroup (36687f9e-e3a5-4dbf-b1dc-15eb381c6863)
    "perf_increase_policy": (
        "36687f9e-e3a5-4dbf-b1dc-15eb381c6863",
        "465e1f50-b610-473a-ab58-00d1077dc418",
    ),
    "perf_decrease_policy": (
        "36687f9e-e3a5-4dbf-b1dc-15eb381c6863",
        "8baa4a8a-14c6-4451-8e8b-14bdbd197537",
    ),
    "boost_policy": (
        "36687f9e-e3a5-4dbf-b1dc-15eb381c6863",
        "45bcc044-d885-43a2-8605-ee0ec6e96b59",
    ),
    "epp": (
        "36687f9e-e3a5-4dbf-b1dc-15eb381c6863",
        "36687f9e-e3a5-4dbf-b1dc-15eb381c6863",
    ),
}

SVC_MODE_MAP = {"auto": "auto", "manual": "demand", "disabled": "disabled",
                "boot": "boot", "system": "system", "delayed": "delayed"}

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
    token = REG_TYPE.get(vtype.upper()) or vtype.upper()
    if vtype.upper() == "BINARY":
        if isinstance(value, str):
            value = value.replace(" ", "")
        elif isinstance(value, int):
            value = hex(value)[2:].zfill(2)
    vflag = "/ve" if _is_default_name(name) else f'/v "{name}"'
    return _run(f'reg add "{hive}\\{path}" {vflag} /t {token} /d "{value}" /f')


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
    vflag = "/ve" if _is_default_name(name) else f'/v "{name}"'
    ok, detail = _run(f'reg delete "{hive}\\{path}" {vflag} /f')
    if not ok and _missing(detail):
        # Deleting an already-absent value is a success (idempotent revert):
        # the desired end state is achieved even though reg.exe errored.
        return True, f"already absent: {hive}\\{path} [{name}]"
    return ok, detail


def _reg_key_delete(hive, path):
    ok, detail = _run(f'reg delete "{hive}\\{path}" /f')
    if not ok and _missing(detail):
        return True, f"already absent: {hive}\\{path}"
    return ok, detail


# ---------------- value snapshot / exact restore ----------------

_VALUE_RE = re.compile(
    r"^\s+(?P<name>.+?)\s+(?P<type>REG_[A-Z_]+)\s+(?P<data>.*?)\s*$")


def _reg_read_value(hive, path, name):
    """Read one registry value -> (existed, vtype, data).

    vtype/data are the raw REG_* token and data string printed by reg.exe.
    ``existed`` is False when the value (or its key) is absent.
    """
    ok, out = _run(f'reg query "{hive}\\{path}" {"/ve" if _is_default_name(name) else f"/v {chr(34)}{name}{chr(34)}"}')
    if not ok:
        return False, None, None
    for line in (out or "").splitlines():
        m = _VALUE_RE.match(line)
        if m:
            mname = m.group("name").strip('"')
            if mname.lower() == str(name).lower() or (_is_default_name(name) and mname.lower() == "(default)"):
                data = m.group("data")
                if data.strip().lower() == "(value not set)":
                    return False, None, None
                return True, m.group("type"), data
    return False, None, None


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
    """Record each reg/regall value's previous state before the apply writes it.

    Backups are kept from the FIRST apply: re-applying never overwrites the
    snapshot, so revert always lands on the true pre-tweak value.  A value that
    already equals the target is not snapshotted (revert then falls back to the
    hardcoded revert list).  ``regall`` writes are snapshotted per subkey, so a
    revert restores each subkey's real previous value instead of deleting it.
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

    for a in actions:
        if len(a) < 6:
            continue
        kind = a[0]
        if kind == "reg":
            _one(a[1], a[2], a[3], a[4], a[5])
        elif kind == "regall":
            hive, base, name, value, vtype = a[1], a[2], a[3], a[4], a[5]
            for sub in _reg_subkeys(hive, base):
                _one(hive, sub, name, value, vtype)
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
    """Return fully-qualified names of base's immediate subkeys."""
    full = f"{hive}\\{base}" if not base.startswith(hive) else base
    ok, out = _run(f'reg query "{full}"')
    if not ok:
        return []
    prefix = _normalize_hive(full).upper()
    keys = []
    for line in (out or "").splitlines():
        s = line.strip().upper()
        if s.startswith(prefix + "\\") and not s.startswith(prefix + "\\\\"):
            keys.append(line.strip())
    return keys


def _reg_write_all(hive, base, name, value, vtype):
    """Write a value into every immediate subkey of base."""
    keys = _reg_subkeys(hive, base)
    if not keys:
        return False, f"no subkeys found under {hive}\\{base}"
    token = REG_TYPE.get(vtype.upper()) or vtype.upper()
    ok_all, details = True, []
    for key in keys:
        ok, detail = _run(f'reg add "{key}" /v "{name}" /t {token} /d {value} /f')
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
        ok, detail = _run(f'reg delete "{key}" /v "{name}" /f')
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


def _power(setting, value, scheme):
    spec = POWER_SETTINGS.get(setting)
    if spec is None:
        return False, f"unknown power setting {setting!r}"
    subgroup, guid = spec
    index = "AC" if scheme in ("AC", None) else "DC"
    flag = "/SETACVALUEINDEX" if index == "AC" else "/SETDCVALUEINDEX"
    ok1, msg1 = _run(f'powercfg {flag} SCHEME_CURRENT {subgroup} {guid} {value}')
    if not ok1:
        return ok1, msg1
    ok2, msg2 = _run("powercfg /setactive SCHEME_CURRENT")
    return ok2, msg2 or "applied"


def _powerscheme(op, *args):
    if op == "setactive":
        return _run(f'powercfg /setactive "{args[0]}"')
    if op == "duplicate":
        return _run(f'powercfg -duplicatescheme "{args[0]}"')
    if op == "change":
        return _run(f'powercfg /change {args[0]} {args[1]} {args[2]}')
    return False, f"unknown powerscheme op {op!r}"


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
            timeout = action[2] if len(action) > 2 and isinstance(action[2], (int, float)) else None
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
            return _power(action[1], action[2], scheme)
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

    Apply snapshots every registry value (and file/ini value) it is about to
    change; revert restores those exact previous values (falling back to the
    hardcoded revert list only when no snapshot exists, e.g. tweaks applied
    before this feature shipped).
    """
    tweak = BY_ID.get(tweak_id)
    if tweak is None:
        return False, [(tweak_id, False, "unknown tweak id")]
    if mode == "revert":
        return _revert_tweak(tweak, dry_run=dry_run)
    # Fail fast on missing elevation BEFORE any snapshot is taken: a failed
    # apply must never leave behind backups for a change that never happened.
    if tweak["admin"] and not dry_run and not _is_admin():
        return False, [(a, False, "requires administrator privileges") for a in tweak["actions"]]
    if not dry_run:
        _snapshot_reg_targets(tweak_id, tweak["actions"])
        _snapshot_file_targets(tweak_id, tweak["actions"])
        _snapshot_ini_targets(tweak_id, tweak["actions"])
    return apply_actions(tweak["actions"], dry_run=dry_run,
                         admin_required=tweak["admin"])


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
    """Back up the previous value of every ini key a tweak will set."""
    from engine import state as state_mgr  # deferred: avoids import cycle

    existing = state_mgr.get_ini_backups(tweak_id) or {}
    changed = False
    for a in actions:
        if len(a) < 5 or a[0] != "ini":
            continue
        path, section, key = a[1], a[2], a[3]
        ikey = _ini_backup_key(path, section, key)
        if ikey in existing:
            continue
        existed, value = _ini_read_value(path, section, key)
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
    """Revert using exact value backups when present, else the revert list."""
    from engine import state as state_mgr  # deferred: avoids import cycle

    tid = tweak["id"]
    reg_backups = state_mgr.get_reg_backups(tid) or {}
    file_backups = state_mgr.get_file_backups(tid) or {}
    ini_backups = state_mgr.get_ini_backups(tid) or {}
    has_backups = bool(reg_backups or file_backups or ini_backups)
    if not has_backups:
        return apply_actions(tweak["revert"], dry_run=dry_run,
                             admin_required=tweak["admin"])

    def _covered_regdelall(hive, base):
        prefix = f"{hive.upper()}\\{base.replace('\\\\', '\\').upper()}\\"
        return any(k.startswith(prefix) for k in reg_backups)

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
        if a[0] == "regdelall" and len(a) >= 4 and _covered_regdelall(a[1], a[2]):
            continue
        if a[0] == "file" and len(a) >= 3:
            if _file_backup_key(a[2]) in file_backups:
                continue
        if a[0] in ("ini", "inidel") and len(a) >= 4:
            if _ini_backup_key(a[1], a[2], a[3]) in ini_backups:
                continue
        ok, detail = _execute_action(a, dry_run=dry_run)
        results.append((a, ok, detail))

    # Restore the exact previous state of every snapshotted value.
    ok_all = True
    for key, entry in reg_backups.items():
        ok, detail = _restore_backup(entry, dry_run=dry_run)
        if not ok:
            ok_all = False
        results.append(("restore", ok,
                        f"restored {entry['hive']}\\{entry['path']} "
                        f"[{entry['name']}] -> {detail}"))
    for key, entry in file_backups.items():
        ok, detail = _restore_file_backup(entry, dry_run=dry_run)
        if not ok:
            ok_all = False
        results.append(("restore", ok,
                        f"restored {entry['path']} -> {detail}"))
    for key, entry in ini_backups.items():
        ok, detail = _restore_ini_backup(entry, dry_run=dry_run)
        if not ok:
            ok_all = False
        results.append(("restore", ok,
                        f"restored {entry['section']}.{entry['key']} -> {detail}"))
    if ok_all and not dry_run:
        state_mgr.clear_reg_backups(tid)
        state_mgr.clear_file_backups(tid)
        state_mgr.clear_ini_backups(tid)
    return ok_all and all(ok for _, ok, _ in results), results
