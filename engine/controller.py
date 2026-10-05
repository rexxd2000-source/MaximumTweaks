"""Controller Overclock engine — real detection and real, reversible tweaks.

Everything here touches genuine Windows knobs:
  * USB selective suspend          -> powercfg (USB settings subgroup)
  * per-device "turn off to save"  -> root\\wmi MSPower_DeviceEnable
  * device detection (USB vs BT)   -> PnP device tree walk
  * polling measurement            -> XInput dwPacketNumber / HID report reads

We do NOT write fake "priority" registry keys. If Windows does not expose a
setting for a row, that row is reported unsupported for the connected device.
"""
from __future__ import annotations

import json
import re
import subprocess
import time

CREATE_NO_WINDOW = 0x08000000

SUB_USB = "2a737441-1930-4402-8d77-b2bebba308a3"
SEL_SUSPEND = "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"

_GAMEPAD_NAME = re.compile(
    r"controller|gamepad|joystick|dualsense|dualshock|8bitdo|xbox|rail"
    r"|witcher|sn30 pro|pro 2|valve|razer Wolverine|wireless gamepad"
    r"|wireless controller|gamesir|thrustmaster|logitech|nintendo"
    r"|fightpad|hori|powera|nacon|steelseries|steam virtual"
    r"|g[pP]ro|game\s?pad", re.I)


def _ps(script: str, timeout: int = 90) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW, timeout=timeout)
        return (r.stdout or "").strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
#  Detection
# ---------------------------------------------------------------------------

_DETECT_PS = r'''
$pads = @()
$seen = @{}
Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPDeviceID -like 'HID\*' -and $_.Name -match 'controller|gamepad|joystick|dualsense|dualshock|8bitdo|xbox|rail|witcher|valve|gamesir|thrustmaster|logitech|nintendo|fightpad|hori|powera|nacon|steelseries' } | ForEach-Object {
  $id = $_.PNPDeviceID
  $seen[$id.ToLower()] = $true
  $chain = @()
  $cur = $id
  for ($i = 0; $i -lt 8 -and $cur; $i++) {
    $par = (Get-PnpDeviceProperty -InstanceId $cur -KeyName DEVPKEY_Device_Parent -ErrorAction SilentlyContinue).Data
    if (-not $par) { break }
    $chain += $par
    $cur = $par
  }
  $conn = 'USB'
  if ($id -match '^BTH' -or ($chain -join ' ') -match '^BTH|\bBTH') { $conn = 'Bluetooth' }
  $drv = (Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_Device_DriverProviderName -ErrorAction SilentlyContinue).Data
  $vid = if ($id -match 'VID_([0-9A-F]{4})') { $matches[1] } else { '' }
  $pidv = if ($id -match 'PID_([0-9A-F]{4})') { $matches[1] } else { '' }
  $pads += [pscustomobject]@{ name = $_.Name; id = $id; vid = $vid; pid = $pidv; conn = $conn; drv = ($drv -or ''); chain = $chain; via = 'name' }
}
# Second pass: any USB device whose class is 05 (physical game device) is a
# real controller even if it has a generic name — never skipped.
Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPDeviceID -like 'USB\*' } | ForEach-Object {
  $id = $_.PNPDeviceID
  if (($_.CompatibleIDs -join ',') -match 'USB\\Class_05') {
    if ($seen[$id.ToLower()]) { return }
    $kids = (Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_Device_Children -ErrorAction SilentlyContinue).Data
    $dup = $false
    foreach ($k in ($kids | Select-Object -First 4)) { if ($seen[$k.ToLower()]) { $dup = $true } }
    if ($dup) { return }
    $conn = if ($id -match '^BTH') { 'Bluetooth' } else { 'USB' }
    $vid = if ($id -match 'VID_([0-9A-F]{4})') { $matches[1] } else { '' }
    $pidv = if ($id -match 'PID_([0-9A-F]{4})') { $matches[1] } else { '' }
    $chain = @($id)
    $pads += [pscustomobject]@{ name = ($_.Name -or ('Game device ' + $vid + ':' + $pidv)); id = $id; vid = $vid; pid = $pidv; conn = $conn; drv = ''; chain = $chain; via = 'class05' }
  }
}
$pm = @(Get-CimInstance -Namespace root/wmi -ClassName MSPower_DeviceEnable -ErrorAction SilentlyContinue | ForEach-Object { @{ n = $_.InstanceName; e = [bool]$_.Enable } })
@{ pads = $pads; pm = $pm } | ConvertTo-Json -Compress -Depth 5
'''


def detect() -> dict:
    """Return {'pads':[...], 'pm':{instance_base: enabled}, 'sel_suspend':bool}."""
    out = {"pads": [], "pm": {}, "sel_suspend": None, "xinput": False}
    js = _ps(_DETECT_PS)
    if js:
        try:
            data = json.loads(js)
            pads = data.get("pads") or []
            if isinstance(pads, dict):
                pads = [pads]
            # Drop known false positives (vendor dongles enumerating as
            # "system controller", not actual gamepads).
            pads = [p for p in pads
                    if p.get("name")
                    and "system controller" not in p["name"].lower()]
            out["pads"] = pads
            for e in (data.get("pm") or []):
                if isinstance(e, dict):
                    base = re.sub(r'_\d+$', '', e["n"])
                    out["pm"][base.lower()] = bool(e["e"])
        except Exception:
            pass
    set_pm_cache(out["pm"])
    out["sel_suspend"] = selective_suspend_get()
    out["xinput"] = xinput_present()
    return out


def related_instances(pad: dict) -> dict:
    """Power-manageable instances connected to this pad, grouped by role:
    {'hid': {base: enabled}, 'controller': {...}, 'hubs': {...}}.

    Matches MSPower_DeviceEnable instance bases against the pad's own HID
    device, its USB device(s), and PCI/root-hub ancestors in the chain."""
    chain = [c for c in (pad.get("chain") or []) if c]
    buckets = {
        "hid": [pad.get("id") or ""],
        "controller": [c for c in chain if c.upper().startswith("USB\\")],
        "hubs": [c for c in chain
                 if c.upper().startswith(("PCI\\",)) or "ROOT_HUB" in c.upper()],
    }
    result = {}
    for kind, wants in buckets.items():
        hits = {}
        for want in wants:
            w = want.lower()
            for base, enabled in _PM_CACHE.items():
                if base == w or base.startswith(w) or w.startswith(base):
                    hits[base] = enabled
        result[kind] = hits
    return result


_PM_CACHE: dict = {}


def set_pm_cache(pm: dict):
    global _PM_CACHE
    _PM_CACHE = pm or {}


# ---------------------------------------------------------------------------
#  USB selective suspend (powercfg)
# ---------------------------------------------------------------------------

def selective_suspend_get() -> bool | None:
    """True = suspend enabled (Windows default), False = disabled. None on err."""
    out = subprocess.run(
        ["powercfg", "/query", "SCHEME_CURRENT", SUB_USB, SEL_SUSPEND],
        capture_output=True, text=True, errors="ignore",
        creationflags=CREATE_NO_WINDOW).stdout
    m = re.search(r"Current AC Power Setting Index:\s*0x0*(\d)", out)
    return (m.group(1) == "1") if m else None


def selective_suspend_set(disable: bool) -> bool:
    val = "0" if disable else "1"
    ok = True
    for which in ("/setacvalueindex", "/setdcvalueindex"):
        r = subprocess.run(
            ["powercfg", which, "SCHEME_CURRENT", SUB_USB, SEL_SUSPEND, val],
            capture_output=True, creationflags=CREATE_NO_WINDOW)
        ok = ok and r.returncode == 0
    subprocess.run(["powercfg", "/setactive", "SCHEME_CURRENT"],
                   capture_output=True, creationflags=CREATE_NO_WINDOW)
    return ok


# ---------------------------------------------------------------------------
#  Per-device power management (root\wmi MSPower_DeviceEnable)
# ---------------------------------------------------------------------------

def _ps_quote(s: str) -> str:
    return s.replace("'", "''")


def device_pm_set(instances: list[str], allow_sleep: bool) -> bool:
    """Enable/Disable 'the computer can turn off this device' for each
    instance base. Returns True if no call errored."""
    if not instances:
        return True
    lines = []
    for inst in instances:
        q = _ps_quote(inst)
        lines.append(
            "$c = Get-CimInstance -Namespace root/wmi -ClassName "
            "MSPower_DeviceEnable -Filter \"InstanceName='" + q + "'\" "
            "-ErrorAction SilentlyContinue; "
            "if ($c) { Set-CimInstance -InputObject $c "
            "-Property @{Enable=$" + ("True" if allow_sleep else "False") + "} }")
    script = "; ".join(lines) + "; Write-Output OK"
    return _ps(script) == "OK"


def device_pm_restore(instances: list[str]) -> bool:
    return device_pm_set(instances, True)


# ---------------------------------------------------------------------------
#  XInput
# ---------------------------------------------------------------------------

class _XIGamepad:  # noqa: N801
    _fields_ = [("wButtons", "H"), ("bLeftTrigger", "B"),
                ("bRightTrigger", "B"), ("sThumbLX", "h"),
                ("sThumbLY", "h"), ("sThumbRX", "h"), ("sThumbRY", "h")]


class _XIS:
    _fields_ = [("dwPacketNumber", "I"), ("Gamepad", _XIGamepad)]


_XIN = None


def _xinput_dll():
    global _XIN
    if _XIN is not None:
        return _XIN
    import ctypes
    for name in ("xinput9_1_0.dll", "xinput1_4.dll", "xinput1_3.dll"):
        try:
            _XIN = ctypes.WinDLL(name)
            return _XIN
        except OSError:
            continue
    _XIN = False
    return _XIN


def xinput_present() -> bool:
    return bool(_xinput_dll())


def xinput_connected_slots() -> list[int]:
    dll = _xinput_dll()
    if not dll:
        return []
    import ctypes
    slots = []
    for i in range(4):
        try:
            st = _XIS()
            if dll.XInputGetState(i, ctypes.byref(st)) == 0:
                slots.append(i)
        except Exception:
            break
    return slots


# ---------------------------------------------------------------------------
#  Polling measurement
# ---------------------------------------------------------------------------

def _test_xinput(slot: int, seconds: float, stop=None) -> dict:
    import ctypes
    dll = _xinput_dll()
    if not dll:
        return {"error": "no xinput"}
    st = _XIS()
    deadline = time.perf_counter() + seconds
    prev = None
    packets = 0
    intervals: list[float] = []
    last_t = None
    axes = trig = btns = 0
    while time.perf_counter() < deadline:
        if stop is not None and stop():
            break
        if dll.XInputGetState(slot, ctypes.byref(st)) != 0:
            return {"error": "disconnected"}
        gp = st.Gamepad
        sig = (gp.wButtons, gp.bLeftTrigger, gp.bRightTrigger,
               gp.sThumbLX, gp.sThumbLY, gp.sThumbRX, gp.sThumbRY)
        if prev is not None:
            pn = st.dwPacketNumber & 0x7FFFFFFF
            if pn != (prev[0] & 0x7FFFFFFF):
                now = time.perf_counter()
                if last_t is not None:
                    intervals.append((now - last_t) * 1000.0)
                last_t = now
                packets += 1
                d = (sig[3] - prev[1][3], sig[4] - prev[1][4],
                     sig[5] - prev[1][5], sig[6] - prev[1][6])
                if any(abs(x) > 300 for x in d):
                    axes = 1
                if abs(sig[1] - prev[1][1]) > 16 or abs(sig[2] - prev[1][2]) > 16:
                    trig = 1
                if sig[0] != prev[1][0]:
                    btns = 1
            prev = (st.dwPacketNumber, sig)
        else:
            prev = (st.dwPacketNumber, sig)
        time.sleep(0.0004)
    return {"packets": packets, "axes": axes, "triggers": trig,
            "buttons": btns, "intervals": intervals}


def test_controller(pad: dict, seconds: float = 2.2, stop=None) -> dict:
    """Measure the live report rate. Xbox pads use XInput's packet counter;
    everything else falls back to reading the HID input report stream."""
    slots = xinput_connected_slots()
    res = None
    if slots:
        res = _test_xinput(slots[0], seconds, stop)
        if res and "packets" in res:
            res["path"] = "XInput"
    if res is None or res.get("error"):
        res = _test_hid(pad, seconds, stop)
    if res is None or not res.get("packets"):
        return {"ok": False, "hz": None, "note":
                "No input seen — press buttons/move sticks during the test."}
    iv = res.get("intervals") or []
    hz = (1000.0 / (sum(iv) / len(iv))) if iv else res["packets"] / seconds
    cons = None
    if len(iv) >= 8:
        srt = sorted(iv)
        core = srt[len(srt) // 10: len(srt) - len(srt) // 10] or srt
        avg = sum(srt) / len(srt)
        spread = max(core) - min(core)
        cons = max(0.0, min(100.0, 100.0 * (1.0 - spread / (avg * 2 + 1e-9))))
        return {"ok": True, "path": res.get("path", "HID"),
                "hz": round(hz), "packets": res["packets"],
                "avg_ms": round(sum(iv) / len(iv), 2) if iv else None,
                "consistency": round(cons, 1) if cons is not None else None,
                "intervals": [round(x, 3) for x in iv[-200:]],
                "axes": res.get("axes", 0), "triggers": res.get("triggers", 0),
                "buttons": res.get("buttons", 0)}


def _test_hid(pad: dict, seconds: float, stop=None) -> dict | None:
    import ctypes
    from ctypes import wintypes as wt
    try:
        cfgmgr = ctypes.windll.cfgmgr32
        hid = ctypes.windll.hid
        kernel = ctypes.windll.kernel32
    except Exception:
        return None

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD),
                    ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID),
                    ("Flags", wt.DWORD), ("Reserved", ctypes.POINTER(wt.ULONG))]

    class HIDD_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Size", wt.ULONG), ("VendorID", wt.USHORT),
                    ("ProductID", wt.USHORT), ("VersionNumber", wt.USHORT)]

    g = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(g))
    DIGCF_PRESENT, DIGCF_DEVICEINTERFACE = 0x02, 0x10
    setd = cfgmgr.SetupDiGetClassDevsW(ctypes.byref(g), None, None,
                                       DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if setd == -1:
        return None
    want_vid = int(pad.get("vid") or 0, 16)
    want_pid = int(pad.get("pid") or 0, 16)
    path = None
    idx = 0
    detail_buf = (ctypes.c_ubyte * 512)()
    while True:
        did = SP_DEVICE_INTERFACE_DATA()
        did.cbSize = ctypes.sizeof(did)
        if not cfgmgr.SetupDiEnumDeviceInterfaces(
                setd, None, ctypes.byref(g), idx, ctypes.byref(did)):
            break
        idx += 1
        req = wt.DWORD()
        cfgmgr.SetupDiGetDeviceInterfaceDetailW(
            setd, ctypes.byref(did), None, 0, ctypes.byref(req), None)
        if req.value > 512 or req.value == 0:
            continue
        ctypes.memset(detail_buf, 0, req.value)
        ctypes.cast(detail_buf, ctypes.POINTER(wt.DWORD))[0] = ctypes.sizeof(wt.DWORD)
        if not cfgmgr.SetupDiGetDeviceInterfaceDetailW(
                setd, ctypes.byref(did), ctypes.cast(detail_buf, ctypes.c_void_p),
                req.value, None, None):
            continue
        p = ctypes.cast(ctypes.byref(detail_buf, ctypes.sizeof(wt.DWORD)),
                        ctypes.c_wchar_p).value
        if not p:
            continue
        h = kernel.CreateFileW(p, 0xC0000000, 3, None, 3, 0, None)
        if h == -1:
            continue
        at = HIDD_ATTRIBUTES()
        at.Size = ctypes.sizeof(at)
        if hid.HidD_GetAttributes(h, ctypes.byref(at)) and \
                at.VendorID == want_vid and at.ProductID == want_pid:
            path = p
            kernel.CloseHandle(h)
            break
        kernel.CloseHandle(h)
    cfgmgr.SetupDiDestroyDeviceInfoList(setd)
    if not path:
        return None

    h = kernel.CreateFileW(path, 0xC0000000, 3, None, 0x40000000, 0, None)
    if h == -1:
        return None
    preparsed = ctypes.c_void_p()
    if not hid.HidD_GetPreparsedData(h, ctypes.byref(preparsed)):
        kernel.CloseHandle(h)
        return None

    class HIDP_CAPS(ctypes.Structure):
        _fields_ = [("UsagePage", wt.USHORT), ("Usage", wt.USHORT),
                    ("InputReportByteLength", wt.USHORT),
                    ("OutputReportByteLength", wt.USHORT),
                    ("FeatureReportByteLength", wt.USHORT),
                    ("Reserved", wt.USHORT * 17),
                    ("NumberLinkCollectionNodes", wt.USHORT),
                    ("NumberInputDataBuffers", wt.USHORT),
                    ("NumberInputDataButtons", wt.USHORT),
                    ("NumberInputDataValueAry", wt.USHORT),
                    ("NumberOfOutputDataBuffers", wt.USHORT),
                    ("NumberOfOutputDataButtons", wt.USHORT),
                    ("NumberOfOutputDataValueAry", wt.USHORT)]

    caps = HIDP_CAPS()
    ok = hid.HIDP_GetCaps(preparsed, ctypes.byref(caps))
    hid.HidD_FreePreparsedData(preparsed)
    if ok != 0 or caps.UsagePage != 1 or caps.Usage not in (4, 5, 6, 8, 9):
        kernel.CloseHandle(h)
        return None
    n = max(8, caps.InputReportByteLength)
    buf = (ctypes.c_ubyte * n)()
    event = kernel.CreateEventW(None, True, False, None)
    ov = (ctypes.c_void_p * 8)()
    ov[1] = event
    seen = None
    packets = axes = 0
    intervals: list[float] = []
    last_t = None
    deadline = time.perf_counter() + seconds
    try:
        while time.perf_counter() < deadline:
            if stop is not None and stop():
                break
            kernel.ResetEvent(event)
            read = wt.DWORD(0)
            if not kernel.ReadFile(h, buf, n, ctypes.byref(read),
                                   ctypes.cast(ov, ctypes.c_void_p)):
                if kernel.WaitForSingleObject(event, 250) != 0:
                    continue
                if not kernel.GetOverlappedResult(h, ctypes.cast(ov, ctypes.c_void_p),
                                                  ctypes.byref(read), True):
                    break
            b = bytes(buf[:read.value or n])
            if seen is None or b != seen:
                now = time.perf_counter()
                if last_t is not None:
                    intervals.append((now - last_t) * 1000.0)
                last_t = now
                packets += 1
                if seen is not None and any(x != y for x, y in zip(b[1:9], seen[1:9])):
                    axes = 1
                seen = b
        return {"packets": packets, "axes": axes, "triggers": 0,
                "buttons": 0, "path": "HID", "intervals": intervals}
    finally:
        kernel.CancelIoEx(h, None)
        kernel.CloseHandle(event)
        kernel.CloseHandle(h)


# ---------------------------------------------------------------------------
#  Hidden tier — genuine system-level latency knobs (all reversible)
# ---------------------------------------------------------------------------

_HUBS_FILTER_PS = r"""
$hubs = @(Get-CimInstance Win32_PnPEntity | Where-Object {
  $_.PNPDeviceID -like 'USB\*' -and $_.Name -match 'hub' } | ForEach-Object { $_.PNPDeviceID })
$targets = @()
foreach ($h in $hubs) {
  $base = ($h -replace '#.*$', '')
  Get-CimInstance -Namespace root/wmi -ClassName MSPower_DeviceEnable `
      -ErrorAction SilentlyContinue |
    Where-Object { $_.InstanceName.ToLower() -like ($base.ToLower() + '*') } |
    ForEach-Object { $targets += $_ }
}
$targets
"""


def _hubs_pm(enable: bool) -> int:
    script = (_HUBS_FILTER_PS
              + "\n$t = $targets | Where-Object { $_.Enable -ne $"
              + ("True" if enable else "False") + " }"
              + "\n$t | ForEach-Object { Set-CimInstance -InputObject $_ "
              "-Property @{Enable=$" + ("True" if enable else "False") + "} }"
              "\nWrite-Output ('N=' + @($t).Count)")
    out = _ps(script)
    m = re.search(r"N=(\d+)", out or "")
    return int(m.group(1)) if m else -1


def all_hubs_pm_disable() -> int:
    """Turn off 'allow computer to turn off this device' on every USB hub.
    (MSPower Enable=false = never sleep). Returns changed count; -1 err."""
    return _hubs_pm(False)


def all_hubs_pm_restore() -> int:
    return _hubs_pm(True)


def _bcd_get() -> str:
    try:
        return subprocess.run(
            ["bcdedit", "/enum", "{current}"],
            capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW).stdout or ""
    except Exception:
        return ""


def bcd_status() -> dict:
    """{'useplatformtick': 'yes'/'no'/'default', 'disabledynamictick': ...}"""
    txt = _bcd_get()
    out = {}
    for key in ("useplatformtick", "disabledynamictick"):
        m = re.search(key + r"\s+([A-Za-z]+)", txt, re.I)
        out[key] = (m.group(1).lower() if m else "default")
    return out


def bcd_set(key: str, value: str) -> bool:
    """bcdedit /set <key> <value> — requires admin. value '' deletes the
    entry back to firmware/OS default."""
    if key not in ("useplatformtick", "disabledynamictick"):
        return False
    cmd = ["bcdedit"] + (["/deletevalue", key] if not value
                         else ["/set", key, value])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="ignore", creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
#  xHCI link power management (the port controller the pad lives on)
# ---------------------------------------------------------------------------

_LPM_KEY = (r"HKLM\SYSTEM\CurrentControlSet\Services\USBXHCI\Parameters")


def lpm_get() -> int | None:
    try:
        out = subprocess.run(
            ["reg", "query", _LPM_KEY, "/v", "LpmTimeoutMs"],
            capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW).stdout
        m = re.search(r"LpmTimeoutMs\s+REG_DWORD\s+0x([0-9a-fA-F]+)", out)
        return int(m.group(1), 16) if m else None
    except Exception:
        return None


def lpm_set(never_suspend: bool) -> bool:
    """Raise the xHCI Link Power Management timeout to 65.5 s (effectively
    never: the USB link keeps full power, so no LPM exit latency on reports).
    False deletes the override (Windows default ~375 ms). Needs reboot."""
    if never_suspend:
        return lpm_set_raw(65535)
    return lpm_set_raw(None)


def lpm_set_raw(value: int | None) -> bool:
    """Write LpmTimeoutMs to an exact value, or None to delete the override.

    Used for revert: if the user's previous value was something other than the
    two states lpm_set() toggles between, it is restored verbatim.
    """
    if value is None:
        cmd = ["reg", "delete", _LPM_KEY, "/v", "LpmTimeoutMs", "/f"]
    else:
        cmd = ["reg", "add", _LPM_KEY, "/v", "LpmTimeoutMs", "/t",
               "REG_DWORD", "/d", str(int(value)), "/f"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="ignore", creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0:
            return False
        return lpm_get() == (None if value is None else int(value))
    except Exception:  # noqa: BLE001
        return False


def pad_chain_pm_disable(pad: dict) -> int:
    """Set 'never turn off for power' on the REAL connected pad's own device
    instances: HID child, USB device, and hub/root-hub parents. Returns
    number of nodes changed, 0/-1 on none/failure."""
    rel = related_instances(pad)
    insts = []
    for kind in ("hid", "controller"):
        insts.extend((rel.get(kind) or {}).keys())
    if not insts:
        return 0
    ok = device_pm_set(insts, False)
    return len(insts) if ok else -1


# ---------------------------------------------------------------------------
#  Game Bar (guide-button overlay stealing focus mid-game)
# ---------------------------------------------------------------------------

_GAMEBAR_KEY = r"HKCU\Software\Microsoft\GameBar"
_GAMEBAR_VALUE = "UseNexusForGameBarEnabled"


def gamebar_get() -> int | None:
    """Raw UseNexusForGameBarEnabled, or None if absent/unreadable.

    This is a real per-user value (it exists on a stock install), which is why
    it is safe to read before writing: the previous value is snapshotted and put
    back exactly on revert rather than assumed.
    """
    return _reg_read_dword(_GAMEBAR_KEY, _GAMEBAR_VALUE)


def gamebar_set(value: int) -> bool:
    """Write UseNexusForGameBarEnabled and read it back to confirm."""
    cmd = ["reg", "add", _GAMEBAR_KEY, "/v", _GAMEBAR_VALUE, "/t",
           "REG_DWORD", "/d", str(int(value)), "/f"]
    try:
        r = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0 and gamebar_get() == int(value)
    except Exception:  # noqa: BLE001
        return False


def gamebar_delete() -> bool:
    """Remove the override entirely, returning to the Windows default."""
    cmd = ["reg", "delete", _GAMEBAR_KEY, "/v", _GAMEBAR_VALUE, "/f"]
    try:
        r = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
#  Foreground input scheduling quantum (Win32PrioritySeparation)
# ---------------------------------------------------------------------------

_PRIORITY_KEY = r"HKLM\SYSTEM\CurrentControlSet\Control\PriorityControl"
_PRIORITY_VALUE = "Win32PrioritySeparation"
# 0x26: short foreground quantum + no foreground boost quantum-reset. The
# stock value is 0x2. Needs admin (HKLM).
PRIORITY_SEPARATION_GAMING = 0x26


def win32_prio_get() -> int | None:
    """Raw Win32PrioritySeparation, or None when absent."""
    return _reg_read_dword(_PRIORITY_KEY, _PRIORITY_VALUE)


def win32_prio_set(value: int) -> bool:
    """Set Win32PrioritySeparation and read it back. Needs admin for HKLM."""
    cmd = ["reg", "add", _PRIORITY_KEY, "/v", _PRIORITY_VALUE, "/t",
           "REG_DWORD", "/d", str(int(value)), "/f"]
    try:
        r = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0 and win32_prio_get() == int(value)
    except Exception:  # noqa: BLE001
        return False


def win32_prio_delete() -> bool:
    """Remove the Win32PrioritySeparation override entirely."""
    cmd = ["reg", "delete", _PRIORITY_KEY, "/v", _PRIORITY_VALUE, "/f"]
    try:
        r = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0 and win32_prio_get() is None
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
#  Bluetooth radio power saving
# ---------------------------------------------------------------------------

def bt_radio_instances() -> list[str]:
    """Power-manageable instance ids of the machine's Bluetooth radio/adapter.

    Two passes, because the radio shows up differently depending on the stack:
    first the BTH\\* entries the power cache already knows about, then a PnP
    query for the adapter itself. Returns [] when the machine has no Bluetooth
    radio, so the caller can grey the row out instead of claiming a change.
    """
    found = [k for k in _PM_CACHE if k.lower().startswith("bth\\")]
    if found:
        return sorted(found)
    out = _ps("Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
              "Where-Object { $_.FriendlyName -match 'Adapter|Radio' } | "
              "ForEach-Object { $_.InstanceId }")
    if not out:
        return []
    hits = []
    for line in out.splitlines():
        inst = line.strip().lower()
        if not inst or inst not in _PM_CACHE:
            continue
        hits.append(inst)
    return sorted(hits)


def driver_version(instance_id: str) -> str | None:
    """Installed driver version for a PnP instance, or None if unavailable."""
    if not instance_id:
        return None
    quoted = instance_id.replace("'", "''")
    out = _ps("(Get-PnpDeviceProperty -InstanceId '%s' "
              "-KeyName 'DEVPKEY_Device_DriverVersion' "
              "-ErrorAction SilentlyContinue).Data" % quoted)
    out = (out or "").strip()
    return out or None


# ---------------------------------------------------------------------------
#  Game DVR / background recording (HKCU)
# ---------------------------------------------------------------------------

_DVR_KEY = r"HKCU\System\GameConfigStore"


def game_dvr_get() -> bool | None:
    """True = Game DVR recording is enabled (Windows default), False =
    disabled, None on error. Key absent counts as enabled."""
    try:
        out = subprocess.run(
            ["reg", "query", _DVR_KEY, "/v", "GameDVR_Enabled"],
            capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW).stdout
    except Exception:
        return None
    m = re.search(r"GameDVR_Enabled\s+REG_DWORD\s+0x([0-9a-fA-F]+)", out)
    if not m:
        return True
    return int(m.group(1), 16) != 0


def game_dvr_set(enabled: bool) -> bool:
    """Disable DVR (enabled=False) by zeroing GameDVR_Enabled; re-enable by
    deleting the override so Windows uses its default."""
    if enabled:
        cmd = ["reg", "delete", _DVR_KEY, "/v", "GameDVR_Enabled", "/f"]
    else:
        cmd = ["reg", "add", _DVR_KEY, "/v", "GameDVR_Enabled",
               "/t", "REG_DWORD", "/d", "0", "/f"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="ignore", creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0:
            return False
        return game_dvr_get() == enabled
    except Exception:
        return False


# ---------------------------------------------------------------------------
#  Multimedia scheduler reservation (HKLM) — the classic input-latency knob
# ---------------------------------------------------------------------------

_MMCSS_KEY = (r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
              r"\Multimedia\SystemProfile")
_MMCSS_DEFAULTS = {"SystemResponsiveness": "10",
                   "NetworkThrottlingIndex": "0x0a"}


def mmcss_get() -> bool | None:
    """True = low-latency mode active (responsiveness 0%, throttle unlocked)."""
    try:
        out = subprocess.run(
            ["reg", "query", _MMCSS_KEY, "/v", "SystemResponsiveness"],
            capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW).stdout
    except Exception:
        return None
    m = re.search(r"SystemResponsiveness\s+REG_DWORD\s+0x([0-9a-fA-F]+)", out)
    return (int(m.group(1), 16) == 0) if m else False


def mmcss_set(off: bool) -> bool:
    """off=True: reserve 0% of CPU for the multimedia scheduler.
    off=False: restore Windows default."""
    vals = ([("SystemResponsiveness", "0")] if off
            else [("SystemResponsiveness", "10")])
    ok = True
    for name, val in vals:
        r = subprocess.run(
            ["reg", "add", _MMCSS_KEY, "/v", name, "/t", "REG_DWORD",
             "/d", val, "/f"],
            capture_output=True, creationflags=CREATE_NO_WINDOW)
        ok = ok and r.returncode == 0
    return ok


# ---------------------------------------------------------------------------
#  Game DVR group policy (HKLM) — layer 2 of the DVR off knob
# ---------------------------------------------------------------------------

_GPU_POLICY_KEY = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\GameDVR"


def game_dvr_policy_get() -> bool | None:
    """True = AllowGameDVR policy forbids DVR (0). None when unset/err."""
    try:
        out = subprocess.run(
            ["reg", "query", _GPU_POLICY_KEY, "/v", "AllowGameDVR"],
            capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW).stdout
    except Exception:
        return None
    m = re.search(r"AllowGameDVR\s+REG_DWORD\s+0x([0-9a-fA-F]+)", out)
    return (int(m.group(1), 16) == 0) if m else None


def game_dvr_policy_set(off: bool) -> bool:
    """off=True: forbid Game DVR via Group Policy. off=False: delete."""
    if off:
        cmd = ["reg", "add", _GPU_POLICY_KEY, "/v", "AllowGameDVR",
               "/t", "REG_DWORD", "/d", "0", "/f"]
    else:
        cmd = ["reg", "delete", _GPU_POLICY_KEY, "/v", "AllowGameDVR", "/f"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="ignore", creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0:
            return False
        return (game_dvr_policy_get() is True) if off \
            else (game_dvr_policy_get() is None)
    except Exception:
        return False


# ---------------------------------------------------------------------------
#  Game DVR legacy app capture (HKCU)
# ---------------------------------------------------------------------------

_APP_CAPTURE_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\GameDVR"


def app_capture_get() -> bool | None:
    """True = app capture enabled (default). False = off. None = err."""
    try:
        out = subprocess.run(
            ["reg", "query", _APP_CAPTURE_KEY, "/v", "AppCaptureEnabled"],
            capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW).stdout
    except Exception:
        return None
    m = re.search(r"AppCaptureEnabled\s+REG_DWORD\s+0x([0-9a-fA-F]+)", out)
    return None if not m else bool(int(m.group(1), 16))


def app_capture_set(enabled: bool) -> bool:
    """enabled=False kills Game DVR app capture; True deletes the override."""
    if enabled:
        cmd = ["reg", "delete", _APP_CAPTURE_KEY, "/v", "AppCaptureEnabled",
               "/f"]
    else:
        cmd = ["reg", "add", _APP_CAPTURE_KEY, "/v", "AppCaptureEnabled",
               "/t", "REG_DWORD", "/d", "0", "/f"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="ignore", creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0:
            return False
        return app_capture_get() == enabled
    except Exception:
        return False


# ---------------------------------------------------------------------------
#  MMCSS "Games" task priority profile (HKLM)
# ---------------------------------------------------------------------------

_GAMES_KEY = (r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
              r"\Multimedia\SystemProfile\Tasks\Games")

_GAMES_HIGH = {"Priority": ("REG_DWORD", "2"),
               "Scheduling Category": ("REG_SZ", "High"),
               "SFIO Priority": ("REG_SZ", "High"),
               "GPU Priority": ("REG_DWORD", "8")}


def _reg_read_dword(key: str, name: str) -> int | None:
    try:
        out = subprocess.run(
            ["reg", "query", key, "/v", name],
            capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW).stdout
    except Exception:
        return None
    m = re.search(name + r"\s+REG_DWORD\s+0x([0-9a-fA-F]+)", out)
    return int(m.group(1), 16) if m else None


# ---------------------------------------------------------------------------
#  Per-device "Device Parameters" power values
#
#  These sit on the device's own Enum key, one level below where
#  MSPower_DeviceEnable / AllowIdleIrpInD3 lives, and are the two switches
#  Windows actually consults for idle power on a USB/HID endpoint:
#
#    EnhancedPowerManagementEnabled  the "Enhanced Power Management" checkbox
#                                    in Device Manager's Power Management tab
#    SelectiveSuspendEnabled         the D0 idle -> suspended policy
#
#  Both are genuine Windows values, not invented. A value of 0 means "off",
#  which is what the card turns on; 1/absent means Windows may power the node
#  down. Revert deletes the value when it was absent before, so nothing is
#  invented on disk.
# ---------------------------------------------------------------------------

_ENUM_ROOT = r"HKLM\SYSTEM\CurrentControlSet\Enum"

_ENHANCED_PM = "EnhancedPowerManagementEnabled"
_DEVICE_SUSPEND = "SelectiveSuspendEnabled"


def devparam_get(instances: list[str], name: str) -> dict:
    """{instance: raw DWORD or None}. None = the value is not present."""
    out: dict = {}
    for inst in instances or []:
        out[inst] = _reg_read_dword(_ENUM_ROOT + "\\" + inst
                                    + "\\Device Parameters", name)
    return out


def devparam_set(instances: list[str], name: str, value: int | None) -> bool:
    """Write one DWORD to each instance, or delete it when value is None.

    Returns True only if every call succeeded AND every read-back agrees, so
    a silent permission failure cannot look like a successful apply.
    """
    instances = list(instances or [])
    if not instances:
        return False
    for inst in instances:
        key = _ENUM_ROOT + "\\" + inst + "\\Device Parameters"
        cmd = (["reg", "add", key, "/v", name, "/t", "REG_DWORD",
                "/d", str(int(value)), "/f"] if value is not None
               else ["reg", "delete", key, "/v", name, "/f"])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               errors="ignore",
                               creationflags=CREATE_NO_WINDOW)
        except Exception:
            return False
        if value is None:
            # Deleting a value that was never there is still a success.
            if r.returncode != 0 and "cannot find" not in (r.stderr or "").lower():
                return False
        elif r.returncode != 0:
            return False
    check = devparam_get(instances, name)
    for inst in instances:
        if value is None:
            if check.get(inst) is not None:
                return False
        elif check.get(inst) != int(value):
            return False
    return True


def epm_get(instances: list[str]) -> dict:
    """Enhanced power management raw values (see module note)."""
    return devparam_get(instances, _ENHANCED_PM)


def epm_set(instances: list[str], off: bool) -> bool:
    """off=True writes 0 (no enhanced power management), off=False writes 1."""
    return devparam_set(instances, _ENHANCED_PM, 0 if off else 1)


def dss_get(instances: list[str]) -> dict:
    """Per-device selective suspend raw values (see module note)."""
    return devparam_get(instances, _DEVICE_SUSPEND)


def dss_set(instances: list[str], off: bool) -> bool:
    """off=True writes 0 (never idle-suspend), off=False writes 1."""
    return devparam_set(instances, _DEVICE_SUSPEND, 0 if off else 1)


def _reg_read_sz(key: str, name: str) -> str | None:
    try:
        out = subprocess.run(
            ["reg", "query", key, "/v", name],
            capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW).stdout
    except Exception:
        return None
    m = re.search(name + r"\s+REG_SZ\s+(\S+)", out)
    return m.group(1) if m else None


def mmcss_games_get() -> bool | None:
    """True = Games MMCSS profile is forced to High scheduling."""
    cat = _reg_read_sz(_GAMES_KEY, "Scheduling Category")
    if cat is None:
        return False
    return cat.lower() == "high"


def mmcss_games_set(high: bool) -> bool:
    ok = True
    if high:
        for name, (vtype, val) in _GAMES_HIGH.items():
            r = subprocess.run(
                ["reg", "add", _GAMES_KEY, "/v", name, "/t", vtype,
                 "/d", val, "/f"],
                capture_output=True, creationflags=CREATE_NO_WINDOW)
            ok = ok and r.returncode == 0
    else:
        for name in _GAMES_HIGH:
            r = subprocess.run(
                ["reg", "delete", _GAMES_KEY, "/v", name, "/f"],
                capture_output=True, creationflags=CREATE_NO_WINDOW)
            ok = ok and r.returncode == 0
    return ok and (mmcss_games_get() == high)


# ---------------------------------------------------------------------------
#  Power throttling off (HKLM)
# ---------------------------------------------------------------------------

_PWT_KEY = r"HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerThrottling"


def power_throttle_get() -> bool | None:
    """True = power throttling disabled (PowerThrottlingOff == 1)."""
    v = _reg_read_dword(_PWT_KEY, "PowerThrottlingOff")
    return (v == 1) if v is not None else None


def power_throttle_set(off: bool) -> bool:
    if off:
        cmd = ["reg", "add", _PWT_KEY, "/v", "PowerThrottlingOff",
               "/t", "REG_DWORD", "/d", "1", "/f"]
    else:
        cmd = ["reg", "delete", _PWT_KEY, "/v", "PowerThrottlingOff", "/f"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="ignore", creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0:
            return False
        return (power_throttle_get() is True) if off \
            else (power_throttle_get() is None)
    except Exception:
        return False


# ---------------------------------------------------------------------------
#  PCIe Express Link State Power Management (powercfg)
# ---------------------------------------------------------------------------

_SUB_PCIE = "ee12f906-d277-404b-b6da-e5fa1a576df5"
_SET_ASPM = "501a4d13-42af-4429-9fd1-a8218c268e20"


def pcie_aspm_get() -> int | None:
    out = subprocess.run(
        ["powercfg", "/query", "SCHEME_CURRENT", _SUB_PCIE, _SET_ASPM],
        capture_output=True, text=True, errors="ignore",
        creationflags=CREATE_NO_WINDOW).stdout
    m = re.search(r"Current AC Power Setting Index:\s*0x0*([0-9a-fA-F]+)", out)
    return int(m.group(1), 16) if m else None


def pcie_aspm_set(off: bool) -> bool:
    """off=True turns off PCIe link state power management (0), False restores
    the default 'moderate' value (2)."""
    val = "0" if off else "2"
    ok = True
    for which in ("/setacvalueindex", "/setdcvalueindex"):
        r = subprocess.run(
            ["powercfg", which, "SCHEME_CURRENT", _SUB_PCIE, _SET_ASPM, val],
            capture_output=True, creationflags=CREATE_NO_WINDOW)
        ok = ok and r.returncode == 0
    subprocess.run(["powercfg", "/setactive", "SCHEME_CURRENT"],
                   capture_output=True, creationflags=CREATE_NO_WINDOW)
    return ok


# ---------------------------------------------------------------------------
#  Network throttling index (unlock DWM budget)
# ---------------------------------------------------------------------------

_NTI_KEY = _MMCSS_KEY


def nti_get() -> bool | None:
    """True = network throttle unlocked (0xffffffff)."""
    v = _reg_read_dword(_NTI_KEY, "NetworkThrottlingIndex")
    if v is None:
        return False
    return v >= 0xffff0000


def nti_set(off: bool) -> bool:
    """off=True unlocks the network throttle (0xffffffff); False restores
    the Windows default (10)."""
    val = "0xffffffff" if off else "0x0a"
    r = subprocess.run(
        ["reg", "add", _NTI_KEY, "/v", "NetworkThrottlingIndex",
         "/t", "REG_DWORD", "/d", val, "/f"],
        capture_output=True, creationflags=CREATE_NO_WINDOW)
    return r.returncode == 0 and nti_get() == off


# ---------------------------------------------------------------------------
#  MSI interrupts on the pad's xHCI controller (HKLM\Enum)
# ---------------------------------------------------------------------------

_MSI_SUB = r"Device Parameters\Interrupt Management\MessageSignaledInterruptProperties"


def _xhci_instance(pad: dict) -> str | None:
    """First PCI ancestor in the pad chain = the xHCI controller instance."""
    for c in (pad.get("chain") or []):
        if c and c.upper().startswith("PCI\\"):
            return c
    return None


def msi_get(pad: dict) -> bool | None:
    """True = MSI enabled (MSISupported == 1). False = disabled/default.
    None = the pad has no PCI (xHCI) ancestor in its chain."""
    inst = _xhci_instance(pad)
    if not inst:
        return None
    key = _ENUM_ROOT + "\\" + inst + "\\" + _MSI_SUB
    v = _reg_read_dword(key, "MSISupported")
    return (v == 1) if v is not None else False


def msi_set(pad: dict, on: bool) -> bool:
    return msi_set_raw(pad, 1 if on else None)


def msi_raw(pad: dict) -> int | None:
    """Raw MSISupported DWORD, or None when the pad has no xHCI ancestor or
    the value is absent. Used so revert can restore the exact original."""
    inst = _xhci_instance(pad)
    if not inst:
        return None
    return _reg_read_dword(_ENUM_ROOT + "\\" + inst + "\\" + _MSI_SUB,
                           "MSISupported")


def msi_set_raw(pad: dict, value: int | None) -> bool:
    """Write MSISupported, or delete it when value is None."""
    inst = _xhci_instance(pad)
    if not inst:
        return False
    base = _ENUM_ROOT + "\\" + inst + "\\" + _MSI_SUB
    cmd = (["reg", "add", base, "/v", "MSISupported", "/t", "REG_DWORD",
            "/d", str(int(value)), "/f"] if value is not None
           else ["reg", "delete", base, "/v", "MSISupported", "/f"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="ignore", creationflags=CREATE_NO_WINDOW)
    except Exception:
        return False
    if r.returncode != 0:
        if value is None and "cannot find" in (r.stderr or "").lower():
            return True
        return False
    return msi_raw(pad) == value


# ---------------------------------------------------------------------------
#  Hibernation (powercfg /h)
# ---------------------------------------------------------------------------

_POWER_KEY = r"HKLM\SYSTEM\CurrentControlSet\Control\Power"


def hibernate_get() -> bool | None:
    """True = hibernation enabled. None when the flag is absent."""
    v = _reg_read_dword(_POWER_KEY, "HibernateEnabled")
    return (v == 1) if v is not None else None


def hibernate_set(enabled: bool) -> bool:
    """powercfg /h off / on — requires admin."""
    try:
        r = subprocess.run(
            ["powercfg", "/h", "on" if enabled else "off"],
            capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0:
            return False
        return hibernate_get() == enabled
    except Exception:
        return False
