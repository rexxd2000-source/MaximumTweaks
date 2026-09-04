"""Diagnostics — real, self-contained measurement runners.

Each runner performs genuine local measurements (no canned data) and returns
a dict: {"rows": [(label, value)], "grade": "a"|"b"|"c"|None, "error": str|None}.
Everything is best-effort and time-boxed; unavailable signals degrade to an
honest note instead of a fake result.
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import socket
import struct
import subprocess
import threading
import time

CREATE_NO_WINDOW = 0x08000000
_PS = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]


def _ps(script: str, timeout: int = 25) -> str:
    try:
        r = subprocess.run(_PS + [script], capture_output=True, text=True,
                           errors="ignore", creationflags=CREATE_NO_WINDOW,
                           timeout=timeout)
        return (r.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _out(rows, grade=None, error=None):
    return {"rows": rows, "grade": grade, "error": error}


# ------------------------------------------------------------- bufferbloat

def _tcp_rtt(host="1.1.1.1", port=443, n=12):
    """n TCP-handshake RTT samples (ms) to host:port."""
    samples = []
    for _ in range(n):
        try:
            t0 = time.perf_counter()
            s = socket.create_connection((host, port), timeout=1.0)
            samples.append((time.perf_counter() - t0) * 1000.0)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                         struct.pack("ii", 1, 0))
            s.close()
        except Exception:  # noqa: BLE001
            continue
        time.sleep(0.05)
    return samples


def run_bufferbloat(stop=None):
    idle = _tcp_rtt(n=10)
    if not idle:
        return _out([], None, "network unreachable")
    # Apply real load: pull ~6 MB, and measure RTT during the transfer.
    loaded = []
    stop_flag = {"v": False}

    def load():
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://speed.cloudflare.com/__down?bytes=6000000",
                headers={"User-Agent": "MaximumTweaks"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                end = time.time() + 2.6
                while time.time() < end:
                    if resp.read(65536) == b"":
                        break
                stop_flag["v"] = True
        except Exception:  # noqa: BLE001
            stop_flag["v"] = True

    th = threading.Thread(target=load, daemon=True)
    th.start()
    while th.is_alive():
        loaded += _tcp_rtt(n=2)
    th.join(timeout=1)
    idle_avg = sum(idle) / len(idle)
    if loaded:
        load_avg = sum(loaded) / len(loaded)
        delta = max(0.0, load_avg - idle_avg)
    else:
        load_avg, delta = idle_avg, 0.0
    grade = "a" if delta < 25 else "b" if delta < 80 else "c"
    rows = [("Idle latency", f"{idle_avg:.1f} ms"),
            ("Under load", f"{load_avg:.1f} ms"),
            ("Latency increase", f"+{delta:.0f} ms")]
    return _out(rows, grade)


# ---------------------------------------------------------------------- dns

_RESOLVERS = (("Cloudflare", "1.1.1.1"), ("Google", "8.8.8.8"),
              ("Quad9", "9.9.9.9"), ("OpenDNS", "208.67.222.222"),
              ("AdGuard", "94.140.14.14"), ("Level3", "209.244.0.3"))


def _dns_query(server, name="cloudflare.com", timeout=1.2):
    """Raw A-record query; returns RTT seconds or raises."""
    tid = random.randrange(0, 0xFFFF)
    # DNS header: ID FLAGS QDCOUNT ANCOUNT NSCOUNT ARCOUNT  (6 x 16-bit)
    header = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    q = header + qname + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        t0 = time.perf_counter()
        s.sendto(q, (server, 53))
        data, _ = s.recvfrom(512)
        dt = time.perf_counter() - t0
        ancount = struct.unpack(">H", data[6:8])[0]
        return dt if ancount else None
    finally:
        s.close()


def run_dns(stop=None):
    results = []
    for label, ip in _RESOLVERS:
        times = []
        for _ in range(3):
            try:
                dt = _dns_query(ip)
                if dt is not None:
                    times.append(dt * 1000.0)
            except Exception:  # noqa: BLE001
                continue
        if times:
            results.append((label, sum(times) / len(times)))
    if not results:
        return _out([], None, "no resolver reachable")
    # current default resolver latency (system DNS)
    try:
        t0 = time.perf_counter()
        socket.getaddrinfo("cloudflare.com", 443, socket.AF_INET)
        cur = (time.perf_counter() - t0) * 1000.0
    except Exception:  # noqa: BLE001
        cur = None
    results.sort(key=lambda r: r[1])
    best, best_ms = results[0]
    grade = "a" if cur is None or best_ms < max(10.0, (cur or 99) * 0.7) \
        else "b" if best_ms < (cur or 0) else "c"
    rows = [("Fastest", f"{best} \u2014 {best_ms:.0f} ms")]
    if cur is not None:
        rows.append(("Your current DNS", f"{cur:.0f} ms"))
    rows.append(("Providers tested", str(len(results))))
    return _out(rows, grade)


# -------------------------------------------------------------------- speed

def run_speed(stop=None):
    import urllib.request
    ping = _tcp_rtt(n=6)
    ping_ms = sum(ping) / len(ping) if ping else None

    def dl(size):
        req = urllib.request.Request(
            f"https://speed.cloudflare.com/__down?bytes={size}",
            headers={"User-Agent": "MaximumTweaks"})
        got = 0
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=8) as r:
            while True:
                chunk = r.read(131072)
                if not chunk:
                    break
                got += len(chunk)
                if time.perf_counter() - t0 > 4.5:
                    break
        dt = time.perf_counter() - t0
        return got * 8 / dt / 1e6 if dt > 0 else 0.0

    def up():
        payload = os.urandom(2_000_000)
        req = urllib.request.Request(
            "https://speed.cloudflare.com/__up", data=payload,
            headers={"User-Agent": "MaximumTweaks",
                     "Content-Type": "application/octet-stream"})
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=8) as r:
            r.read(16)
        dt = time.perf_counter() - t0
        return len(payload) * 8 / dt / 1e6 if dt > 0 else 0.0

    try:
        down = dl(25_000_000)
        try:
            upl = up()
        except Exception:  # noqa: BLE001
            upl = None
    except Exception:  # noqa: BLE001
        return _out([], None, "download endpoint unreachable")
    grade = "a" if down > 100 else "b" if down > 25 else "c"
    rows = [("Download", f"{down:.0f} Mbps")]
    if upl is not None:
        rows.append(("Upload", f"{upl:.0f} Mbps"))
    if ping_ms is not None:
        rows.append(("Ping", f"{ping_ms:.0f} ms"))
    return _out(rows, grade)


# ---------------------------------------------------------------- benchmark

def _cpu_worker(deadline, box, stop=None):
    import hashlib
    ops = 0
    h = hashlib.sha256
    data = os.urandom(65536)          # large buffers release the GIL
    t0 = time.perf_counter()
    while time.perf_counter() < deadline:
        if stop is not None and stop():
            break
        h(data).digest()
        ops += 1
    dt = time.perf_counter() - t0
    if dt > 0:
        box.append(ops * 64.0 / 1024.0 / 1024.0 / dt)   # GiB/s


def run_benchmark(stop=None):
    try:
        import psutil
        cores = psutil.cpu_count(logical=True) or 4
    except Exception:  # noqa: BLE001
        cores = 4
    dur = 1.0
    box = []
    _cpu_worker(time.perf_counter() + dur, box, stop)
    single = box[0] if box else 0.0
    box2 = []
    ts = []
    deadline = time.perf_counter() + dur + 0.35  # GIL fairness window
    for _ in range(min(cores, 8)):
        t = threading.Thread(target=_cpu_worker, args=(deadline, box2, stop))
        t.start()
        ts.append(t)
    for t in ts:
        t.join()
    if box2:
        multi = sum(box2) / len(box2)
        spread = (max(box2) - min(box2)) / (multi or 1)
    else:
        multi, spread = 0.0, 0.0
    grade = "a" if single >= 1.0 and spread < 0.35 else \
        "b" if single >= 0.5 else "c"
    rows = [("Single-core", f"{single:.2f} GiB/s"),
            ("Per-core avg (8 threads)", f"{multi:.2f} GiB/s"),
            ("Core fairness spread", f"{spread * 100:.0f} %")]
    return _out(rows, grade)


# ------------------------------------------------------------------ drivers

def run_drivers(stop=None):
    script = r'''
$out = @()
Get-CimInstance Win32_VideoController | ForEach-Object {
  $out += "GPU|$($_.Name)|$($_.DriverVersion)|$($_.DriverDate)"
}
$old = @(Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue |
  Where-Object { $_.DriverDate -and $_.DriverDate -lt (Get-Date).AddMonths(-24) -and
                 $_.DeviceClass -in @('DISPLAY','NET','MEDIA','SYSTEM') })
$out += "OLD|$($old.Count)"
$bad = @(Get-CimInstance Win32_PnPEntity | Where-Object {
  $_.ConfigManagerErrorCode -ne 0 -and $_.Present })
$out += "BAD|$($bad.Count)"
$out -join "`n"
'''
    txt = _ps(script)
    if not txt:
        return _out([], None, "driver query failed")
    lines = txt.splitlines()
    gpu = next((l.split("|") for l in lines if l.startswith("GPU|")), None)
    bad = next((int(l.split("|")[1]) for l in lines if l.startswith("BAD|")), 0)
    oldn = next((int(l.split("|")[1]) for l in lines if l.startswith("OLD|")), 0)
    months = None
    if gpu and len(gpu) > 3 and gpu[3]:
        raw = re.sub(r"[^0-9]", "", gpu[3])[:8]   # e.g. 20240115000000.****
        try:
            import datetime as _dt2
            dt = _dt2.datetime.strptime(raw, "%Y%m%d")
            months = max(0, int((_dt2.datetime.now() - dt).days / 30.4))
        except Exception:  # noqa: BLE001
            months = None
    rows = []
    if gpu:
        age = f" ({months} mo old)" if months is not None else ""
        rows.append(("GPU driver", f"{gpu[2] or '?'}{age}"))
    rows.append(("Drivers > 2 yr old", str(oldn)))
    rows.append(("Problem devices", str(bad)))
    grade = "a" if bad == 0 and oldn == 0 else \
        "b" if bad <= 1 and oldn <= 2 else "c"
    return _out(rows, grade)


# -------------------------------------------------------------- disk health

def run_disk(stop=None):
    script = r'''
$d = Get-PhysicalDisk | Where-Object { $_.MediaType -ne 'Unknown' }
foreach ($x in $d) {
  $rc = $null
  try { $rc = $x | Get-StorageReliabilityCounter -ErrorAction Stop } catch {}
  $realloc = if ($rc -and $rc.ReallocSectorCount -ne $null) { [int]$rc.ReallocSectorCount } else { -1 }
  $temp = if ($rc) { [int]$rc.Temperature } else { -1 }
  "DISK|$($x.FriendlyName)|$($x.HealthStatus)|$($x.OperationalStatus)|$($x.MediaType)|$realloc|$temp"
}
'''
    txt = _ps(script)
    if not txt:
        return _out([], None, "SMART query failed (needs admin)")
    disks = [l.split("|") for l in txt.splitlines() if l.startswith("DISK|")]
    if not disks:
        return _out([], None, "no physical disks found")
    worst = "Healthy"
    realloc = 0
    healthy = True
    name = ""
    for d in disks:
        name = d[1]
        if len(d) > 6 and int(d[5]) > 0 and int(d[5]) > -1:
            realloc += int(d[5])
        hs = d[2]
        if hs not in ("Healthy", ""):
            healthy = False
            worst = hs
    grade = "a" if healthy and realloc == 0 else \
        "b" if healthy else "c"
    rows = [("Drive", name[:22] or "?"),
            ("Health", "Good" if healthy else worst),
            ("Reallocated sectors",
             str(realloc) if realloc else "0 / n/a")]
    return _out(rows, grade)


# ----------------------------------------------------- network jitter test

def run_jitter(stop=None):
    """30 TCP RTT samples to 1.1.1.1:443 -> jitter (mean deviation) and
    packet/connection loss rate."""
    total = 30
    samples = _tcp_rtt(n=total)
    loss = total - len(samples)
    if not samples:
        return _out([], None, "network unreachable")
    avg = sum(samples) / len(samples)
    jitter = sum(abs(s - avg) for s in samples) / len(samples)
    grade = "a" if loss == 0 and jitter < 3 else \
        "b" if loss <= 1 and jitter < 10 else "c"
    rows = [("Average latency", f"{avg:.1f} ms"),
            ("Jitter", f"{jitter:.1f} ms"),
            ("Lost probes", f"{loss} / {total}")]
    return _out(rows, grade)


# ------------------------------------------------- GPU throttling scanner

def run_throttle(stop=None):
    """Real clock-throttle state via nvidia-smi performance queries."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "-q", "-d", "PERFORMANCE"],
            capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW, timeout=15)
    except Exception:  # noqa: BLE001
        r = None
    if r is None or r.returncode != 0:
        return _out([], None, "nvidia-smi unavailable (no NVIDIA GPU?)")
    txt = r.stdout or ""
    m = re.search(r"Performance State\s*:\s*(\S+)", txt)
    pstate = m.group(1) if m else ""
    reasons_block = txt.split("Clocks Event Reasons")[-1] \
        if "Clocks Event Reasons" in txt else ""
    active = [name.strip().rstrip(":").lstrip("| ")
              for line in reasons_block.splitlines()
              for name in [line]
              if re.match(r"\s*[| ]{2,}\w.*?: Active\s*: Yes", line, re.I)]
    util = None
    try:
        q = subprocess.run(
            ["nvidia-smi", "--query-gpu=clocks.sm,clocks.max.sm,temperature."
             "gpu,power.draw", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW, timeout=10)
        parts = [p.strip() for p in (q.stdout or "").split(",")]
        if len(parts) >= 4:
            util = (parts[0], parts[1], parts[2], parts[3])
    except Exception:  # noqa: BLE001
        pass
    rows = [("Perf state", pstate or "?"),
            ("Throttle reasons", ", ".join(active) if active else "none active")]
    if util:
        rows.append(("SM clocks", f"{util[0]} / {util[1]} MHz"))
        rows.append(("Temp / Power", f"{util[2]} \u00b0C \u00b7 {util[3]} W"))
    grade = "a" if not active else ("c" if any(
        "SW" not in x and "HW" in x for x in active) else "b")
    return _out(rows, grade)


# --------------------------------------------- recording process scanner

_RECORDER_PAT = (r"nvcontainer|nvspblog|nvscp(?:base)?|shadowplay|"
                 r"gamebar|game_dvr|xgamebar|obs(64)?|medal|wetv|xdm|"
                 r"streamlabs|action|discord_ex|rumble|bitchute")


def run_recorders(stop=None):
    """Real process scan for background game recording / capture clients."""
    script = r'''
$pat = 'nvcontainer|nvsp|shadow|gamebar|game.?dvr|captura?|obs|medal|wetv|xdm|streamlabs|replay|recor|nvstream'
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match $pat } | ForEach-Object { "$($_.ProcessName)|$([math]::Round($_.WorkingSet64/1MB))" }
"DVRREG|$(try { (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\GameDVR' -ErrorAction Stop).AppCaptureEnabled } catch { 'n/a' })"
'''
    txt = _ps(script)
    procs = [l.split("|") for l in txt.splitlines() if "|" in l
             and not l.startswith("DVRREG")]
    dvr = next((l.split("|", 1)[1] for l in txt.splitlines()
                if l.startswith("DVRREG|")), "n/a")
    rows = [(p[0], f"{p[1]} MB RAM") for p in procs[:6]]
    rows.append(("Xbox Game DVR", "enabled" if str(dvr) == "1"
                 else "off" if dvr == "n/a" else "disabled"))
    if procs:
        grade = "c" if len(procs) > 1 else "b"
        rows.insert(0, ("Recorders found", str(len(procs))))
    else:
        grade = "a"
        rows.insert(0, ("Recorders found", "0"))
    return _out(rows, grade)


# ----------------------------------------------- PCIe link / memory / Hz

def run_pcie(stop=None):
    """Current vs max GPU PCIe link width/speed via PnP device properties."""
    script = r'''
$g = Get-CimInstance Win32_VideoController | Where-Object { $_.PNPDeviceID -like 'PCI\*' } | Select-Object -First 1
if (-not $g) { "NOPNP"; exit }
$id = $g.PNPDeviceID
$w = (Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_PciDevice_CurrentLinkWidth  -ErrorAction SilentlyContinue).Data
$Wmax = (Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_PciDevice_MaxLinkWidth    -ErrorAction SilentlyContinue).Data
$s = (Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_PciDevice_CurrentLinkSpeed   -ErrorAction SilentlyContinue).Data
$Smax = (Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_PciDevice_MaxLinkSpeed    -ErrorAction SilentlyContinue).Data
$sp = (Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_PciDevice_CurrentLinkSpeedPct -ErrorAction SilentlyContinue).Data
"PCIE|$w|$Wmax|$s|$Smax|$sp"
'''
    txt = _ps(script)
    m = [l for l in txt.splitlines() if l.startswith("PCIE|")]
    if not m:
        return _out([], None, "PCIe query unavailable")
    _, w, wmax, s, smax, sp = (m[0].split("|") + ["?"] * 6)[:6]
    rows = [("Link width", f"x{w or '?'} (max x{wmax or '?'})"),
            ("Link speed", f"{s or '?'} GT/s (max {smax or '?'})")]
    try:
        ok = (w == wmax) and (s == smax)
    except Exception:  # noqa: BLE001
        ok = False
    grade = "a" if ok else "b"
    if sp not in ("?", ""):
        try:
            grade = "a" if int(float(sp)) >= 95 else "c" if int(float(sp)) < 60 else "b"
        except Exception:  # noqa: BLE001
            pass
    return _out(rows, grade)


def run_memory(stop=None):
    """Real RAM/commit/standby snapshot + hard-fault rate via Get-Counter."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
    except Exception:  # noqa: BLE001
        return _out([], None, "psutil unavailable")
    script = r'''
$c = (Get-Counter '\Memory\Pages/sec' -ErrorAction SilentlyContinue).CounterSamples.CookedValue
"HF|$c"
'''
    txt = _ps(script)
    hf = next((l.split("|", 1)[1] for l in txt.splitlines()
               if l.startswith("HF|")), "?")
    pressure = vm.percent
    grade = "a" if pressure < 75 else "b" if pressure < 90 else "c"
    rows = [("RAM in use", f"{vm.used / 2**30:.1f} / {vm.total / 2**30:.1f} GB ({pressure} %)"),
            ("Commit", f"{sw.used / 2**20:.0f} MB / {sw.total / 2**20:.0f} MB"),
            ("Page-in rate", (f"{float(hf):.0f}/s" if hf != "?" else "?"))]
    return _out(rows, grade)


def run_refresh(stop=None):
    """Current vs max refresh rate per attached display (WMI)."""
    script = r'''
Get-CimInstance Win32_VideoController | ForEach-Object {
  "$($_.Name)|$($_.CurrentRefreshRate)|$($_.MaxRefreshRate)|$($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution)"
}
'''
    txt = _ps(script)
    lines = [l.split("|") for l in txt.splitlines() if l.strip()]
    if not lines:
        return _out([], None, "display query failed")
    rows = []
    grade = "a"
    for parts in lines[:4]:
        try:
            name, cur_hz, max_hz, res = (parts + ["?"] * 4)[:4]
            c, mx = int(cur_hz), int(max_hz)
            rows.append((name[:18] + f" ({res})", f"{c} Hz (max {mx} Hz)"))
            if mx - c > 1:
                grade = "c" if c < max(30, mx // 2) else "b"
        except Exception:  # noqa: BLE001
            continue
    return _out(rows, grade if rows else None, None if rows else "unreadable")


RUNNERS = {
    "bufferbloat": (run_bufferbloat, "Bufferbloat Test", 8),
    "dns": (run_dns, "DNS Benchmark", 7),
    "speed": (run_speed, "Speed Test", 12),
    "benchmark": (run_benchmark, "Benchmark", 5),
    "drivers": (run_drivers, "Driver Check", 25),
    "disk": (run_disk, "Disk Health", 20),
    "jitter": (run_jitter, "Network Jitter Test", 10),
    "throttle": (run_throttle, "GPU Throttling Scan", 20),
    "recorders": (run_recorders, "Recorder Process Scan", 12),
    "pcie": (run_pcie, "PCIe Link Diagnostic", 15),
    "memory": (run_memory, "Memory Pressure Check", 8),
    "refresh": (run_refresh, "Refresh Rate Verify", 4),
}
