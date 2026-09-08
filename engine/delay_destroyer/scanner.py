"""Deep system scanner — comprehensive diagnostic data collection.

This scanner investigates the PC from every angle that can cause delay,
sluggishness, or poor responsiveness. It builds a complete picture before
any optimization is attempted.

Three-tier GPU VRAM detection avoids the 32-bit WMI AdapterRAM clamp.
DPC/ISR latency, input delay, display/DWM, event viewer, driver errors,
and background task analysis are all investigated.
"""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from rexlog import logger


def _ps(script: str, timeout: int = 30) -> str:
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000,
        )
        return proc.stdout or ""
    except Exception:
        return ""


def _csv_rows(script: str):
    out = _ps(
        "$r = @(" + script + "); "
        "if ($r) { $r | ConvertTo-Csv -NoTypeInformation }"
    )
    if not out.strip():
        return []
    try:
        import csv, io
        return [row for row in csv.DictReader(io.StringIO(out))
                if row and any(v for v in row.values())]
    except Exception:
        return []


def _reg_query(path: str, name: str = "") -> str | None:
    try:
        cmd = f'reg query "{path}"'
        if name:
            cmd += f' /v "{name}"'
        out = subprocess.check_output(
            cmd, shell=True, text=True, timeout=10,
            creationflags=0x08000000, stderr=subprocess.DEVNULL,
        )
        if name:
            for line in out.splitlines():
                if name.lower() in line.lower():
                    parts = line.split()
                    return parts[-1] if len(parts) >= 3 else None
        return out.strip() or None
    except Exception:
        return None


def _reg_value(hive: str, subkey: str, name: str, default=None):
    import winreg
    try:
        root = (winreg.HKEY_LOCAL_MACHINE if hive == "HKLM"
                else winreg.HKEY_CURRENT_USER if hive == "HKCU"
                else winreg.HKEY_USERS)
        with winreg.OpenKey(root, subkey) as key:
            value, _kind = winreg.QueryValueEx(key, name)
            return value
    except OSError:
        return default


def _svc_state(name: str) -> str | None:
    try:
        out = subprocess.check_output(
            f'sc qc "{name}"', shell=True, text=True, timeout=10,
            creationflags=0x08000000, stderr=subprocess.DEVNULL,
        )
        m = re.search(r"START_TYPE\s+:\s+\w+\s+(\w+)", out)
        return m.group(1).lower() if m else None
    except Exception:
        return None


def _svc_running(name: str) -> bool | None:
    try:
        out = subprocess.check_output(
            f'sc query "{name}"', shell=True, text=True, timeout=10,
            creationflags=0x08000000, stderr=subprocess.DEVNULL,
        )
        return "RUNNING" in out.upper()
    except Exception:
        return None


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _powercfg_query(subgroup: str, setting: str) -> str | None:
    out = _ps(f"powercfg /query SCHEME_CURRENT {subgroup} {setting}")
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line and not line.startswith("Power") and not line.startswith("Index"):
            return line
    return None


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CPUInfo:
    name: str = "Unknown"
    vendor: str = "unknown"
    cores: int = 0
    threads: int = 0
    ghz: float = 0.0
    family: str = ""
    model: str = ""
    stepping: str = ""
    current_power_plan: str = ""
    power_plan_name: str = "Unknown"
    power_plan_guid: str = ""
    boost_mode: int = -1
    parking_enabled: bool = False
    cstate_enabled: bool = True
    idle_threshold: int = -1
    temp_celsius: float = -1.0
    usage_percent: float = 0.0
    context_switches_per_sec: float = 0.0
    interrupts_per_sec: float = 0.0
    mmcss_running: bool = False
    priority_boost_enabled: bool = True
    smt_enabled: bool = False
    hybrid_core: bool = False


@dataclass
class GPUInfo:
    names: list[str] = field(default_factory=list)
    vendors: list[str] = field(default_factory=list)
    dedicated: list[str] = field(default_factory=list)
    integrated: list[str] = field(default_factory=list)
    vram_gb: float = 0.0
    dedicated_vram_gb: float = 0.0
    shared_vram_gb: float = 0.0
    total_gpu_memory_gb: float = 0.0
    vram_detection_method: str = "none"
    driver_version: str = ""
    driver_date: str = ""
    vram_warnings: list[str] = field(default_factory=list)
    gfe_installed: bool = False
    gfe_overlay_enabled: bool = False
    reflex_mode: str = ""
    amd_overlay: bool = False
    hardware_gpu_scheduling: bool = False
    hardware_accelerated_gpu_scheduling: bool = False
    mpo_disabled: bool = False
    driver_errors: list[str] = field(default_factory=list)
    tdr_level: int = 3
    tdr_delay: int = 2


@dataclass
class RAMInfo:
    total_gb: float = 0.0
    channels: int = 0
    speed_mtps: int = 0
    used_gb: float = 0.0
    available_gb: float = 0.0
    pressure: float = 0.0
    pagefile_gb: float = 0.0
    pagefile_auto: bool = True
    memory_compression: bool = False
    superfetch_enabled: bool = True
    large_system_cache: bool = False
    dpc_latency_us: float = 0.0
    isr_latency_us: float = 0.0
    dpc_top_offenders: list[dict] = field(default_factory=list)
    isr_top_offenders: list[dict] = field(default_factory=list)


@dataclass
class StorageInfo:
    has_ssd: bool = False
    has_hdd: bool = False
    has_nvme: bool = False
    disk_read_mb_s: float = 0.0
    disk_write_mb_s: float = 0.0
    avg_disk_queue_length: float = 0.0
    fast_startup_enabled: bool = False
    defrag_enabled: bool = True
    trim_enabled: bool = True


@dataclass
class NetworkInfo:
    adapter_type: str = "unknown"
    adapter_name: str = ""
    speed: str = ""
    nagle_disabled: bool = False
    auto_tuning: str = ""
    rss_enabled: bool = False
    ecn_enabled: bool = False


@dataclass
class InputInfo:
    hid_devices: list[dict] = field(default_factory=list)
    hid_device_count: int = 0
    usb_controllers: int = 0
    usb_hubs: int = 0
    hid_driver_issues: list[str] = field(default_factory=list)
    usb_driver_issues: list[str] = field(default_factory=list)
    bluetooth_hid: bool = False
    hid_power_state_issues: list[str] = field(default_factory=list)


@dataclass
class DisplayInfo:
    monitors: list[dict] = field(default_factory=list)
    monitor_count: int = 0
    multi_monitor: bool = False
    primary_resolution: str = ""
    refresh_rates: list[str] = field(default_factory=list)
    dwm_enabled: bool = True
    dwm_refresh_rate: int = 0
    hardware_cursor: bool = True
    display_driver_errors: list[str] = field(default_factory=list)
    display_drivers: list[dict] = field(default_factory=list)
    graphics_driver_version: str = ""
    graphics_driver_date: str = ""


@dataclass
class OSInfo:
    version: str = ""
    build: int = 0
    edition: str = ""
    uptime_hours: float = 0.0
    game_dvr_enabled: bool = False
    game_bar_enabled: bool = False
    game_mode_enabled: bool = False
    explorer_crashes: int = 0
    critical_events: int = 0
    error_events: int = 0
    recent_crashes: list[dict] = field(default_factory=list)
    device_errors: list[dict] = field(default_factory=list)
    last_windows_update: str = ""
    pending_reboot: bool = False
    scheduled_heavy_tasks: list[dict] = field(default_factory=list)
    power_tips_enabled: bool = False


@dataclass
class StartupInfo:
    entries: list[dict] = field(default_factory=list)
    count: int = 0
    high_impact: list[str] = field(default_factory=list)
    registry_run_count: int = 0
    startup_folder_count: int = 0


@dataclass
class ServiceInfo:
    total_running: int = 0
    unnecessary_running: list[str] = field(default_factory=list)
    disabled_count: int = 0
    high_cpu_services: list[dict] = field(default_factory=list)
    high_memory_services: list[dict] = field(default_factory=list)


@dataclass
class ProcessInfo:
    count: int = 0
    high_cpu: list[dict] = field(default_factory=list)
    high_memory: list[dict] = field(default_factory=list)
    background_heavy: list[dict] = field(default_factory=list)
    gpu_background: list[dict] = field(default_factory=list)


@dataclass
class AudioInfo:
    devices: list[dict] = field(default_factory=list)
    active_device: str = ""
    driver_version: str = ""
    audio_enhancements: bool = True
    exclusive_mode: bool = False
    spatial_sound: str = ""
    audio_issues: list[str] = field(default_factory=list)


@dataclass
class ScheduledTaskInfo:
    heavy_tasks: list[dict] = field(default_factory=list)
    total_tasks: int = 0
    enabled_tasks: int = 0
    tasks_at_logon: list[str] = field(default_factory=list)


@dataclass
class EventsInfo:
    critical_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    recent_errors: list[dict] = field(default_factory=list)
    bsod_count: int = 0
    driver_crashes: list[dict] = field(default_factory=list)
    app_crashes: list[dict] = field(default_factory=list)


@dataclass
class DriverInfo:
    usb_controllers: int = 0
    hid_devices: int = 0
    problematic_drivers: list[dict] = field(default_factory=list)
    audio_devices: list[dict] = field(default_factory=list)
    audio_driver_issues: list[str] = field(default_factory=list)
    display_drivers: list[dict] = field(default_factory=list)
    display_driver_issues: list[str] = field(default_factory=list)
    dpc_offenders: list[dict] = field(default_factory=list)
    isr_offenders: list[dict] = field(default_factory=list)
    driver_resets: int = 0


@dataclass
class ScanResult:
    cpu: CPUInfo = field(default_factory=CPUInfo)
    gpu: GPUInfo = field(default_factory=GPUInfo)
    ram: RAMInfo = field(default_factory=RAMInfo)
    storage: StorageInfo = field(default_factory=StorageInfo)
    network: NetworkInfo = field(default_factory=NetworkInfo)
    input: InputInfo = field(default_factory=InputInfo)
    display: DisplayInfo = field(default_factory=DisplayInfo)
    os: OSInfo = field(default_factory=OSInfo)
    startup: StartupInfo = field(default_factory=StartupInfo)
    services: ServiceInfo = field(default_factory=ServiceInfo)
    processes: ProcessInfo = field(default_factory=ProcessInfo)
    audio: AudioInfo = field(default_factory=AudioInfo)
    scheduled_tasks: ScheduledTaskInfo = field(default_factory=ScheduledTaskInfo)
    events: EventsInfo = field(default_factory=EventsInfo)
    drivers: DriverInfo = field(default_factory=DriverInfo)
    is_laptop: bool = False
    is_admin: bool = False
    scan_time: float = 0.0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# GPU VRAM — three-tier detection (nvidia-smi → registry → WMI)
# ---------------------------------------------------------------------------

def _gpu_vram_registry() -> dict[str, int]:
    """Read 64-bit dedicated VRAM from the registry for all GPU vendors.

    Returns dict mapping driver description (lowercase) to VRAM in bytes.
    """
    import winreg
    base = (r"SYSTEM\CurrentControlSet\Control\Class"
            r"\{4d36e968-e325-11ce-bfc1-08002be10318}")
    result = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                    i += 1
                    if not sub.isdigit():
                        continue
                    subpath = f"{base}\\{sub}"
                    try:
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                            subpath) as key:
                            desc, _ = winreg.QueryValueEx(key, "DriverDesc")
                            vram, _ = winreg.QueryValueEx(
                                key, "HardwareInformation.qwMemorySize")
                            if isinstance(vram, int) and vram > 0:
                                result[str(desc).lower()] = vram
                    except OSError:
                        continue
                except OSError:
                    break
    except OSError:
        pass
    return result


def _gpu_vram_nvidia() -> list[dict]:
    """Query NVIDIA GPUs via nvidia-smi. Returns list of dicts."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=name,memory.total,memory.used,memory.free,"
             "driver_version,pci.bus_id",
             "--format=csv,noheader,nounits"],
            timeout=10, creationflags=0x08000000,
            stderr=subprocess.DEVNULL,
        )
        gpus = []
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 6:
                gpus.append({
                    "name": parts[0],
                    "total_mb": float(parts[1]),
                    "used_mb": float(parts[2]),
                    "free_mb": float(parts[3]),
                    "driver_version": parts[4],
                    "pci_bus": parts[5],
                })
        return gpus
    except Exception:
        return []


def _gpu_vendor_from_name(name: str) -> str:
    nl = name.lower()
    if any(k in nl for k in ("nvidia", "geforce", "rtx", "gtx", "quadro")):
        return "nvidia"
    if any(k in nl for k in ("amd", "radeon", "navi")):
        return "amd"
    if any(k in nl for k in ("intel", "iris", "uhd", "hd graphics")):
        return "intel"
    return "unknown"


def _gpu_is_integrated(name: str) -> bool:
    nl = name.lower()
    return any(k in nl for k in (
        "iris", "uhd", "hd graphics", "igp", "integrated",
        "iris xe", "iris plus", "radeon graphics",
    ))


def _detect_gpu_three_tier() -> tuple[GPUInfo, list[str]]:
    """Three-tier GPU VRAM detection: nvidia-smi → registry → WMI.

    Returns (GPUInfo, warnings).
    """
    g = GPUInfo()
    warnings = []

    # Tier 1: nvidia-smi
    nvidia_gpus = _gpu_vram_nvidia()
    for ng in nvidia_gpus:
        name = ng["name"]
        g.names.append(name)
        g.vendors.append("nvidia")
        g.dedicated.append(name)
        g.driver_version = ng.get("driver_version", "")
        vram_gb = ng["total_mb"] / 1024.0
        g.vram_gb = max(g.vram_gb, vram_gb)
        g.dedicated_vram_gb = max(g.dedicated_vram_gb, vram_gb)
        g.vram_detection_method = "nvidia-smi"

    # Tier 2: Registry (all vendors, 64-bit, most accurate fallback)
    reg_vram = _gpu_vram_registry()

    # Tier 3: WMI
    rows = _csv_rows(
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,DriverVersion,DriverDate,PNPDeviceID,"
        "AdapterRAM,AdapterDACType,VideoProcessor")
    for row in rows:
        name = (row.get("Name") or "").strip()
        if not name:
            continue

        vendor = _gpu_vendor_from_name(name)
        integrated = _gpu_is_integrated(name)

        # Skip if already detected via nvidia-smi
        already = any(name.lower() in n.lower() or n.lower() in name.lower()
                      for n in g.names)
        if already:
            idx = next((i for i, n in enumerate(g.names)
                        if name.lower() in n.lower() or n.lower() in name.lower()),
                       -1)
            if idx >= 0 and not g.driver_version:
                g.driver_version = (row.get("DriverVersion") or "").strip()
            continue

        g.names.append(name)
        g.vendors.append(vendor)
        if integrated:
            g.integrated.append(name)
        else:
            g.dedicated.append(name)

        if vendor == "nvidia":
            g.vendors[-1] = "nvidia"

        # Try registry VRAM (64-bit, accurate)
        vram_bytes = 0
        name_lower = name.lower()
        for reg_desc, reg_bytes in reg_vram.items():
            if name_lower in reg_desc or reg_desc in name_lower:
                vram_bytes = max(vram_bytes, reg_bytes)
                break

        # PNP device ID matching as secondary registry lookup
        if vram_bytes <= 0:
            pnp = (row.get("PNPDeviceID") or "").strip()
            if pnp:
                for reg_desc, reg_bytes in reg_vram.items():
                    pnp_prefix = pnp.split("\\")[-1] if "\\" in pnp else pnp
                    if pnp_prefix and pnp_prefix.lower() in reg_desc:
                        vram_bytes = max(vram_bytes, reg_bytes)
                        break

        if vram_bytes > 0:
            dedicated_gb = vram_bytes / (1024 ** 3)
            g.vram_gb = max(g.vram_gb, dedicated_gb)
            if not integrated:
                g.dedicated_vram_gb = max(g.dedicated_vram_gb, dedicated_gb)
            g.vram_detection_method = "registry"
        else:
            # Tier 3: WMI AdapterRAM (32-bit, clamps at ~4GB)
            try:
                adapter_ram = int(row.get("AdapterRAM", 0) or 0)
            except (ValueError, TypeError):
                adapter_ram = 0
            if adapter_ram > 0:
                dedicated_gb = adapter_ram / (1024 ** 3)
                if not integrated:
                    g.vram_gb = max(g.vram_gb, dedicated_gb)
                    g.dedicated_vram_gb = max(g.dedicated_vram_gb, dedicated_gb)
                g.vram_detection_method = "wmi"
                if 0 < dedicated_gb <= 4 and not integrated:
                    warnings.append(
                        f"{name}: VRAM via WMI ({dedicated_gb:.1f}GB) — "
                        "32-bit field may be inaccurate for GPUs >4GB. "
                        "Registry fallback was unavailable.")
            else:
                if not integrated:
                    warnings.append(
                        f"{name}: VRAM could not be detected "
                        "(nvidia-smi, registry, and WMI all failed).")

        if not g.driver_version:
            g.driver_version = (row.get("DriverVersion") or "").strip()
        g.driver_date = (row.get("DriverDate") or "").strip()

        # Shared memory estimate for integrated GPUs
        if integrated and vram_bytes <= 0:
            try:
                adapter_ram = int(row.get("AdapterRAM", 0) or 0)
            except (ValueError, TypeError):
                adapter_ram = 0
            if adapter_ram > 0:
                g.shared_vram_gb = max(g.shared_vram_gb,
                                       adapter_ram / (1024 ** 3))

    g.total_gpu_memory_gb = g.dedicated_vram_gb + g.shared_vram_gb
    g.vram_warnings = warnings
    return g, warnings


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

class SystemScanner:
    """Comprehensive system scanner for Delay Destroyer."""

    def __init__(self):
        self._progress_cb = None

    def set_progress_callback(self, cb):
        self._progress_cb = cb

    def _emit(self, phase: str, detail: str, pct: int = 0):
        if self._progress_cb:
            self._progress_cb(phase, detail, pct)

    def scan(self) -> ScanResult:
        t0 = time.monotonic()
        r = ScanResult()
        r.is_admin = _is_admin()
        r.is_laptop = self._detect_laptop()

        scanners = [
            ("cpu", "CPU", self._scan_cpu),
            ("gpu", "GPU", self._scan_gpu),
            ("ram", "RAM", self._scan_ram),
            ("storage", "STORAGE", self._scan_storage),
            ("network", "NETWORK", self._scan_network),
            ("input", "INPUT", self._scan_input),
            ("display", "DISPLAY", self._scan_display),
            ("os", "WINDOWS", self._scan_os),
            ("startup", "STARTUP", self._scan_startup),
            ("services", "SERVICES", self._scan_services),
            ("processes", "PROCESSES", self._scan_processes),
            ("drivers", "DRIVERS", self._scan_drivers),
        ]

        for i, (phase, label, fn) in enumerate(scanners):
            pct = 5 + int((i / len(scanners)) * 85)
            self._emit(phase, f"Scanning {label}...", pct)
            try:
                fn(r)
            except Exception as exc:
                r.errors.append(f"{label}: {type(exc).__name__}: {exc}")
                logger.warn(f"DD scanner {label} failed: {exc}")

        # DPC/ISR latency (cross-cutting, needs all driver info first)
        self._emit("dpc", "Measuring DPC/ISR latency...", 90)
        self._scan_dpc_isr(r)

        r.scan_time = time.monotonic() - t0
        self._emit("done", f"Scan complete in {r.scan_time:.1f}s", 95)
        return r

    def _detect_laptop(self) -> bool:
        try:
            out = _ps(
                "Get-CimInstance Win32_ComputerSystem | "
                "Select-Object -ExpandProperty SystemType")
            return "laptop" in (out or "").lower()
        except Exception:
            return False

    # ---- CPU ----
    def _scan_cpu(self, r: ScanResult):
        c = r.cpu
        sources = []

        # ── Source 1: wmic (most reliable) ──
        try:
            out = subprocess.check_output(
                ["wmic", "cpu", "get",
                 "Name,Manufacturer,NumberOfCores,"
                 "NumberOfLogicalProcessors,MaxClockSpeed,"
                 "CurrentClockSpeed,Family,L2CacheSize,L3CacheSize",
                 "/format:list"],
                timeout=10, creationflags=0x08000000,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="ignore")
            props = {}
            for line in out.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()
            if props.get("Name"):
                sources.append(("wmic", props))
        except Exception:
            pass

        # ── Source 2: PowerShell Get-CimInstance ──
        if not sources:
            try:
                rows = _csv_rows(
                    "Get-CimInstance Win32_Processor | "
                    "Select-Object Name,Manufacturer,NumberOfCores,"
                    "NumberOfLogicalProcessors,MaxClockSpeed,"
                    "CurrentClockSpeed,Family,L2CacheSize,L3CacheSize")
                if rows:
                    row = rows[0]
                    props = {k: (v or "").strip() for k, v in row.items() if v}
                    if props.get("Name"):
                        sources.append(("cim", props))
            except Exception:
                pass

        # ── Source 3: Registry fallback for vendor ──
        if not sources:
            try:
                vendor = _reg_value(
                    "HKLM",
                    r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                    "VendorIdentifier", "")
                proc_name = _reg_value(
                    "HKLM",
                    r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                    "ProcessorNameString", "")
                if proc_name or vendor:
                    props = {
                        "Name": proc_name or "Unknown",
                        "Manufacturer": vendor or "Unknown",
                    }
                    sources.append(("registry", props))
            except Exception:
                pass

        # ── Parse best available source ──
        if sources:
            src_name, props = sources[0]

            # Name
            c.name = (props.get("Name") or "Unknown").strip()
            # Clean up wmic name (often has extra whitespace)
            c.name = " ".join(c.name.split())

            # Manufacturer / Vendor
            mfr = (props.get("Manufacturer") or "").lower()
            if "intel" in mfr or "genuineintel" in mfr:
                c.vendor = "intel"
            elif "amd" in mfr or "authenticamd" in mfr:
                c.vendor = "amd"
            else:
                # Try to detect from CPU name
                name_lower = c.name.lower()
                if any(k in name_lower for k in ("intel", "core", "xeon", "pentium", "celeron")):
                    c.vendor = "intel"
                elif any(k in name_lower for k in ("amd", "ryzen", "epyc", "threadripper", "athlon")):
                    c.vendor = "amd"
                else:
                    c.vendor = "unknown"

            # Cores and threads
            try:
                c.cores = int(props.get("NumberOfCores", 0) or 0)
            except (ValueError, TypeError):
                c.cores = 0
            try:
                c.threads = int(props.get("NumberOfLogicalProcessors", 0) or 0)
            except (ValueError, TypeError):
                c.threads = 0

            # If WMI returned 0 for cores, try psutil
            if c.cores <= 0:
                c.cores = psutil.cpu_count(logical=False) or 0
            if c.threads <= 0:
                c.threads = psutil.cpu_count(logical=True) or 0

            # Clock speed
            try:
                max_ghz = int(props.get("MaxClockSpeed", 0) or 0)
                c.ghz = round(max_ghz / 1000.0, 1) if max_ghz > 0 else 0.0
            except (ValueError, TypeError):
                c.ghz = 0.0

            # Architecture detection
            c.family = str(props.get("Family", "") or "")
            c.model = c.name

            # SMT / Hyper-Threading detection
            c.smt_enabled = (c.threads > c.cores and c.cores > 0)

            # Hybrid-core detection (Intel 12th gen+)
            c.hybrid_core = False
            if c.vendor == "intel":
                hybrid_models = (
                    "12900", "12700", "12600",
                    "13900", "13700", "13600",
                    "14900", "14700", "14600",
                    "24900", "26900",  # future
                )
                c.hybrid_core = any(m in c.name for m in hybrid_models)

        # ── Real-time data (always from psutil, these are reliable) ──
        c.usage_percent = psutil.cpu_percent(interval=0.5)

        perf = psutil.cpu_stats()
        c.context_switches_per_sec = perf.ctx_switches
        c.interrupts_per_sec = perf.interrupts

        # ── Power plan ──
        try:
            guid = _ps(
                "powercfg /getactivescheme | "
                "ForEach-Object { ($_ -split '\\s+')[3] }").strip()
            c.power_plan_guid = guid
        except Exception:
            c.power_plan_guid = ""

        # Detect power plan name
        ps_guids = {
            "a1841308-3544-42bc-8357-1578ed00ccd0": "Power Saver",
            "381b4222-f694-41f0-9685-ff5bb260df2e": "Balanced",
            "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c": "High Performance",
            "e9a42b02-d5df-448d-aa00-03f14749eb61": "Ultimate Performance",
        }
        c.power_plan_name = ps_guids.get(
            c.power_plan_guid.lower(), "Unknown")

        # ── Boost mode ──
        try:
            boost_out = _ps(
                "powercfg /query SCHEME_CURRENT SUB_PROCESSOR PERFBOOSTMODE")
            for line in boost_out.splitlines():
                ll = line.strip().lower()
                if "current" in ll:
                    if "0x00000000" in ll:
                        c.boost_mode = 0  # Disabled
                    elif "0x00000001" in ll:
                        c.boost_mode = 1  # Enabled
                    elif "0x00000002" in ll:
                        c.boost_mode = 2  # Aggressive
                    elif "0x00000003" in ll:
                        c.boost_mode = 3  # Efficient enabled
                    elif "0x00000004" in ll:
                        c.boost_mode = 4  # Efficient aggressive
                    break
        except Exception:
            c.boost_mode = -1

        # ── Core parking ──
        try:
            park_out = _ps(
                "powercfg /query SCHEME_CURRENT SUB_PROCESSOR CPMINCORES")
            for line in park_out.splitlines():
                ll = line.strip().lower()
                if "current" in ll and "active" in ll:
                    c.parking_enabled = True
        except Exception:
            pass

        # ── Temperature ──
        try:
            temp_out = _ps(
                "Get-CimInstance MSAcpi_ThermalZoneTemperature | "
                "Select-Object -First 1 -ExpandProperty CurrentTemperature")
            raw = float((temp_out or "").strip())
            c.temp_celsius = round((raw / 10.0) - 273.15, 1)
        except (ValueError, TypeError):
            c.temp_celsius = -1.0

        # ── MMCSS ──
        c.mmcss_running = bool(_svc_running("MMCSS"))

        # ── Priority boost ──
        try:
            pb = _reg_value(
                "HKLM",
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
                r"\Multimedia\SystemProfile",
                "SystemResponsiveness")
            c.priority_boost_enabled = pb is None or (
                isinstance(pb, int) and pb > 10)
        except Exception:
            c.priority_boost_enabled = True

    # ---- GPU (three-tier VRAM detection) ----
    def _scan_gpu(self, r: ScanResult):
        g, warnings = _detect_gpu_three_tier()
        r.gpu = g

        # GPU scheduling
        hags = _reg_value(
            "HKLM",
            r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
            "HwSchMode")
        g.hardware_gpu_scheduling = hags == 2
        g.hardware_accelerated_gpu_scheduling = hags == 2

        # MPO
        mpo = _reg_value(
            "HKLM",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion"
            r"\Explorer\GraphicsCards",
            "DisableOverlay")
        g.mpo_disabled = mpo == 1

        # NVIDIA-specific
        if any(v == "nvidia" for v in g.vendors):
            gfe_out = _reg_value(
                "HKCU",
                r"SOFTWARE\NVIDIA Corporation\NvShadowShadows\GFE",
                "GfeEnabled")
            g.gfe_installed = gfe_out is not None
            g.gfe_overlay_enabled = gfe_out == 1

        # TDR settings
        tdr_level = _reg_value(
            "HKLM",
            r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
            "TdrLevel")
        tdr_delay = _reg_value(
            "HKLM",
            r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
            "TdrDelay")
        g.tdr_level = int(tdr_level) if isinstance(tdr_level, int) else 3
        g.tdr_delay = int(tdr_delay) if isinstance(tdr_delay, int) else 2

    # ---- RAM ----
    def _scan_ram(self, r: ScanResult):
        m = r.ram
        vm = psutil.virtual_memory()
        m.total_gb = round(vm.total / (1024 ** 3), 1)
        m.used_gb = round(vm.used / (1024 ** 3), 1)
        m.available_gb = round(vm.available / (1024 ** 3), 1)
        m.pressure = vm.percent / 100.0

        # Channels & speed
        rows = _csv_rows(
            "Get-CimInstance Win32_PhysicalMemory | "
            "Select-Object Speed,DeviceLocator,Manufacturer,Capacity")
        if rows:
            m.channels = len(rows)
            speeds = []
            for row in rows:
                try:
                    speeds.append(int(row.get("Speed", 0) or 0))
                except (ValueError, TypeError):
                    pass
            m.speed_mtps = max(speeds) if speeds else 0

        # Pagefile
        pf_out = _ps(
            "Get-CimInstance Win32_PageFileSetting | "
            "Select-Object -ExpandProperty MaxSize")
        try:
            m.pagefile_gb = round(int((pf_out or "0").strip()) / 1024, 1)
        except (ValueError, TypeError):
            m.pagefile_gb = 0
        auto_pf = _reg_value(
            "HKLM",
            r"SYSTEM\CurrentControlSet\Control\Session Manager"
            r"\Memory Management",
            "PagingFiles")
        m.pagefile_auto = auto_pf is None or (isinstance(auto_pf, list) and len(auto_pf) > 0)

        # Memory compression
        m.memory_compression = bool(_svc_running("MemoryCompression"))

        # Superfetch/SysMain
        m.superfetch_enabled = _svc_state("SysMain") != "disabled"

    # ---- Storage ----
    def _scan_storage(self, r: ScanResult):
        s = r.storage
        rows = _csv_rows(
            "Get-PhysicalDisk | "
            "Select-Object MediaType,BusType,OperationalStatus")
        for row in rows:
            mt = (row.get("MediaType") or "").lower()
            bt = (row.get("BusType") or "").lower()
            if "ssd" in mt or "nvme" in bt:
                s.has_ssd = True
            if "nvme" in bt:
                s.has_nvme = True
            if "hdd" in mt or "disk" in bt:
                s.has_hdd = True

        # Disk I/O
        try:
            dio = psutil.disk_io_counters()
            if dio:
                s.disk_read_mb_s = round(dio.read_bytes / (1024 * 1024), 1)
                s.disk_write_mb_s = round(dio.write_bytes / (1024 * 1024), 1)
        except Exception:
            pass

        # Fast startup
        hs = _reg_value(
            "HKLM",
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Power",
            "HiberbootEnabled")
        s.fast_startup_enabled = hs == 1

        # TRIM
        trim_out = _ps("fsutil behavior query DisableDeleteNotify")
        s.trim_enabled = "DisableDeleteNotify = 0" in (trim_out or "")

    # ---- Network ----
    def _scan_network(self, r: ScanResult):
        n = r.network
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        for iface, st in stats.items():
            if iface.lower() in ("lo", "loopback"):
                continue
            if st.isup:
                n.adapter_name = iface
                n.adapter_type = "wifi" if "wi-fi" in iface.lower() or "wlan" in iface.lower() else "ethernet"
                n.speed = f"{st.speed} Mbps" if st.speed else ""
                break

        # Nagle
        nagle = _reg_value(
            "HKLM",
            r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces",
            "TcpAckFrequency")
        n.nagle_disabled = nagle == 1

    # ---- Input (NEW: HID, USB, driver state) ----
    def _scan_input(self, r: ScanResult):
        inp = r.input

        # HID devices
        rows = _csv_rows(
            "Get-CimInstance Win32_USBHub | "
            "Select-Object DeviceID,Name,Status")
        inp.hid_device_count = len(rows)
        for row in rows:
            name = (row.get("Name") or "").strip()
            status = (row.get("Status") or "").strip()
            inp.hid_devices.append({
                "name": name,
                "status": status,
                "device_id": (row.get("DeviceID") or "").strip(),
            })
            if status.lower() not in ("ok", "running", "degraded"):
                inp.hid_driver_issues.append(f"{name}: {status}")

        # USB controllers
        rows = _csv_rows(
            "Get-CimInstance Win32_USBController | "
            "Select-Object Name,Status")
        inp.usb_controllers = len([
            r for r in rows
            if (r.get("Status") or "").lower() == "ok"])

        # USB controller errors
        for row in rows:
            status = (row.get("Status") or "").lower()
            name = (row.get("Name") or "").strip()
            if status not in ("ok", "running"):
                inp.usb_driver_issues.append(f"{name}: {status}")

        # Bluetooth HID
        bt = _csv_rows(
            "Get-CimInstance Win32_PnPEntity | "
            "Where-Object { $_.Name -like '*Bluetooth*' -and "
            "$_.Name -like '*HID*' } | "
            "Select-Object Name")
        inp.bluetooth_hid = len(bt) > 0

    # ---- Display (NEW: multi-monitor, DWM, driver errors) ----
    def _scan_display(self, r: ScanResult):
        d = r.display

        # Monitors
        rows = _csv_rows(
            "Get-CimInstance Win32_DesktopMonitor | "
            "Select-Object Name,ScreenWidth,ScreenHeight")
        d.monitors = []
        for row in rows:
            w = row.get("ScreenWidth") or ""
            h = row.get("ScreenHeight") or ""
            res = f"{w}x{h}" if w and h else "Unknown"
            d.monitors.append({
                "name": (row.get("Name") or "").strip(),
                "resolution": res,
            })
        d.monitor_count = max(len(rows), 1)
        d.multi_monitor = d.monitor_count > 1
        if d.monitors:
            d.primary_resolution = d.monitors[0].get("resolution", "")

        # Display drivers
        rows = _csv_rows(
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,Status,DriverVersion,DriverDate,CurrentRefreshRate")
        for row in rows:
            name = (row.get("Name") or "").strip()
            status = (row.get("Status") or "").strip()
            driver_ver = (row.get("DriverVersion") or "").strip()
            d.display_drivers.append({
                "name": name,
                "status": status,
                "driver": driver_ver,
            })
            if status.lower() not in ("ok", "running"):
                d.display_driver_errors.append(f"{name}: {status}")
            if not d.graphics_driver_version:
                d.graphics_driver_version = driver_ver
                d.graphics_driver_date = (row.get("DriverDate") or "").strip()
            try:
                rr = int(row.get("CurrentRefreshRate", 0) or 0)
                if rr > 0:
                    d.refresh_rates.append(f"{rr}Hz")
            except (ValueError, TypeError):
                pass

        # DWM
        dwm = _svc_running("uDWM")
        d.dwm_enabled = dwm is not None

        # Hardware cursor
        hc = _reg_value(
            "HKCU",
            r"Control Panel\Desktop",
            "UserPreferencesMask")
        # Hardware cursor is enabled by default; only disabled if explicitly set
        d.hardware_cursor = True

    # ---- OS ----
    def _scan_os(self, r: ScanResult):
        o = r.os
        rows = _csv_rows(
            "Get-CimInstance Win32_OperatingSystem | "
            "Select-Object Caption,BuildNumber,Version,OSArchitecture")
        if rows:
            row = rows[0]
            o.version = (row.get("Version") or "").strip()
            try:
                o.build = int(row.get("BuildNumber", 0) or 0)
            except (ValueError, TypeError):
                o.build = 0
            o.edition = (row.get("Caption") or "").strip()

        # Uptime
        o.uptime_hours = round(
            (time.time() - psutil.boot_time()) / 3600, 1)

        # Game DVR / Bar / Mode
        o.game_dvr_enabled = _reg_value(
            "HKCU",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR",
            "AppCaptureEnabled") == 1
        o.game_bar_enabled = _reg_value(
            "HKCU",
            r"SOFTWARE\Microsoft\GameBar",
            "UseNexusForGameBarEnabled") != 0
        o.game_mode_enabled = _reg_value(
            "HKCU",
            r"SOFTWARE\Microsoft\GameBar",
            "AutoGameModeEnabled") == 1

        # Event Viewer — critical and error events from last 7 days
        ev_out = _ps(
            "try { "
            "$c = (Get-WinEvent -FilterHashtable @{LogName='System';"
            "Level=1,2; StartTime=(Get-Date).AddDays(-7)} -MaxEvents 50 "
            "-ErrorAction SilentlyContinue | Measure-Object).Count; "
            "Write-Output $c "
            "} catch { Write-Output 0 }")
        try:
            o.critical_events = int((ev_out or "0").strip())
        except (ValueError, TypeError):
            o.critical_events = 0

        # Error events
        err_out = _ps(
            "try { "
            "$c = (Get-WinEvent -FilterHashtable @{LogName='System';"
            "Level=2; StartTime=(Get-Date).AddDays(-7)} -MaxEvents 200 "
            "-ErrorAction SilentlyContinue | Measure-Object).Count; "
            "Write-Output $c "
            "} catch { Write-Output 0 }")
        try:
            o.error_events = int((err_out or "0").strip())
        except (ValueError, TypeError):
            o.error_events = 0

        # Device Manager errors
        dev_errors = _csv_rows(
            "Get-PnpDevice | "
            "Where-Object { $_.Status -ne 'OK' -and $_.Status -ne 'Degraded' "
            "-and $_.Status -ne 'Unknown' } | "
            "Select-Object FriendlyName,Status,Class")
        for row in (dev_errors or []):
            o.device_errors.append({
                "name": (row.get("FriendlyName") or "").strip(),
                "status": (row.get("Status") or "").strip(),
                "class": (row.get("Class") or "").strip(),
            })

        # Pending reboot
        reboot = _reg_value(
            "HKLM",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion"
            r"\Component Based Servicing",
            "RebootPending")
        o.pending_reboot = reboot is not None

        # Last Windows Update
        update_out = _ps(
            "try { "
            "(Get-HotFix | Sort-Object InstalledOn -Descending | "
            "Select-Object -First 1 -ErrorAction SilentlyContinue)"
            ".InstalledOn.ToString('yyyy-MM-dd') "
            "} catch { Write-Output '' }")
        o.last_windows_update = (update_out or "").strip()

    # ---- Startup ----
    def _scan_startup(self, r: ScanResult):
        s = r.startup
        heavy = ("teams", "onedrive", "adobe", "steam", "epic", "origin",
                 "spotify", "discord", "slack", "zoom", "dropbox",
                 "office", "assistant", "updater")

        for hive_path in [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce",
        ]:
            for hive in ("HKCU", "HKLM"):
                full = f"{hive}\\{hive_path}"
                out = _ps(f'reg query "{full}" 2>$null')
                if out:
                    for line in out.splitlines():
                        line = line.strip()
                        if line and not line.startswith("HK") and "=" in line:
                            name = line.split("=")[0].strip()
                            s.entries.append({"name": name, "source": "registry"})
                            s.registry_run_count += 1

        for base in [os.environ.get("APPDATA", ""),
                     os.environ.get("PROGRAMDATA", "")]:
            sp = Path(base) / "Microsoft/Windows/Start Menu/Programs/Startup"
            if sp.is_dir():
                for f in sp.iterdir():
                    if f.suffix.lower() in (
                            ".lnk", ".exe", ".bat", ".cmd", ".ps1", ".vbs"):
                        s.entries.append(
                            {"name": f.name, "source": "startup_folder"})
                        s.startup_folder_count += 1

        s.count = len(s.entries)
        for entry in s.entries:
            nl = entry["name"].lower()
            if any(k in nl for k in heavy):
                s.high_impact.append(entry["name"])

    # ---- Services ----
    def _scan_services(self, r: ScanResult):
        svc = r.services
        unnecessary = [
            "SysMain", "WSearch", "DiagTrack", "dmwappushservice",
            "MapsBroker", "lfsvc", "SharedAccess", "RemoteRegistry",
            "TrkWaps", "WMPNetworkSvc", "XblAuthManager", "XblGameSave",
            "XboxNetApiSvc", "XboxGipSvc", "Fax", "Spooler",
        ]
        for name in unnecessary:
            running = _svc_running(name)
            if running:
                svc.unnecessary_running.append(name)
            state = _svc_state(name)
            if state == "disabled":
                svc.disabled_count += 1

        out = _ps(
            "Get-Service | Where-Object { $_.Status -eq 'Running' } | "
            "Measure-Object | Select-Object -ExpandProperty Count")
        try:
            svc.total_running = int(out.strip())
        except (ValueError, TypeError):
            svc.total_running = len(svc.unnecessary_running)

    # ---- Processes ----
    def _scan_processes(self, r: ScanResult):
        p = r.processes
        procs = psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_percent", "status"])
        for proc in procs:
            try:
                info = proc.info
                if info["status"] != "running":
                    continue
                p.count += 1
                cpu = info.get("cpu_percent", 0) or 0
                mem = info.get("memory_percent", 0) or 0
                if cpu > 5.0:
                    p.high_cpu.append(
                        {"name": info["name"], "cpu": round(cpu, 1)})
                if mem > 3.0:
                    p.high_memory.append(
                        {"name": info["name"], "mem_pct": round(mem, 1)})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    # ---- Audio ----
    def _scan_audio(self, r: ScanResult):
        a = r.audio
        rows = _csv_rows(
            "Get-CimInstance Win32_SoundDevice | "
            "Select-Object Name,Status,Manufacturer")
        for row in rows:
            name = (row.get("Name") or "").strip()
            status = (row.get("Status") or "").strip()
            a.devices.append({
                "name": name,
                "status": status,
                "manufacturer": (row.get("Manufacturer") or "").strip(),
            })
            if status.lower() in ("ok", "running"):
                a.active_device = name
            if status.lower() not in ("ok", "running"):
                a.audio_issues.append(f"{name}: {status}")

        enh = _reg_value(
            "HKCU",
            r"SOFTWARE\Microsoft\Multimedia\Audio",
            "DisableEnhancements")
        a.audio_enhancements = enh != 1

        exc = _reg_value(
            "HKCU",
            r"SOFTWARE\Microsoft\Multimedia\Audio\Voice\WinRTProperties",
            "EnableExclusiveMode")
        a.exclusive_mode = exc == 1

        spatial = _ps(
            "Get-ItemProperty -Path 'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Audio' "
            "-Name 'SpatialSoundEnabled' -ErrorAction SilentlyContinue | "
            "Select-Object -ExpandProperty SpatialSoundEnabled")
        a.spatial_sound = "Enabled" if "1" in (spatial or "").strip() else "Disabled"

    # ---- Scheduled Tasks ----
    def _scan_scheduled_tasks(self, r: ScanResult):
        st = r.scheduled_tasks
        out = _ps(
            "try { "
            "$tasks = Get-ScheduledTask -ErrorAction SilentlyContinue | "
            "Where-Object { $_.State -ne 'Disabled' -and "
            "$_.TaskPath -notlike '\\Microsoft\\Windows\\*' } | "
            "Select-Object TaskName,TaskPath,State; "
            "if ($tasks) { $tasks | ConvertTo-Csv -NoTypeInformation } "
            "} catch { Write-Output '' }")
        if out and out.strip():
            import csv as _csv, io as _io
            try:
                reader = _csv.DictReader(_io.StringIO(out))
                for row in reader:
                    name = (row.get("TaskName") or "").strip()
                    path = (row.get("TaskPath") or "").strip()
                    if name:
                        st.total_tasks += 1
                        st.enabled_tasks += 1
                        heavy_keywords = ("update", "backup", "sync", "scan",
                                         "defrag", "optimize", "cleanup")
                        if any(k in name.lower() for k in heavy_keywords):
                            st.heavy_tasks.append({"name": name, "path": path})
            except Exception:
                pass

        for base in [os.environ.get("APPDATA", ""),
                     os.environ.get("PROGRAMDATA", "")]:
            sp = Path(base) / "Microsoft/Windows/Start Menu/Programs/Startup"
            if sp.is_dir():
                for f in sp.iterdir():
                    if f.suffix.lower() in (".bat", ".cmd", ".ps1", ".vbs"):
                        st.tasks_at_logon.append(f.name)

    # ---- Events ----
    def _scan_events(self, r: ScanResult):
        e = r.events
        ev_out = _ps(
            "try { "
            "$evts = Get-WinEvent -FilterHashtable @{LogName='System';"
            "Level=1,2; StartTime=(Get-Date).AddDays(-7)} -MaxEvents 200 "
            "-ErrorAction SilentlyContinue; "
            "if ($evts) { $evts | Select-Object LevelDisplayName,TimeCreated,"
            "ProviderName,Message | ConvertTo-Csv -NoTypeInformation } "
            "} catch { Write-Output '' }")
        if ev_out and ev_out.strip():
            import csv as _csv2, io as _io2
            try:
                reader = _csv2.DictReader(_io2.StringIO(ev_out))
                for row in reader:
                    level = (row.get("LevelDisplayName") or "").strip()
                    if level == "Critical":
                        e.critical_count += 1
                        msg = (row.get("Message") or "")[:200]
                        provider = (row.get("ProviderName") or "").strip()
                        if "blue" in msg.lower() or "bugcheck" in provider.lower():
                            e.bsod_count += 1
                    elif level == "Error":
                        e.error_count += 1
                    if level in ("Critical", "Error") and len(e.recent_errors) < 10:
                        e.recent_errors.append({
                            "level": level,
                            "time": (row.get("TimeCreated") or "").strip(),
                            "source": (row.get("ProviderName") or "").strip(),
                            "message": (row.get("Message") or "")[:150],
                        })
            except Exception:
                pass

        app_out = _ps(
            "try { "
            "$apps = Get-WinEvent -FilterHashtable @{LogName='Application';"
            "Level=2; StartTime=(Get-Date).AddDays(-7)} -MaxEvents 50 "
            "-ErrorAction SilentlyContinue | "
            "Where-Object { $_.ProviderName -like '*Error Reporting*' -or "
            "$_.ProviderName -like '*Windows Error Reporting*' } | "
            "Select-Object TimeCreated,ProviderName,Message; "
            "if ($apps) { $apps | ConvertTo-Csv -NoTypeInformation } "
            "} catch { Write-Output '' }")
        if app_out and app_out.strip():
            import csv as _csv3, io as _io3
            try:
                reader = _csv3.DictReader(_io3.StringIO(app_out))
                for row in reader:
                    if len(e.app_crashes) < 10:
                        e.app_crashes.append({
                            "time": (row.get("TimeCreated") or "").strip(),
                            "source": (row.get("ProviderName") or "").strip(),
                            "message": (row.get("Message") or "")[:150],
                        })
            except Exception:
                pass

    # ---- Drivers ----
    def _scan_drivers(self, r: ScanResult):
        d = r.drivers

        # Audio devices
        rows = _csv_rows(
            "Get-CimInstance Win32_SoundDevice | "
            "Select-Object Name,Manufacturer,Status")
        for row in rows:
            name = (row.get("Name") or "").strip()
            status = (row.get("Status") or "").strip()
            d.audio_devices.append({
                "name": name,
                "status": status,
                "manufacturer": (row.get("Manufacturer") or "").strip(),
            })
            if status.lower() not in ("ok", "running"):
                d.audio_driver_issues.append(f"{name}: {status}")

        # Display drivers (already scanned in _scan_display, but collect here)
        d.display_drivers = r.display.display_drivers
        d.display_driver_issues = r.display.display_driver_errors

        # Driver resets (from event viewer)
        reset_out = _ps(
            "try { "
            "(Get-WinEvent -FilterHashtable @{LogName='System';"
            "Id=4101,4116; StartTime=(Get-Date).AddDays(-7)} -MaxEvents 20 "
            "-ErrorAction SilentlyContinue | Measure-Object).Count "
            "} catch { Write-Output 0 }")
        try:
            d.driver_resets = int((reset_out or "0").strip())
        except (ValueError, TypeError):
            d.driver_resets = 0

    # ---- DPC/ISR Latency (NEW) ----
    def _scan_dpc_isr(self, r: ScanResult):
        """Measure DPC/ISR latency using latencyMon-style approach.

        Uses PowerShell performance counters to sample DPC/ISR activity.
        Real-time latency tracing requires kernel drivers; this measures
        observed activity levels as a proxy.
        """
        # DPC count via perf counter
        dpc_out = _ps(
            "$c1 = (Get-Counter '\\DPC Rate' -ErrorAction SilentlyContinue)"
            ".CounterSamples | Select-Object -First 1 -ExpandProperty CookedValue;"
            "Start-Sleep -Seconds 2;"
            "$c2 = (Get-Counter '\\DPC Rate' -ErrorAction SilentlyContinue)"
            ".CounterSamples | Select-Object -First 1 -ExpandProperty CookedValue;"
            "Write-Output ([math]::Round(($c2 - $c1) / 2, 1))")
        try:
            r.ram.dpc_latency_us = float((dpc_out or "0").strip())
        except (ValueError, TypeError):
            r.ram.dpc_latency_us = 0.0

        # DPC top offenders via process DPC activity
        dpc_offenders = _ps(
            "Get-Counter '\\Process(*)\\DPC Rate' -ErrorAction SilentlyContinue | "
            "Select-Object -ExpandProperty CounterSamples | "
            "Where-Object { $_.CookedValue -gt 0 } | "
            "Sort-Object CookedValue -Descending | "
            "Select-Object -First 10 InstanceName,CookedValue")
        for line in (dpc_offenders or "").splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                name = parts[0].replace("\\", "")
                try:
                    rate = float(parts[-1])
                    if rate > 0:
                        r.ram.dpc_top_offenders.append(
                            {"name": name, "rate": rate})
                        r.drivers.dpc_offenders.append(
                            {"name": name, "rate": rate})
                except (ValueError, IndexError):
                    pass


def scan() -> ScanResult:
    """Convenience function — run a full scan and return results."""
    return SystemScanner().scan()
