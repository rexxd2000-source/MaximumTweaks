"""Launch native Windows system tools and run DB tweak commands.

Never raises: every entry point returns a bool (or a tuple) so the UI can
show a clean toast on failure instead of a silent crash.

Launch rules (so tools open the right way and nothing flashes a stray
console):
  * shell-launchable targets (.msc / .cpl / .exe / bare app names) are
    ShellExecute'd via ``cmd /c start`` in a hidden window;
  * PowerShell / console commands (DISM, SFC, chkdsk, ipconfig...) run in a
    visible console so the user can watch progress;
  * admin-flagged tweaks that are not already elevated re-launch through a
    UAC prompt up front (never a failed permission check first), leaving the
    elevated console visible so DISM/SFC output stays readable.
"""
from __future__ import annotations

import ctypes
import os
import re
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

# Extensions that should be ShellExecute'd (windows open, not a console).
_GUI_EXT = (".msc", ".cpl", ".lnk", ".scr", ".exe", ".htm", ".html", ".url")
# Extension-less Windows utilities ShellExecute can resolve by name.
_GUI_NAMES = {
    "taskmgr", "regedit", "resmon", "msconfig", "sigverif", "perfmon",
    "mdsched", "control", "explorer", "mmc", "gpedit", "winver", "dxdiag",
    "msinfo32", "eventvwr", "devicepairingwizard",
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
    Commands flagged ``admin`` launch elevated (UAC) up front when the
    current process is not already running as administrator, so tools like
    SFC/DISM never die on a fast "access denied" check first.
    """
    for action in tweak.get("actions", []):
        if not isinstance(action, (tuple, list)) or len(action) < 2:
            continue
        kind = action[0]
        if kind == "cmd":
            cmd = action[1]
            if tweak.get("admin") and not is_elevated():
                ok = run_cmd_elevated(cmd)
            else:
                ok = run_cmd(cmd)
            return ok, "run"
        if kind == "guidance":
            return True, "guidance"
    return False, "none"


def run_cmd_elevated(cmd: str) -> bool:
    """Run a command line elevated through a UAC prompt.

    The elevated console is left visible so long-running repairs (DISM, SFC,
    chkdsk) show their progress. Blocks only until the user answers the UAC
    prompt; returns True once accepted and the elevated process is launched.
    """
    try:
        script = (
            "Start-Process cmd -ArgumentList '/c {}' -Verb RunAs"
        ).format(cmd.replace('"', '\\"'))
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            rc = proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            return True  # UAC still pending -> assume the user will answer
        return rc == 0
    except OSError as exc:
        logger.error(f"elevated run({cmd}) failed: {exc}")
        return False


def run_cmd(cmd: str) -> bool:
    """Run a raw command line (as stored in a tweak action)."""
    cmd = cmd.strip()
    if not cmd:
        return False
    low = cmd.lower()
    if low.startswith("start "):
        return _shell_open(cmd[6:].strip().strip('"'))
    if low.startswith("powershell"):
        rest = cmd[len("powershell"):].strip()
        for flag in ("-noprofile", "-command", "-noninteractive"):
            idx = rest.lower().find(flag)
            if idx != -1:
                rest = rest[idx + len(flag):].strip()
        return _new_console(["powershell", "-NoProfile", "-Command", rest])
    # GUI / shell-launchable target: ShellExecute it, no console flash.
    token = _first_token(cmd)
    if _is_gui_target(token):
        return _shell_open(token)
    # Plain console command (DISM, sfc, chkdsk, ipconfig...) - visible window.
    return _new_console(["cmd", "/c", cmd])


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _first_token(cmd: str) -> str:
    m = re.match(r'^\s*([^\s]+)', cmd)
    return m.group(1).strip('"') if m else ""


def _is_gui_target(token: str) -> bool:
    t = token.lower()
    if os.path.splitext(t)[1] in _GUI_EXT:
        return True
    return t in _GUI_NAMES


def _startfile(path: str) -> bool:
    try:
        os.startfile(path)  # noqa: S606 - launching a trusted system tool
        return True
    except OSError as exc:
        logger.error(f"startfile({path}) failed: {exc}")
        return False


def _shell_open(target: str) -> bool:
    """ShellExecute a target via ``cmd /c start`` in a hidden window.

    Resolves extension-less names and URI-style targets (windowsdefender:)
    the way Explorer does, without flashing a console.
    """
    flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.Popen(
            ["cmd", "/c", "start", "", target],
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.wait(timeout=10)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _new_console(argv: list[str]) -> bool:
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
