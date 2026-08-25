"""Npcap detection and interactive installation helper.

Npcap's free edition does NOT support silent /S installs (OEM only).
This module finds the bundled npcap-*.exe and launches it interactively.
A PySide6 dialog (NpcapInstallDialog) can be shown to guide the user.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from typing import Optional


def _frozen_base() -> Optional[str]:
    """Return the PyInstaller _MEIPASS temp dir when running as a frozen exe."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS  # type: ignore[attr-defined]
    return None


def _dev_base() -> str:
    """Return the project root when running from source."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def is_npcap_installed() -> bool:
    """Check if Npcap (wpcap.dll) is present on the system."""
    for folder in ("System32", "SysWOW64"):
        for sub in ("Npcap", ""):
            dll = os.path.join(
                os.environ.get("SystemRoot", r"C:\Windows"),
                folder, sub, "wpcap.dll",
            )
            if os.path.isfile(dll):
                return True
    for pf in ("ProgramFiles", "ProgramFiles(x86)"):
        dll = os.path.join(os.environ.get(pf, ""), "Npcap", "wpcap.dll")
        if os.path.isfile(dll):
            return True
    return False


def find_bundled_installer() -> Optional[str]:
    """Locate the npcap-*.exe installer bundled with the app."""
    candidates = []
    base = _frozen_base()
    if base:
        candidates.append(base)
    candidates.append(_dev_base())
    candidates.append(os.path.dirname(os.path.abspath(__file__)))
    for base_dir in candidates:
        if not base_dir or not os.path.isdir(base_dir):
            continue
        for root, _dirs, files in os.walk(base_dir):
            for name in files:
                if name.lower().startswith("npcap") and name.lower().endswith(".exe"):
                    return os.path.join(root, name)
    return None


def launch_installer(installer_path: str) -> Optional[subprocess.Popen]:
    """Launch the Npcap installer interactively. Returns the Popen handle."""
    if not os.path.isfile(installer_path):
        return None
    try:
        proc = subprocess.Popen(
            [installer_path],
            creationflags=getattr(subprocess, "SHELLFLAG", 0) | 0x00000040,  # SW_SHOWDEFAULT
        )
        return proc
    except Exception:
        return None
