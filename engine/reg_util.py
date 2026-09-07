"""In-process registry access replacing reg.exe subprocess calls.

Every registry snapshot, write, delete and verify in the app previously
spawned ``cmd.exe`` -> ``reg.exe`` (two OS processes per operation).  Apply
All / Revert All batches execute hundreds of these per tweak, so a full batch
was spawning thousands of processes back-to-back — taking minutes and
saturating the machine while the UI appeared frozen.

This module does the same work in-process via :mod:`winreg`.  Value formats
are kept byte-compatible with what ``reg.exe`` printed so the existing
equality/snapshot/restore logic (``_values_equal``, ``_target_key``, the
state_checker comparisons) behaves identically:

  DWORD/QWORD  ->  "0x" + lowercase hex      (int() compatible)
  SZ / EXPAND  ->  raw string
  MULTI_SZ     ->  "\\n".join(values)
  BINARY       ->  uppercase hex pairs with spaces

Errors are returned as (ok, detail) tuples with detail strings chosen so the
callers' ``_missing()`` matcher still recognizes already-absent targets as a
successful idempotent delete.
"""
from __future__ import annotations

import winreg

_DEFAULT_NAMES = ("", "(default)", "(default value)")

_HIVES = {
    "HKLM": winreg.HKEY_LOCAL_MACHINE,
    "HKCU": winreg.HKEY_CURRENT_USER,
    "HKCR": winreg.HKEY_CLASSES_ROOT,
    "HKU": winreg.HKEY_USERS,
    "HKCC": winreg.HKEY_CURRENT_CONFIG,
}
# Full hive names (what reg.exe echoes) are also accepted at the input edge.
_FULL_TO_HIVES = {
    "HKEY_LOCAL_MACHINE": "HKLM",
    "HKEY_CURRENT_USER": "HKCU",
    "HKEY_CLASSES_ROOT": "HKCR",
    "HKEY_USERS": "HKU",
    "HKEY_CURRENT_CONFIG": "HKCC",
}

# Short action tokens -> winreg value-type constants.
_WRITE_TYPES = {
    "DWORD": winreg.REG_DWORD,
    "QWORD": winreg.REG_QWORD,
    "STRING": winreg.REG_SZ,
    "EXPAND_STRING": winreg.REG_EXPAND_SZ,
    "BINARY": winreg.REG_BINARY,
    "MULTI_STRING": winreg.REG_MULTI_SZ,
}

# winreg type constants -> reg.exe type tokens (REG_DWORD, REG_SZ, ...).
_TOKENS = {
    winreg.REG_DWORD: "REG_DWORD",
    winreg.REG_DWORD_BIG_ENDIAN: "REG_DWORD_BIG_ENDIAN",
    winreg.REG_QWORD: "REG_QWORD",
    winreg.REG_SZ: "REG_SZ",
    winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
    winreg.REG_BINARY: "REG_BINARY",
    winreg.REG_MULTI_SZ: "REG_MULTI_SZ",
    winreg.REG_LINK: "REG_LINK",
    winreg.REG_NONE: "REG_NONE",
    winreg.REG_RESOURCE_LIST: "REG_RESOURCE_LIST",
    winreg.REG_FULL_RESOURCE_DESCRIPTOR: "REG_FULL_RESOURCE_DESCRIPTOR",
}


def _resolve_hive(hive: str):
    """Map a hive short/full name to a winreg root handle (or None)."""
    h = (hive or "").strip().upper()
    root = _HIVES.get(h)
    if root is not None:
        return root
    short = _FULL_TO_HIVES.get(h)
    if short is not None:
        return _HIVES[short]
    return None


def _value_name(name) -> str:
    """Map default-value aliases to winreg's '' sentinel."""
    if str(name).strip().lower() in _DEFAULT_NAMES:
        return ""
    return name


def _token(rtype: int) -> str:
    return _TOKENS.get(rtype, f"REG_UNKNOWN_{rtype}")


def _format_data(value, rtype: int) -> str:
    """Format a raw winreg value like ``reg.exe query`` would echo it."""
    if rtype in (winreg.REG_DWORD, winreg.REG_DWORD_BIG_ENDIAN):
        return hex(int(value))
    if rtype == winreg.REG_QWORD:
        return hex(int(value))
    if rtype == winreg.REG_BINARY:
        raw = value if isinstance(value, (bytes, bytearray)) else b""
        return " ".join(f"{b:02X}" for b in raw)
    if rtype == winreg.REG_MULTI_SZ:
        parts = value if isinstance(value, (list, tuple)) else []
        return "\n".join(str(p) for p in parts)
    if value is None:
        return ""
    return str(value)


def _write_type(vtype) -> int | None:
    return _WRITE_TYPES.get(str(vtype).upper())


def _convert_value(value, vtype: str):
    """Convert an action-tuple value into the winreg-native Python type."""
    if isinstance(value, bool):
        value = int(value)
    token = str(vtype).upper()
    if token in ("DWORD", "QWORD"):
        if isinstance(value, str):
            return int(value, 16) if value.lower().startswith("0x") else int(value)
        return int(value)
    if token == "BINARY":
        hv = str(value).replace(" ", "")
        return bytes.fromhex(hv) if hv else b""
    if token == "MULTI_STRING":
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value]
        parts = str(value).split("\n")
        return [p for p in parts if p != ""] if len(parts) > 1 else parts
    return str(value)


def read_value(hive: str, path: str, name: str) -> tuple[bool, str | None, str | None]:
    """Read one registry value -> (existed, reg_token, data).

    ``existed`` is False when the value (or its key) is absent or unreadable,
    matching the previous ``reg.exe``-based implementation.
    """
    root = _resolve_hive(hive)
    if root is None:
        return False, None, None
    try:
        with winreg.OpenKey(root, str(path), 0, winreg.KEY_READ) as key:
            value, rtype = winreg.QueryValueEx(key, _value_name(name))
    except FileNotFoundError:
        return False, None, None
    except OSError:
        return False, None, None
    return True, _token(rtype), _format_data(value, rtype)


def map_values(hive: str, path: str) -> dict[str, tuple[str, str]]:
    """All values under a key -> {lower-cased name: (reg_token, data)}.

    Returns an empty dict when the key is absent or unreadable (a missing key
    reads as "no values", i.e. every value absent — the same contract reg.exe
    gave the state checker).
    """
    root = _resolve_hive(hive)
    if root is None:
        return {}
    try:
        with winreg.OpenKey(root, str(path), 0, winreg.KEY_READ) as key:
            values = {}
            i = 0
            while True:
                try:
                    vname, value, rtype = winreg.EnumValue(key, i)
                except OSError:
                    break
                vkey = str(vname).strip().lower() or "(default)"
                values[vkey] = (_token(rtype), _format_data(value, rtype))
                i += 1
            return values
    except OSError:
        return {}


def write_value(hive: str, path: str, name: str, value, vtype: str) -> tuple[bool, str]:
    """Write one registry value (creating the key if needed)."""
    root = _resolve_hive(hive)
    if root is None:
        return False, f"unknown hive {hive!r}"
    rtype = _write_type(vtype)
    if rtype is None:
        return False, f"unknown value type {vtype!r}"
    try:
        with winreg.CreateKeyEx(root, str(path), 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, _value_name(name), 0, rtype,
                              _convert_value(value, vtype))
        return True, f"wrote {hive}\\{path} [{name}]"
    except OSError as exc:
        return False, str(exc)


def delete_value(hive: str, path: str, name: str) -> tuple[bool, str]:
    """Delete one registry value.

    An already-absent value returns ok=False with "does not exist" so callers'
    idempotent-delete handling treats it as a success.
    """
    root = _resolve_hive(hive)
    if root is None:
        return False, f"unknown hive {hive!r}"
    try:
        with winreg.OpenKey(root, str(path), 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _value_name(name))
        return True, f"deleted {hive}\\{path} [{name}]"
    except FileNotFoundError:
        return False, f"value does not exist: {hive}\\{path} [{name}]"
    except OSError as exc:
        return False, str(exc)


def _delete_key_recursive(root, rel_path: str) -> tuple[bool, str]:
    """Recursively delete a key and everything below it (reg.exe semantics)."""
    try:
        with winreg.OpenKey(root, rel_path, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as key:
            while True:
                try:
                    sub = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_key_recursive(root, f"{rel_path}\\{sub}".strip("\\"))
    except OSError as exc:
        return False, str(exc)
    try:
        winreg.DeleteKey(root, rel_path)
    except FileNotFoundError:
        return False, f"key does not exist: {rel_path}"
    except OSError as exc:
        return False, str(exc)
    return True, f"deleted {rel_path}"


def delete_key(hive: str, path: str) -> tuple[bool, str]:
    """Delete a registry key recursively (like ``reg delete key /f``)."""
    root = _resolve_hive(hive)
    if root is None:
        return False, f"unknown hive {hive!r}"
    if not str(path).strip():
        return False, "refusing to delete a hive root"
    return _delete_key_recursive(root, str(path).strip("\\"))


def key_exists(hive: str, path: str) -> bool:
    """True when the key itself exists (even if it has no values)."""
    root = _resolve_hive(hive)
    if root is None:
        return False
    try:
        with winreg.OpenKey(root, str(path), 0, winreg.KEY_READ):
            return True
    except OSError:
        return False


def subkeys(hive: str, base: str) -> list[str]:
    """Immediate subkeys of ``base`` -> relative paths (``base\\child``)."""
    root = _resolve_hive(hive)
    if root is None:
        return []
    try:
        with winreg.OpenKey(root, str(base), 0, winreg.KEY_READ) as key:
            names = []
            i = 0
            while True:
                try:
                    names.append(winreg.EnumKey(key, i))
                except OSError:
                    break
                i += 1
    except OSError:
        return []
    prefix = str(base).strip("\\")
    return [f"{prefix}\\{n}".strip("\\") for n in names]