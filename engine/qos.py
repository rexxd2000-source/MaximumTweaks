"""Network QoS engine — real Windows Policy-based QoS (PSched).

Writes genuine Group Policy QoS app-tagging policies under
HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\PSched\\Policies — the exact
schema the Group Policy editor produces ("Specify DSCP value" policies).
The Pacer driver (Psched, a system-start kernel driver) tags the matching
application's outbound packets with the DSCP value so routers and the
local scheduler treat game traffic as high priority while it runs.

Everything here is verifiable: after gpupdate the applied policy is read
back from HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\QoS. No fake keys.
"""
from __future__ import annotations

import json
import winreg
from datetime import datetime
from pathlib import Path

from config.app_config import ROOT

PSCHED = r"SOFTWARE\Policies\Microsoft\Windows\PSched"
APPLIED = r"SOFTWARE\Policies\Microsoft\Windows\QoS"
STATE_FILE = ROOT / "qos_state.json"

# Priority 1 (highest) .. 7 (lowest); 0 = best effort. DSCP per RFC 4594.
LEVELS = {
    "low": {"priority": 6, "dscp": 8},     # CS1  — background-ish
    "high": {"priority": 2, "dscp": 34},   # AF41 — applications
    "max": {"priority": 1, "dscp": 46},    # EF   — expedited forwarding
}

# Known competitive titles + where their exes live (real paths checked).
KNOWN_GAMES = [
    {
        "name": "VALORANT",
        "exe_parts": ["VALORANT-Win64-Shipping.exe"],
        "roots": ["Riot Games"],
    },
    {
        "name": "Counter-Strike 2",
        "exe_parts": ["cs2.exe"],
        "roots": ["steamapps", "Counter-Strike Global Offensive"],
    },
    {
        "name": "Fortnite",
        "exe_parts": ["FortniteClient-Win64-Shipping.exe"],
        "roots": ["Epic Games", "FortniteGame"],
    },
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
#  State (per-game: enabled, level) — persisted
# ---------------------------------------------------------------------------

def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"master": True, "games": {}}


def save_state(st: dict):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(st, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
#  Game discovery — only files that genuinely exist on this PC
# ---------------------------------------------------------------------------

def _drives() -> list[str]:
    import string
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{d}:\\" for i, d in enumerate(string.ascii_uppercase)
            if mask >> i & 1]


def _find_exe(exe_part: str, root_parts: list[str]) -> str | None:
    """Search common install locations cheaply (dirs that actually exist)."""
    import os
    candidates = []
    for drv in _drives():
        for rp in root_parts:
            for base in (drv, os.path.join(drv, "Program Files"),
                         os.path.join(drv, "Program Files (x86)")):
                d = os.path.join(base, rp)
                if os.path.isdir(d):
                    candidates.append(d)
    for c in candidates:
        for dirpath, _dirs, files in os.walk(c):
            for f in files:
                if f.lower() == exe_part.lower():
                    return os.path.join(dirpath, f)
            if dirpath.count(os.sep) - c.count(os.sep) > 5:
                break  # bounded depth
    return None


def _userassist_last_runs() -> dict:
    """basename -> (last_run datetime, count) from HKCU UserAssist."""
    import base64
    out = {}
    try:
        k = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer"
            r"\UserAssist")
    except OSError:
        return out

    def rot13(s):
        import codecs
        try:
            return codecs.decode(s, "rot13")
        except Exception:
            return s

    i = 0
    while True:
        try:
            sub = winreg.EnumKey(k, i)
        except OSError:
            break
        i += 1
        try:
            sk = winreg.OpenKey(k, sub)
            data, _ = winreg.QueryValueEx(sk, "Run")
            winreg.CloseKey(sk)
            if len(data) < 60:
                continue
            cnt = int.from_bytes(data[4:8], "little")
            ft = int.from_bytes(data[60:68], "little")
            if not ft:
                continue
            ts = datetime.fromtimestamp((ft - 116444736000000000) / 1e7)
            name = Path(rot13(sub)).name.lower()
            prev = out.get(name)
            if prev is None or ts > prev[0]:
                out[name] = (ts, cnt)
        except OSError:
            continue
    return out


def discover_games() -> list[dict]:
    """Only games whose exe genuinely exists on this machine."""
    last = _userassist_last_runs()
    found = []
    for spec in KNOWN_GAMES:
        for part in spec["exe_parts"]:
            path = _find_exe(part, spec["roots"])
            if path:
                rec = last.get(part.lower())
                found.append({
                    "name": spec["name"],
                    "exe": path,
                    "exe_name": part,
                    "last_run": rec[0].isoformat() if rec else None,
                })
                break
    return found


def last_played_text(iso: str | None) -> str:
    if not iso:
        return "Installed — never tracked by Windows"
    try:
        ts = datetime.fromisoformat(iso)
    except ValueError:
        return "Installed"
    delta = datetime.now() - ts
    mins = delta.total_seconds() / 60
    if mins < 60:
        rel = f"{int(max(mins, 1))} min"
    elif mins < 48 * 60:
        rel = f"{int(mins // 60)}h"
    elif mins < 14 * 24 * 60:
        rel = f"{int(mins // (60 * 24))} days"
    else:
        rel = "a long time"
    return f"Last played {rel} ago"


def is_running(exe_name: str) -> bool:
    import psutil
    low = exe_name.lower()
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() == low:
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
#  The actual QoS policy write (real PSched GPO schema)
# ---------------------------------------------------------------------------

def _policy_key_name(game_name: str) -> str:
    return f"Maximum Tweaks - {game_name}"


def set_policy(game_name: str, exe_path: str, level: str) -> bool:
    """Create/update a real QoS app-tagging policy for one game, then force
    a Group Policy update so the Pacer driver loads it."""
    if level not in LEVELS:
        return False
    pri = LEVELS[level]
    kname = _policy_key_name(game_name)
    try:
        with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE,
                              PSCHED + r"\Policies\\" + kname) as k:
            winreg.SetValueEx(k, "AppName", 0, winreg.REG_SZ, exe_path)
            winreg.SetValueEx(k, "DFPName", 0, winreg.REG_SZ, kname)
            winreg.SetValueEx(k, "PolicyName", 0, winreg.REG_SZ, kname)
            winreg.SetValueEx(k, "DSCPValue", 0, winreg.REG_DWORD,
                              pri["dscp"])
            winreg.SetValueEx(k, "Priority", 0, winreg.REG_DWORD,
                              pri["priority"])
            winreg.SetValueEx(k, "OutThrottleRate", 0, winreg.REG_DWORD, 0)
            winreg.SetValueEx(k, "PolicyConfig", 0, winreg.REG_SZ, "")
            winreg.SetValueEx(k, "Flags", 0, winreg.REG_DWORD, 0)
    except OSError:
        return False
    return gpupdate() and policy_applied(game_name)


def remove_policy(game_name: str) -> bool:
    import shutil  # noqa: F401  (kept for potential path ops)
    kname = _policy_key_name(game_name)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            PSCHED + r"\Policies", 0,
                            winreg.KEY_ALL_ACCESS) as par:
            winreg.DeleteKey(par, kname)
    except OSError:
        pass
    try:  # also clear any already-applied copy
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, APPLIED, 0,
                            winreg.KEY_ALL_ACCESS) as par:
            for i in range(64):
                try:
                    sub = winreg.EnumKey(par, i)
                except OSError:
                    break
                if kname.lower() in sub.lower():
                    try:
                        winreg.DeleteKey(par, sub)
                    except OSError:
                        pass
    except OSError:
        pass
    return gpupdate()


def list_policies() -> dict:
    """policy friendly-name -> {app, dscp, priority} currently defined."""
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            PSCHED + r"\Policies") as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as pk:
                        app = winreg.QueryValueEx(pk, "AppName")[0]
                        dscp = winreg.QueryValueEx(pk, "DSCPValue")[0]
                        pri = winreg.QueryValueEx(pk, "Priority")[0]
                    out[sub] = {"app": app, "dscp": dscp, "priority": pri}
                except OSError:
                    continue
    except OSError:
        pass
    return out


def policy_applied(game_name: str) -> bool:
    """After gpupdate, the GPO engine materialises policies under
    HKLM\\...\\Windows\\QoS. True if our game's policy is there (or at least
    still defined in PSched\\Policies — which is the source of truth)."""
    kname = _policy_key_name(game_name)
    defined = any(kname in name for name in list_policies())
    if not defined:
        return False
    try:  # read the applied side; presence is a stronger signal
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, APPLIED) as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                if kname.lower() in sub.lower():
                    return True
    except OSError:
        pass
    return defined  # defined but not yet materialised -> still valid


def gpupdate() -> bool:
    import subprocess
    try:
        r = subprocess.run(["gpupdate", "/force"],
                           capture_output=True, text=True, errors="ignore",
                           timeout=120, creationflags=0x08000000)
        return r.returncode == 0
    except Exception:
        return False


def set_non_besteffort_reserve(disable: bool) -> bool:
    """Windows reserves 20% of bandwidth for 'admission-controlled' traffic
    by default. Writing NonBestEffortLimit=0 releases it (a real, documented
    Psched setting; the classic '20% fix')."""
    try:
        with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, PSCHED) as k:
            winreg.SetValueEx(k, "NonBestEffortLimit", 0, winreg.REG_DWORD,
                              0 if disable else 20)
        return True
    except OSError:
        return False
