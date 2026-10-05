"""Shared primitives for the App Optimizers screen.

Everything here is reversible.  Each app records a JSON *ledger* of the
operations it performed; ``reset`` walks that ledger back in reverse and
restores each backup (moved file, edited text, deleted registry value,
blocked hosts entry, disabled scheduled task).  Nothing is deleted without a
backup copy and nothing is "reset" to a hardcoded default — Restore always
brings back the user's true previous state.

The heavy lifting uses in-process winreg (engine.reg_util) and plain file
operations instead of spawning cmd/powershell, matching engine/debloat's
philosophy.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from engine import reg_util
from maxlog import logger

APP_OPT_DIR = Path(os.environ.get("LOCALAPPDATA") or "") / "MaximumTweaks" / "app_optimizer"
BACKUP_DIR = APP_OPT_DIR / "backups"
LEDGER_DIR = APP_OPT_DIR / "ledgers"


def _mk_dirs() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)


def is_admin() -> bool:
    """True when the current process runs elevated (needed for Program Files
    strips and hosts-file edits; everything else works unelevated)."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------- ledgers

def _ledger_path(app_key: str) -> Path:
    _mk_dirs()
    return LEDGER_DIR / f"{app_key}.json"


def load_ledger(app_key: str) -> dict:
    p = _ledger_path(app_key)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"app_optimizer: ledger {app_key} unreadable: {exc}")
    return {"ops": [], "engaged_at": None}


def save_ledger(app_key: str, ledger: dict) -> None:
    _mk_dirs()
    tmp = _ledger_path(app_key).with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    os.replace(tmp, _ledger_path(app_key))


def _record(app_key: str, op: dict) -> None:
    ledger = load_ledger(app_key)
    ledger.setdefault("ops", []).append(op)
    ledger["engaged_at"] = ledger.get("engaged_at") or time.strftime("%Y-%m-%d %H:%M")
    save_ledger(app_key, ledger)


def snapshot_text(path: str) -> dict:
    """Back up a text file's contents before an edit -> (record, ok)."""
    record = {"kind": "text", "path": path, "existed": os.path.isfile(path)}
    if record["existed"]:
        _mk_dirs()
        dst = BACKUP_DIR / f"{time.time_ns()}_{os.path.basename(path)}.bak"
        try:
            shutil.copy2(path, dst)
            record["backup"] = str(dst)
            return record, True
        except Exception as exc:  # noqa: BLE001
            return {"kind": "text", "path": path, "existed": False, "error": str(exc)}, False
    return record, True


def restore_text(record: dict) -> tuple[bool, str]:
    """Put a text file back the way we found it from its snapshot record."""
    path = record.get("path")
    if not path:
        return False, "no path in record"
    try:
        backup = record.get("backup")
        if record.get("existed") and backup and os.path.isfile(backup):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copy2(backup, path)
            return True, f"restored {path}"
        if not record.get("existed") and os.path.isfile(path):
            os.remove(path)
            return True, f"removed {path} (did not exist before)"
        return False, f"nothing to restore for {path}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def path_size(path: str) -> int:
    """Total bytes of a file or directory tree (used to report real disk
    reclaimed, not an estimate)."""
    total = 0
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"app_optimizer: path_size failed on {path}: {exc}")
    return total


def move_away(path: str, label: str = "") -> tuple[dict, bool]:
    """Move a file/folder into the backup dir (locale strips, module renames).

    Returns (record, ok).  A locked file (app currently running) records an
    error instead of failing the whole app.  The record stores the real byte
    size that left the install directory so the UI can report an exact disk
    figure.
    """
    base = os.path.basename(path.rstrip("\\/"))
    dst = BACKUP_DIR / f"{time.time_ns()}_{base}"
    try:
        if os.path.isfile(path) or os.path.isdir(path):
            size = path_size(path)
            os.makedirs(dst.parent, exist_ok=True)
            if os.path.exists(dst):
                dst = BACKUP_DIR / f"{time.time_ns()}_{base}_dup"
            shutil.move(path, dst)
            return {"kind": "move", "src": path, "dst": str(dst),
                    "label": label, "bytes": size}, True
        return {"kind": "move", "src": path, "dst": None, "label": label,
                "missing": True}, False
    except Exception as exc:  # noqa: BLE001
        return {"kind": "move", "src": path, "dst": None, "label": label,
                "error": str(exc)}, False


def restore_move(record: dict) -> tuple[bool, str]:
    src, dst = record.get("src"), record.get("dst")
    if not src or not dst or not os.path.exists(dst):
        return False, "backup missing — leaving as-is"
    try:
        os.makedirs(os.path.dirname(src), exist_ok=True)
        shutil.move(dst, src)
        return True, f"restored {src}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def reg_snapshot(hive: str, path: str, name: str) -> dict:
    """Snapshot a registry value before writing it -> snapshot record."""
    existed, rtype, data = reg_util.read_value(hive, path, name)
    return {"kind": "reg", "hive": hive, "path": path, "name": name,
            "existed": existed, "vtype": rtype, "data": data}


def restore_reg(record: dict) -> tuple[bool, str]:
    hive, path, name = record.get("hive"), record.get("path"), record.get("name")
    if record.get("existed"):
        ok, msg = reg_util.write_value(hive, path, name, record.get("data"),
                                       record.get("vtype") or "STRING")
        if ok:
            return True, f"{name} restored to its previous value"
        # Say what went wrong in terms of the key, not just the raw reg.exe
        # message: a silent "unknown type" here used to leave the optimized
        # value in place while reset reported success.
        return False, f"{hive}\\{path}\\{name}: {msg}"
    # The value was absent before we touched it, so reverting means deleting
    # it.  An already-absent value is the correct end state, not a failure
    # (same idempotent-delete contract reg_util documents for reg.exe).
    existed, _rtype, _data = reg_util.read_value(hive, path, name)
    if not existed:
        return True, f"{name} already absent — correct end state"
    ok, msg = reg_util.delete_value(hive, path, name)
    return ok, msg


# ------------------------------------------------------------- host file

HOSTS_FILE = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                          "System32", "drivers", "etc", "hosts")
_HOSTS_MARK = "# MaximumTweaks App Optimizers block"
# Each app gets its own marker pair so blocking one app never disturbs (or a
# reset of one app never wipes) another app's block. The hosts file is shared
# global state, so isolation here is what makes per-app revert safe.
_HOSTS_MARK_PREFIX = _HOSTS_MARK + ": "
_HOSTS_END = "# End MaximumTweaks"


def _mark(app_key: str) -> str:
    return f"{_HOSTS_MARK_PREFIX}{app_key}"


def hosts_block(hostnames: list[str], app_key: str = "shared") -> tuple[dict, bool]:
    """Append ``0.0.0.0 <host>`` lines (inside an app-scoped marker block) to
    the hosts file. Only this app's previous block is replaced; other apps'
    blocks and the user's own lines are preserved. Requires elevation."""
    if not hostnames:
        return {"kind": "hosts", "backup": None, "entries": [], "app": app_key}, True
    start, end = _mark(app_key), _HOSTS_END
    record = {"kind": "hosts", "backup": None, "entries": list(hostnames),
              "app": app_key, "mark": start, "end": end}
    try:
        original = ""
        try:
            original = Path(HOSTS_FILE).read_text(encoding="utf-8",
                                                  errors="replace")
        except OSError:
            pass
        _mk_dirs()
        bak = BACKUP_DIR / f"{time.time_ns()}_hosts_{app_key}.bak"
        bak.write_text(original, encoding="utf-8")
        record["backup"] = str(bak)

        # Drop only this app's block; keep every other app's block intact.
        out, inside = [], False
        for line in original.splitlines():
            s = line.strip()
            if s == start:
                inside = True
                continue
            if inside:
                if s == end:
                    inside = False
                continue
            out.append(line)
        block = ["", start]
        block += [f"0.0.0.0 {h}" for h in hostnames]
        block += [end, ""]
        # `out` may not end with a newline, so join explicitly or the last
        # pre-existing hosts line gets glued onto our marker comment.
        body = ("\n".join(out) + "\n") if out else ""
        Path(HOSTS_FILE).write_text(body + "\n".join(block), encoding="utf-8")
        return record, True
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"{exc} (run as admin to block hosts)"
        return record, False


def _strip_block(text: str, start: str, end: str) -> tuple[str, bool]:
    """Remove one app's marker block -> (cleaned text, block_was_present)."""
    out, inside, found = [], False, False
    for line in text.splitlines():
        s = line.strip()
        if s == start:
            inside, found = True, True
            continue
        if inside:
            if s == end:
                inside = False
            continue
        out.append(line)
    return "\n".join(out).strip("\n") + "\n", found


def restore_hosts(record: dict) -> tuple[bool, str]:
    """Remove this app's marker block from the hosts file.

    Deliberately *not* a whole-file copy of the backup: the hosts file is
    shared global state, and restoring a full snapshot would silently wipe
    blocks belonging to other apps that were blocked afterwards. Stripping
    only our own marker block is per-app reversible and order-independent.
    """
    try:
        app = record.get("app") or "shared"
        start = record.get("mark") or _mark(app)
        end = record.get("end") or _HOSTS_END
        p = Path(HOSTS_FILE)
        current = p.read_text(encoding="utf-8", errors="replace")
        cleaned, found = _strip_block(current, start.strip(), end.strip())
        if not found:
            return True, "hosts block already absent — correct end state"
        p.write_text(cleaned, encoding="utf-8")
        return True, f"unblocked {len(record.get('entries', []))} host(s)"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


# ------------------------------------------------------------- firewall

_FW_GROUP = "MaximumTweaks App Optimizers"


def _netsh(args: list[str], timeout: int = 25) -> tuple[bool, str]:
    """Run a netsh advfirewall subcommand -> (ok, output). Never raises."""
    try:
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", *args],
            capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000,
        )
        return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _fw_rule_names() -> set[str]:
    """Every firewall rule name currently present (needs elevation to be
    complete, but a partial read only costs us a duplicate check, never
    correctness, because the add is idempotent at the OS level too)."""
    ok, text = _netsh(["show", "rule", "name=all"])
    if not ok:
        return set()
    names = set()
    for line in text.splitlines():
        parts = line.split(":", 1)
        if len(parts) == 2 and parts[0].strip().lower() == "rule name":
            names.add(parts[1].strip())
    return names


def _fw_rule_name(app_key: str, program: str) -> str:
    tag = Path(program).stem or "app"
    return f"[MT] block inbound for {tag} ({app_key})"


def firewall_block_inbound(app_key: str,
                           programs: list[str]) -> tuple[dict, bool]:
    """Add per-program inbound-block rules to Windows Firewall.

    Real effect: none of these apps accept inbound connections, so an inbound
    allow rule does nothing useful -- it only widens the attack surface.
    Blocking inbound is therefore a low-risk change to a program the user still
    uses, and it does not block anything outgoing (updates, sync, streaming).

    Reversibility is by rule *name*, not a firewall snapshot: every rule created
    here is prefixed ``[MT]`` and carries the app key, so reset removes exactly
    its own rules and cannot touch one the user or another app made. Requires
    elevation; without it netsh fails and the error is reported.
    """
    record = {"kind": "firewall", "app": app_key, "rules": []}
    targets = [p for p in programs if p and os.path.isfile(p)]
    if not targets:
        record["skipped"] = "no matching executable on disk"
        return record, True
    existing = _fw_rule_names()
    errors = []
    for program in targets:
        name = _fw_rule_name(app_key, program)
        if name in existing:
            continue  # idempotent: no duplicate, nothing for reset to unwind
        ok, msg = _netsh(["add", "rule", f"name={name}", "dir=in",
                          "action=block", f"program={program}", "enable=yes"])
        if ok:
            record["rules"].append(name)
        else:
            errors.append(f"{Path(program).name}: {msg}")
    if errors:
        record["errors"] = errors
    if not record["rules"] and not errors:
        record["skipped"] = "rules already in place"
    return record, not errors


def restore_firewall(record: dict) -> tuple[bool, str]:
    """Delete only the inbound-block rules this app created."""
    names = record.get("rules") or []
    if not names:
        return True, "no firewall rules recorded — nothing to remove"
    failed = []
    for name in names:
        ok, msg = _netsh(["delete", "rule", f"name={name}"])
        if not ok:
            failed.append(f"{name}: {msg}")
    if failed:
        return False, "; ".join(failed)
    return True, f"removed {len(names)} firewall rule(s)"


# ------------------------------------------------- Windows startup approval

_STARTUP_APPROVED = (r"Software\Microsoft\Windows\CurrentVersion"
                     r"\Explorer\StartupApproved\Run")
_STARTUP_APPROVED_32 = (r"Software\Microsoft\Windows\CurrentVersion"
                        r"\Explorer\StartupApproved\Run32")
# Explorer stores StartupApproved entries as a 12-byte REG_BINARY: a 4-byte
# state word followed by an 8-byte FILETIME. State 2 = disabled by the user,
# state 3 = enabled. Writing state 2 for a previously enabled entry is what
# Task Manager's own "Disable" button does, and the original bytes are
# snapshotted so reset restores the user's real choice.
_STARTUP_DISABLED = "02 00 00 00 00 00 00 00 00 00 00 00"


def startup_approved_disable(app_key: str, entries: list[str],
                             subkey: str = "") -> tuple[list[dict], bool, str]:
    """Disable per-user startup entries the way Task Manager does.

    The HKCU Run value and the StartupApproved state are two different things,
    and the previous pass only handled the first: removing the Run value takes
    the entry out of the list entirely, while StartupApproved is what Explorer
    reads to grey out an entry the user switched off. Both are snapshotted.

    ``entries`` are Run value names. Nothing is deleted -- only the approval
    state changes -- so an update that recreates the Run value stays disabled.
    """
    records, ok = [], True
    path = subkey or _STARTUP_APPROVED
    for name in entries:
        snap = reg_snapshot("HKCU", path, name)
        existed, rtype, data = reg_util.read_value("HKCU", path, name)
        # Already disabled: no write, and nothing to record. read_value returns
        # BINARY as space-separated hex, so compare through the shared helper
        # rather than string-matching the raw bytes.
        if existed and reg_util.value_equals(data, rtype, _STARTUP_DISABLED,
                                             "BINARY"):
            continue
        records.append(snap)
        wok, msg = reg_util.write_value("HKCU", path, name,
                                         _STARTUP_DISABLED, "BINARY")
        if not wok:
            ok = False
            logger.warn(f"app_optimizer: StartupApproved {name} failed: {msg}")
    if not records:
        return [], True, "startup entries already disabled"
    return records, ok, f"{len(records)} startup entr(y/ies) disabled"


# --------------------------------------------------------- scheduled tasks

def _ps(command: str, timeout: int = 20) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000,
        )
        return (r.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def disable_task(task_name: str) -> tuple[dict, bool]:
    """Disable a scheduled task (records its previous State).

    Returns ``(record, ok)``. ``ok`` is False only for a genuine failure —
    a task that is already Disabled, or simply absent, is a clean no-op and
    must NOT be recorded, otherwise reset would later try to re-enable a
    task it never touched.
    """
    state = _ps(f"(Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue).State")
    rec = {"kind": "task", "task": task_name, "was": state or "unknown"}
    if not state:
        rec["missing"] = True
        return rec, False
    if state.lower() == "disabled":
        # Already disabled by the user — nothing for us to change or undo.
        rec["already"] = True
        return rec, True
    _ps(f"Disable-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue | Out-Null")
    # Verify the task actually ended up Disabled rather than assuming success.
    time.sleep(0.2)
    after = _ps(f"(Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue).State")
    if after and after.lower() != "disabled":
        rec["error"] = f"{task_name} is still {after} after disable"
        return rec, False
    rec["changed"] = True
    return rec, True


def restore_task(record: dict) -> tuple[bool, str]:
    name = record.get("task")
    if record.get("missing"):
        return True, "task was absent — nothing to restore"
    if record.get("already"):
        return True, f"{name} was already disabled — left as found"
    if record.get("was", "").lower() in ("ready", "running"):
        _ps(f"Enable-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue | Out-Null")
        return True, f"re-enabled {name}"
    return True, f"{name} was already disabled"


# --------------------------------------------------------------- process

def process_mem_mb(names: list[str]) -> float:
    """Real aggregated WorkingSet (MB) of every running process whose name
    matches the app's process names (case-insensitive, full-name match)."""
    wanted = {n.lower() for n in names}
    total = 0.0
    try:
        import psutil
        for proc in psutil.process_iter(["name", "memory_info"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                if pname in wanted:
                    total += (proc.info.get("memory_info").rss or 0) / (1024 ** 2)
            except Exception:  # noqa: BLE001
                continue
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"app_optimizer: process_mem_mb failed: {exc}")
    return round(total, 1)


def helper_cpu(names: list[str]) -> float:
    """Aggregate real %CPU of currently-running helper/updater processes."""
    wanted = {n.lower() for n in names}
    total = 0.0
    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                if pname in wanted:
                    total += proc.cpu_percent(interval=None) or 0.0
            except Exception:  # noqa: BLE001
                continue
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"app_optimizer: helper_cpu failed: {exc}")
    return round(total, 1)


def terminate_processes(names: list[str]) -> list[str]:
    """Best-effort kill of helper/updater processes by exact name (never the
    main app). Returns the names actually stopped (real RAM freed)."""
    wanted = {n.lower() for n in names}
    stopped, handled = [], set()
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                if pname in wanted and pname not in handled:
                    proc.terminate()
                    stopped.append(proc.info.get("name"))
                    handled.add(pname)
            except Exception:  # noqa: BLE001
                continue
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"app_optimizer: terminate_processes failed: {exc}")
    return stopped