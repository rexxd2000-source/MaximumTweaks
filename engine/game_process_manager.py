"""Shared Game Process Manager (CPU spec PART 3).

Process-aware CPU features for running games.  Never touches anti-cheat
processes: every Win32 call opens the game with the minimum required rights
and an Access Denied result just marks the game as unsupported.

Implemented operations (each is detect-first and revert-safe):

  high_qos              ProcessPowerThrottling -> execution-speed throttling
                        explicitly OFF (High QoS / Efficiency Mode disabled)
  clear_cpu_sets        Clear an explicit process default CPU Set assignment
  memory_normal         Restore process memory priority to Normal (5)
  priority_above_normal Set process priority class to Above Normal

All four restore the exact original value captured before apply via
engine.state ``process_backups`` keyed by executable name.  If the game
process is not running when a tweak is applied, the op is a safe no-op that
reports why.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from engine.state import (
    get_process_backups,
    save_process_backups,
    clear_process_backups,
)
from maxlog import logger

# ── Win32 access rights (minimum required per spec) ──────────────────────
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_LIMITED_INFORMATION = 0x2000
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_INFORMATION = 0x0200
_QUERY_RIGHTS = PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_QUERY_INFORMATION
_SET_RIGHTS = PROCESS_SET_LIMITED_INFORMATION | PROCESS_SET_INFORMATION

# PROCESS_INFORMATION_CLASS constants (kernel32 Set/GetProcessInformation)
ProcessMemoryPriority = 37
ProcessPowerThrottling = 39

# PROCESS_POWER_THROTTLING_STATE
PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1

# Priority classes (winnt.h)
NORMAL_PRIORITY_CLASS = 0x00000020
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
_PRIORITY_CLASS_LABELS = {
    NORMAL_PRIORITY_CLASS: "Normal",
    ABOVE_NORMAL_PRIORITY_CLASS: "Above Normal",
    0x00000040: "Idle",
    0x00004000: "Below Normal",
    0x00000080: "High",
    0x00000100: "Realtime",
}

_MEMORY_PRIORITY_LABELS = {
    1: "Very Low",
    2: "Low",
    3: "Medium",
    4: "Below Normal",
    5: "Normal",
}


class _GROUP_AFFINITY(ctypes.Structure):
    _fields_ = [
        ("Mask", ctypes.c_ulonglong),       # KAFFINITY (ULONG_PTR)
        ("Group", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort * 3),
    ]


class _PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.ULONG),
        ("ControlMask", wintypes.ULONG),
        ("StateMask", wintypes.ULONG),
    ]


class _MEMORY_PRIORITY_INFORMATION(ctypes.Structure):
    _fields_ = [("MemoryPriority", wintypes.ULONG)]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),   # ULONG_PTR
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Pointer-sized returns MUST declare restype or handles get truncated.
_kernel32.OpenProcess.restype = ctypes.c_void_p
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.Process32FirstW.restype = wintypes.BOOL
_kernel32.Process32FirstW.argtypes = [wintypes.HANDLE,
                                      ctypes.POINTER(_PROCESSENTRY32W)]
_kernel32.Process32NextW.restype = wintypes.BOOL
_kernel32.Process32NextW.argtypes = [wintypes.HANDLE,
                                     ctypes.POINTER(_PROCESSENTRY32W)]
_kernel32.GetPriorityClass.restype = wintypes.DWORD
_kernel32.GetPriorityClass.argtypes = [wintypes.HANDLE]
_kernel32.SetPriorityClass.restype = wintypes.BOOL
_kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.GetProcessInformation.restype = wintypes.BOOL
_kernel32.GetProcessInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                            ctypes.c_void_p, wintypes.DWORD]
_kernel32.SetProcessInformation.restype = wintypes.BOOL
_kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                            ctypes.c_void_p, wintypes.DWORD]
_kernel32.GetProcessDefaultCpuSets.restype = wintypes.BOOL
_kernel32.GetProcessDefaultCpuSets.argtypes = [wintypes.HANDLE,
                                               ctypes.POINTER(_GROUP_AFFINITY),
                                               wintypes.USHORT,
                                               ctypes.POINTER(wintypes.USHORT)]
_kernel32.SetProcessDefaultCpuSets.restype = wintypes.BOOL
_kernel32.SetProcessDefaultCpuSets.argtypes = [wintypes.HANDLE,
                                               ctypes.POINTER(_GROUP_AFFINITY),
                                               wintypes.USHORT]


def _supported_exes() -> set[str]:
    """Lowercased executable names for every game catalogued in nvprofiles."""
    from engine import nvprofiles
    return {exe.lower()
            for game in nvprofiles.GAMES.values()
            for exe in (game.get("exes") or [])}


_SUPPORTED_EXES: set[str] | None = None


def supported_exes() -> set[str]:
    global _SUPPORTED_EXES
    if _SUPPORTED_EXES is None:
        _SUPPORTED_EXES = _supported_exes()
    return _SUPPORTED_EXES


def _running_processes() -> list[dict]:
    """Return [{pid, exe, name}] for every process on the system."""
    TH32CS_SNAPPROCESS = 0x00000002
    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        if not _kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return []
        result = []
        while True:
            try:
                name = entry.szExeFile.split("\\")[-1]
                result.append({"pid": int(entry.th32ProcessID),
                               "exe": name.lower(), "name": name})
            except Exception:  # noqa: BLE001
                pass
            if not _kernel32.Process32NextW(snap, ctypes.byref(entry)):
                break
        return result
    finally:
        _kernel32.CloseHandle(snap)


def detect_games() -> list[dict]:
    """Return currently running supported game processes."""
    wanted = supported_exes()
    return [p for p in _running_processes() if p["exe"] in wanted]


def _open(pid: int, access: int):
    """Open a process handle with the given rights (0 on failure/denied)."""
    return _kernel32.OpenProcess(access, False, int(pid))


def _close(h) -> None:
    if h:
        try:
            _kernel32.CloseHandle(h)
        except Exception:  # noqa: BLE001
            pass


def _last_error() -> str:
    """Read the Win32 error from the last kernel32 call (0 when none)."""
    try:
        return f"Win32 error {ctypes.get_last_error()}"
    except Exception:  # noqa: BLE001
        return "Win32 error unavailable"


# ── State queries ─────────────────────────────────────────────────────────

def get_priority_class(pid: int) -> int | None:
    h = _open(pid, _QUERY_RIGHTS)
    if not h:
        return None
    try:
        raw = _kernel32.GetPriorityClass(h)
        return int(raw) if raw else None
    finally:
        _close(h)


def get_memory_priority(pid: int) -> int | None:
    h = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if not h:
        return None
    try:
        info = _MEMORY_PRIORITY_INFORMATION()
        ok = _kernel32.GetProcessInformation(
            h, ProcessMemoryPriority, ctypes.byref(info), ctypes.sizeof(info))
        return int(info.MemoryPriority) if ok else None
    finally:
        _close(h)


def get_cpu_sets(pid: int) -> list[tuple[int, int]] | None:
    """Return the process default CPU Set assignment as [(mask, group), ...].

    None means the query failed; [] means no explicit restriction.
    """
    h = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if not h:
        return None
    try:
        needed = wintypes.USHORT(0)
        _kernel32.GetProcessDefaultCpuSets(h, None, 0, ctypes.byref(needed))
        if needed.value == 0:
            return []
        count = int(needed.value)
        arr = (_GROUP_AFFINITY * count)()
        ok = _kernel32.GetProcessDefaultCpuSets(
            h, ctypes.cast(arr, ctypes.POINTER(_GROUP_AFFINITY)),
            wintypes.USHORT(count), ctypes.byref(needed))
        if not ok:
            return None
        return [(int(g.Mask), int(g.Group)) for g in arr[:int(needed.value)]]
    finally:
        _close(h)


def game_state(pid: int, exe: str) -> dict:
    """Healthy state report for one game process (access-aware)."""
    state = {"pid": pid, "exe": exe, "access": False,
             "priority_class": None, "memory_priority": None,
             "cpu_sets": None}
    state["priority_class"] = get_priority_class(pid)
    state["memory_priority"] = get_memory_priority(pid)
    state["cpu_sets"] = get_cpu_sets(pid)
    state["access"] = state["priority_class"] is not None \
        and state["memory_priority"] is not None
    return state


def report_state() -> dict:
    """Public diagnostics: every running supported game + its CPU state."""
    games = []
    for g in detect_games():
        try:
            games.append(game_state(g["pid"], g["exe"]))
        except Exception as exc:  # noqa: BLE001
            games.append({"pid": g["pid"], "exe": g["exe"],
                          "access": False, "error": str(exc)})
    return {"games": games, "supported": len(supported_exes())}


# ── Low-level writers ─────────────────────────────────────────────────────

def _set_power_throttling(pid: int, enable_control: bool) -> tuple[bool, str]:
    h = _open(pid, _SET_RIGHTS)
    if not h:
        return False, _last_error()
    try:
        state = _PROCESS_POWER_THROTTLING_STATE(
            PROCESS_POWER_THROTTLING_CURRENT_VERSION,
            PROCESS_POWER_THROTTLING_EXECUTION_SPEED if enable_control else 0,
            0,
        )
        ok = _kernel32.SetProcessInformation(
            h, ProcessPowerThrottling, ctypes.byref(state), ctypes.sizeof(state))
        if ok:
            return True, ""
        return False, _last_error()
    finally:
        _close(h)


def _set_memory_priority(pid: int, value: int) -> tuple[bool, str]:
    h = _open(pid, _SET_RIGHTS)
    if not h:
        return False, _last_error()
    try:
        info = _MEMORY_PRIORITY_INFORMATION(value)
        ok = _kernel32.SetProcessInformation(
            h, ProcessMemoryPriority, ctypes.byref(info), ctypes.sizeof(info))
        return (True, "") if ok else (False, _last_error())
    finally:
        _close(h)


def _set_priority_class(pid: int, value: int) -> tuple[bool, str]:
    h = _open(pid, PROCESS_SET_LIMITED_INFORMATION)
    if not h:
        h = _open(pid, PROCESS_SET_INFORMATION)
    if not h:
        return False, _last_error()
    try:
        ok = _kernel32.SetPriorityClass(h, value)
        return (True, "") if ok else (False, _last_error())
    finally:
        _close(h)


def _clear_default_cpu_sets(pid: int) -> tuple[bool, str]:
    h = _open(pid, _SET_RIGHTS)
    if not h:
        return False, _last_error()
    try:
        ok = _kernel32.SetProcessDefaultCpuSets(h, None, wintypes.USHORT(0))
        return (True, "") if ok else (False, _last_error())
    finally:
        _close(h)


def _restore_cpu_sets(pid: int, sets: list[tuple[int, int]]) -> tuple[bool, str]:
    h = _open(pid, _SET_RIGHTS)
    if not h:
        return False, _last_error()
    try:
        if not sets:
            ok = _kernel32.SetProcessDefaultCpuSets(h, None, wintypes.USHORT(0))
        else:
            arr = (_GROUP_AFFINITY * len(sets))()
            for i, (mask, group) in enumerate(sets):
                arr[i] = _GROUP_AFFINITY(mask, group, (0, 0, 0))
            ok = _kernel32.SetProcessDefaultCpuSets(
                h, ctypes.cast(arr, ctypes.POINTER(_GROUP_AFFINITY)),
                wintypes.USHORT(len(sets)))
        return (True, "") if ok else (False, _last_error())
    finally:
        _close(h)


# ── Operations (apply) ────────────────────────────────────────────────────

def _high_qos_apply(pid: int, exe: str) -> tuple[bool, str]:
    ok, err = _set_power_throttling(pid, True)
    return ok, err or "High QoS / Efficiency Mode Disabled"


def _high_qos_revert(pid: int, exe: str) -> tuple[bool, str]:
    ok, err = _set_power_throttling(pid, False)
    return ok, err or "Windows Managed"


def _cpu_sets_apply(pid: int, exe: str) -> tuple[bool, str]:
    sets = get_cpu_sets(pid)
    if sets is None:
        return False, "CPU Set query unavailable (protected process?)"
    if not sets:
        return True, "No explicit CPU Set restriction - nothing to clear"
    ok, err = _clear_default_cpu_sets(pid)
    return ok, err or "Restriction cleared - CPU Sets: Windows Default"


def _memory_normal_apply(pid: int, exe: str) -> tuple[bool, str]:
    cur = get_memory_priority(pid)
    if cur is None:
        return False, "memory priority query unavailable (protected process?)"
    if cur >= 5:
        return True, f"Memory Priority: Normal ({_MEMORY_PRIORITY_LABELS.get(cur, cur)})"
    ok, err = _set_memory_priority(pid, 5)
    label = _MEMORY_PRIORITY_LABELS.get(cur, cur)
    return ok, err or f"Memory Priority: Normal (was {label})"


def _priority_apply(pid: int, exe: str) -> tuple[bool, str]:
    cur = get_priority_class(pid)
    if cur is None:
        return False, "priority query unavailable (protected process?)"
    if cur == ABOVE_NORMAL_PRIORITY_CLASS:
        return True, "Priority: Above Normal (already)"
    ok, err = _set_priority_class(pid, ABOVE_NORMAL_PRIORITY_CLASS)
    return ok, err or "Priority: Above Normal"


def _restore_snapshot(op_base: str, tweak_id: str, exe: str) -> tuple[bool, str]:
    """Restore a saved original value for one exe (revert path)."""
    type_map = {"high_qos": None, "clear_cpu_sets": "cpu_sets",
                "memory_normal": "memory_priority",
                "priority_above_normal": "priority_class"}
    kind = type_map.get(op_base)
    if not kind:
        return True, "Windows Managed"
    snapshots = get_process_backups(tweak_id) or {}
    entry = snapshots.get(exe.lower())
    if entry is None or entry.get(kind) is None:
        return False, f"no prior {kind} snapshot for {exe} - nothing to restore"
    expect_pid = entry.get("pid")
    games = detect_games()
    target = next((g for g in games if g["exe"] == exe.lower()
                   and (expect_pid is None or g["pid"] == expect_pid)), None)
    if target is None:
        return False, f"{exe} (pid {expect_pid}) is not running - cannot restore now"
    pid = target["pid"]
    if kind == "cpu_sets":
        ok, err = _restore_cpu_sets(pid, entry.get("cpu_sets") or [])
    elif kind == "memory_priority":
        ok, err = _set_memory_priority(pid, int(entry.get("memory_priority")))
    elif kind == "priority_class":
        ok, err = _set_priority_class(pid, int(entry.get("priority_class")))
    else:
        return False, f"unknown restore kind {kind!r}"
    return bool(ok), err if not ok else f"{exe}: original {kind} restored"


_OPS = {
    "high_qos": _high_qos_apply,
    "high_qos_revert": _high_qos_revert,
    "clear_cpu_sets": _cpu_sets_apply,
    "memory_normal": _memory_normal_apply,
    "priority_above_normal": _priority_apply,
}

# base op -> human label (executor reports)
OP_NAMES = {
    "high_qos": "Disable Game Efficiency Mode",
    "high_qos_revert": "Restore Windows-managed efficiency",
    "clear_cpu_sets": "Restore Windows CPU Scheduling",
    "clear_cpu_sets_revert": "Restore prior CPU Set assignment",
    "memory_normal": "Normalize Memory Priority",
    "memory_normal_revert": "Restore prior memory priority",
    "priority_above_normal": "Game CPU Priority: Above Normal",
    "priority_above_normal_revert": "Restore original priority class",
}


def _capture_snapshot(tweak_id: str, op_base: str) -> None:
    """Save original values for every running supported game before apply."""
    games = detect_games()
    if not games:
        return
    entries = {}
    for g in games:
        exe = g["exe"]
        entries[exe] = {
            "kind": op_base,
            "pid": g["pid"],
            "priority_class": get_priority_class(g["pid"]),
            "memory_priority": get_memory_priority(g["pid"]),
            "cpu_sets": get_cpu_sets(g["pid"]),
        }
    save_process_backups(tweak_id, entries)
    logger.info(f"game_process: captured original state for {sorted(entries)} ({op_base})")


def _do_each(fn) -> tuple[bool, str, list[dict]]:
    """Run fn(pid, exe) on every running supported game once.

    Returns (all_ok, summary, per-game results).  If no game is running the
    op is skipped with a clear reason.  Access-denied games are never
    retried or bypassed.
    """
    games = detect_games()
    if not games:
        return False, "no supported game process running", [{
            "ok": False, "exe": "-", "detail":
            "No supported game process running - launch the game, then re-apply."}]
    results = []
    ok_all = True
    for g in games:
        try:
            ok, err = fn(g["pid"], g["exe"])
        except Exception as exc:  # noqa: BLE001
            ok, err = False, f"{type(exc).__name__}: {exc}"
        results.append({"ok": ok, "exe": g["exe"], "pid": g["pid"],
                        "detail": err or "ok"})
        ok_all = ok_all and bool(ok)
    summary = "all done" if ok_all else "some targets unavailable/denied"
    return ok_all, summary, results


def run_op(op: str, tweak_id: str | None = None) -> tuple[bool, str, list[dict]]:
    """Run a process op from the executor (apply or revert).

    Returns (ok, summary, per-game detail lines).
    """
    tid = tweak_id or "game_process"
    if op not in _OPS and not op.endswith("_revert"):
        return False, f"unknown process op {op!r}", []
    revert = op.endswith("_revert")
    op_base = op[: -len("_revert")] if revert else op

    def fn(pid: int, exe: str):
        if revert and op_base in ("clear_cpu_sets", "memory_normal",
                                  "priority_above_normal"):
            return _restore_snapshot(op_base, tid, exe)
        if revert:  # high_qos revert
            return _high_qos_revert(pid, exe)
        return _OPS[op_base](pid, exe)

    if not revert:
        _capture_snapshot(tid, op_base)
    ok, summary, results = _do_each(fn)
    # Only drop snapshots once every game was fully restored.
    if revert and ok:
        clear_process_backups(tid)
    return ok, summary, results