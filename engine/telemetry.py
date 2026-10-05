"""Live hardware telemetry for the Dashboard.

Polls CPU / GPU / RAM / disk every 1000 ms on a background thread and emits a
metrics dict to the UI. Expensive subprocess sources (nvidia-smi, Libre
Hardware Monitor's WMI provider) are cached with short TTLs so the sampler
stays light and never blocks the UI thread.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import tempfile
import time

from PySide6.QtCore import QThread, Signal

import psutil

INTERVAL_S = 1.0           # spec: poll every 1000 ms
_NVIDIA_TTL = 2.0          # nvidia-smi subprocess cache (seconds)
_AMD_TTL = 5.0             # AMD WMI perf-counter cache (seconds)
_LHM_TTL = 5.0             # LibreHardwareMonitor WMI cache (seconds)
_DISK_TTL = 30.0           # games/OS folder-size scan cache (seconds)

_CPU_THREADS = psutil.cpu_count(logical=True) or 0
_CPU_CORES = psutil.cpu_count(logical=False) or 0
_SYSTEM_DRIVE = os.path.splitdrive(os.environ.get("SystemDrive", "C:"))[0] + "\\"
_NO_WINDOW = 0x08000000


def _now() -> float:
    return time.monotonic()


class _Cached:
    """Thin value cache with a monotonic-clock TTL."""

    def __init__(self, ttl: float, fn):
        self._ttl = ttl
        self._fn = fn
        self._value = None
        self._at = 0.0

    def get(self):
        t = _now()
        if self._value is None or t - self._at > self._ttl:
            self._value = self._fn()
            self._at = t
        return self._value


# --------------------------------------------------------------------------
# GPU (NVIDIA primary via nvidia-smi, best-effort)
# --------------------------------------------------------------------------

def _gpu_sample() -> dict | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,"
             "temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2.5,
            creationflags=_NO_WINDOW)
        line = out.stdout.strip().splitlines()
        if not line:
            return None
        parts = [p.strip() for p in line[0].split(",")]
        if len(parts) < 5:
            return None
        name, util, mem_used, mem_total, temp = parts
        return {
            "gpu_name": name,
            "gpu_util": int(util),
            "gpu_mem_used": int(mem_used),
            "gpu_mem_total": int(mem_total),
            "gpu_temp": int(temp),
        }
    except Exception:  # noqa: BLE001
        return None


def _amd_gpu_sample() -> dict | None:
    """AMD path — Windows GPU Performance Counters via WMI.

    Returns name / utilization (sum of 3D engine load) / VRAM used & total for
    the first AMD display adapter, or None when no AMD GPU is present. Cached
    at the sampler level (see _amd_gpu_cache) so the PowerShell cost is paid
    every _AMD_TTL seconds at most.
    """
    script = (
        "$e=(Get-CimInstance -Namespace root\\cimv2 -ClassName "
        "Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine | "
        "Where-Object { $_.Name -match 'engtype_3D' } | "
        "Measure-Object UtilizationPercentage -Sum).Sum;"
        "$m=(Get-CimInstance -Namespace root\\cimv2 -ClassName "
        "Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory | "
        "Measure-Object DedicatedUsage -Sum).Sum;"
        "$vc=Get-CimInstance Win32_VideoController | "
        "Where-Object { $_.PNPDeviceID -match 'VEN_1002|VEN_1022' } | "
        "Select-Object -First 1;"
        "Write-Output ('U=' + $e);"
        "Write-Output ('M=' + $m);"
        "if($vc){ Write-Output ('N=' + $vc.Name) }"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True, text=True, timeout=6,
            creationflags=_NO_WINDOW)
        vals = {}
        for line in out.stdout.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                vals[key] = value
        if "N" not in vals or vals.get("U") is None:
            return None
        util = max(0, min(100, int(float(vals["U"]))))
        used_mb = int(vals.get("M") or 0) // 2**20
        result = {
            "gpu_name": vals["N"],
            "gpu_util": util,
            "gpu_mem_used": used_mb,
            "gpu_mem_total": _amd_vram_total_mb(),
        }
        return result
    except Exception:  # noqa: BLE001
        return None


def _amd_vram_total_mb() -> int | None:
    """Total dedicated VRAM for the AMD adapter from the driver class key.

    Win32_VideoController.AdapterRAM is capped at ~4 GB and the perf-counter
    set exposes only used memory, so the driver-written
    HardwareInformation.qwMemorySize is the authoritative total."""
    try:
        import winreg
    except Exception:  # noqa: BLE001
        return None
    base = (r"SYSTEM\CurrentControlSet\Control\Class"
            r"\{4d36e968-e325-11ce-bfc1-08002be10318}")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    return None
                i += 1
                path = base + "\\" + sub
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                        mid, _ = winreg.QueryValueEx(k, "MatchingDeviceId")
                        mid = str(mid)
                        if "VEN_1002" not in mid and "VEN_1022" not in mid:
                            continue
                        for name in ("HardwareInformation.qwMemorySize",
                                     "HardwareInformation.QWordMemorySize"):
                            try:
                                mem, fmt = winreg.QueryValueEx(k, name)
                            except OSError:
                                continue
                            if isinstance(mem, int) and mem > 0:
                                return max(1, mem // 2**20)
                        return None
                except OSError:
                    continue
    except Exception:  # noqa: BLE001
        return None
    return None


# --------------------------------------------------------------------------
# Temperatures — psutil sensors first, LibreHardwareMonitor WMI as fallback.
# --------------------------------------------------------------------------

def _lhm_temps() -> dict | None:
    """Query Libre Hardware Monitor's WMI provider (CPU/GPU temperatures).

    Returns {"cpu": float, "gpu": float} or None when LHM is not running.
    """
    try:
        cmd = ("powershell -NoProfile -Command \"Get-CimInstance -Namespace "
               "'root\\LibreHardwareMonitor' -ClassName Sensor | "
               "Where-Object { $_.SensorType -eq 'Temperature' } | "
               "ForEach-Object { $_.Name + '|' + $_.Value }\"")
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5,
                             creationflags=_NO_WINDOW)
        cpu_vals: list[float] = []
        gpu_vals: list[float] = []
        for line in out.stdout.splitlines():
            if "|" not in line:
                continue
            name, _, value = line.partition("|")
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            lower = name.lower()
            if "gpu" in lower:
                gpu_vals.append(value)
            elif any(k in lower for k in ("cpu package", "cpu core", "core #",
                                          "core max", "tdie", "ccd", "tctl")):
                cpu_vals.append(value)
        result = {}
        if cpu_vals:
            result["cpu"] = max(cpu_vals)
        if gpu_vals:
            result["gpu"] = max(gpu_vals)
        return result or None
    except Exception:  # noqa: BLE001
        return None


def _cpu_temp() -> float | None:
    try:
        temps = psutil.sensors_temperatures()
        for name in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            for entry in temps.get(name, []) or []:
                if entry.current:
                    return float(entry.current)
    except Exception:  # noqa: BLE001
        pass
    lhm = _lhm_temps_cache.get()
    if lhm:
        return lhm.get("cpu")
    return None


def _gpu_temp(fallback: float | None) -> float | None:
    if fallback is not None:
        return fallback
    lhm = _lhm_temps_cache.get()
    return lhm.get("gpu") if lhm else None


# --------------------------------------------------------------------------
# Disk — live usage + an OS / Games / Free breakdown for the segmented bar.
# --------------------------------------------------------------------------

def _volume_label(drive: str) -> str | None:
    try:
        buf = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_ulong()
        max_len = ctypes.c_ulong()
        flags = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            drive, buf, 261, ctypes.byref(serial), ctypes.byref(max_len),
            ctypes.byref(flags), None, 0)
        return buf.value if ok else None
    except Exception:  # noqa: BLE001
        return None


def _dir_size(path: str, budget_s: float) -> int:
    """Sum file bytes under path, stopping once the time budget runs out."""
    total = 0
    deadline = _now() + budget_s
    stack = [path]
    while stack and _now() < deadline:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat().st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _games_bytes(drive: str) -> int:
    roots = [
        os.path.join(drive, "Steam", "steamapps", "common"),
        os.path.join(drive, "Program Files (x86)", "Steam", "steamapps", "common"),
        os.path.join(drive, "Program Files", "Steam", "steamapps", "common"),
        os.path.join(drive, "Games"),
        os.path.join(drive, "GOG Games"),
        os.path.join(drive, "Program Files", "Epic Games"),
        os.path.join(drive, "Program Files (x86)", "Epic Games"),
        os.path.join(drive, "Ubisoft Game Launcher", "games"),
        os.path.join(drive, "Riot Games"),
        os.path.join(drive, "Battle.net"),
    ]
    existing = [r for r in roots if os.path.isdir(r)]
    if not existing:
        return 0
    budget = 3.0 / len(existing)
    return sum(_dir_size(r, budget) for r in existing)


def _disk_breakdown() -> dict:
    try:
        total, used, free = shutil.disk_usage(_SYSTEM_DRIVE)
    except Exception:  # noqa: BLE001
        return {"total": 0, "used": 0, "free": 0, "games": 0, "appdata": 0,
                "label": None, "drive": _SYSTEM_DRIVE}
    games = _games_bytes(_SYSTEM_DRIVE)
    local = os.environ.get("LOCALAPPDATA") or ""
    appdata = _dir_size(local, 2.5) if os.path.isdir(local) else 0
    return {
        "total": total, "used": used, "free": free, "games": games,
        "appdata": appdata,
        "label": _volume_label(_SYSTEM_DRIVE), "drive": _SYSTEM_DRIVE,
    }


# --------------------------------------------------------------------------
# Temp-file cleanup (Disk card "Clean up files" action)
# --------------------------------------------------------------------------

def clean_temp_files() -> dict:
    """Delete user + system temp contents; locked files are skipped."""
    targets = [tempfile.gettempdir()]
    root = os.environ.get("SystemRoot", r"C:\Windows")
    targets.append(os.path.join(root, "Temp"))

    freed = 0
    files = 0
    folders = 0
    errors = 0
    seen: set[str] = set()

    for base in targets:
        base = os.path.realpath(base)
        if base in seen or not os.path.isdir(base):
            continue
        seen.add(base)
        try:
            entries = os.listdir(base)
        except OSError:
            continue
        for name in entries:
            path = os.path.join(base, name)
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path, ignore_errors=True)
                    folders += 1
                else:
                    try:
                        size = os.path.getsize(path)
                    except OSError:
                        size = 0
                    os.remove(path)
                    freed += size
                    files += 1
            except OSError:
                errors += 1

    return {"freed_bytes": freed, "files": files, "folders": folders,
            "errors": errors}


# --------------------------------------------------------------------------
# Sampler thread — one metrics dict every 1000 ms.
# --------------------------------------------------------------------------

def collect_metrics() -> dict:
    data = {
        "cpu_percent": 0.0, "cpu_freq_mhz": None, "cpu_temp": None,
        "cpu_cores": _CPU_CORES, "cpu_threads": _CPU_THREADS,
        "gpu_name": None, "gpu_util": None, "gpu_mem_used": None,
        "gpu_mem_total": None, "gpu_temp": None,
        "ram_used_gb": 0.0, "ram_total_gb": 0.0, "ram_avail_gb": 0.0,
        "ram_pct": 0.0, "uptime_s": 0.0, "hostname": None,
        "disk_total_gb": 0.0, "disk_used_gb": 0.0, "disk_free_gb": 0.0,
        "disk_games_gb": 0.0, "disk_appdata_gb": 0.0, "disk_label": None,
    }
    try:
        data["cpu_percent"] = float(psutil.cpu_percent(None) or 0.0)
        try:
            freq = psutil.cpu_freq()
            data["cpu_freq_mhz"] = int(freq.current) if freq else None
        except Exception:  # noqa: BLE001
            pass
        data["cpu_temp"] = _cpu_temp()
        try:
            vm = psutil.virtual_memory()
            data["ram_used_gb"] = round(vm.used / 2**30, 1)
            data["ram_total_gb"] = round(vm.total / 2**30, 1)
            data["ram_avail_gb"] = round(vm.available / 2**30, 1)
            data["ram_pct"] = float(vm.percent)
        except Exception:  # noqa: BLE001
            pass
        data["uptime_s"] = time.time() - psutil.boot_time()
        data["hostname"] = os.environ.get("COMPUTERNAME")
    except Exception:  # noqa: BLE001
        pass

    gpu = _gpu_cache.get()
    if not gpu:
        gpu = _amd_gpu_cache.get()
    if gpu:
        data.update(gpu)
    data["gpu_temp"] = _gpu_temp(gpu.get("gpu_temp") if gpu else None)

    disk = _disk_cache.get()
    if disk:
        data["disk_total_gb"] = round(disk["total"] / 2**30, 1)
        data["disk_used_gb"] = round(disk["used"] / 2**30, 1)
        data["disk_free_gb"] = round(disk["free"] / 2**30, 1)
        data["disk_games_gb"] = round(disk["games"] / 2**30, 1)
        data["disk_appdata_gb"] = round(disk["appdata"] / 2**30, 1)
        data["disk_label"] = disk.get("label")
    return data


_gpu_cache = _Cached(_NVIDIA_TTL, _gpu_sample)
_amd_gpu_cache = _Cached(_AMD_TTL, _amd_gpu_sample)
_lhm_temps_cache = _Cached(_LHM_TTL, _lhm_temps)
_disk_cache = _Cached(_DISK_TTL, _disk_breakdown)


def invalidate_disk_cache() -> None:
    """Force the next metrics tick to re-scan disk usage (after cleanup)."""
    _disk_cache._at = 0.0


class TelemetrySampler(QThread):
    """Polls live metrics on a background thread and emits them each second."""

    metrics = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = False

    def run(self):
        try:
            psutil.cpu_percent(interval=0.2)  # prime the first reading
        except Exception:  # noqa: BLE001
            pass
        while not self._stop:
            t0 = _now()
            data = collect_metrics()
            if self._stop:
                return
            self.metrics.emit(data)
            wait = INTERVAL_S - (_now() - t0)
            if wait > 0:
                for _ in range(int(wait / 0.05)):
                    if self._stop:
                        return
                    time.sleep(0.05)

    def stop(self):
        self._stop = True
