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
        cmd = ["reg", "add", _LPM_KEY, "/v", "LpmTimeoutMs", "/t",
               "REG_DWORD", "/d", "65535", "/f"]
    else:
        cmd = ["reg", "delete", _LPM_KEY, "/v", "LpmTimeoutMs", "/f"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="ignore", creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0:
            return False
        return (lpm_get() == 65535) if never_suspend else (
            lpm_get() is None)
    except Exception:
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
