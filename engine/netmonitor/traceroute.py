"""ICMP/TCP traceroute collector using Windows tracert and raw probing."""
from __future__ import annotations

import re
import subprocess
import socket
import time
import threading
from typing import Optional

from engine.netmonitor.types import (
    Hop, HopProbes, HopStatus, ProbeMethod, Route,
)


def _parse_tracert_line(line: str) -> Optional[dict]:
    """Parse a single line of Windows tracert output."""
    line = line.strip()
    if not line or line.startswith("Tracing") or line.startswith("Over"):
        return None
    if line.startswith("Unable") or line.startswith("Cannot"):
        return None

    pattern = re.compile(
        r"^\s*(\d+)\s+"
        r"((?:<1\s+ms|\d+\s+ms|\d+\s+ms|\*))+\s*"
        r"([\d\.]+|[\w\.\-]+)?"
    )
    match = pattern.match(line)
    if not match:
        star_pattern = re.compile(r"^\s*(\d+)\s+(\*\s+\*\s+\*)")
        star_match = star_pattern.match(line)
        if star_match:
            return {"hop": int(star_match.group(1)), "ip": None, "times": []}
        return None

    hop_num = int(match.group(1))
    times_str = match.group(2) or ""
    ip = match.group(3)

    times = []
    for m in re.finditer(r"(\d+)\s*ms", times_str):
        times.append(float(m.group(1)))
    if "<1" in times_str:
        times.insert(0, 0.5)

    return {"hop": hop_num, "ip": ip, "times": times}


def run_traceroute(
    destination: str,
    max_hops: int = 30,
    timeout: float = 5.0,
    method: ProbeMethod = ProbeMethod.ICMP,
    callback=None,
    stop_event: Optional[threading.Event] = None,
) -> Route:
    """Run tracert on Windows and return a Route with discovered hops."""
    route = Route(
        destination=destination,
        protocol=method,
        max_ttl=max_hops,
    )

    try:
        resolved = socket.getaddrinfo(destination, None, socket.AF_INET)
        if resolved:
            route.destination_ip = resolved[0][4][0]
            route.destination_ips = list({r[4][0] for r in resolved})
    except (socket.gaierror, OSError):
        pass

    cmd = ["tracert", "-d", "-w", "2000", "-h", str(max_hops), destination]
    if method == ProbeMethod.ICMP:
        cmd = ["tracert", "-d", "-w", "2000", "-h", str(max_hops), destination]
    elif method == ProbeMethod.TCP:
        cmd = ["tracert", "-d", "-w", "2000", "-h", str(max_hops), "-T", "-P", "80", destination]

    try:
        creation_flags = 0x08000000
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creation_flags,
        )

        hop_data: dict[int, dict] = {}
        for line in proc.stdout:
            if stop_event and stop_event.is_set():
                proc.kill()
                return route

            parsed = _parse_tracert_line(line)
            if parsed:
                hop_num = parsed["hop"]
                if hop_num not in hop_data:
                    hop_data[hop_num] = {
                        "ip": parsed.get("ip"),
                        "times": list(parsed.get("times", [])),
                    }
                else:
                    if parsed.get("ip"):
                        hop_data[hop_num]["ip"] = parsed["ip"]
                    hop_data[hop_num]["times"].extend(parsed.get("times", []))

                if callback:
                    callback(hop_num, hop_data[hop_num])

        proc.wait(timeout=timeout + 5)
    except (subprocess.TimeoutExpired, OSError):
        pass

    start_time = time.time()
    for hop_num in sorted(hop_data.keys()):
        data = hop_data[hop_num]
        ip = data.get("ip") or ""
        times = data.get("times", [])

        probes = HopProbes()
        if times:
            probes.sent = max(len(times), 3)
            probes.received = len([t for t in times if t is not None])
            probes.lost = probes.sent - probes.received
            valid_times = [t for t in times if t is not None]
            if valid_times:
                probes.min_latency = min(valid_times)
                probes.max_latency = max(valid_times)
                probes.avg_latency = sum(valid_times) / len(valid_times)
                if len(valid_times) >= 2:
                    diffs = [
                        abs(valid_times[i] - valid_times[i - 1])
                        for i in range(1, len(valid_times))
                    ]
                    probes.jitter = sum(diffs) / len(diffs) if diffs else 0.0
                probes.latency_samples = list(valid_times)
                probes.packet_loss_pct = (
                    (probes.lost / probes.sent * 100) if probes.sent > 0 else 0.0
                )
            status = HopStatus.HEALTHY
        elif ip:
            probes.sent = 3
            probes.lost = 3
            probes.packet_loss_pct = 100.0
            status = HopStatus.TIMEOUT
        else:
            probes.sent = 3
            probes.lost = 3
            probes.packet_loss_pct = 100.0
            status = HopStatus.TIMEOUT

        is_private = False
        if ip:
            parts = ip.split(".")
            if len(parts) == 4:
                try:
                    first = int(parts[0])
                    second = int(parts[1])
                    if first == 10 or first == 127:
                        is_private = True
                    elif first == 172 and 16 <= second <= 31:
                        is_private = True
                    elif first == 192 and second == 168:
                        is_private = True
                    elif first == 100 and 64 <= second <= 127:
                        is_private = True
                        route.hops[-1].network.is_cgnat = True if route.hops else False
                except ValueError:
                    pass

        if is_private and hop_num == 1:
            status = HopStatus.PRIVATE
            role = HopRole.GATEWAY
        elif is_private:
            status = HopStatus.PRIVATE
            role = HopRole.LOCAL
        else:
            role = HopRole.UNKNOWN

        hop = Hop(
            number=hop_num,
            ip=ip or "",
            status=status,
            role=role,
            probes=probes,
            method=method,
        )
        hop.network.is_private = is_private
        route.hops.append(hop)

    route.total_hops = len(route.hops)
    route.scan_duration = time.time() - start_time

    if route.hops:
        last = route.hops[-1]
        if last.status == HopStatus.HEALTHY:
            last.is_last_hop = True
            last.role = HopRole.DESTINATION

    return route


def run_tcp_probe(
    host: str,
    port: int = 80,
    ttl: int = 30,
    timeout: float = 2.0,
) -> tuple[bool, float]:
    """TCP connect probe. Returns (success, latency_ms)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        if hasattr(socket, "IP_TTL"):
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
            except OSError:
                pass
        start = time.time()
        result = sock.connect_ex((host, port))
        latency = (time.time() - start) * 1000
        sock.close()
        return result == 0, latency
    except (OSError, socket.timeout):
        return False, 0.0


def multi_probe_hop(
    ip: str,
    count: int = 5,
    timeout: float = 2.0,
    method: ProbeMethod = ProbeMethod.ICMP,
) -> HopProbes:
    """Send multiple probes to a single hop and collect statistics."""
    probes = HopProbes(sent=count)
    times = []

    for _ in range(count):
        if method == ProbeMethod.ICMP:
            try:
                cmd = ["ping", "-n", "1", "-w", "2000", ip]
                creation_flags = 0x08000000
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout + 2,
                    creationflags=creation_flags,
                )
                match = re.search(r"time[=<](\d+)ms", proc.stdout)
                if match:
                    times.append(float(match.group(1)))
                elif "Request timed out" in proc.stdout:
                    times.append(None)
                else:
                    times.append(None)
            except (subprocess.TimeoutExpired, OSError):
                times.append(None)
        else:
            ok, lat = run_tcp_probe(ip, port=80, timeout=timeout)
            times.append(lat if ok else None)

    valid = [t for t in times if t is not None]
    probes.received = len(valid)
    probes.lost = probes.sent - probes.received

    if valid:
        probes.min_latency = min(valid)
        probes.max_latency = max(valid)
        probes.avg_latency = sum(valid) / len(valid)
        if len(valid) >= 2:
            diffs = [abs(valid[i] - valid[i - 1]) for i in range(1, len(valid))]
            probes.jitter = sum(diffs) / len(diffs)
        probes.latency_samples = valid

    probes.packet_loss_pct = (probes.lost / probes.sent * 100) if probes.sent > 0 else 0.0
    return probes
