"""Tweak definition DSL for the Maximum Tweaks database.

Every category module builds its tweak list with the small ``T`` factory
produced by :func:`make_T`. The factory validates fields and fills sane
defaults so category files stay compact and readable.

Action tuples (first element selects executor implementation):

  ("reg", hive, path, value_name, value, vtype)
      Write a registry value.  hive in {"HKLM","HKCU","HKCR","HKU"}
      vtype in {"DWORD","QWORD","STRING","EXPAND_STRING","BINARY","MULTI_STRING"}
  ("regall", hive, base_path, value_name, value, vtype)
      Write a value into EVERY immediate subkey of base_path (e.g. all
      TCP/IP interface keys).  Live-state checks it as "all subkeys match".
  ("regdel", hive, path, value_name)      Delete a value (for reverts)
  ("regdelall", hive, base_path, value_name)
      Delete a value from every immediate subkey of base_path (for reverts)
  ("regkeydel", hive, path)               Delete a key tree (for reverts)
  ("svc", name, startup_mode)             startup_mode: auto|manual|disabled
  ("svcstart", name) / ("svcstop", name)  Runtime control
  ("cmd", command, [timeout_seconds])     Run a shell command
  ("file", action, path, content)         action: write|append|delete
  ("ini", path, section, key, value)      Set key=value in an ini file
                                          (e.g. a game's GameUserSettings.ini)
  ("power", setting, value, scheme)       powercfg value, scheme default SCHEME_CURRENT
  ("powerscheme", "setactive", guid)      Activate a power scheme
  ("powerscheme", "duplicate", base_guid, name)  Create new scheme
  ("sched", "disable", "/TN \\"task\\"") / ("sched", "enable", ...)
  ("appx", "remove", package)             Remove a per-user Appx package
  ("appx", "register", package)           Re-register a package (revert)
  ("restart", "explorer")                 Restart explorer.exe
  ("mkdir", path)                         Create directory tree (revert-safe)

Tweak fields:
  id, name, desc, changes, why, category, risk, impact, recommended,
  win, admin, confirm, when, tags, actions, revert
"""
from __future__ import annotations

import re

ALLOWED_HIVES = {"HKLM", "HKCU", "HKCR", "HKU"}
ALLOWED_VTYPES = {"DWORD", "QWORD", "STRING", "EXPAND_STRING", "BINARY", "MULTI_STRING"}
ALLOWED_RISK = ("safe", "low", "moderate", "advanced")
ALLOWED_IMPACT = ("very low", "low", "moderate", "high", "extreme")
ALLOWED_REC = ("recommended", "optional", "experimental", "advanced", "not_recommended")
WINDOWS_VERSIONS = {"7", "8", "10", "11"}


def _norm_int(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an int, got bool")
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be int-like, got {value!r}")


def _norm_hive(hive):
    hive = hive.upper()
    if hive not in ALLOWED_HIVES:
        raise ValueError(f"Unknown registry hive {hive!r}")
    return hive


def _validate_action(action, tweak_id):
    if not isinstance(action, (tuple, list)) or not action:
        raise ValueError(f"Tweak {tweak_id}: empty/invalid action {action!r}")
    kind = action[0]
    if kind in ("reg", "regall"):
        if len(action) < 6:
            raise ValueError(f"Tweak {tweak_id}: {kind} action needs 6 parts")
        hive, path, name, value, vtype = action[1:6]
        _norm_hive(hive)
        if vtype.upper() not in ALLOWED_VTYPES:
            raise ValueError(f"Tweak {tweak_id}: bad registry type {vtype!r}")
        if vtype.upper() in ("DWORD", "QWORD") and not isinstance(value, int):
            raise ValueError(f"Tweak {tweak_id}: {vtype} value must be int")
    elif kind in ("regdel", "regkeydel", "regdelall"):
        if len(action) < 3:
            raise ValueError(f"Tweak {tweak_id}: {kind} needs hive+path")
        _norm_hive(action[1])
        if kind == "regdelall" and len(action) < 4:
            raise ValueError(f"Tweak {tweak_id}: regdelall needs value name")
    elif kind == "svc":
        if len(action) < 3 or action[2] not in ("auto", "manual", "disabled", "boot", "system", "delayed"):
            raise ValueError(f"Tweak {tweak_id}: bad svc action {action!r}")
    elif kind in ("svcstart", "svcstop"):
        if len(action) < 2:
            raise ValueError(f"Tweak {tweak_id}: {kind} needs service name")
    elif kind == "sc":
        if len(action) < 3 or action[1] not in ("disable", "enable", "start", "stop"):
            raise ValueError(f"Tweak {tweak_id}: bad sc action {action!r}")
    elif kind == "cmd":
        if len(action) < 2 or not isinstance(action[1], str):
            raise ValueError(f"Tweak {tweak_id}: cmd needs command string")
    elif kind == "file":
        if len(action) < 3 or action[1] not in ("write", "append", "delete"):
            raise ValueError(f"Tweak {tweak_id}: bad file action {action!r}")
    elif kind == "ini":
        if len(action) < 5 or not isinstance(action[1], str):
            raise ValueError(f"Tweak {tweak_id}: ini needs path, section, key, value")
    elif kind == "inidel":
        if len(action) < 4 or not isinstance(action[1], str):
            raise ValueError(f"Tweak {tweak_id}: inidel needs path, section, key")
    elif kind == "power":
        if len(action) < 3:
            raise ValueError(f"Tweak {tweak_id}: power needs setting+value")
    elif kind == "powerscheme":
        if len(action) < 2 or action[1] not in ("setactive", "duplicate", "change"):
            raise ValueError(f"Tweak {tweak_id}: bad powerscheme action {action!r}")
    elif kind in ("sched", "appx", "restart", "mkdir"):
        if len(action) < 2:
            raise ValueError(f"Tweak {tweak_id}: {kind} action incomplete")
    elif kind == "guidance":
        if len(action) < 2 or not isinstance(action[1], str):
            raise ValueError(f"Tweak {tweak_id}: guidance action needs text")
    else:
        raise ValueError(f"Tweak {tweak_id}: unknown action kind {kind!r}")


def _normalize_when(when):
    out = {}
    for key, req in (when or {}).items():
        if key in ("gpu", "cpu_vendor", "ntfs", "win_versions"):
            out[key] = list(req) if isinstance(req, (list, tuple)) else [req]
        elif isinstance(req, dict) and req.keys() <= {">=", "<=", "==", ">", "<"}:
            out[key] = {k: _norm_int(v, f"{key}.{k}") for k, v in req.items()}
        elif isinstance(req, bool):
            out[key] = req
        else:
            raise ValueError(f"Bad when condition for {key!r}: {req!r}")
    return out


def make_T(category, win_default="7,8,10,11"):
    """Return a tweak factory bound to a category."""

    def T(tid, name, desc, actions=None, revert=None, why=None, changes=None,
          risk="low", impact="moderate", recommended="recommended", win=None,
          admin=False, confirm=False, when=None, tags=None, crafted_for=None,
          status="VALID", evidence="UNKNOWN", target="WINDOWS", verdict="SHIP"):
        if not tid or not isinstance(tid, str):
            raise ValueError("Tweak id required")
        actions = list(actions or [])
        revert = list(revert or [])
        for a in actions + revert:
            _validate_action(a, tid)
        if risk not in ALLOWED_RISK:
            raise ValueError(f"Tweak {tid}: bad risk {risk!r}")
        if impact not in ALLOWED_IMPACT:
            raise ValueError(f"Tweak {tid}: bad impact {impact!r}")
        if recommended not in ALLOWED_REC:
            raise ValueError(f"Tweak {tid}: bad recommended flag {recommended!r}")
        win = win or win_default
        for v in win.split(","):
            v = v.strip()
            if v and v not in WINDOWS_VERSIONS:
                raise ValueError(f"Tweak {tid}: bad windows version list {win!r}")
        return {
            "id": tid,
            "name": name,
            "desc": desc,
            "category": category,
            "actions": actions,
            "revert": revert,
            "why": why or desc,
            "changes": changes or desc,
            "risk": risk,
            "impact": impact,
            "recommended": recommended,
            "win": win,
            "admin": bool(admin),
            "confirm": bool(confirm),
            "when": _normalize_when(when),
            "tags": list(tags or []),
            "crafted_for": crafted_for,
            "status": status,
            "evidence": evidence,
            "target": target,
            "verdict": verdict,
        }

    return T


def validate_module(module_name, tweaks):
    """Run structural validation over a category's tweak list."""
    ids = [t["id"] for t in tweaks]
    if len(ids) != len(set(ids)):
        dupes = {i for i in ids if ids.count(i) > 1}
        raise ValueError(f"{module_name}: duplicate tweak ids {sorted(dupes)}")
    return tweaks


# Compact regex guard used by loader to confirm ids are filesystem-safe.
SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")
