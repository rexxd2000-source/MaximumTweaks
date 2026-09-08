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
    if any(k in n for k in ("intel arc", "arc a", "arc b")):
        return "intel"
    if any(k in n for k in ("intel", "iris", "uhd", "hd graphics")):
        return "intel"
    return "unknown"


def _gpu_is_integrated(name):
    n = name.lower()
    return any(k in n for k in (
        "iris", "uhd", "hd graphics", "igp", "integrated",
        # Intel iGPU families (non-Arc)
        "iris xe", "iris plus", "iris xeon",
    ))


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
        "gpu_vendors": [],
        "gpu_dedicated": [],
        "gpu_integrated": [],
        "gpu_vram_gb": 0,
        "gpu_driver_version": "",
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
        "has_audio_realtek": False,
        "has_audio_usb": False,
        "has_audio_bluetooth": False,
        "has_audio_hdmi": False,
        "audio_devices": [],
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
    _detect_audio(profile)
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


def _nvidia_smi_vram() -> list[dict]:
    """Query nvidia-smi for accurate NVIDIA GPU VRAM and driver info."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=name,memory.total,memory.used,memory.free,"
             "driver_version,pci.bus_id,gpu_id",
             "--format=csv,noheader,nounits"],
            text=True, timeout=10,
            creationflags=0x08000000, stderr=subprocess.DEVNULL,
        )
        gpus = []
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                try:
                    dedicated_mb = int(float(parts[1]))
                except (ValueError, IndexError):
                    dedicated_mb = 0
                gpus.append({
                    "name": parts[0],
                    "dedicated_mb": dedicated_mb,
                    "driver_version": parts[4] if len(parts) > 4 else "",
                    "pci_bus": parts[5] if len(parts) > 5 else "",
                })
        return gpus
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return []


def _registry_gpu_vram() -> dict[str, int]:
    """Read 64-bit VRAM from registry (HardwareInformation.qwMemorySize).

    The WMI AdapterRAM field is a 32-bit value that clamps at ~4GB.
    The registry qwMemorySize is the accurate 64-bit value.
    """
    import re as _re
    result = {}
    base = (
        r"SYSTEM\CurrentControlSet\Control\Class"
        r"\{4d36e968-e325-11ce-bfc1-08002be10318}"
    )
    try:
        import winreg
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
        for i in range(winreg.QueryInfoKey(root)[0]):
            sub = winreg.EnumKey(root, i)
            if not _re.fullmatch(r"\d+", sub):
                continue
            try:
                with winreg.OpenKey(root, sub) as k:
                    def _qv(name):
                        try:
                            v, _t = winreg.QueryValueEx(k, name)
                            return v
                        except OSError:
                            return None
                    desc = str(_qv("DriverDesc") or "").strip()
                    vram = _qv("HardwareInformation.qwMemorySize")
                    if desc:
                        result[desc.lower()] = int(vram) if vram else 0
            except OSError:
                continue
    except (OSError, ImportError):
        pass
    return result


def _detect_gpu(p):
    """Detect GPU with reliable VRAM detection.

    Uses three methods and cross-checks:
    1. nvidia-smi (most accurate for NVIDIA)
    2. Registry qwMemorySize (64-bit, accurate for all vendors)
    3. WMI AdapterRAM (fallback only, broken for >4GB)

    Reports dedicated VRAM separately from shared GPU memory.
    """
    rows = _csv_rows(
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,DriverVersion,AdapterRAM,DriverDate,"
        "PNPDeviceID,VideoProcessor,CurrentHorizontalResolution,"
        "CurrentVerticalResolution,CurrentRefreshRate")
    nvidia_info = _nvidia_smi_vram()
    reg_vram = _registry_gpu_vram()

    for row in rows:
        name = (row.get("Name") or "Unknown Video Controller").strip()
        if not name or "microsoft" in name.lower():
            continue
        vendor = _gpu_vendor(name)
        integrated = _gpu_is_integrated(name)
        p["gpu_names"].append(name)
        if vendor not in p["gpu"]:
            p["gpu"].append(vendor)
        if vendor not in p["gpu_vendors"]:
            p["gpu_vendors"].append(vendor)
        if integrated:
            p["gpu_integrated"].append(name)
        else:
            p["gpu_dedicated"].append(name)

        dedicated_mb = 0
        detection_method = "none"

        # Method 1: nvidia-smi (gold standard for NVIDIA)
        if vendor == "nvidia":
            for ngpu in nvidia_info:
                if (ngpu["name"].lower() in name.lower()
                        or name.lower() in ngpu["name"].lower()):
                    dedicated_mb = ngpu["dedicated_mb"]
                    detection_method = "nvidia-smi"
                    if ngpu.get("driver_version"):
                        p["gpu_driver_version"] = ngpu["driver_version"]
                    break

        # Method 2: Registry qwMemorySize (64-bit, all vendors)
        if dedicated_mb <= 0:
            reg_vram_bytes = reg_vram.get(name.lower(), 0)
            if reg_vram_bytes > 0:
                dedicated_mb = int(reg_vram_bytes / (1024 * 1024))
                detection_method = "registry"

        # Method 3: WMI AdapterRAM (fallback, may be wrong for >4GB)
        if dedicated_mb <= 0:
            try:
                wmi_vram = int(float(row.get("AdapterRAM") or 0) / (1024 * 1024))
                if wmi_vram > 0:
                    dedicated_mb = wmi_vram
                    detection_method = "wmi"
            except (TypeError, ValueError):
                pass

        dedicated_gb = round(dedicated_mb / 1024, 1)
        p["gpu_vram_gb"] = max(p["gpu_vram_gb"], dedicated_gb)

        # Flag potential detection issues
        if detection_method == "wmi" and 0 < dedicated_gb <= 4 and not integrated:
            p.setdefault("gpu_vram_warnings", []).append(
                f"{name}: VRAM via WMI ({dedicated_gb}GB) — "
                "may be inaccurate for >4GB GPUs")
        elif not integrated and dedicated_gb == 0:
            p.setdefault("gpu_vram_warnings", []).append(
                f"{name}: VRAM could not be detected")

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


def _detect_audio(p):
    """Detect audio hardware: Realtek, USB, Bluetooth, HDMI/DP devices."""
    rows = _csv_rows(
        "Get-CimInstance Win32_SoundDevice | "
        "Select-Object Name,Manufacturer,Status,PNPDeviceID")
    for row in rows:
        name = (row.get("Name") or "").strip()
        mfr = (row.get("Manufacturer") or "").strip()
        pnp = (row.get("PNPDeviceID") or "").strip().lower()
        dev = {"name": name, "manufacturer": mfr,
               "status": (row.get("Status") or "Unknown").strip()}
        p["audio_devices"].append(dev)
        nl = name.lower() + " " + mfr.lower()
        if any(k in nl for k in ("realtek", "alc", "conexant")):
            p["has_audio_realtek"] = True
        if pnp.startswith("usb"):
            p["has_audio_usb"] = True
        if any(k in nl for k in ("bluetooth", "bt", "a2dp")) or "bth" in pnp:
            p["has_audio_bluetooth"] = True
        if any(k in nl for k in ("hdmi", "displayport", "nvidia high definition",
                                  "amd high definition", "intel display")):
            p["has_audio_hdmi"] = True
    # Fallback: check for Bluetooth audio services
    if not p["has_audio_bluetooth"]:
        bt_rows = _csv_rows(
            "Get-Service -Name 'BthHFEnum','BthA2dp' -ErrorAction SilentlyContinue | "
            "Select-Object Name,Status")
        for bt in bt_rows:
            if (bt.get("Status") or "").lower() == "running":
                p["has_audio_bluetooth"] = True
                break
