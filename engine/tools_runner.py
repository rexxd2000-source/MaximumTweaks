"""Launch native Windows system tools and run DB tweak commands.

Never raises: every entry point returns a bool (or a tuple) so the UI can
show a clean toast on failure instead of a silent crash.
"""
from __future__ import annotations

import ctypes
import os
import subprocess

from rexlog import logger

# key -> executable / shell document opened via ShellExecute (os.startfile).
SHELL_TOOLS = {
    "winver": "winver.exe",
    "msinfo32": "msinfo32.exe",
    "dxdiag": "dxdiag.exe",
    "devmgmt": "devmgmt.msc",
    "ncpa": "ncpa.cpl",
}


def launch_tool(key: str) -> bool:
    """Launch a system tool by key. Returns True on success."""
    if key == "flushdns":
        return run_cmd("ipconfig /flushdns")
    target = SHELL_TOOLS.get(key)
    if target is None:
        logger.error(f"Unknown tool key: {key}")
        return False
    return _startfile(target)


def run_tweak(tweak: dict) -> tuple[bool, str]:
    """Run a database tweak's first cmd/guidance action.

    Returns (ok, kind) where kind is "run", "guidance" or "none".
    Commands flagged ``admin`` retry elevated via a UAC prompt when the
    current process is not already running as administrator.
    """
    for action in tweak.get("actions", []):
        if not isinstance(action, (tuple, list)) or len(action) < 2:
            continue
        kind = action[0]
        if kind == "cmd":
            ok = run_cmd(action[1])
            if not ok and tweak.get("admin") and not is_elevated():
                ok = run_cmd_elevated(action[1])
            return ok, "run"
        if kind == "guidance":
            return True, "guidance"
    return False, "none"


def run_cmd_elevated(cmd: str) -> bool:
    """Relaunch a command line elevated through a UAC prompt."""
    try:
        script = ("Start-Process cmd -ArgumentList '/c {}' -Verb RunAs "
                  "-WindowStyle Hidden").format(cmd.replace('"', '\\"'))
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc.poll() is None
    except OSError as exc:
        logger.error(f"elevated run({cmd}) failed: {exc}")
        return False


def run_cmd(cmd: str) -> bool:
    """Run a raw command line (as stored in a tweak action).

    Handles the "start <program>" form (ShellExecute), PowerShell scripts
    (opens in a new console so the user sees the output), and plain
    command lines (new console). Long-running/verbose commands like DISM,
    SFC, ping and powercfg all get a visible console window.
    """
    cmd = cmd.strip()
    if not cmd:
        return False
    low = cmd.lower()
    if low.startswith("start "):
        target = cmd[6:].strip().strip('"')
        if not target:
            return False
        return _startfile(target)
    if low.startswith("powershell -noprofile -command"):
        return _run_new_console(["powershell", "-NoProfile", "-Command",
                                 cmd.split("-Command", 1)[1].strip()])
    if low.startswith("powershell"):
        return _run_new_console(["powershell", "-NoProfile", "-Command",
                                 cmd.split("powershell", 1)[1].strip()])
    # Fallback: hand to cmd /c so built-ins (ver, ping, ipconfig, DISM...)
    # resolve correctly and the output is visible in a new console.
    return _run_new_console(["cmd", "/c", cmd])


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _startfile(path: str) -> bool:
    try:
        os.startfile(path)  # noqa: S606 - launching a trusted system tool
        return True
    except OSError as exc:
        logger.error(f"startfile({path}) failed: {exc}")
        return False


def _run_new_console(argv: list[str]) -> bool:
    flags = 0
    if hasattr(subprocess, "CREATE_NEW_CONSOLE"):
        flags = subprocess.CREATE_NEW_CONSOLE
    try:
        proc = subprocess.Popen(
            argv,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            rc = proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            return True  # still running -> treat as launched
        return rc == 0
    except OSError as exc:
        logger.error(f"run({argv}) failed: {exc}")
        return False
