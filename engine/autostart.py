"""Keep the app's own Windows autostart entry pointing at *this* build.

An autostart value aimed at an old or portable MaximumTweaks.exe (for example
one left on the Desktop) keeps resurrecting a pre-update copy on every login -
the "old version comes back after updating" report. On startup we repair the
HKCU Run entry: if it targets a *different* MaximumTweaks.exe we repoint it at
the running executable (preserving its arguments), and if the target is gone we
drop the dead entry. Entries that don't name our exe are left untouched.
"""
from __future__ import annotations

import os
import sys

from engine import reg_util

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "MaximumTweaks"
EXE_NAME = "MaximumTweaks.exe"


def _current_exe() -> str:
    try:
        return os.path.abspath(sys.executable or "")
    except Exception:  # noqa: BLE001
        return ""


def _split_command(command: str) -> tuple:
    """Split a Run command line -> (executable, arguments)."""
    command = (command or "").strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        if end == -1:
            return "", ""
        return command[1:end], command[end + 1:].strip()
    parts = command.split(" ", 1)
    return parts[0], (parts[1].strip() if len(parts) > 1 else "")


def repair_stale_autostart(name: str = RUN_NAME, run_key: str = RUN_KEY,
                           exe_name: str = EXE_NAME) -> bool:
    """Repoint/remove the app's own stale HKCU Run entry.

    Returns True when the entry was changed. Never raises.
    """
    if not getattr(sys, "frozen", False):
        return False  # don't rewrite the entry to python.exe in dev
    try:
        existed, _rtype, data = reg_util.read_value("HKCU", run_key, name)
        if not existed or not data:
            return False
        target, args = _split_command(str(data))
        if not target or os.path.basename(target).lower() != exe_name.lower():
            return False  # not ours - leave it alone

        current = _current_exe()
        if not current:
            return False
        if os.path.normcase(os.path.abspath(target)) == os.path.normcase(current):
            return False  # already points at us

        if not os.path.isfile(target):
            ok, _msg = reg_util.delete_value("HKCU", run_key, name)
            return ok

        value = f'"{current}"' + (f" {args}" if args else "")
        ok, _msg = reg_util.write_value("HKCU", run_key, name, value, "STRING")
        return ok
    except Exception:  # noqa: BLE001
        return False
