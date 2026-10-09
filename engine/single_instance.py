"""Version-aware single-instance guard for the desktop app.

The legacy guard matched the running window by its *versioned* title
(``Maximum Tweaks v2.5.9``). A second launch therefore never found an
already-running copy of a *different* version, so it exited silently and the
stale window stayed on screen - the "the update did nothing until I fully close
and reopen the app" report. This module matches any MaximumTweaks window
regardless of version and only defers to one that is at least as new as ours;
an older lingering build (an autostart leftover or a portable copy) is
terminated so the newer build can take over.
"""
from __future__ import annotations

import os

MUTEX_NAME = "Local\\MaximumTweaks.SingleInstance"
ERROR_ALREADY_EXISTS = 183


def parse_version(text) -> tuple:
    """``'v2.5.9'`` / ``'2.5.10'`` / ``'2.5.9-rc1'`` -> comparable int tuple."""
    if text is None:
        return ()
    s = str(text).strip().lstrip("vV")
    nums: list = []
    for chunk in s.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        nums.append(int(digits))
    return tuple(nums)


def title_version(app_name: str, title: str):
    """Return the version in a main-window title, or None if it isn't ours."""
    prefix = f"{app_name} v"
    if not title or not title.startswith(prefix):
        return None
    return title[len(prefix):].strip() or None


def decide(running, ours: str) -> tuple:
    """Pick what to do given the versions of already-running windows.

    Returns one of::

        ("start", None)        nothing running - open the GUI
        ("focus", version)     a same-or-newer build runs - focus it, exit
        ("takeover", version)  only older builds run - kill them, then open
    """
    parsed = [(v, parse_version(v)) for v in running]
    parsed = [(v, t) for v, t in parsed if t]
    if not parsed:
        return ("start", None)
    newest_v, newest_t = max(parsed, key=lambda vt: vt[1])
    if newest_t >= parse_version(ours):
        return ("focus", newest_v)
    return ("takeover", newest_v)


def _enum_app_windows(app_name: str):
    """``(hwnd, pid, version)`` for every top-level MaximumTweaks window."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    results: list = []

    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                      ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    enumproc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                  wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        ver = title_version(app_name, buf.value)
        if ver is None:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        results.append((hwnd, pid.value, ver))
        return True

    user32.EnumWindows(enumproc(_cb), 0)
    return results


def _focus(hwnd) -> None:
    import ctypes
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)


def _terminate(pid: int) -> None:
    import ctypes
    from ctypes import wintypes

    PROCESS_TERMINATE = 0x0001
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                     wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
    if handle:
        kernel32.TerminateProcess(handle, 1)
        kernel32.CloseHandle(handle)


def enforce_single_instance(app_name: str, our_version: str,
                            mutex_name: str = MUTEX_NAME) -> bool:
    """Return True when the GUI should start, False when it must exit.

    A same-or-newer instance is brought to the foreground and we exit; an
    older-only set of instances is terminated so this newer build can run.
    """
    import ctypes
    import time
    from ctypes import wintypes

    try:
        kernel32 = ctypes.windll.kernel32
    except AttributeError:  # not Windows - don't block startup
        return True
    if not hasattr(kernel32, "CreateMutexW"):
        return True

    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                      wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, mutex_name)
    if kernel32.GetLastError() != ERROR_ALREADY_EXISTS:
        return True  # we own the mutex

    # The other instance may still be booting - give its window a moment.
    wins: list = []
    for _ in range(30):  # up to ~6s
        wins = _enum_app_windows(app_name)
        if wins:
            break
        time.sleep(0.2)

    if not wins:
        # Mutex held but no window we can see: a zombie or a sub-second race.
        # Silently dying is the bug we are fixing, so own the mutex and go.
        return True

    action, ver = decide([v for _h, _p, v in wins], our_version)
    if action == "focus":
        for hwnd, _pid, v in wins:
            if v == ver:
                _focus(hwnd)
                break
        return False
    if action == "takeover":
        me = os.getpid()
        for _hwnd, pid, _v in wins:
            if pid and pid != me:
                _terminate(pid)
        # Our own handle keeps the named mutex alive, so close it and re-create
        # once the old processes have died to become the owner.
        for _ in range(25):
            kernel32.CloseHandle(handle)
            handle = kernel32.CreateMutexW(None, False, mutex_name)
            if kernel32.GetLastError() != ERROR_ALREADY_EXISTS:
                break
            time.sleep(0.2)
        return True
    return True
