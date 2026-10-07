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
  process   win32       -> running-game CPU state (see game_process_manager)
  netadp    powershell  -> active NIC advanced properties / adapter RSS
  guidance/restart/mkdir -> None (no persistent state)

All reads go through a per-process cache, so a full-system audit reuses
previous answers (one ``reg query`` serves every value under a key, one
``powercfg /qh SCHEME_CURRENT`` serves every power setting). The cache is
invalidated after apply/revert batches so the UI re-syncs to the real system.
"""
from __future__ import annotations

import re
import subprocess
import threading

from maxlog import logger

from . import reg_util

_LOCK = threading.RLock()
_CACHE: dict = {}
_GEN = 0

# PowerShell power-settings aliases -> the GUIDs that powercfg reports.
_ALIAS_GUIDS = {
    "scheme_min": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",       # High performance
    "scheme_max": "a1841308-3541-4fab-bc81-f71556f20b4a",       # Power saver
    "scheme_balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",  # Balanced
    # "Ultimate Performance" ships with a machine-specific GUID on some
    # OEM/VM builds, so "ultimate" is resolved by friendly name via
    # `_scheme_named` rather than trusting a hardcoded GUID.
    "ultimate": "e9a42b02-d5df-448d-aa00-03f14749eb61",
}
# Friendly name (exact, case-insensitive) for scheme aliases that are not
# guaranteed to carry a fixed GUID across machines.
_ALIAS_NAMES = {"ultimate": "ultimate performance"}

# Named power settings used by ("power", ...) actions -> (subgroup, setting).
#
# SINGLE SOURCE OF TRUTH: database/executor.py aliases this table as
# POWER_SETTINGS, so apply and detect can never disagree on a GUID. Every
# setting GUID below was verified against this machine's own
# HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerSettings registry
# FriendlyName entries (and powercfg /query where the plan exposes them).
POWER_NAMES = {
    # Display subgroup (7516b95f-f776-4464-8c53-06167f40cc99)
    "adaptive_brightness": (
        "7516b95f-f776-4464-8c53-06167f40cc99",          # Display subgroup
        "fbd9aa66-9553-4097-ba44-ed6e9d65eab8",          # Adaptive display brightness
    ),
    "display_brightness": (
        "7516b95f-f776-4464-8c53-06167f40cc99",
        "aded5e82-b909-4619-9949-f5d71dac0bcb",          # Display brightness
    ),
    "display_brightness_dim": (
        "7516b95f-f776-4464-8c53-06167f40cc99",
        "f1fbfde2-a960-4165-9f88-50667911ce96",          # Dimmed display brightness
    ),
    "display_timeout": (
        "7516b95f-f776-4464-8c53-06167f40cc99",          # Display subgroup
        "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e",          # Turn off display after
    ),
    # Disk subgroup (0012ee47-9041-4b5d-9b77-535fba8b1442)
    "hdd_timeout": (
        "0012ee47-9041-4b5d-9b77-535fba8b1442",          # Disk subgroup
        "6738e2c4-e8a5-4a42-b16a-e040e769756e",          # Turn off hard disk after
    ),
    # Sleep subgroup (238c9fa8-0aad-41ed-83f4-97be242c8f20)
    "sleep_timeout": (
        "238c9fa8-0aad-41ed-83f4-97be242c8f20",
        "29f6c1db-86da-48c5-9fdb-f2b67b1f44da",          # Sleep after
    ),
    "away_mode": (
        "238c9fa8-0aad-41ed-83f4-97be242c8f20",
        "25dfa149-5dd1-4736-b5ab-e8a37b5b8187",          # Allow away mode policy
    ),
    "hybrid_sleep": (
        "238c9fa8-0aad-41ed-83f4-97be242c8f20",
        "94ac6d29-73ce-41a6-809f-6363ba21b47e",          # Allow hybrid sleep
    ),
    "wake_timers": (
        "238c9fa8-0aad-41ed-83f4-97be242c8f20",
        "bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d",          # Allow wake timers
    ),
    "hibernate_timeout": (
        "238c9fa8-0aad-41ed-83f4-97be242c8f20",
        "9d7815a6-7ee4-497e-8888-515a05f02364",          # Hibernate after
    ),
    # Power buttons subgroup (4f971e89-eebd-4455-a8de-9e59040e7347)
    "lid_action": (
        "4f971e89-eebd-4455-a8de-9e59040e7347",          # Power buttons subgroup
        "5ca83367-6e45-459f-a27b-476b1d01c936",          # Lid close action
    ),
    # PCI Express subgroup (501a4d13-42af-4429-9fd1-a8218c268e20)
    "pcie_aspm": (
        "501a4d13-42af-4429-9fd1-a8218c268e20",          # PCI Express subgroup
        "ee12f906-d277-404b-b6da-e5fa1a576df5",          # Link State Power Management
    ),
    # USB settings subgroup (2a737441-1930-4402-8d77-b2bebba308a3)
    "usb_selective": (
        "2a737441-1930-4402-8d77-b2bebba308a3",          # USB settings subgroup
        "48e6b7a6-50f5-4782-a5d4-53bb8f07e226",          # USB selective suspend
    ),
    # Processor subgroup (54533251-82be-4824-96c1-47b60b740d00)
    "processor_max": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "bc5038f7-23e0-4960-96da-33abaf5935ec",          # Maximum processor state
    ),
    "processor_min": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "893dee8e-2bef-41e0-89c6-b55d0929964c",          # Minimum processor state
    ),
    "boost_mode": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "be337238-0d82-4146-a960-4f3749d470c7",          # Processor performance boost mode
    ),
    "boost_policy": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "45bcc044-d885-43e2-8605-ee0ec6e96b59",          # Processor performance boost policy
    ),
    "perf_increase_threshold": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "06cadf0e-64ed-448a-8927-ce7bf90eb35d",          # Perf increase threshold
    ),
    "perf_decrease_threshold": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "12a0ab44-fe28-4fa9-b3bd-4b64f44960a6",          # Perf decrease threshold
    ),
    "perf_increase_policy": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "465e1f50-b610-473a-ab58-00d1077dc418",          # Perf increase policy
    ),
    "perf_decrease_policy": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "40fbefc7-2e9d-4d25-a185-0cfd8574bac6",          # Perf decrease policy
    ),
    "proc_freq_max": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "75b0ae3f-bce0-45a7-8c89-c9611c25e100",          # Maximum processor frequency
    ),
    "sys_cooling_pol": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "94d3a615-a899-4ac5-ae2b-e4d8f634367f",          # System cooling policy
    ),
    "parking_min": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "0cc5b647-c1df-4637-891a-dec35c318583",          # Core parking min cores
    ),
    "parking_max": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "ea062031-0e34-4ff1-9b6d-eb1059334028",          # Core parking max cores
    ),
    "epp": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "36687f9e-e3a5-4dbf-b1dc-15eb381c6863",          # Energy perf preference
    ),
    # Heterogeneous (P-core / E-core) scheduling. Only meaningful on hybrid
    # parts; 0=All, 1=Performant, 2=Prefer performant, 3=Efficient,
    # 4=Prefer efficient, 5=Automatic. Both default to 5/2 on a desktop.
    "sched_policy": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "93b8b6dc-0698-4d1c-9ee4-0644e900c85d",          # Heterogeneous thread scheduling
    ),
    "short_sched_policy": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "bae08b81-2d5e-4688-ad6a-13243356654b",          # Short running thread scheduling
    ),
    # Processor idle disable is an ENUM, not a percentage:
    # 0 = Enable idle, 1 = Disable idle.
    "idle_disable": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "5d76a2ca-e8c0-402f-a133-2158492d58ad",          # Processor idle disable
    ),
    # Processor idle demote threshold (percentage used by the idle
    # demotion heuristic); promote threshold kept for symmetry.
    "processor_idle_demote_threshold": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "4b92d758-5a24-4851-a470-815d78aee119",          # Processor idle demote threshold
    ),
    "processor_idle_promote_threshold": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "7b224883-b3cc-4d79-819f-8374152cbe7c",          # Processor idle promote threshold
    ),
    # Processor performance time check interval, in milliseconds.
    "time_check": (
        "54533251-82be-4824-96c1-47b60b740d00",
        "4d2b0152-7d5c-498b-88e2-34345392a2c5",          # Idle time check
    ),
}

# `powercfg /change <name>-timeout-ac N` -> (subgroup, setting).
CHANGE_SETTINGS = {
    "standby-timeout": ("238c9fa8-0aad-41ed-83f4-97be242c8f20",
                        "29f6c1db-86da-48c5-9fdb-f2b67b1f44da"),
    "monitor-timeout": ("7516b95f-f776-4464-8c53-06167f40cc99",
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
        entry = _CACHE.get(key)
        if entry is None or entry[0] != _GEN:
            return _MISS
        return entry[1]


_MISS = object()


def _current_gen() -> int:
    """Snapshot of the cache generation (read before a slow system query)."""
    with _LOCK:
        return _GEN


def _cache_set(key, value, gen=None):
    """Store a value read under generation ``gen`` (default: the current one).

    If ``gen`` is given and differs from the current generation, the value was
    read before an invalidate_cache() happened (e.g. a concurrent audit that
    started its query pre-apply and finished post-apply). It is tagged with the
    old generation so _cache_get never serves the stale pre-change result.
    """
    with _LOCK:
        _CACHE[key] = (_GEN if gen is None else gen, value)


def invalidate_cache():
    """Drop every cached system read (call after apply/revert).

    Also bumps the generation, so any system read that started BEFORE this call
    (a concurrent in-flight audit query) is dropped when it completes and can
    never be served to a later caller.
    """
    global _GEN
    with _LOCK:
        _GEN += 1
        _CACHE.clear()


def current_gen() -> int:
    """Current cache generation.

    A result computed under an older generation is stale: the system state was
    invalidated (an apply/revert) while it was being read, so it must not be
    shown. Audit workers snapshot this before each check and emit it with the
    result so the UI can drop stale emissions.
    """
    return _current_gen()


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
    gen = _current_gen()
    values = reg_util.map_values(hive, path)
    _cache_set(key, values, gen)
    return values


def _reg_data(hive: str, path: str, name: str):
    key = name.strip().lower()
    if key in ("", "(default)", "(default value)"):
        key = "(default)"
    return _reg_map(hive, path).get(key)


def _svc_start_type(name: str) -> str | None:
    key = ("sc_start", name.upper())
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached
    gen = _current_gen()
    ok, out = _run(f'sc qc "{name}"')
    m = re.search(r"START_TYPE\s*:\s*\d+\s+([A-Z_]+)", out)
    result = m.group(1) if (ok and m) else None
    _cache_set(key, result, gen)
    return result


def _svc_running(name: str) -> bool | None:
    key = ("sc_run", name.upper())
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached
    gen = _current_gen()
    ok, out = _run(f'sc query "{name}"')
    if not ok:
        # Access denied / service not installed must NOT read as "stopped":
        # a svcstop tweak would then falsely verify as applied. Report unknown
        # and let the caller treat it as unmeasurable.
        result: bool | None = None
    else:
        result = bool(re.search(r"STATE\s*:\s*\d+\s+RUNNING", out))
    _cache_set(key, result, gen)
    return result


def _active_scheme() -> tuple[str, str]:
    """Return (lowercased GUID, friendly name) of the active power scheme."""
    cached = _cache_get(("scheme",))
    if cached is not _MISS:
        return cached
    gen = _current_gen()
    ok, out = _run("powercfg /getactivescheme")
    guid = name = ""
    if ok:
        m = _GUID_RE.search(out)
        if m:
            guid = m.group(0).lower()
        n = re.search(r"\(([^)]*)\)", out)
        if n:
            name = n.group(1).strip()
    _cache_set(("scheme",), (guid, name), gen)
    return guid, name


def _power_map() -> dict[tuple[str, str], tuple[int, int]]:
    """{(subgroup, setting): (AC value, DC value)} from `powercfg /qh`.

    Must be the hidden view. ``/query`` lists only the ~6 visible processor
    settings, so EPP, boost mode, core parking, the increase/decrease policies,
    the heterogeneous scheduling policies and idle-disable returned nothing -
    and the cards carrying them showed no current value at all.
    """
    cached = _cache_get(("power",))
    if cached is not _MISS:
        return cached
    gen = _current_gen()
    ok, out = _run("powercfg /qh SCHEME_CURRENT")
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
    _cache_set(("power",), power, gen)
    return power


def _power_ac(subgroup: str, setting: str) -> int | None:
    entry = _power_map().get((subgroup.lower(), setting.lower()))
    return entry[0] if entry else None


def _scheme_list() -> set[str]:
    cached = _cache_get(("scheme_list",))
    if cached is not _MISS:
        return cached
    gen = _current_gen()
    ok, out = _run("powercfg /list")
    guids = {g.lower() for g in (_GUID_RE.findall(out) if ok else [])}
    _cache_set(("scheme_list",), guids, gen)
    return guids


def _scheme_named(name: str) -> str | None:
    """GUID of the power scheme whose friendly name matches (or None)."""
    target = (name or "").strip().lower()
    if not target:
        return None
    cached = _cache_get(("scheme_named", target))
    if cached is not _MISS:
        return cached
    gen = _current_gen()
    guid: str | None = None
    ok, out = _run("powercfg /list")
    if ok:
        for line in out.splitlines():
            m = re.search(
                r"Power Scheme GUID:\s*([0-9a-fA-F-]+)\s*\(([^)]*)\)", line)
            if m and m.group(2).strip().lower() == target:
                guid = m.group(1).lower()
                break
    _cache_set(("scheme_named", target), guid, gen)
    return guid


def _sched_status(task: str) -> str | None:
    key = ("sched", task.upper())
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached
    gen = _current_gen()
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
    _cache_set(key, status, gen)
    return status


def _bcd_values():
    """Flat BCD store: boot-option name -> value (from `bcdedit /enum`).

    Returns None if the BCD store could not be read (e.g. access denied),
    otherwise a dict (options that are not explicitly set are absent).
    """
    cached = _cache_get(("bcd",))
    if cached is not _MISS:
        return cached
    gen = _current_gen()
    ok, out = _run("bcdedit /enum")
    vals: dict[str, str] = {}
    if ok:
        for line in out.splitlines():
            m = re.match(r"^\s*([A-Za-z0-9_-]+)\s+(.+?)\s*$", line)
            if m and not line.startswith(("identifier", "--")):
                vals[m.group(1).lower()] = m.group(2).strip()
    result: dict[str, str] | None = vals if ok else None
    _cache_set(("bcd",), result, gen)
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
    gen = _current_gen()
    ok, out = _run("netsh interface tcp show global")
    vals: dict[str, str] = {}
    if ok:
        for line in out.splitlines():
            m = re.match(r"^\s*(.+?)\s*:\s*(.+?)\s*$", line)
            if m:
                vals[m.group(1).strip().lower()] = m.group(2).strip()
    _cache_set(("netsh",), vals, gen)
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


def _netadp_props() -> list[dict]:
    """Advanced properties of active physical adapters: [{adapter, display,
    keyword, value}]. Cached per audit generation like every other read."""
    cached = _cache_get(("netadp_props",))
    if cached is not _MISS:
        return cached
    gen = _current_gen()
    rows: list[dict] = []
    try:
        from . import net_latency
        for a in net_latency.adapter_names():
            for p in net_latency.advanced_props(a):
                rows.append({
                    "adapter": a,
                    "display": str(p.get("DisplayName") or "").strip(),
                    "keyword": str(p.get("RegistryKeyword") or "").strip(),
                    "value": str(p.get("DisplayValue") or "").strip(),
                })
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"state checker: NIC property query failed: {exc}")
    _cache_set(("netadp_props",), rows, gen)
    return rows


def _netadp_rss() -> list[dict]:
    """RSS state of active physical adapters: [{adapter, enabled}]."""
    cached = _cache_get(("netadp_rss",))
    if cached is not _MISS:
        return cached
    gen = _current_gen()
    rows: list[dict] = []
    try:
        from . import net_latency
        rows = [{"adapter": str(r.get("adapter") or "").strip(),
                 "enabled": bool(r.get("enabled"))}
                for r in net_latency.rss_state()]
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"state checker: NIC RSS query failed: {exc}")
    _cache_set(("netadp_rss",), rows, gen)
    return rows


def _check_netadp(op: str) -> bool | None:
    """Live-state check for the NIC latency ops (see engine.net_latency)."""
    from . import net_latency
    if op == "interrupt_moderation":
        rows = [r for r in _netadp_props()
                if net_latency.is_interrupt_moderation(r["display"], r["keyword"])]
        if not rows:
            return None
        return all(net_latency.is_disabled_value(r["value"]) for r in rows)
    if op == "rss":
        g = _netsh_tcp_global().get("receive-side scaling state")
        if g is None:
            return None
        if g.strip().lower() != "enabled":
            return False
        rows = _netadp_rss()
        if rows and not all(bool(r["enabled"]) for r in rows):
            return False
        return True
    if op == "nicpower":
        rows = [r for r in _netadp_props()
                if net_latency.is_power_prop(r["display"], r["keyword"])]
        if not rows:
            return None
        return all(net_latency.is_disabled_value(r["value"]) for r in rows)
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
    return str(data).strip().lower() == str(target).strip().lower()


def _reg_value_absent(hive, path, name) -> bool:
    return _reg_data(hive, path, name) is None


def _reg_key_absent(hive, path) -> bool:
    # A key that exists but has no values must NOT read as "absent" (regkeydel
    # would falsely verify). Existence is judged by opening the key.
    key = ("regkey_exists", hive.upper(), path.upper())
    cached = _cache_get(key)
    if cached is not _MISS:
        return not bool(cached)
    gen = _current_gen()
    ok = reg_util.key_exists(hive, path)
    _cache_set(key, ok, gen)
    return not ok


def _reg_subkeys(hive, path) -> list[str]:
    """Hive-relative paths of path's immediate subkeys (cached)."""
    key = ("regsubkeys", hive.upper(), path.upper())
    cached = _cache_get(key)
    if cached is not _MISS:
        return cached
    gen = _current_gen()
    names = reg_util.subkeys(hive, path)
    _cache_set(key, names, gen)
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
        ultimate = _scheme_named("ultimate performance")
        return (active_guid == guid
                or active_guid == _ALIAS_GUIDS["ultimate"]
                or (ultimate is not None and active_guid == ultimate)
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
        if guid:
            return active_guid == guid.group(0).lower()
        # Non-GUID token (e.g. "ultimate"): resolve via the name lookup so the
        # check still passes on machines where the plan's GUID differs.
        name = _ALIAS_NAMES.get(target)
        resolved = _scheme_named(name) if name else None
        return bool(resolved) and active_guid == resolved
    wanted = _ALIAS_GUIDS.get(target)
    if wanted is None:
        return False
    active_guid, _active_name = _active_scheme()
    if active_guid == wanted:
        return True
    name = _ALIAS_NAMES.get(target)
    resolved = _scheme_named(name) if name else None
    return bool(resolved) and active_guid == resolved


def _check_powerscheme(action) -> bool | None:
    """Live-state check for a ``powerscheme`` action."""
    op = action[1]
    if op == "setactive":
        return _scheme_active(action[2])
    if op in ("create", "duplicate"):
        if len(action) >= 4:
            # Named creation: the derived plan must exist under that exact
            # name; "create" additionally requires it to be the active plan.
            guid = _scheme_named(action[3])
            if guid is None:
                return False
            if op == "duplicate":
                return True
            active_guid, active_name = _active_scheme()
            return active_guid == guid or active_name.strip().lower() == action[3].strip().lower()
        guid = action[2].lower()
        active_guid, active_name = _active_scheme()
        return (active_guid == guid
                or "ultimate" in active_name.lower()
                or guid in _scheme_list())
    if op == "delete":
        guid = action[2].lower()
        active_guid, _active_name = _active_scheme()
        return guid not in _scheme_list() and active_guid != guid
    return None


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
                running = _svc_running(action[2])
                return None if running is None else bool(running)
            if subop == "stop":
                running = _svc_running(action[2])
                return None if running is None else not bool(running)
            return None
        if kind == "svcstart":
            running = _svc_running(action[1])
            return None if running is None else bool(running)
        if kind == "svcstop":
            running = _svc_running(action[1])
            return None if running is None else not bool(running)
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
            return _check_powerscheme(action)
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
        if kind == "netadp":
            return _check_netadp(action[1] if len(action) > 1 else "")
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
    gen = _current_gen()
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
    _cache_set(key, sections, gen)
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


def _appx_packages() -> set | None:
    """Lower-cased names of every installed Appx package, cached per audit
    generation. A full ``Get-AppxPackage`` listing replaces per-tweak probes
    (each tweak used to spawn its own PowerShell process — several seconds of
    process spawn overhead for every two-package audit). None on failure."""
    cached = _cache_get(("appx_packages",))
    if cached is not _MISS:
        return cached
    gen = _current_gen()
    packages: set | None = None
    cmd = ('powershell -NoProfile -Command '
           '"Get-AppxPackage | Select-Object -ExpandProperty Name"')
    ok, out = _run(cmd, timeout=30)
    if ok:
        packages = {ln.strip().lower() for ln in out.splitlines() if ln.strip()}
    _cache_set(("appx_packages",), packages, gen)
    return packages


def _check_appx(op: str, package: str) -> bool | None:
    packages = _appx_packages()
    if packages is None:
        return None
    present = package.lower() in packages
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
