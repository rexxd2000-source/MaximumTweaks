"""Hardware detection — builds a system profile the recommender can evaluate.

The profile dict keys are matched against each tweak's ``when`` condition:

    gpu            list of vendor ids, e.g. ["nvidia", "amd", "intel"]
    cpu_vendor     "intel" | "amd"
    cpu_cores      physical core count (int)
    ram_gb         total installed RAM in GB (float)
    ram_channels   populated memory slots (int)
    hdd / ssd      boolean — any mechanical / solid-state disk present
    nvme           boolean — any NVMe drive present
    laptop         boolean
    win_version    "10" | "11"
    win_build      OS build number (int)
"""
from __future__ import annotations

import csv
import io
import platform
import re
import subprocess

import psutil

from rexlog import logger


def _ps(script, timeout=40):
    """Run a PowerShell script and return stdout text."""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        return proc.stdout or ""
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"detect: powershell failed ({type(exc).__name__}): {exc}")
        return ""


def _csv_rows(script):
    """Run a PowerShell pipeline and parse its ConvertTo-Csv output."""
    out = _ps(f"$r = @({script}); if ($r) {{ $r | ConvertTo-Csv -NoTypeInformation }}")
    if not out.strip():
        return []
    try:
        reader = csv.DictReader(io.StringIO(out))
        return [row for row in reader if row and any(v for v in row.values())]
    except Exception:  # noqa: BLE001
        return []


def _gpu_vendor(name):
    n = name.lower()
    if any(k in n for k in ("nvidia", "geforce", "quadro", "tesla")):
        return "nvidia"
    if any(k in n for k in ("radeon", "amd", "ati", "firepro", "rx ")):
        return "amd"
    if any(k in n for k in ("intel", "arc", "iris", "uhd", "hd graphics")):
        return "intel"
    return "unknown"


def _chassis_is_laptop():
    rows = _csv_rows(
        "Get-CimInstance Win32_SystemEnclosure | Select-Object -ExpandProperty ChassisTypes")
    portable = {8, 9, 10, 11, 12, 14, 18, 21, 30, 31}
    for row in rows:
        for key, val in row.items():
            try:
                if int(float(val)) in portable:
                    return True
            except (TypeError, ValueError):
                continue
    return psutil.sensors_battery() is not None


def detect() -> dict:
    """Detect the system and return a profile dict."""
    profile = {
        "cpu_name": "Unknown",
        "cpu_vendor": "unknown",
        "cpu_cores": psutil.cpu_count(logical=False) or 0,
        "cpu_threads": psutil.cpu_count(logical=True) or 0,
        "cpu_ghz": 0.0,
        "gpu": [],
        "gpu_names": [],
        "ram_gb": round(psutil.virtual_memory().total / (1024 ** 3), 1),
        "ram_channels": 0,
        "ram_mtps": 0,
        "ssd": False,
        "hdd": False,
        "nvme": False,
        "laptop": False,
        "win_version": "10",
        "win_build": 0,
        "monitor_refresh": 0,
        "adapter": {"name": "-", "type": "unknown", "speed": ""},
    }
    _detect_cpu(profile)
    _detect_gpu(profile)
    _detect_memory(profile)
    _detect_disks(profile)
    _detect_os(profile)
    _detect_display(profile)
    _detect_network(profile)
    profile["laptop"] = _chassis_is_laptop()
    profile["ram_channels"] = max(1, profile["ram_channels"])
    logger.info("Detection complete: " + ", ".join(
        f"{k}={v}" for k, v in profile.items() if isinstance(v, (str, int, float, bool))))
    return profile


def _detect_cpu(p):
    rows = _csv_rows(
        "Get-CimInstance Win32_Processor | Select-Object Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed")
    if rows:
        row = rows[0]
        p["cpu_name"] = (row.get("Name") or p["cpu_name"]).strip()
        mfr = (row.get("Manufacturer") or "").lower()
        p["cpu_vendor"] = "intel" if "intel" in mfr else "amd" if "amd" in mfr else p["cpu_vendor"]
        try:
            p["cpu_cores"] = int(float(row.get("NumberOfCores") or p["cpu_cores"]))
        except (TypeError, ValueError):
            pass
        try:
            p["cpu_threads"] = int(float(row.get("NumberOfLogicalProcessors") or p["cpu_threads"]))
        except (TypeError, ValueError):
            pass
        try:
            p["cpu_ghz"] = round(int(float(row.get("MaxClockSpeed") or 0)) / 1000.0, 2)
        except (TypeError, ValueError):
            pass


def _detect_gpu(p):
    rows = _csv_rows(
        "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion")
    for row in rows:
        name = (row.get("Name") or "Unknown Video Controller").strip()
        vendor = _gpu_vendor(name)
        p["gpu_names"].append(name)
        if vendor not in p["gpu"]:
            p["gpu"].append(vendor)
    if not p["gpu"]:
        p["gpu"] = ["unknown"]


def _detect_memory(p):
    rows = _csv_rows(
        "Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed")
    if rows:
        p["ram_channels"] = len(rows)
        speeds = []
        for row in rows:
            try:
                speeds.append(int(float(row.get("Speed") or 0)))
            except (TypeError, ValueError):
                pass
        if speeds:
            p["ram_mtps"] = max(speeds)


def _detect_disks(p):
    rows = _csv_rows(
        "Get-PhysicalDisk | Select-Object FriendlyName,MediaType,BusType,Size")
    for row in rows:
        media = (row.get("MediaType") or "").lower()
        bus = (row.get("BusType") or "").lower()
        if media == "hdd" or "hdd" in media:
            p["hdd"] = True
        elif media == "ssd" or "ssd" in media:
            p["ssd"] = True
        if bus == "nvme":
            p["nvme"] = True


def _detect_os(p):
    rows = _csv_rows(
        "Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber")
    if rows:
        row = rows[0]
        caption = row.get("Caption") or ""
        try:
            p["win_build"] = int(float(row.get("BuildNumber") or 0))
        except (TypeError, ValueError):
            pass
        p["win_version"] = "11" if "11" in caption or p["win_build"] >= 22000 else "10"
    elif "windows" in platform.platform().lower():
        ver, build, _ = platform.win32_ver()
        p["win_version"] = "11" if build >= 22000 else "10"
        p["win_build"] = build


def _detect_display(p):
    rows = _csv_rows(
        "Get-CimInstance Win32_VideoController | Select-Object Name,CurrentRefreshRate")
    rates = []
    for row in rows:
        try:
            rates.append(int(float(row.get("CurrentRefreshRate") or 0)))
        except (TypeError, ValueError):
            continue
    if rates:
        p["monitor_refresh"] = max(rates)


def _detect_network(p):
    addrs = psutil.net_if_stats()
    for name, stats in addrs.items():
        if stats.isup and stats.speed and stats.speed > 0 and not name.lower().startswith("loopback"):
            kind = "wifi" if any(k in name.lower() for k in ("wi-fi", "wlan", "wireless")) else "ethernet"
            if kind == "wifi" or p["adapter"]["type"] == "unknown":
                p["adapter"] = {"name": name, "type": kind, "speed": f"{stats.speed} Mbps"}
    rows = _csv_rows(
        "Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | Select-Object Name,InterfaceDescription,LinkSpeed")
    if rows:
        for row in rows[:1]:
            p["adapter"]["name"] = row.get("Name") or p["adapter"]["name"]
            desc = (row.get("InterfaceDescription") or "").lower()
            if "wireless" in desc or "wi-fi" in desc:
                p["adapter"]["type"] = "wifi"
            elif p["adapter"]["type"] == "unknown":
                p["adapter"]["type"] = "ethernet"
            p["adapter"]["speed"] = row.get("LinkSpeed") or p["adapter"]["speed"]
