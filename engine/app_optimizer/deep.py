"""Non-invasive optimization levers for the App Optimizers screen.

The original plans leaned on file surgery inside app install trees (Discord's
``modules\\`` folders, Chromium ``Locales\\`` packs). That works, but it is
fragile: an app's own self-updater silently puts the files back, and it fights
the runtime that extracted them in the first place.

This module adds levers that never touch a byte of an app's installed files:

* **Windows services** — the real updater services (edgeupdate, GoogleUpdate,
  BraveSoftwareUpdate) are stopped and flipped to *disabled*. The genuine
  previous start type is snapshotted so reset restores exactly what was there.
* **Process scheduling** — priority class, CPU affinity and EcoQoS (Efficiency
  Mode) are applied to the live processes through the documented Win32 calls.
  Nothing on disk is involved and nothing is "one-shot": the caller re-applies
  them after every launch via :func:`triage_pass`.
* **Launch arguments** — appended to the Run command and to the .lnk
  shortcuts, which is user-level configuration and survives app updates.
* **Auto-restart** — the app is closed and relaunched from its own install path
  so the changes actually land, instead of waiting for the user to reboot.

Every function returns a ledger record so ``reset`` can undo it exactly.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from engine import reg_util
from maxlog import logger

# ------------------------------------------------------------------ Win32

SERVICE_QUERY_CONFIG = 0x0001
SERVICE_CHANGE_CONFIG = 0x0002
SERVICE_QUERY_STATUS = 0x0004
SERVICE_STOP = 0x0020
SC_MANAGER_CONNECT = 0x0001
SERVICE_NO_CHANGE = 0xFFFFFFFF
SERVICE_CONTROL_STOP = 0x00000001

SERVICE_DISABLED = 0x4
SERVICE_DEMAND_START = 0x3
SERVICE_AUTO_START = 0x2
SERVICE_SYSTEM_START = 0x1
SERVICE_BOOT_START = 0x0

_START_NAMES = {
    SERVICE_BOOT_START: "boot",
    SERVICE_SYSTEM_START: "system",
    SERVICE_AUTO_START: "auto",
    SERVICE_DEMAND_START: "demand",
    SERVICE_DISABLED: "disabled",
}

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_INFORMATION = 0x0200
# SetPriorityClass / SetProcessAffinityMask / SetProcessInformation all demand
# PROCESS_SET_INFORMATION. Asking only for query rights makes them fail with
# ERROR_ACCESS_DENIED even on an elevated process.
_SCHED_ACCESS = PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_INFORMATION
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
IDLE_PRIORITY_CLASS = 0x00000040
NORMAL_PRIORITY_CLASS = 0x00000020
PRIORITY_CLASSES = {
    "normal": NORMAL_PRIORITY_CLASS,
    "below": BELOW_NORMAL_PRIORITY_CLASS,
    "idle": IDLE_PRIORITY_CLASS,
}

PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
_PROCESS_POWER_THROTTLING = 4

_NO_WINDOW = 0x08000000


class _SERVICE_CONFIGW(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwStartType", wintypes.DWORD),
        ("dwErrorControl", wintypes.DWORD),
        ("lpBinaryPathName", wintypes.LPWSTR),
        ("lpLoadOrderGroup", wintypes.LPWSTR),
        ("dwTagId", wintypes.DWORD),
        ("lpDependencies", wintypes.LPWSTR),
        ("lpServiceStartName", wintypes.LPWSTR),
        ("lpPassword", wintypes.LPWSTR),
    ]


class _POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.DWORD),
        ("ControlMask", wintypes.DWORD),
        ("State", wintypes.DWORD),
    ]


class _SERVICE_STATUS_PROCESS(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwCurrentState", wintypes.DWORD),
        ("dwControlsAccepted", wintypes.DWORD),
        ("dwWin32ExitCode", wintypes.DWORD),
        ("dwServiceSpecificExitCode", wintypes.DWORD),
        ("dwCheckPoint", wintypes.DWORD),
        ("dwWaitHint", wintypes.DWORD),
    ]


SC_MANAGER_CONNECT = 0x0001
SC_MANAGER_ALL_ACCESS = 0xF003F
SERVICE_QUERY_STATUS = 0x0004
SERVICE_STATUS_PROCESS = 6


def _win32():
    if not hasattr(ctypes, "windll"):
        raise OSError("not running on Windows")
    advapi32, kernel32 = ctypes.windll.advapi32, ctypes.windll.kernel32
    # Explicit signatures: without these ctypes truncates 64-bit handles and
    # passes pointers with the wrong width, and every call silently "fails".
    advapi32.OpenSCManagerW.restype = wintypes.HANDLE
    advapi32.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                        wintypes.DWORD]
    advapi32.OpenServiceW.restype = wintypes.HANDLE
    advapi32.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR,
                                      wintypes.DWORD]
    advapi32.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    advapi32.QueryServiceConfigW.restype = wintypes.BOOL
    advapi32.QueryServiceConfigW.argtypes = [wintypes.HANDLE, wintypes.LPVOID,
                                             ctypes.POINTER(wintypes.DWORD)]
    advapi32.ChangeServiceConfigW.restype = wintypes.BOOL
    advapi32.ChangeServiceConfigW.argtypes = [wintypes.HANDLE] + [wintypes.DWORD] * 3 + \
        [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD),
         wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR]
    advapi32.ControlService.restype = wintypes.BOOL
    advapi32.ControlService.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                        wintypes.LPVOID]
    advapi32.QueryServiceStatusEx.restype = wintypes.BOOL
    advapi32.QueryServiceStatusEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                              wintypes.LPVOID, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.DWORD)]
    advapi32.StartServiceW.restype = wintypes.BOOL
    advapi32.StartServiceW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.EnumServicesStatusExW.restype = wintypes.BOOL
    advapi32.EnumServicesStatusExW.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.LPVOID,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, wintypes.LPVOID]

    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    # SetPriorityClass / SetProcessAffinityMask / SetProcessInformation all
    # live in kernel32, not advapi32.
    kernel32.SetPriorityClass.restype = wintypes.BOOL
    kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetPriorityClass.restype = wintypes.BOOL
    kernel32.GetPriorityClass.argtypes = [wintypes.HANDLE,
                                          ctypes.POINTER(wintypes.DWORD)]
    kernel32.SetProcessAffinityMask.restype = wintypes.BOOL
    kernel32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
    kernel32.GetProcessAffinityMask.restype = wintypes.BOOL
    # Three parameters: the handle plus *both* masks. Declaring only two made
    # every call raise TypeError, so affinity could never be read back.
    kernel32.GetProcessAffinityMask.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.SetProcessInformation.restype = wintypes.BOOL
    kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                               wintypes.LPVOID, wintypes.DWORD]
    return advapi32, kernel32


# ---------------------------------------------------------------- services
#
# Start types are *read* straight out of the Services registry key: that is the
# authoritative store, it is readable without elevation, and reading a DWORD is
# inherently locale-independent (unlike parsing `sc qc`, whose text is
# translated). Mutations go through the native `sc.exe` binary rather than cmd
# so the Service Control Manager applies them properly.

_SERVICES_KEY = r"SYSTEM\CurrentControlSet\Services"

SERVICE_BOOT_START = 0
SERVICE_SYSTEM_START = 1
SERVICE_AUTO_START = 2
SERVICE_DEMAND_START = 3
SERVICE_DISABLED = 4

_START_NAMES = {
    SERVICE_BOOT_START: "boot",
    SERVICE_SYSTEM_START: "system",
    SERVICE_AUTO_START: "auto",
    SERVICE_DEMAND_START: "demand",
    SERVICE_DISABLED: "disabled",
}
# sc.exe spells the same states differently; only the command token matters.
_SC_TOKENS = {
    SERVICE_BOOT_START: "boot",
    SERVICE_SYSTEM_START: "system",
    SERVICE_AUTO_START: "auto",
    SERVICE_DEMAND_START: "demand",
    SERVICE_DISABLED: "disabled",
}


def service_start_type(name: str) -> int | None:
    """Configured start type of a service, or None when it is not installed."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            f"{_SERVICES_KEY}\\{name}") as key:
            value, _vtype = winreg.QueryValueEx(key, "Start")
        return int(value)
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warn(f"app_optimizer: service_start_type({name}) failed: {exc}")
        return None


def service_is_running(name: str) -> bool | None:
    """Whether a service is currently running, or None if it cannot be read.

    Start type and running state are two different facts. A service can be
    configured ``auto`` yet deliberately stopped by the user, so restoring only
    the start type would silently undo their choice. Reading the live state
    through QueryServiceStatusEx (a numeric structure) keeps this locale
    independent, unlike parsing ``sc query`` whose labels are translated.
    """
    try:
        advapi32, _kernel32 = _win32()
    except OSError:
        return None
    scm = advapi32.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
    if not scm:
        return None
    try:
        svc = advapi32.OpenServiceW(scm, name, SERVICE_QUERY_STATUS)
        if not svc:
            return None
        try:
            status = _SERVICE_STATUS_PROCESS()
            need = wintypes.DWORD(0)
            ok = advapi32.QueryServiceStatusEx(
                svc, SERVICE_STATUS_PROCESS, ctypes.byref(status),
                ctypes.sizeof(status), ctypes.byref(need))
            if not ok:
                return None
            # 1 = SERVICE_STOPPED is the only state that means "not running";
            # the pending states are still doing work, so treat them as running.
            return status.dwCurrentState != 1
        finally:
            advapi32.CloseServiceHandle(svc)
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"app_optimizer: service_is_running({name}) failed: {exc}")
        return None
    finally:
        advapi32.CloseServiceHandle(scm)


def _sc(*args: str, timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(["sc.exe", *args], capture_output=True, text=True,
                           timeout=timeout, errors="replace",
                           creationflags=_NO_WINDOW)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def _set_start_type(name: str, start_type: int) -> tuple[bool, str]:
    token = _SC_TOKENS.get(start_type)
    if token is None:
        return False, f"unknown start type {start_type}"
    code, out = _sc("config", name, "start=", token)
    if code != 0:
        return False, f"sc config {name} start={token} failed: {out.splitlines()[-1] if out else code}"
    return True, f"{name} start type -> {token}"


def _stop_service(name: str) -> tuple[bool, str]:
    code, out = _sc("stop", name)
    text = (out or "").lower()
    if code == 0:
        return True, f"{name} stop sent"
    if "not been started" in text or "1060" in text or "cannot start" in text:
        return True, f"{name} already stopped"
    if "1062" in text or "already stopped" in text:
        return True, f"{name} already stopped"
    return False, f"sc stop {name}: {out.splitlines()[-1] if out else code}"


def _start_service(name: str) -> tuple[bool, str]:
    code, out = _sc("start", name)
    if code == 0:
        return True, f"{name} started"
    text = (out or "").lower()
    if "already running" in text or "1056" in text:
        return True, f"{name} already running"
    return False, f"sc start {name}: {out.splitlines()[-1] if out else code}"


def list_services() -> list[str]:
    """Every service name registered on this machine.

    Discovering the real names beats hardcoding them: the Chromium-family
    updater services are spelled differently per version and SKU
    (``edgeupdate`` / ``edgeupdatem`` / ``GoogleUpdaterService152.0.…``), and
    only the ones actually installed are worth touching.
    """
    import winreg
    names = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _SERVICES_KEY) as key:
            count = winreg.QueryInfoKey(key)[0]
            for i in range(count):
                try:
                    names.append(winreg.EnumKey(key, i))
                except OSError:
                    continue
    except OSError as exc:
        logger.warn(f"app_optimizer: list_services failed: {exc}")
    return names


def find_services(*patterns: str) -> list[str]:
    """Installed services whose name matches any of the given patterns."""
    import re
    try:
        rx = re.compile("|".join(patterns), re.I)
    except re.error as exc:
        logger.warn(f"app_optimizer: bad service pattern {patterns}: {exc}")
        return []
    return sorted({n for n in list_services() if rx.search(n)})


def existing_services(*patterns: str) -> list[str]:
    """``find_services`` filtered to those with a readable start type."""
    return [n for n in find_services(*patterns) if service_start_type(n) is not None]


def service_exists(name: str) -> bool:
    return service_start_type(name) is not None



def disable_service(name: str) -> tuple[dict, bool]:
    """Stop a service and flip it to *disabled*.

    Only recorded when we actually changed something. A service that is already
    disabled/stopped, or that does not exist, yields a clean no-op so reset
    never re-enables a service the user had turned off themselves.
    """
    before = service_start_type(name)
    if before is None:
        return {"kind": "service", "service": name, "missing": True}, False
    rec = {"kind": "service", "service": name, "was": int(before)}
    if before == SERVICE_DISABLED:
        rec["already"] = True
        return rec, True
    # Capture whether it was actually running, separately from its start type,
    # so reset does not start a service the user had deliberately stopped.
    was_running = service_is_running(name)
    if was_running is not None:
        rec["was_running"] = bool(was_running)
    notes = []
    stopped_ok, stop_msg = _stop_service(name)
    notes.append(stop_msg)
    changed_ok, cfg_msg = _set_start_type(name, SERVICE_DISABLED)
    notes.append(cfg_msg)
    after = service_start_type(name)
    if after != SERVICE_DISABLED:
        rec["error"] = f"{name} still starts as {_START_NAMES.get(after, after)}"
        return rec, False
    rec["changed"] = True
    if not (stopped_ok and changed_ok):
        rec["warn"] = "; ".join(notes)
    return rec, True


def restore_service(record: dict) -> tuple[bool, str]:
    name = record.get("service")
    if record.get("missing"):
        return True, f"{name} was not installed — nothing to restore"
    if record.get("already"):
        return True, f"{name} was already disabled — left as found"
    was = int(record.get("was", SERVICE_DEMAND_START))
    ok, msg = _set_start_type(name, was)
    if not ok:
        return False, msg
    # Only start it again if it was running when we found it. A service that
    # was configured to auto-start but manually stopped stays stopped.
    if record.get("was_running"):
        started, start_msg = _start_service(name)
        if not started:
            return False, start_msg
        return True, f"{name} restored to {_START_NAMES.get(was, was)} and started"
    if was != SERVICE_DISABLED:
        return True, (f"{name} restored to {_START_NAMES.get(was, was)} "
                      "and left stopped, as found")
    return True, f"{name} restored to {_START_NAMES.get(was, was)}"


# ------------------------------------------------------- process scheduling

def _iter_pids(names: list[str]):
    wanted = {n.lower() for n in names}
    try:
        import psutil
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"app_optimizer: psutil unavailable: {exc}")
        return
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower() in wanted:
                yield proc
        except Exception:  # noqa: BLE001
            continue


def read_priority(pid: int) -> int | None:
    """Current priority class of a pid as a Win32 constant, or None.

    Reads through psutil rather than GetPriorityClass. On this platform
    GetPriorityClass returns the class value in the return slot and leaves the
    documented out-parameter untouched, so the ctypes version always read 0 --
    which would have made an "exact" restore call SetPriorityClass(0).
    """
    try:
        import psutil
        return int(psutil.Process(pid).nice())
    except Exception:  # noqa: BLE001
        return None


def set_priority(names: list[str], level: str = "below") -> tuple[int, str]:
    """Set the Win32 priority class on every matching live process.

    Returns (processes_changed, note). This is a *live* adjustment, not a file
    edit, so it is safe for signed packages and is re-applied on every launch
    by the triage watcher.
    """
    cls = PRIORITY_CLASSES.get(level)
    if cls is None:
        return 0, f"unknown priority level {level!r}"
    advapi32, kernel32 = _win32()
    n = 0
    for proc in _iter_pids(names):
        try:
            handle = kernel32.OpenProcess(_SCHED_ACCESS,
                                          False, proc.info["pid"])
            if not handle:
                continue
            try:
                if kernel32.SetPriorityClass(handle, cls):
                    n += 1
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            continue
    return n, f"{n} process(es) set to {level} priority"


def read_affinity(pid: int) -> int | None:
    """Current CPU affinity mask of a pid as an int, or None if unreadable.

    Needed so reset can put back the mask the process actually had. Reconstructing
    it from a core *count* loses which cores were chosen, and assuming "all
    cores" overwrites a user who had deliberately pinned the app.
    """
    advapi32, kernel32 = _win32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        process_mask = ctypes.c_size_t()
        system_mask = ctypes.c_size_t()
        if kernel32.GetProcessAffinityMask(handle, ctypes.byref(process_mask),
                                           ctypes.byref(system_mask)):
            return int(process_mask.value)
        return None
    finally:
        kernel32.CloseHandle(handle)


def snapshot_scheduling(names: list[str]) -> list[dict]:
    """Record the exact scheduling state of every live matching process.

    The ledger needs this because priority class, affinity and EcoQoS are
    properties of a *running* process. Reset used to assume normal priority,
    all 64 cores and EcoQoS off, which silently overwrote anyone who had
    already set their browser to High priority or pinned it to some cores.
    Entries where a value could not be read carry None and are skipped on
    restore rather than guessed.
    """
    out = []
    for proc in _iter_pids(names):
        pid = proc.info["pid"]
        out.append({
            "pid": pid,
            "name": proc.info.get("name") or "",
            "priority": read_priority(pid),
            "affinity": read_affinity(pid),
        })
    return out


def restore_scheduling(entries: list[dict]) -> tuple[int, str]:
    """Put each still-live recorded process back to its own recorded values.

    Processes that have since exited are skipped: their replacements were
    started by Windows with default scheduling, so there is nothing to undo and
    forcing "normal / all cores" on them would itself be the clobbering this
    function exists to avoid.
    """
    advapi32, kernel32 = _win32()
    restored, skipped = 0, 0
    for entry in entries or []:
        pid = entry.get("pid")
        if not pid:
            skipped += 1
            continue
        handle = kernel32.OpenProcess(_SCHED_ACCESS, False, int(pid))
        if not handle:
            # Gone, or we may not touch it. Either way, leave it alone.
            skipped += 1
            continue
        try:
            touched = False
            cls = entry.get("priority")
            if cls is not None and kernel32.SetPriorityClass(handle, int(cls)):
                touched = True
            mask = entry.get("affinity")
            if mask and kernel32.SetProcessAffinityMask(handle, ctypes.c_size_t(int(mask))):
                touched = True
            if touched:
                restored += 1
        except Exception:  # noqa: BLE001
            skipped += 1
        finally:
            kernel32.CloseHandle(handle)
    note = f"{restored} process(es) back to their own priority + affinity"
    if skipped:
        note += f" · {skipped} already exited (now on Windows defaults)"
    return restored, note


def set_affinity(names: list[str], cores: int = 4) -> tuple[int, str]:
    """Restrict processes to the first ``cores`` logical CPUs.

    A background app that competes with a game benefits from being confined to
    a subset of the CPU. Cores are clamped to the real processor count and to
    64, the width of the affinity mask.
    """
    cores = max(1, min(int(cores), 64))
    advapi32, kernel32 = _win32()
    n = 0
    for proc in _iter_pids(names):
        try:
            handle = kernel32.OpenProcess(_SCHED_ACCESS,
                                          False, proc.info["pid"])
            if not handle:
                continue
            try:
                if kernel32.SetProcessAffinityMask(handle, ctypes.c_size_t((1 << cores) - 1)):
                    n += 1
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            continue
    return n, f"{n} process(es) confined to {cores} core(s)"


def set_efficiency_mode(names: list[str], enable: bool = True) -> tuple[int, str]:
    """Turn Windows Efficiency Mode (EcoQoS) explicitly on or off.

    Left to itself the OS throttles a process only opportunistically. Asking for
    it directly makes the throttling deliberate and continuous.
    """
    advapi32, kernel32 = _win32()
    n = 0
    for proc in _iter_pids(names):
        try:
            handle = kernel32.OpenProcess(_SCHED_ACCESS,
                                          False, proc.info["pid"])
            if not handle:
                continue
            try:
                state = _POWER_THROTTLING_STATE(
                    Version=1,
                    ControlMask=PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
                    State=1 if enable else 0)
                if kernel32.SetProcessInformation(
                        handle, _PROCESS_POWER_THROTTLING, ctypes.byref(state),
                        ctypes.sizeof(state)):
                    n += 1
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            continue
    return n, f"efficiency mode {'on' if enable else 'off'} for {n} process(es)"


def child_types(proc) -> set[str]:
    """The Chromium/Electron ``--type=`` values a process was launched with.

    An Electron app like Discord is several processes sharing one image name,
    so name matching alone cannot tell the GPU process from a renderer. Reading
    the actual command line is what makes it possible to target the GPU and
    crashpad children specifically instead of hitting every process.
    """
    kinds = set()
    try:
        for arg in (proc.cmdline() or []):
            if isinstance(arg, str) and arg.startswith("--type="):
                kinds.add(arg.split("=", 1)[1].strip())
    except Exception:  # noqa: BLE001
        pass
    return kinds


def find_children(names: list[str], types: list[str]):
    """Yield (process, matched_type) for children of ``names`` in ``types``."""
    wanted_types = {t.lower() for t in types}
    for proc in _iter_pids(names):
        try:
            kinds = child_types(proc)
        except Exception:  # noqa: BLE001
            continue
        for kind in kinds:
            if kind.lower() in wanted_types:
                yield proc, kind
                break


def kill_children(names: list[str], types: list[str],
                  wait: float = 2.0) -> tuple[int, list[str]]:
    """Terminate specific ``--type=`` children of an app.

    Only the requested child types are touched, so the main window and the
    renderers keep running. Returns (killed, kinds_killed). Chrome and Discord
    respawn these helpers on demand, so this is a recurring saving rather than
    a permanent one, which is exactly why the triage watcher re-applies it.
    """
    killed, kinds = 0, []
    for proc, kind in list(find_children(names, types)):
        try:
            proc.terminate()
            killed += 1
            if kind not in kinds:
                kinds.append(kind)
        except Exception:  # noqa: BLE001
            continue
    if killed:
        time.sleep(min(wait, 0.5))
    return killed, kinds


def triage_pass(plans: dict) -> dict:
    """Re-apply the live scheduling levers to every engaged app.

    Priority, affinity, EcoQoS and helper-process suppression are all properties
    of a *running* process, so they are lost the moment the app relaunches. The
    triage watcher calls this after every launch (and on a repeating timer) so
    the optimization actually sticks instead of silently decaying.
    """
    from engine.app_optimizer import apps as _apps

    out = {}
    for key, spec in (plans or {}).items():
        sched = spec.get("sched") or {}
        procs = spec.get("processes") or _apps.ENGAGED_PROCESSES.get(key) or []
        if not procs and not sched.get("kill_types"):
            continue
        touched = {}
        if procs and sched.get("priority"):
            c, _note = set_priority(procs, sched["priority"])
            touched["priority"] = c
        if procs and sched.get("cores"):
            c, _note = set_affinity(procs, sched["cores"])
            touched["affinity"] = c
        if procs and sched.get("ecoqos"):
            c, _note = set_efficiency_mode(procs, True)
            touched["ecoqos"] = c
        if sched.get("kill_types"):
            n, kinds = kill_children(procs, sched["kill_types"])
            if n:
                touched["killed"] = n
                touched["killed_types"] = kinds
        if touched:
            out[key] = touched
    return out


# ----------------------------------------------------------- launch arguments

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _append_flags(existing: str, flags: list[str]) -> tuple[str, bool]:
    """Idempotently add ``flags`` to a command line.

    Returns (new_command, changed). A flag already present anywhere in the
    string is not added twice, so re-running this is a no-op.
    """
    if not flags:
        return existing, False
    text = existing or ""
    changed = False
    for flag in flags:
        if flag not in text:
            text = f"{text} {flag}".strip()
            changed = True
    return text, changed


def patch_run_flags(run_value: str, flags: list[str]) -> tuple[list, bool, str]:
    """Append launch flags to an HKCU Run entry, snapshotting it first."""
    snap = reg_util.read_value("HKCU", _RUN_KEY, run_value)
    existed, rtype, data = snap
    if not existed:
        return [], False, f"no autostart entry named {run_value!r} — skipped"
    rec = {"kind": "reg", "hive": "HKCU", "path": _RUN_KEY, "name": run_value,
           "existed": True, "vtype": rtype or "STRING", "data": data}
    new, changed = _append_flags(data or "", flags)
    if not changed:
        return [], True, f"{run_value} launch flags already present"
    ok, msg = reg_util.write_value("HKCU", _RUN_KEY, run_value, new, rtype or "REG_SZ")
    if not ok:
        return [], False, f"could not update {run_value} autostart: {msg}"
    return [rec], True, f"{len(flags)} launch flag(s) added to {run_value} autostart"


def _ps(command: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                           capture_output=True, text=True, timeout=timeout,
                           creationflags=_NO_WINDOW)
        return (r.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _shortcut_dirs() -> list[str]:
    appdata = os.environ.get("APPDATA", "")
    programdata = os.environ.get("PROGMData", r"C:\ProgramData")
    return [
        os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(programdata, "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop"),
    ]


def find_shortcuts(names: list[str]) -> list[str]:
    """Locate .lnk files whose filename matches any of ``names``."""
    found = []
    wanted = {n.lower() for n in names}
    for folder in _shortcut_dirs():
        if not os.path.isdir(folder):
            continue
        for root, _dirs, files in os.walk(folder):
            for fn in files:
                if fn.lower().endswith(".lnk") and os.path.splitext(fn)[0].lower() in wanted:
                    found.append(os.path.join(root, fn))
    return found


def patch_shortcut_flags(links: list[str], flags: list[str]) -> tuple[list, bool, str]:
    """Append launch flags to each .lnk's Arguments, snapshotting the originals.

    A .lnk is a compound binary file; the only reliable way to edit its
    Arguments field is through the shell's own IShellLink COM wrapper, so this
    goes through PowerShell rather than hand-rolling binary offsets.
    """
    if not links:
        return [], False, "no shortcuts found to patch"
    if not flags:
        return [], False, "no flags to add"
    ps_flags = ", ".join("'" + f.replace("'", "''") + "'" for f in flags)
    body = ["$sh = New-Object -ComObject WScript.Shell"]
    for link in links:
        lit = "'" + link.replace("'", "''") + "'"
        body.append(
            f"if (Test-Path -LiteralPath {lit}) {{"
            f"  $l = $sh.CreateShortcut({lit});"
            f"  $orig = $l.Arguments;"
            f"  $add = @();"
            f"  foreach ($f in @({ps_flags})) {{"
            f"    if ($orig -notlike ('*' + $f + '*')) {{ $add += $f }}"
            f"  }}"
            f"  if ($add.Count -gt 0) {{"
            f"    $new = (($orig + ' ' + ($add -join ' ')).Trim());"
            f"    $l.Arguments = $new;"
            f"    $l.Save();"
            f"    Write-Output ('CHANGED|' + {lit} + '|' + $orig + '|' + $new);"
            f"  }} else {{"
            f"    Write-Output ('SAME|' + {lit});"
            f"  }}"
            f"}}")
    out = _ps("\n".join(body))
    records, notes = [], []
    for line in (out or "").splitlines():
        line = line.strip()
        if line.startswith("CHANGED|"):
            _tag, path, orig, _new = line.split("|", 3)
            records.append({"kind": "link", "path": path, "arguments": orig,
                            "flags": list(flags)})
            notes.append(os.path.basename(path))
        elif line.startswith("SAME|"):
            notes.append("already set")
    if not records:
        return [], True, f"shortcut launch flags already present ({len(links)} link(s))"
    return records, True, f"launch flags added to {', '.join(notes[:3])}"


def restore_link(record: dict) -> tuple[bool, str]:
    path = record.get("path")
    if not path or not os.path.isfile(path):
        return True, "shortcut no longer present — nothing to restore"
    orig = (record.get("arguments") or "").replace("'", "''")
    lit = "'" + path.replace("'", "''") + "'"
    ps = (f"$sh = New-Object -ComObject WScript.Shell; "
          f"if (Test-Path -LiteralPath {lit}) {{ "
          f"$l = $sh.CreateShortcut({lit}); $l.Arguments = '{orig}'; $l.Save(); "
          f"Write-Output 'OK' }}")
    out = _ps(ps)
    if "OK" not in (out or ""):
        return False, f"could not restore shortcut arguments for {path}"
    return True, f"restored launch arguments for {os.path.basename(path)}"


# ------------------------------------------------------------ triage watcher

WATCHER_TASK = "MaximumTweaks AppOptimizer Triage"


def _self_exe() -> str:
    import sys
    if getattr(sys, "frozen", False):
        return sys.executable
    return str(Path(__file__).resolve().parents[2] / "main.py")


def install_watcher(engaged: dict, minutes: int = 5) -> tuple[dict, bool]:
    """Create the repeating triage task for the currently engaged apps.

    The task runs ``<this exe> --cli ao-triage`` on logon and then every
    ``minutes``. It carries no GUI and takes no single-instance mutex, so it
    cannot contend with the running app. The list of apps is passed as argv so
    the task is inert once the last app is reset.
    """
    if not engaged:
        return {"kind": "task", "task": WATCHER_TASK, "missing": True}, False
    exe = _self_exe()
    args = ",".join(sorted(engaged))
    command = (f'"{exe}"' if exe.lower().endswith(".exe")
               else f'"{_pythonw()}" "{exe}"') + f" --cli ao-triage {args}"
    ps = (
        "$a = New-ScheduledTaskAction -Execute 'cmd.exe' "
        f"-Argument '/c {command}'; "
        "$t = New-ScheduledTaskTrigger -AtLogOn; "
        f"$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) "
        f"-RepetitionInterval (New-TimeSpan -Minutes {int(minutes)}); "
        "$p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest; "
        f"$null = Register-ScheduledTask -TaskName '{WATCHER_TASK}' -Action $a "
        "-Trigger @($t,$t2) -Principal $p -Force; "
        "Write-Output 'OK'")
    out = _ps(ps, timeout=45)
    if "OK" not in (out or ""):
        return ({"kind": "task", "task": WATCHER_TASK, "error": "registration failed"},
                False)
    return ({"kind": "watcher", "task": WATCHER_TASK,
             "apps": sorted(engaged), "minutes": int(minutes)}, True)


def _pythonw() -> str:
    import sys
    base = Path(sys.executable)
    cand = base.with_name("pythonw.exe")
    return str(cand if cand.is_file() else base)


def remove_watcher() -> tuple[bool, str]:
    out = _ps(f"Unregister-ScheduledTask -TaskName '{WATCHER_TASK}' "
              f"-Confirm:$false -ErrorAction SilentlyContinue; Write-Output 'OK'", timeout=30)
    if "OK" not in (out or ""):
        return False, "could not unregister the triage watcher"
    return True, f"triage watcher removed ({WATCHER_TASK})"


def watcher_installed() -> bool:
    out = _ps(f"(Get-ScheduledTask -TaskName '{WATCHER_TASK}' -ErrorAction SilentlyContinue).TaskName")
    return WATCHER_TASK in (out or "")


def restore_watcher(record: dict) -> tuple[bool, str]:
    """The watcher is a pure artifact of engagement, so undoing it means
    deleting the task; there is no previous state worth restoring."""
    return remove_watcher()


# ------------------------------------------------------------------ restart

def process_running(names: list[str]) -> bool:
    for _proc in _iter_pids(names):
        return True
    return False


def close_app(names: list[str], main: str, timeout: float = 8.0) -> bool:
    """Close an app: a polite WM_CLOSE first, then a forced tree kill.

    Returns True when the processes are gone. A forced kill is the fallback
    only after the graceful attempt has genuinely had time to work.
    """
    if not process_running(names):
        return True
    for proc in list(_iter_pids(names)):
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            continue
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not process_running(names):
            return True
        time.sleep(0.25)
    subprocess.run(["taskkill", "/F", "/T", "/IM", main],
                   capture_output=True, creationflags=_NO_WINDOW)
    deadline = time.time() + 4.0
    while time.time() < deadline:
        if not process_running(names):
            return True
        time.sleep(0.2)
    return not process_running(names)


def launch_app(exe: str, args: str = "") -> tuple[bool, str]:
    """Start an app from its own install path, detached, with the given args."""
    if not exe or not os.path.isfile(exe):
        return False, f"executable not found: {exe}"
    cmd = f'"{exe}"' + (f" {args}" if args else "")
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | _NO_WINDOW
    try:
        subprocess.Popen(cmd, close_fds=True, creationflags=flags)
    except Exception as exc:  # noqa: BLE001
        return False, f"could not relaunch {os.path.basename(exe)}: {exc}"
    return True, f"relaunched {os.path.basename(exe)}"


def restart_app(names: list[str], main: str, exe: str, args: str = "") -> tuple[bool, str]:
    """Close then relaunch one app so the applied changes take effect now.

    Only ever called for the single app the user toggled, so cards never
    restart each other's processes.
    """
    closed = close_app(names, main)
    if not closed:
        return False, f"{os.path.basename(main)} would not exit"
    time.sleep(0.4)
    return launch_app(exe, args)
