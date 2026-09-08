"""Detect the actual Windows system state for each tweak.

For every tweak definition this module inverts its ``actions`` (the apply
operations) into *read* operations and reports whether the live system already
matches the tweak's target "optimized" value:

    True   -> the tweak is currently ACTIVE  (system matches the target)
    False  -> the tweak is currently INACTIVE (system uses a default/other value)
    None   -> not detectable (guidance, one-shot commands, unknown mapping)

Detection is implemented natively per action kind:

  reg       reg query   -> value matches the applied target
  regdel    reg query   -> value is absent
  regkeydel reg query   -> key is absent
  svc       sc qc       -> startup mode matches (auto/manual/disabled/...)
  sc        sc qc       -> disabled/enabled/start/stop semantics
  svcstart  sc query    -> service currently running
  svcstop   sc query    -> service currently stopped
  power     powercfg    -> named setting value (AC/DC) matches
  powerscheme powercfg  -> active / present power scheme
  sched     schtasks    -> scheduled-task state matches
  file      filesystem  -> file exists / content present / absent
  ini       filesystem  -> ini key=value matches the applied target
  appx      powershell  -> package present/absent
  cmd       parsing     -> powercfg, reg add/delete command forms
  guidance/restart/mkdir -> None (no persistent state)

All reads go through a per-process cache, so a full-system audit reuses
previous answers (one ``reg query`` serves every value under a key, one
``powercfg /query SCHEME_CURRENT`` serves every power setting). The cache is
invalidated after apply/revert batches so the UI re-syncs to the real system.
"""
from __future__ import annotations

import re
import subprocess
import threading

from rexlog import logger

_LOCK = threading.RLock()
_CACHE: dict = {}

# PowerShell power-settings aliases -> the GUIDs that powercfg reports.
_ALIAS_GUIDS = {
    "scheme_min": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",       # High performance
    "scheme_max": "a1841308-3541-4fab-bc81-f71556f20b4a",       # Power saver
    "scheme_balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",  # Balanced
    "ultimate": "e9a42b02-d5df-448d-aa00-03f14749eb61",
}

# Named power settings used by ("power", ...) actions -> (subgroup, setting).
POWER_NAMES = {
    "processor_max": ("54533251-82be-4824-96c1-47b60b740d00",
                      "bc5038f7-23e0-4960-96da-33abaf5935ec"),
    "processor_min": ("54533251-82be-4824-96c1-47b60b740d00",
                      "893dee8e-2bef-41e0-89c6-b55d0929964c"),
    "boost_mode": ("54533251-82be-4824-96c1-47b60b740d00",
                   "be337238-0d82-4146-a960-4f3749d470c7"),
    "perf_increase_threshold": ("54533251-82be-4824-96c1-47b60b740d00",
                                "06cadf0e-64ed-448a-8927-ce7bf90eb35d"),
    "perf_decrease_threshold": ("54533251-82be-4824-96c1-47b60b740d00",
                                "12a0ab44-fe28-4fa9-b3fb-4b64a26f8725"),
    "idle_disable": ("54533251-82be-4824-96c1-47b60b740d00",
                     "5d76a2ca-e8c0-402f-a133-2158312c3406"),
    "time_check": ("54533251-82be-4824-96c1-47b60b740d00",
                   "18a7d39f-c168-4f6f-b3c4-bbf17f66a4c9"),
    "parking_min": ("54533251-82be-4824-96c1-47b60b740d00",
                    "0cc5b647-c1df-4637-891a-dec35c318583"),
    "parking_max": ("54533251-82be-4824-96c1-47b60b740d00",
                    "ea062031-0e34-4ff1-9b6d-eb1059334028"),
    "perf_increase_policy": ("36687f9e-e3a5-4dbf-b1dc-15eb381c6863",
                             "465e1f50-b610-473a-ab58-00d1077dc418"),
    "perf_decrease_policy": ("36687f9e-e3a5-4dbf-b1dc-15eb381c6863",
                             "8baa4a8a-14c6-4451-8e8b-14bdbd197537"),
    "boost_policy": ("36687f9e-e3a5-4dbf-b1dc-15eb381c6863",
                     "45bcc044-d885-43a2-8605-ee0ec6e96b59"),
    "epp": ("36687f9e-e3a5-4dbf-b1dc-15eb381c6863",
            "36687f9e-e3a5-4dbf-b1dc-15eb381c6863"),
    "display_timeout": ("3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e",
                        "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e"),
    "adaptive_brightness": ("7516b95f-f776-4464-8c53-06167f40cc99",
                            "fbd9aa66-9553-4097-ba44-ed6e9d65eab8"),
    "hdd_timeout": ("0012ee47-9041-4b5d-9b77-535fba8b1442",
                    "6738e2c4-e8a5-4a42-b16a-e040e769756e"),
    "usb_selective": ("2a737441-1930-4402-8d77-b2bebba308a3",
                      "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"),
}

# `powercfg /change <name>-timeout-ac N` -> (subgroup, setting).
CHANGE_SETTINGS = {
    "standby-timeout": ("238c9fa8-0aad-41ed-83f4-97be242c8f20",
                        "29f6c1db-86da-48c5-9fdb-f2b67b1f44da"),
    "monitor-timeout": ("3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e",
                        "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e"),
    "disk-timeout": ("0012ee47-9041-4b5d-9b77-535fba8b1442",
                     "6738e2c4-e8a5-4a42-b16a-e040e769756e"),
    "hibernate-timeout": ("238c9fa8-0aad-41ed-83f4-97be242c8f20",
                          "9d7815a6-7ee4-497e-8888-515a05f02364"),
}

# reg.exe type tokens for comparing applied values.
_REG_TOKENS = {
    "DWORD": "REG_DWORD", "QWORD": "REG_QWORD", "STRING": "REG_SZ",
    "EXPAND_STRING": "REG_EXPAND_SZ", "BINARY": "REG_BINARY",
    "MULTI_STRING": "REG_MULTI_SZ",
}
_HIVE_FULL = {
    "HKLM": "HKEY_LOCAL_MACHINE", "HKCU": "HKEY_CURRENT_USER",
    "HKCR": "HKEY_CLASSES_ROOT", "HKU": "HKEY_USERS",
}
_FULL_HIVE = {v: k for k, v in _HIVE_FULL.items()}


def _split_hive(path: str):
    """Split 'HKLM\\Software\\...' (or full HKEY_ form) into (hive, subpath)."""
    up = path.strip().upper()
    for hive in ("HKLM", "HKCU", "HKCR", "HKU"):
        if up == hive or up.startswith(hive + "\\"):
            return hive, path.strip()[len(hive) + 1:] if up != hive else ""
    full = up.split("\\", 1)[0]
    if full in _FULL_HIVE:
        return _FULL_HIVE[full], path.strip().split("\\", 1)[1] if "\\" in up else ""
    return None, path.strip()
_SVC_TOKENS = {
    "auto": "AUTO_START", "manual": "DEMAND_START", "disabled": "DISABLED",
    "boot": "BOOT_START", "system": "SYSTEM_START", "delayed": "DELAYED_START",
}
_REG_VALUE_RE = re.compile(r"^\s+(?P<name>.+?)\s+(?P<type>REG_[A-Z_]+)\s+(?P<data>.*?)\s*$")
_HKEY_RE = re.compile(r"^\s*(?P<path>HKEY_[A-Z_]+\\.*?)\s*$")
_GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


# ---------------- low-level readers (cached) ----------------

def _run(args, timeout=10):
    """Run a command; returns (ok, output). No console window is spawned."""
    try:
        proc = subprocess.run(
            args, shell=True, capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000,
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return proc.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, ""
    except OSError:
        return False, ""


def _cache_get(key):
    with _LOCK:
        return _CACHE.get(key, _MISS)


_MISS = object()


def _cache_set(key, value):
    with _LOCK:
        _CACHE[key] = value


def invalidate_cache():
    """Drop every cached system read (call after apply/revert)."""
    with _LOCK:
        _CACHE.clear()


def invalidate_ini(path: str):
    """Drop the cached parse of one ini file (call after mutating it)."""
    import os
    path = os.path.expandvars(os.path.expanduser(path))
    with _LOCK:
        _CACHE.pop(("ini", path.lower()), None)


def _reg_map(hive: str, path: str) -> dict[str, tuple[str, str]]:
    """dict value_name -> (REG_TYPE, raw data) for one registry key (cached)."""
    key = ("reg", hive.upper(), path.upper())
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached
    full = _HIVE_FULL.get(hive.upper(), hive.upper())
    ok, out = _run(f'reg query "{hive}\\{path}"')
    values: dict[str, tuple[str, str]] = {}
    if ok:
        wanted = f"{full}\\{path}".upper()
        section = None
        for line in out.splitlines():
            hm = _HKEY_RE.match(line)
            if hm:
                section = hm.group("path").upper()
                continue
            if section != wanted:
                continue
            m = _REG_VALUE_RE.match(line)
            if m:
                data = m.group("data")
                if data.strip().lower() == "(value not set)":
                    continue
                values[m.group("name")] = (m.group("type"), data)
    _cache_set(key, values)
    return values


def _reg_data(hive: str, path: str, name: str):
    key = name.strip().lower()
    if key in ("", "(default)", "(default value)"):
        key = "(Default)"
    return _reg_map(hive, path).get(key)


def _svc_start_type(name: str) -> str | None:
    key = ("sc_start", name.upper())
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached
    ok, out = _run(f'sc qc "{name}"')
    m = re.search(r"START_TYPE\s*:\s*\d+\s+([A-Z_]+)", out)
    result = m.group(1) if (ok and m) else None
    _cache_set(key, result)
    return result


def _svc_running(name: str) -> bool | None:
    key = ("sc_run", name.upper())
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached
    ok, out = _run(f'sc query "{name}"')
    running = bool(ok and re.search(r"STATE\s*:\s*\d+\s+RUNNING", out))
    _cache_set(key, running)
    return running


def _active_scheme() -> tuple[str, str]:
    """Return (lowercased GUID, friendly name) of the active power scheme."""
    cached = _cache_get(("scheme",))
    if cached is not _MISS:
        return cached
    ok, out = _run("powercfg /getactivescheme")
    guid = name = ""
    if ok:
        m = _GUID_RE.search(out)
        if m:
            guid = m.group(0).lower()
        n = re.search(r"\(([^)]*)\)", out)
        if n:
            name = n.group(1).strip()
    _cache_set(("scheme",), (guid, name))
    return guid, name


def _power_map() -> dict[tuple[str, str], tuple[int, int]]:
    """{(subgroup, setting): (AC value, DC value)} from `powercfg /query`."""
    cached = _cache_get(("power",))
    if cached is not _MISS:
        return cached
    ok, out = _run("powercfg /query SCHEME_CURRENT")
    power: dict[tuple[str, str], tuple[int, int]] = {}
    sub = setid = None
    ac = dc = None
    for line in (out.splitlines() if ok else []):
        m = re.search(r"Subgroup GUID:\s*([0-9a-fA-F-]+)", line)
        if m:
            sub = m.group(1).lower()
            setid = None
            continue
        m = re.search(r"Power Setting GUID:\s*([0-9a-fA-F-]+)", line)
        if m:
            setid = m.group(1).lower()
            ac = dc = None
            continue
        m = re.search(r"Current AC Power Setting Index:\s*(0x[0-9a-fA-F]+)", line)
        if m and sub and setid:
            ac = int(m.group(1), 16)
            power[(sub, setid)] = (ac, dc)
            continue
        m = re.search(r"Current DC Power Setting Index:\s*(0x[0-9a-fA-F]+)", line)
        if m and sub and setid:
            dc = int(m.group(1), 16)
            power[(sub, setid)] = (ac, dc)
    _cache_set(("power",), power)
    return power


def _power_ac(subgroup: str, setting: str) -> int | None:
    entry = _power_map().get((subgroup.lower(), setting.lower()))
    return entry[0] if entry else None


def _scheme_list() -> set[str]:
    cached = _cache_get(("scheme_list",))
    if cached is not _MISS:
        return cached
    ok, out = _run("powercfg /list")
    guids = {g.lower() for g in (_GUID_RE.findall(out) if ok else [])}
    _cache_set(("scheme_list",), guids)
    return guids


def _sched_status(task: str) -> str | None:
    key = ("sched", task.upper())
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached
    ok, out = _run(f'schtasks /Query /TN "{task}" /FO LIST')
    status = None
    if ok:
        for line in out.splitlines():
            low = line.strip().lower()
            if low.startswith("status:"):
                status = line.split(":", 1)[1].strip()
                break
            if low.startswith("scheduled task state:"):
                status = line.split(":", 1)[1].strip()
                break
    _cache_set(key, status)
    return status


def _bcd_values():
    """Flat BCD store: boot-option name -> value (from `bcdedit /enum`).

    Returns None if the BCD store could not be read (e.g. access denied),
    otherwise a dict (options that are not explicitly set are absent).
    """
    cached = _cache_get(("bcd",))
    if cached is not _MISS:
        return cached
    ok, out = _run("bcdedit /enum")
    vals: dict[str, str] = {}
    if ok:
        for line in out.splitlines():
            m = re.match(r"^\s*([A-Za-z0-9_-]+)\s+(.+?)\s*$", line)
            if m and not line.startswith(("identifier", "--")):
                vals[m.group(1).lower()] = m.group(2).strip()
    result: dict[str, str] | None = vals if ok else None
    _cache_set(("bcd",), result)
    return result


def _check_bcd_set(name: str, value: str) -> bool | None:
    store = _bcd_values()
    if store is None:
        return None
    actual = store.get(name.lower())
    if actual is None:
        return False  # option not explicitly configured -> target not set
    return actual.lower() == value.lower()


# Labels (as shown by `netsh int tcp show global`) used by netsh tweaks.
_NETSH_LABELS = {
    "autotuninglevel": ["Receive Window Auto-Tuning Level"],
    "congestionprovider": ["Add-On Congestion Control Provider",
                           "Congestion Control Provider"],
    "rss": ["Receive-Side Scaling State"],
    "ecncapability": ["ECN Capability"],
    "timestamps": ["RFC 1323 Timestamps", "Timestamps"],
    "initialrto": ["Initial RTO"],
}


def _netsh_tcp_global() -> dict[str, str]:
    cached = _cache_get(("netsh",))
    if cached is not _MISS:
        return cached
    ok, out = _run("netsh interface tcp show global")
    vals: dict[str, str] = {}
    if ok:
        for line in out.splitlines():
            m = re.match(r"^\s*(.+?)\s*:\s*(.+?)\s*$", line)
            if m:
                vals[m.group(1).strip().lower()] = m.group(2).strip()
    _cache_set(("netsh",), vals)
    return vals


def _check_netsh(name: str, value: str) -> bool | None:
    labels = _NETSH_LABELS.get(name)
    if not labels:
        return None
    values = _netsh_tcp_global()
    for label in labels:
        actual = values.get(label.lower())
        if actual is not None:
            return actual.lower() == value.lower()
    return None


# ---------------- value comparison helpers ----------------

def _num_match(target, data: str) -> bool:
    """Compare a numeric reg target against raw `reg query` data."""
    data = (data or "").strip()
    if not data:
        return False
    try:
        if data.lower().startswith("0x"):
            actual = int(data, 16)
        else:
            actual = int(data, 10)
    except ValueError:
        return False
    if isinstance(target, bool):
        target = int(target)
    return actual == int(target)


def _bin_match(target, data: str) -> bool:
    want = target
    if isinstance(target, int):
        want = hex(target)[2:].zfill(2)
    want = str(want).replace(" ", "").lower()
    return (data or "").replace(" ", "").lower() == want


def _reg_value_matches(hive, path, name, target, vtype) -> bool:
    entry = _reg_data(hive, path, name)
    if entry is None:
        return False
    rtype, data = entry
    want_type = _REG_TOKENS.get(vtype.upper(), vtype.upper())
    if rtype.upper() != want_type.upper():
        return False
    if vtype.upper() in ("DWORD", "QWORD"):
        return _num_match(target, data)
    if vtype.upper() == "BINARY":
        return _bin_match(target, data)
    return str(data) == str(target)


def _reg_value_absent(hive, path, name) -> bool:
    return _reg_data(hive, path, name) is None


def _reg_key_absent(hive, path) -> bool:
    return not bool(_reg_map(hive, path))


def _reg_subkeys(hive, path) -> list[str]:
    """Hive-relative paths of path's immediate subkeys (cached)."""
    key = ("regsubkeys", hive.upper(), path.upper())
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached
    full = _HIVE_FULL.get(hive.upper(), hive.upper())
    ok, out = _run(f'reg query "{hive}\\{path}"')
    names = []
    if ok:
        wanted = f"{full}\\{path}".upper()
        for line in out.splitlines():
            m = _HKEY_RE.match(line)
            if m:
                sec = m.group("path").upper()
                if sec.startswith(wanted + "\\") and not sec.startswith(wanted + "\\\\"):
                    names.append(f"{path}\\{sec[len(wanted) + 1:]}")
    _cache_set(key, names)
    return names


def _reg_all_match(hive, base, name, target, vtype) -> bool | None:
    """True when every immediate subkey of base has the target value."""
    subkeys = _reg_subkeys(hive, base)
    if not subkeys:
        return None
    results = [_reg_value_matches(hive, sub, name, target, vtype) for sub in subkeys]
    return all(results)


def _reg_all_absent(hive, base, name) -> bool | None:
    """True when the value is absent from every immediate subkey of base."""
    subkeys = _reg_subkeys(hive, base)
    if not subkeys:
        return None
    return all(_reg_value_absent(hive, sub, name) for sub in subkeys)


# ---------------- action checks ----------------

def _check_cmd(cmd: str) -> bool | None:
    low = " ".join(cmd.strip().lower().split())
    if not low:
        return None

    # powercfg /setactive <target>
    m = re.match(r"^powercfg\s+/setactive\s+(\S+)$", low)
    if m:
        return _scheme_active(m.group(1))

    # powercfg /SETACVALUEINDEX SCHEME_CURRENT <sub> <set> <val>
    m = re.match(
        r"^powercfg\s+/set(?:ac|dc)valueindex\s+scheme_current\s+"
        r"([0-9a-f-]+)\s+([0-9a-f-]+)\s+(0x[0-9a-f]+|\d+)$", low)
    if m:
        val = _power_ac(m.group(1), m.group(2))
        if val is None:
            return None
        return val == _int_of(m.group(3))

    # powercfg /change <name>-timeout-<ac|dc> <val>
    m = re.match(r"^powercfg\s+/change\s+([a-z_]+)-timeout-(ac|dc)\s+(\d+)$", low)
    if m:
        spec = CHANGE_SETTINGS.get(m.group(1))
        if spec is None:
            return None
        val = _power_ac(*spec)
        if val is None:
            return None
        return val == int(m.group(3))

    # powercfg /h on|off
    m = re.match(r"^powercfg\s+/h\s+(on|off)$", low)
    if m:
        data = _reg_data("HKLM", r"SYSTEM\CurrentControlSet\Control\Power",
                         "HibernateEnabled")
        if data is None:
            return False
        return _num_match(1 if m.group(1) == "on" else 0, data[1])

    # powercfg -duplicatescheme <guid>
    m = re.match(r"^powercfg\s+(?:-|/)duplicatescheme\s+(\S+)$", low)
    if m:
        guid = m.group(1).lower()
        active_guid, active_name = _active_scheme()
        return (active_guid == guid
                or active_guid == _ALIAS_GUIDS["ultimate"]
                or "ultimate" in active_name.lower()
                or guid in _scheme_list())

    # reg add <path> /v <name> /t <type> /d <value> /f
    m = re.match(
        r"^reg\s+add\s+(?P<path>.+?)\s+/v\s+(?P<name>[\"']?[^\"'\s]+[\"']?)"
        r"\s+/t\s+(?P<type>REG_[A-Z_]+)\s+/d\s+(?P<value>.+?)\s*/f\s*$",
        cmd, re.IGNORECASE)
    if m:
        hive, path = _split_hive(m.group("path").strip('"\''))
        if hive is not None:
            vtype = m.group("type").upper()
            if vtype.startswith("REG_"):
                vtype = vtype[4:]
            return _reg_value_matches(hive, path, m.group("name").strip("\"'"),
                                      m.group("value").strip("\"'"), vtype)

    # reg delete <path> /v <name> /f
    m = re.match(
        r"^reg\s+delete\s+(?P<path>.+?)\s+/v\s+(?P<name>[\"']?[^\"'\s]+[\"']?)\s*/f\s*$",
        cmd, re.IGNORECASE)
    if m:
        hive, path = _split_hive(m.group("path").strip("\"'"))
        if hive is not None:
            return _reg_value_absent(hive, path, m.group("name").strip("\"'"))

    # bcdedit /set <name> <value>
    m = re.match(r"^bcdedit\s+/set\s+([\w-]+)\s+(.+?)\s*$", low)
    if m:
        return _check_bcd_set(m.group(1), m.group(2))

    # bcdedit /timeout <seconds>
    m = re.match(r"^bcdedit\s+/timeout\s+(\d+)$", low)
    if m:
        return _check_bcd_set("timeout", m.group(1))

    # netsh int tcp set global <name>=<value>
    m = re.match(r"^netsh\s+int(?:erface)?\s+tcp\s+set\s+global\s+([\w]+)=(\S+)$", low)
    if m:
        return _check_netsh(m.group(1), m.group(2).strip("'\""))
    return None


def _scheme_active(target: str) -> bool:
    target = target.lower()
    if not target.startswith("scheme_"):
        guid = _GUID_RE.search(target)
        active_guid, _name = _active_scheme()
        return bool(guid) and active_guid == guid.group(0).lower()
    wanted = _ALIAS_GUIDS.get(target)
    if wanted is None:
        return False
    active_guid, _active_name = _active_scheme()
    return active_guid == wanted


def _int_of(text: str) -> int:
    text = text.strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def _check_action(action) -> bool | None:
    """Invert one apply action into a live-state check."""
    try:
        kind = action[0]
        if kind == "reg":
            return _reg_value_matches(action[1], action[2], action[3],
                                      action[4], action[5])
        if kind == "regall":
            return _reg_all_match(action[1], action[2], action[3],
                                  action[4], action[5])
        if kind == "regdel":
            return _reg_value_absent(action[1], action[2], action[3])
        if kind == "regdelall":
            return _reg_all_absent(action[1], action[2], action[3])
        if kind == "regkeydel":
            return _reg_key_absent(action[1], action[2])
        if kind == "svc":
            target = _SVC_TOKENS.get(action[2])
            start = _svc_start_type(action[1])
            return None if (target is None or start is None) else start == target
        if kind == "sc":
            subop = action[1]
            if subop in ("disable", "enable"):
                target = "DISABLED" if subop == "disable" else "AUTO_START"
                start = _svc_start_type(action[2])
                return None if start is None else start == target
            if subop == "start":
                return _svc_running(action[2])
            if subop == "stop":
                return not bool(_svc_running(action[2]))
            return None
        if kind == "svcstart":
            return _svc_running(action[1])
        if kind == "svcstop":
            return not bool(_svc_running(action[1]))
        if kind == "power":
            spec = POWER_NAMES.get(action[1])
            if spec is None:
                return None
            scheme = action[3] if len(action) > 3 else "AC"
            if scheme.upper() == "DC":
                entry = _power_map().get((spec[0].lower(), spec[1].lower()))
                return None if entry is None else entry[1] == int(action[2])
            val = _power_ac(*spec)
            return None if val is None else val == int(action[2])
        if kind == "powerscheme":
            op = action[1]
            if op == "setactive":
                return _scheme_active(action[2])
            if op == "duplicate":
                guid = action[2].lower()
                active_guid, active_name = _active_scheme()
                return (active_guid == guid
                        or "ultimate" in active_name.lower()
                        or guid in _scheme_list())
            return None
        if kind == "sched":
            task = _extract_task(action[2])
            status = _sched_status(task) if task else None
            if status is None:
                return None
            want = "Disabled" if action[1] == "disable" else "Ready"
            return status.lower() == want.lower()
        if kind == "cmd":
            return _check_cmd(action[1])
        if kind == "file":
            return _check_file(action[1], action[2],
                               action[3] if len(action) > 3 else "")
        if kind == "ini":
            return _check_ini(action[1], action[2], action[3], action[4])
        if kind == "inidel":
            return _check_ini_absent(action[1], action[2], action[3])
        if kind == "appx":
            return _check_appx(action[1], action[2])
    except Exception as exc:  # noqa: BLE001 - never let one check break the audit
        logger.warn(f"state checker: {action[0]} check failed: {exc}")
        return None
    return None


def _extract_task(arg: str) -> str | None:
    m = re.search(r"['\"]([^'\"]+)['\"]", arg)
    if m:
        return m.group(1)
    parts = arg.split()
    for i, p in enumerate(parts):
        if p.lower() in ("/tn", "/tn:"):
            return parts[i + 1].strip() if i + 1 < len(parts) else None
    return None


def _check_file(action: str, path: str, content: str = "") -> bool | None:
    import os
    path = os.path.expandvars(os.path.expanduser(path))
    try:
        if action == "delete":
            return not os.path.exists(path)
        if not os.path.exists(path):
            return False
        if action in ("write", "append") and content:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    return content in fh.read()
            except OSError:
                return False
        return True
    except OSError:
        return None


def _ini_map(path: str) -> dict[str, dict[str, str]]:
    """section(lower) -> {key(lower): value} for an ini file (cached)."""
    import os
    path = os.path.expandvars(os.path.expanduser(path))
    key = ("ini", path.lower())
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached
    sections: dict[str, dict[str, str]] = {}
    cur = None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    for raw in lines:
        line = raw.strip()
        m = re.match(r"^\[(.+)\]\s*$", line)
        if m:
            cur = m.group(1).strip().lower()
            sections.setdefault(cur, {})
            continue
        if cur and "=" in line and not line.startswith((";", "#")):
            k, _, v = line.partition("=")
            sections[cur][k.strip().lower()] = v.strip()
    _cache_set(key, sections)
    return sections


def _check_ini(path: str, section: str, key: str, value) -> bool | None:
    sections = _ini_map(path)
    vals = sections.get(section.strip().lower())
    if not vals:
        return False
    actual = vals.get(key.strip().lower())
    if actual is None:
        return False
    want = str(value).strip()
    got = str(actual).strip()
    try:
        return float(got) == float(want)
    except ValueError:
        return got.lower() == want.lower()


def _check_ini_absent(path: str, section: str, key: str) -> bool | None:
    sections = _ini_map(path)
    vals = sections.get(section.strip().lower())
    if not vals:
        return True
    return vals.get(key.strip().lower()) is None


def _check_appx(op: str, package: str) -> bool | None:
    cmd = (f'powershell -NoProfile -Command '
           f'"([bool](Get-AppxPackage *{package}*))"')
    ok, out = _run(cmd, timeout=20)
    if not ok:
        return None
    present = "True" in out
    return (not present) if op == "remove" else present


# ---------------- public API ----------------

def check_tweak(tweak: dict) -> bool | None:
    """Live-state check for one tweak definition.

    True = system matches the apply target; False = it does not;
    None = no checkable action exists.
    """
    results = [_check_action(a) for a in tweak.get("actions", [])]
    checkable = [r for r in results if r is not None]
    if not checkable:
        return None
    return all(checkable)


def check_id(tweak_id: str) -> bool | None:
    from database import BY_ID
    tweak = BY_ID.get(tweak_id)
    return check_tweak(tweak) if tweak else None
