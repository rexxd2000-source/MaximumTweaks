"""Shared per-subsystem detection probes.

Each probe inspects one subsystem (CPU, GPU, RAM, network, TCP, UDP, DNS,
mouse, keyboard, storage, power, display, audio, services, ...) and returns a
flat result dict:

    {
        "label":   display title, e.g. "Network Adapter",
        "ok":      bool — did detection succeed,
        "facts":   [(label, value), ...] — human-readable fact rows,
        "data":    { ... } — machine-readable values for the optimizer layer,
    }

Probes are registered via the @probe decorator into the PROBES registry so a
new subsystem can be added without touching the UI or the engine.  Probes
never raise — every failure degrades to a partial result.
"""
from __future__ import annotations

import platform
import re
import time
import winreg

from rexlog import logger

from .detector import _csv_rows, _ps, _gpu_vendor, _gpu_is_integrated, _chassis_is_laptop

# Probe results are cached briefly so repeated scans (page open, scan button,
# optimize dialog) do not re-spawn several PowerShell processes each time.
_CACHE: dict = {}
_CACHE_TTL = 45.0

PROBES: dict = {}


def probe(name: str):
    """Decorator that registers a probe function in the PROBES registry."""
    def deco(fn):
        PROBES[name] = fn
        return fn
    return deco


def run_probe(name: str, refresh: bool = False) -> dict:
    """Run a registered probe, honoring the short TTL cache."""
    fn = PROBES.get(name)
    if fn is None:
        return {"label": name, "ok": False, "facts": [], "data": {}}
    if not refresh:
        cached = _CACHE.get(name)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL:
            return cached[1]
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"probe {name} failed: {type(exc).__name__}: {exc}")
        result = {"label": name, "ok": False, "facts": [], "data": {}}
    if not isinstance(result, dict) or "data" not in result:
        result = {"label": name, "ok": False, "facts": [], "data": result or {}}
    _CACHE[name] = (time.monotonic(), result)
    return result


def clear_cache():
    _CACHE.clear()


def _reg_value(hive: str, subkey: str, name: str, default=None):
    """Read a single registry value via winreg (fast, no process spawn)."""
    try:
        root = (winreg.HKEY_LOCAL_MACHINE if hive == "HKLM"
                else winreg.HKEY_CURRENT_USER if hive == "HKCU"
                else winreg.HKEY_USERS)
        with winreg.OpenKey(root, subkey) as key:
            value, _kind = winreg.QueryValueEx(key, name)
            return value
    except OSError:
        return default


def _decode_utf16(raw):
    if not raw:
        return ""
    try:
        text = bytes(raw).decode("utf-16-le", errors="ignore")
    except Exception:  # noqa: BLE001
        return ""
    return text.strip("\x00").strip()


# --------------------------------------------------------------------------
# CPU
# --------------------------------------------------------------------------

@probe("cpu")
def _probe_cpu():
    profile = _base_profile()
    rows = _csv_rows(
        "Get-CimInstance Win32_Processor | Select-Object Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,Architecture")
    data = {
        "name": profile.get("cpu_name", "Unknown"),
        "vendor": profile.get("cpu_vendor", "unknown"),
        "cores": profile.get("cpu_cores", 0),
        "threads": profile.get("cpu_threads", 0),
        "ghz": profile.get("cpu_ghz", 0.0),
        "arch": "Unknown",
    }
    if rows:
        row = rows[0]
        arch_map = {0: "x86", 5: "ARM", 6: "Intel Itanium", 9: "x64",
                    12: "ARM64", 0xFFFF: "Unknown"}
        try:
            data["arch"] = arch_map.get(int(float(row.get("Architecture") or -1)),
                                        "Unknown")
        except (TypeError, ValueError):
            pass
    facts = [
        ("Model", f"{data['name']}"),
        ("Cores", f"{data['cores']} cores / {data['threads']} threads"),
        ("Clock", f"{data['ghz']} GHz"),
        ("Architecture", data["arch"]),
    ]
    return {"label": "CPU", "ok": True, "facts": facts, "data": data}


# --------------------------------------------------------------------------
# GPU
# --------------------------------------------------------------------------

# Display-adapter device class GUID; each adapter is a numbered subkey.
_GPU_CLASS_GUID = r"{4d36e968-e325-11ce-bfc1-08002be10318}"


def _gpu_vram_registry() -> list[dict]:
    """[{desc, vram_bytes, match_id}] read from the display class registry.

    Win32_VideoController.AdapterRAM is a 32-bit field, so drivers clamp it to
    0xFFFFFFFF (~4.0 GB) on GPUs with more VRAM. ``HardwareInformation
    .qwMemorySize`` under each adapter subkey is the accurate 64-bit value.
    """
    out: list[dict] = []
    base = (r"SYSTEM\CurrentControlSet\Control\Class"
            + "\\" + _GPU_CLASS_GUID)
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return out
    try:
        for i in range(winreg.QueryInfoKey(root)[0]):
            sub = winreg.EnumKey(root, i)
            if not re.fullmatch(r"\d+", sub):
                continue
            try:
                with winreg.OpenKey(root, sub) as k:

                    def _qv(name):
                        try:
                            v, _t = winreg.QueryValueEx(k, name)
                            return v
                        except OSError:
                            return None

                    vram = _qv("HardwareInformation.qwMemorySize")
                    out.append({
                        "desc": str(_qv("DriverDesc") or "").strip(),
                        "vram_bytes": int(vram) if vram else 0,
                        "match": str(_qv("MatchingDeviceId") or "").strip().upper(),
                    })
            except OSError:
                continue
    finally:
        winreg.CloseKey(root)
    return out


@probe("gpu")
def _probe_gpu():
    rows = _csv_rows(
        "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,AdapterRAM,PNPDeviceID,VideoModeDescription")
    gpus, vendors = [], []
    integrated, dedicated = [], []
    reg_gpus = _gpu_vram_registry()
    total_vram = 0
    for row in rows:
        name = (row.get("Name") or "Unknown Video Controller").strip()
        vendor = _gpu_vendor(name)
        is_integrated = _gpu_is_integrated(name)
        if vendor not in vendors:
            vendors.append(vendor)
        vram = 0
        pnp = (row.get("PNPDeviceID") or "").strip().upper()
        vram_bytes = 0
        for rg in reg_gpus:
            if rg["match"] and pnp.startswith(rg["match"]):
                vram_bytes = max(vram_bytes, rg["vram_bytes"])
        if vram_bytes <= 0 and len(reg_gpus) == 1:
            vram_bytes = reg_gpus[0]["vram_bytes"]
        if vram_bytes > 0:
            vram = round(vram_bytes / (1024 ** 3), 1)
        else:
            try:
                vram = round(int(float(row.get("AdapterRAM") or 0)) / (1024 ** 3), 1)
            except (TypeError, ValueError):
                pass
        total_vram = max(total_vram, vram)
        gpu_type = "integrated" if is_integrated else "dedicated"
        if is_integrated:
            integrated.append(name)
        else:
            dedicated.append(name)
        gpus.append({
            "name": name,
            "driver": (row.get("DriverVersion") or "Unknown").strip(),
            "vram_gb": vram,
            "vendor": vendor,
            "type": gpu_type,
            "mode": (row.get("VideoModeDescription") or "").strip(),
            "pnp": pnp,
        })
    if not gpus:
        gpus = [{"name": "Unknown GPU", "driver": "Unknown", "vram_gb": 0,
                 "vendor": "unknown", "type": "unknown", "mode": "", "pnp": ""}]
        vendors = ["unknown"]
    facts = []
    for g in gpus:
        res = (f" · {g['mode']}" if g.get("mode") else "")
        vram = f" · {g['vram_gb']} GB VRAM" if g.get("vram_gb") else ""
        gpu_type = f" ({g['type']})" if g.get("type") != "unknown" else ""
        facts.append(("GPU", f"{g['name']}{gpu_type}{vram}{res}"))
        facts.append(("Driver", g["driver"]))
    return {"label": "GPU", "ok": True, "facts": facts,
            "data": {"gpus": gpus, "vendors": vendors,
                     "integrated": integrated, "dedicated": dedicated,
                     "total_vram_gb": total_vram}}


# --------------------------------------------------------------------------
# RAM
# --------------------------------------------------------------------------

_DDR_MAP = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5"}


@probe("ram")
def _probe_ram():
    profile = _base_profile()
    rows = _csv_rows(
        "Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,ConfiguredClockSpeed,SMBIOSMemoryType,Manufacturer,PartNumber")
    sticks = []
    for row in rows:
        cap = 0
        try:
            cap = round(int(float(row.get("Capacity") or 0)) / (1024 ** 3), 1)
        except (TypeError, ValueError):
            pass
        speed = configured = 0
        try:
            speed = int(float(row.get("Speed") or 0))
        except (TypeError, ValueError):
            pass
        try:
            configured = int(float(row.get("ConfiguredClockSpeed") or 0))
        except (TypeError, ValueError):
            pass
        memtype = ""
        try:
            memtype = _DDR_MAP.get(int(float(row.get("SMBIOSMemoryType") or 0)), "")
        except (TypeError, ValueError):
            pass
        sticks.append({
            "capacity_gb": cap,
            "speed": speed,
            "configured_speed": configured,
            "memtype": memtype,
            "manufacturer": (row.get("Manufacturer") or "").strip() or "Unknown",
            "part": (row.get("PartNumber") or "").strip(),
        })
    if not sticks:
        sticks = [{"capacity_gb": profile.get("ram_gb", 0), "speed": 0,
                   "configured_speed": 0, "memtype": "", "manufacturer": "Unknown",
                   "part": ""}]
    ddr = sorted({s["memtype"] for s in sticks if s["memtype"]})
    data = {
        "total_gb": profile.get("ram_gb", 0),
        "sticks": sticks,
        "channels": len(sticks),
        "mtps": max((s["speed"] for s in sticks), default=0),
        "ddr_gen": "/".join(ddr) or "Unknown",
    }
    facts = [
        ("Total", f"{data['total_gb']} GB"),
        ("Modules", f"{data['channels']} x {sticks[0]['capacity_gb']} GB"),
        ("Speed", f"{data['mtps']} MT/s"
                  + (f" (configured {sticks[0]['configured_speed']} MT/s)"
                     if sticks[0].get("configured_speed") else "")),
        ("Generation", data["ddr_gen"]),
    ]
    return {"label": "RAM", "ok": True, "facts": facts, "data": data}


# --------------------------------------------------------------------------
# Network adapter
# --------------------------------------------------------------------------

@probe("network")
def _probe_network():
    rows = _csv_rows(
        "Get-NetAdapter -Physical -ErrorAction SilentlyContinue | Where-Object Status -eq 'Up' | Select-Object Name,InterfaceDescription,LinkSpeed,MediaType,MacAddress")
    dns = _active_dns()
    data = {"name": "-", "desc": "-", "manufacturer": "Unknown", "driver": "-",
            "driver_version": "Unknown", "link_speed": "", "media": "ethernet",
            "ipv4": "", "dns": dns}
    if rows:
        row = rows[0]
        name = row.get("Name") or "-"
        desc = row.get("InterfaceDescription") or "-"
        link = row.get("LinkSpeed") or ""
        media = "wifi" if ("wireless" in desc.lower() or "wi-fi" in desc.lower()) \
            else "ethernet"
        data.update({"name": name, "desc": desc, "link_speed": str(link),
                     "media": media})
        data["mac"] = (row.get("MacAddress") or "").upper()
    driver_rows = _csv_rows(
        "Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue | Where-Object DeviceClass -eq 'Net' | Select-Object DeviceName,Manufacturer,DriverVersion")
    if driver_rows:
        desc = (data["desc"] or "").lower()
        for row in driver_rows:
            dev = (row.get("DeviceName") or "").lower()
            if not desc or desc in dev or dev in desc:
                data["manufacturer"] = (row.get("Manufacturer") or "Unknown").strip()
                data["driver_version"] = (row.get("DriverVersion") or "Unknown").strip()
                break
        else:
            data["manufacturer"] = (driver_rows[0].get("Manufacturer")
                                    or "Unknown").strip()
            data["driver_version"] = (driver_rows[0].get("DriverVersion")
                                      or "Unknown").strip()
    try:
        stats = _ps("Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {$_.InterfaceAlias -eq \"" + data["name"] + "\"} | Select-Object -ExpandProperty IPAddress")
        data["ipv4"] = (stats.strip().splitlines() or [""])[0]
    except Exception:  # noqa: BLE001
        pass
    facts = [
        ("Adapter", data["name"]),
        ("Model", data["desc"]),
        ("Manufacturer", data["manufacturer"]),
        ("Driver", data["driver_version"]),
        ("Link", data["link_speed"] or "unknown"),
        ("Type", "Wi-Fi" if data["media"] == "wifi" else "Ethernet"),
        ("IPv4", data.get("ipv4") or "-"),
        ("DNS", ", ".join(data["dns"][:3]) or "-"),
    ]
    return {"label": "Network Adapter", "ok": True, "facts": facts, "data": data}


def _active_dns() -> list:
    rows = _csv_rows(
        "Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object ServerAddresses | Select-Object InterfaceAlias,ServerAddresses")
    out = []
    seen = set()
    for row in rows:
        for chunk in str(row.get("ServerAddresses") or "").split(" "):
            ip = chunk.strip("{} ")
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip) and ip not in seen:
                seen.add(ip)
                out.append(ip)
    return out[:6]


# --------------------------------------------------------------------------
# TCP / UDP / DNS subsystems
# --------------------------------------------------------------------------

@probe("tcp")
def _probe_tcp():
    base = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"
    names = ["Tcp1323Opts", "GlobalMaxTcpWindowSize", "TcpWindowSize",
             "TcpTimedWaitDelay", "DefaultTTL", "MaxUserPort", "EnableRSS",
             "TcpAckFrequency", "TcpNoDelay", "GlobalMaxConnections",
             "SynAttackProtect", "TcpInitialRtt"]
    params = {}
    for n in names:
        v = _reg_value("HKLM", base, n, None)
        if v is not None:
            params[n] = v
    rss = _netsh_kv("netsh int tcp show global")
    data = {"params": params, "rss": rss}
    facts = []
    labels = {"Tcp1323Opts": "TCP window scaling (1323)",
              "GlobalMaxTcpWindowSize": "Max window size",
              "TcpTimedWaitDelay": "Timed-wait delay",
              "DefaultTTL": "Default TTL",
              "EnableRSS": "RSS",
              "TcpAckFrequency": "ACK frequency",
              "TcpNoDelay": "Nagle (no-delay)"}
    for n in names:
        if n in params:
            facts.append((labels.get(n, n), params[n]))
    for k in ("Receive-Side Scaling State", "RFC 1323 Timestamps"):
        if k in rss:
            facts.append((k, rss[k]))
    if not facts:
        facts.append(("TCP", "Stock Windows defaults"))
    return {"label": "TCP", "ok": True, "facts": facts, "data": data}


@probe("udp")
def _probe_udp():
    rows = _csv_rows(
        "Get-NetAdapterAdvancedProperty -Physical -ErrorAction SilentlyContinue | Where-Object DisplayName -match 'UDP' | Select-Object Name,DisplayName,DisplayValue | Sort-Object Name,DisplayName")
    items = [{"adapter": r.get("Name") or "-",
              "setting": r.get("DisplayName") or "",
              "value": r.get("DisplayValue") or ""} for r in rows]
    data = {"items": items}
    facts = [(i["setting"], f"{i['adapter']} = {i['value']}") for i in items[:8]]
    if not facts:
        facts.append(("UDP", "No UDP offload settings exposed by the driver"))
    return {"label": "UDP", "ok": True, "facts": facts, "data": data}


@probe("dns")
def _probe_dns():
    rows = _csv_rows(
        "Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object ServerAddresses | Select-Object InterfaceAlias,ServerAddresses")
    interfaces = []
    for row in rows:
        servers = []
        for chunk in str(row.get("ServerAddresses") or "").split(" "):
            ip = chunk.strip("{} ")
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
                servers.append(ip)
        if servers:
            interfaces.append({"name": row.get("InterfaceAlias") or "-",
                               "servers": servers})
    data = {"interfaces": interfaces,
            "active": [ip for iface in interfaces for ip in iface["servers"]]}
    facts = []
    for iface in interfaces[:4]:
        facts.append(("Interface", iface["name"]))
        facts.append(("DNS", ", ".join(iface["servers"])))
    if not facts:
        facts.append(("DNS", "No IPv4 DNS servers reported"))
    return {"label": "DNS", "ok": True, "facts": facts, "data": data}


def _netsh_kv(command: str) -> dict:
    out = _ps(command, timeout=20)
    result = {}
    for line in out.splitlines():
        line = line.strip()
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip()
    return result


# --------------------------------------------------------------------------
# Mouse / Keyboard / Input
# --------------------------------------------------------------------------

def _pnp_devices(classes: list) -> list:
    rows = _csv_rows(
        "Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Class -in @('" + "','".join(classes) + "') } | "
        "Select-Object FriendlyName,Manufacturer,InstanceId,Status")
    devices = []
    for row in rows:
        instance = row.get("InstanceId") or ""
        low = instance.lower()
        if "bluetooth" in low or low.startswith("bth"):
            connection = "Bluetooth"
        elif low.startswith("usb"):
            connection = "USB"
        elif low.startswith("hid"):
            connection = "HID"
        elif low.startswith("pci") or low.startswith("root"):
            connection = "Internal"
        elif low.startswith("acpi") or low.startswith("ps2"):
            connection = "PS/2"
        else:
            connection = "Unknown"
        devices.append({
            "name": (row.get("FriendlyName") or "Unknown device").strip(),
            "manufacturer": (row.get("Manufacturer") or "").strip() or "Unknown",
            "connection": connection,
            "status": (row.get("Status") or "").strip(),
        })
    return devices


@probe("mouse")
def _probe_mouse():
    devices = [d for d in _pnp_devices(["Mouse"]) if d["status"].lower() == "ok"]
    data = {
        "devices": devices,
        "pointer": {
            "acceleration": _reg_value(
                "HKCU", r"Control Panel\Mouse", "MouseSpeed", "?"),
            "sensitivity": _reg_value(
                "HKCU", r"Control Panel\Mouse", "MouseSensitivity", "?"),
            "enhance_pointer_precision": _reg_value(
                "HKCU", r"Control Panel\Mouse", "MouseSpeed", "?") != "1",
        },
    }
    facts = []
    for d in devices:
        facts.append(("Device", d["name"]))
        facts.append(("Connection", d["connection"]))
    if not devices:
        facts.append(("Device", "No mouse detected"))
        facts.append(("Connection", "-"))
    facts.append(("Pointer accel", "On" if data["pointer"]["acceleration"] == "1"
                  else "Off" if data["pointer"]["acceleration"] != "?" else "?"))
    facts.append(("Sensitivity", str(data["pointer"]["sensitivity"])))
    return {"label": "Mouse", "ok": True, "facts": facts, "data": data}


@probe("keyboard")
def _probe_keyboard():
    devices = [d for d in _pnp_devices(["Keyboard"]) if d["status"].lower() == "ok"]
    data = {
        "devices": devices,
        "repeat": {
            "delay": _reg_value("HKCU", r"Control Panel\Keyboard", "KeyboardDelay", "?"),
            "speed": _reg_value("HKCU", r"Control Panel\Keyboard", "KeyboardSpeed", "?"),
        },
    }
    facts = []
    for d in devices:
        facts.append(("Device", d["name"]))
        facts.append(("Connection", d["connection"]))
    if not devices:
        facts.append(("Device", "No keyboard detected"))
        facts.append(("Connection", "-"))
    facts.append(("Repeat delay", str(data["repeat"]["delay"])))
    facts.append(("Repeat speed", str(data["repeat"]["speed"])))
    return {"label": "Keyboard", "ok": True, "facts": facts, "data": data}


@probe("usb")
def _probe_usb():
    controllers = _pnp_devices(["USB"])
    hubs = [d for d in controllers if "hub" in d["name"].lower()]
    controllers = [d for d in controllers if d["name"].lower().startswith(
        ("intel", "amd", "asmedia", "renesas", "via"))]
    data = {"controllers": controllers[:8], "hubs": len(hubs),
            "usb_devices": len(_pnp_devices(["USB"]))}
    facts = []
    for c in data["controllers"]:
        facts.append(("Controller", c["name"]))
    if not data["controllers"]:
        facts.append(("USB", "No USB host controllers detected"))
    facts.append(("USB devices", data["usb_devices"]))
    return {"label": "USB", "ok": True, "facts": facts, "data": data}


@probe("input")
def _probe_input():
    mouse = _pnp_devices(["Mouse"])
    keyboard = _pnp_devices(["Keyboard"])
    gamepads = [d for d in _pnp_devices(["HIDClass"])
                if any(k in d["name"].lower() for k in
                       ("controller", "gamepad", "joystick", "xbox"))]
    data = {
        "mouse": [d for d in mouse if d["status"].lower() == "ok"],
        "keyboard": [d for d in keyboard if d["status"].lower() == "ok"],
        "gamepads": gamepads,
    }
    facts = []
    if data["mouse"]:
        facts.append(("Mouse", data["mouse"][0]["name"]))
    if data["keyboard"]:
        facts.append(("Keyboard", data["keyboard"][0]["name"]))
    for g in data["gamepads"]:
        facts.append(("Gamepad", g["name"]))
    if not facts:
        facts.append(("Input", "No input devices detected"))
    return {"label": "Input", "ok": True, "facts": facts, "data": data}


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

@probe("storage")
def _probe_storage():
    rows = _csv_rows(
        "Get-PhysicalDisk -ErrorAction SilentlyContinue | Select-Object FriendlyName,MediaType,BusType,Size,HealthStatus")
    disks = []
    for row in rows:
        size = 0
        try:
            size = round(int(float(row.get("Size") or 0)) / (1024 ** 3), 0)
        except (TypeError, ValueError):
            pass
        disks.append({
            "name": (row.get("FriendlyName") or "Unknown disk").strip(),
            "media": (row.get("MediaType") or "Unknown").strip(),
            "bus": (row.get("BusType") or "Unknown").strip(),
            "size_gb": size,
            "health": (row.get("HealthStatus") or "Unknown").strip(),
        })
    fs_rows = _csv_rows(
        "Get-Volume -DriveLetter C -ErrorAction SilentlyContinue | Select-Object FileSystemLabel,FileSystem,DriveType")
    fs = ""
    if fs_rows:
        fs = str(fs_rows[0].get("FileSystem") or "")
    trim = _reg_value("HKLM", r"SYSTEM\CurrentControlSet\Control\FileSystem",
                      "DisableDeleteNotify", None)
    data = {"disks": disks, "filesystem": fs, "trim_disabled": trim}
    facts = []
    for d in disks:
        facts.append(("Drive", d["name"]))
        facts.append(("Type", f"{d['media']} \u00b7 {d['bus']} \u00b7 "
                              f"{d['size_gb']:.0f} GB \u00b7 {d['health']}"))
    if fs:
        facts.append(("File system", fs))
    if trim is not None:
        facts.append(("TRIM", "Off" if trim else "On"))
    if not facts:
        facts.append(("Storage", "No disks detected"))
    return {"label": "Storage", "ok": True, "facts": facts, "data": data}


# --------------------------------------------------------------------------
# Power
# --------------------------------------------------------------------------

@probe("power")
def _probe_power():
    out = _ps("powercfg /getactivescheme", timeout=15)
    active = "Unknown"
    m = re.search(r"\((.*?)\)", out)
    if m:
        active = m.group(1).strip()
    laptop = _chassis_is_laptop()
    battery = psutil_battery()
    data = {"active_scheme": active, "laptop": laptop, "battery": battery}
    facts = [
        ("Active plan", active),
        ("Form factor", "Laptop" if laptop else "Desktop"),
        ("Battery", "Present" if battery else "None"),
    ]
    return {"label": "Power", "ok": True, "facts": facts, "data": data}


def psutil_battery() -> bool:
    try:
        import psutil
        return psutil.sensors_battery() is not None
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------
# Display
# --------------------------------------------------------------------------

@probe("display")
def _probe_display():
    rows = _csv_rows(
        "Get-CimInstance Win32_VideoController | Select-Object Name,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate")
    monitor_rows = _csv_rows(
        "Get-CimInstance -Namespace root\\wmi WmiMonitorID -ErrorAction SilentlyContinue | Select-Object UserFriendlyName,ManufacturerName")
    monitors = []
    for row in monitor_rows:
        name = _decode_utf16(row.get("UserFriendlyName")) or "Generic Monitor"
        mfr = _decode_utf16(row.get("ManufacturerName"))
        monitors.append((mfr + " " + name).strip() if mfr else name)
    displays = []
    max_refresh = 0
    for i, row in enumerate(rows):
        res = ""
        try:
            h = int(float(row.get("CurrentHorizontalResolution") or 0))
            v = int(float(row.get("CurrentVerticalResolution") or 0))
            if h and v:
                res = f"{h} x {v}"
        except (TypeError, ValueError):
            pass
        refresh = 0
        try:
            refresh = int(float(row.get("CurrentRefreshRate") or 0))
        except (TypeError, ValueError):
            pass
        max_refresh = max(max_refresh, refresh)
        monitor = monitors[i] if i < len(monitors) else "Unknown monitor"
        displays.append({
            "gpu": (row.get("Name") or "Unknown GPU").strip(),
            "resolution": res,
            "refresh": refresh,
            "monitor": monitor,
        })
    data = {"displays": displays, "refresh_max": max_refresh}
    facts = []
    for d in displays:
        facts.append(("Monitor", d["monitor"]))
        facts.append(("Signal", f"{d['gpu']} \u00b7 {d['resolution'] or '?'} "
                               f"@ {d['refresh'] or '?'} Hz"))
    if not facts:
        facts.append(("Display", "No display detected"))
    facts.append(("HDR / VRR", "driver-dependent"))
    return {"label": "Display", "ok": True, "facts": facts, "data": data}


# --------------------------------------------------------------------------
# Audio
# --------------------------------------------------------------------------

@probe("audio")
def _probe_audio():
    rows = _csv_rows(
        "Get-CimInstance Win32_SoundDevice | Select-Object Name,Manufacturer,Status")
    devices = []
    for row in rows:
        devices.append({
            "name": (row.get("Name") or "Unknown device").strip(),
            "manufacturer": (row.get("Manufacturer") or "").strip() or "Unknown",
            "status": (row.get("Status") or "Unknown").strip(),
        })
    data = {"devices": devices}
    facts = []
    for d in devices[:6]:
        facts.append(("Device", d["name"]))
        facts.append(("Driver", f"{d['manufacturer']} \u00b7 {d['status']}"))
    if not facts:
        facts.append(("Audio", "No audio devices detected"))
    return {"label": "Audio", "ok": True, "facts": facts, "data": data}


# --------------------------------------------------------------------------
# System / Windows
# --------------------------------------------------------------------------

@probe("system")
def _probe_system():
    profile = _base_profile()
    rows = _csv_rows(
        "Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber")
    caption, version, build = "Windows", "10", profile.get("win_build", 0)
    edition = _reg_value("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
                         "EditionID", None)
    if rows:
        caption = rows[0].get("Caption") or caption
        try:
            build = int(float(rows[0].get("BuildNumber") or build))
        except (TypeError, ValueError):
            pass
        version = rows[0].get("Version") or version
    data = {
        "caption": caption,
        "version": version,
        "build": build,
        "edition": edition or "Unknown",
        "win_version": "11" if build >= 22000 else "10",
        "cpu": profile.get("cpu_name", "Unknown"),
        "gpu": "/".join(profile.get("gpu_names", [])[:2]) or "Unknown",
        "ram_gb": profile.get("ram_gb", 0),
    }
    facts = [
        ("Windows", f"{data['caption']} (build {data['build']})"),
        ("Edition", data["edition"]),
        ("CPU", data["cpu"]),
        ("GPU", data["gpu"]),
        ("RAM", f"{data['ram_gb']} GB"),
    ]
    return {"label": "System", "ok": True, "facts": facts, "data": data}


# --------------------------------------------------------------------------
# Services
# --------------------------------------------------------------------------

@probe("services")
def _probe_services():
    rows = _csv_rows(
        "Get-CimInstance Win32_Service | Select-Object Name,DisplayName,State,StartMode")
    services = {}
    running = auto = 0
    for row in rows:
        name = (row.get("Name") or "").strip()
        state = (row.get("State") or "").strip()
        start = (row.get("StartMode") or "").strip()
        if not name:
            continue
        services[name] = {"state": state, "start": start,
                          "display": (row.get("DisplayName") or name).strip()}
        if state.lower() == "running":
            running += 1
        if start.lower() == "auto":
            auto += 1
    data = {"services": services, "total": len(services), "running": running,
            "auto_start": auto}
    facts = [
        ("Total services", data["total"]),
        ("Running", data["running"]),
        ("Auto start", data["auto_start"]),
    ]
    return {"label": "Services", "ok": True, "facts": facts, "data": data}


# --------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------

@probe("startup")
def _probe_startup():
    rows = _csv_rows(
        "Get-CimInstance Win32_StartupCommand | Select-Object Name,Command,Location")
    items = []
    for row in rows:
        items.append({
            "name": (row.get("Name") or "Unknown").strip(),
            "command": (row.get("Command") or "").strip()[:60],
            "location": (row.get("Location") or "").strip(),
        })
    data = {"items": items, "count": len(items)}
    facts = [("Startup items", data["count"])]
    for i in items[:6]:
        facts.append(("Item", i["name"]))
    if not items:
        facts.append(("Startup", "No startup commands detected"))
    return {"label": "Startup", "ok": True, "facts": facts, "data": data}


# --------------------------------------------------------------------------
# Privacy / Telemetry
# --------------------------------------------------------------------------

@probe("privacy")
def _probe_privacy():
    policies = _reg_value(
        "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\DataCollection",
        "AllowTelemetry", None)
    current = _reg_value(
        "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\DataCollection",
        "AllowTelemetry", None)
    diagtrack = _reg_value(
        "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Diagnostics\DiagTrack",
        "AllowTelemetry", None)
    data = {"telemetry": policies if policies is not None else current,
            "diagtrack": diagtrack}
    level = {0: "Security (0)", 1: "Basic (1)", 2: "Enhanced (2)", 3: "Full (3)"}
    tele = data["telemetry"]
    facts = [
        ("Telemetry level", level.get(tele, f"{tele} (custom)") if tele is not None
         else "Default"),
        ("DiagTrack", "Configured" if diagtrack is not None else "Default"),
    ]
    return {"label": "Privacy / Telemetry", "ok": True, "facts": facts,
            "data": data}


# --------------------------------------------------------------------------
# Thin probes built on the base profile (registry/performance/games/diagnostics)
# --------------------------------------------------------------------------

@probe("registry")
def _probe_registry():
    det = run_probe("system")
    data = dict(det["data"])
    data["registry_tweaks"] = len(_registry_applyable())
    facts = det["facts"] + [("Registry tweaks", data["registry_tweaks"])]
    return {"label": "Registry", "ok": True, "facts": facts, "data": data}


@probe("performance")
def _probe_performance():
    cpu = run_probe("cpu")["data"]
    gpu = run_probe("gpu")["data"]
    data = {"cpu": cpu, "gpu": gpu}
    facts = [
        ("CPU", f"{cpu.get('name')} \u00b7 {cpu.get('cores')}c/{cpu.get('threads')}t"),
        ("GPU", " / ".join(g["name"] for g in gpu.get("gpus", []))),
    ]
    return {"label": "Performance", "ok": True, "facts": facts, "data": data}


@probe("games")
def _probe_games():
    profile = _base_profile()
    dvr = _reg_value("HKCU", r"System\GameConfigStore", "GameDVR_Enabled", None)
    gamebar = _reg_value(
        "HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode", None)
    data = {"dvr_enabled": dvr, "allow_auto_game_mode": gamebar,
            "gpu": profile.get("gpu_names", []),
            "cpu_vendor": profile.get("cpu_vendor", "unknown")}
    facts = []
    if dvr is not None:
        facts.append(("Game DVR", "On" if dvr else "Off"))
    if gamebar is not None:
        facts.append(("Auto Game Mode", "On" if gamebar else "Off"))
    if not facts:
        facts.append(("Gaming", "Game Mode / DVR on stock settings"))
    return {"label": "Gaming", "ok": True, "facts": facts, "data": data}


@probe("fortnite")
def _probe_fortnite():
    import os
    path = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                        r"FortniteGame\Saved\Config\WindowsClient\GameUserSettings.ini")
    data = {"config_present": os.path.exists(path), "config_path": path,
            "profile": _base_profile()}
    facts = [
        ("Config", "Found" if data["config_present"] else "Not found"),
        ("Path", path),
    ]
    return {"label": "Fortnite", "ok": True, "facts": facts, "data": data}


@probe("diagnostics")
def _probe_diagnostics():
    svc = run_probe("services")["data"]
    sysd = run_probe("system")["data"]
    data = {"services": svc, "system": sysd}
    facts = [
        ("OS", f"{sysd.get('caption')} (build {sysd.get('build')})"),
        ("Services running", svc.get("running", 0)),
        ("Disks", "see Storage"),
    ]
    return {"label": "Diagnostics", "ok": True, "facts": facts, "data": data}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

_BASE_PROFILE: dict = {}


def _base_profile() -> dict:
    """Lazily cache the full hardware.detector profile once per process."""
    global _BASE_PROFILE
    if not _BASE_PROFILE:
        try:
            from .detector import detect
            _BASE_PROFILE = detect()
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"base profile failed: {type(exc).__name__}: {exc}")
            _BASE_PROFILE = {}
    return _BASE_PROFILE


def _registry_applyable():
    """Ids of registry-action tweaks (for the registry probe summary)."""
    from database import TWEAKS
    return [t["id"] for t in TWEAKS
            if t.get("actions") and any(
                a and a[0] in ("reg", "regdel", "regall", "regkeydel")
                for a in t["actions"])]


def _pv(value, default=""):
    return value if value is not None else default


# Guard so `import platform` stays used (windows build fallback path).
_PLATFORM = platform.platform() if False else platform.system()
