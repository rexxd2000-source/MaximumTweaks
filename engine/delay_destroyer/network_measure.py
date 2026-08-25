"""Network measurement engine — real latency, jitter, and loss measurement.

Measures actual network conditions rather than guessing from registry keys.
Distinguishes between LOCAL SYSTEM LATENCY (DPC, ISR, scheduling) and
NETWORK LATENCY (ping, jitter, routing).
"""
from __future__ import annotations

import re
import statistics
import subprocess
import time
from dataclasses import dataclass, field


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


def _ping_host_ps(host: str, count: int = 10, timeout_ms: int = 2000) -> list[float]:
    """Ping a host using ping.exe. Returns list of latencies in ms."""
    timeout_s = max(1, timeout_ms // 1000)
    try:
        proc = subprocess.run(
            ["ping", "-n", str(count), "-w", str(timeout_ms), host],
            capture_output=True, text=True, timeout=max(30, count * 3),
            creationflags=0x08000000,
        )
        output = proc.stdout or ""
    except Exception:
        return []
    latencies = []
    for line in output.splitlines():
        line = line.strip()
        if "time" in line.lower() and "ms" in line.lower():
            m = re.search(r"time[=<](\d+)ms", line, re.IGNORECASE)
            if m:
                latencies.append(float(m.group(1)))
            elif re.search(r"time\s*<\s*1ms", line, re.IGNORECASE):
                latencies.append(0.5)
    return latencies


def _get_default_gateway() -> str:
    """Get default gateway IP."""
    out = _ps(
        "Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
        "Sort-Object RouteMetric | Select-Object -First 1 -ExpandProperty NextHop"
    )
    gw = out.strip()
    if gw and re.match(r"^\d+\.\d+\.\d+\.\d+$", gw):
        return gw
    # Fallback: ipconfig
    out2 = _ps(
        "(Get-NetAdapter | Where-Object {$_.Status -eq 'Up'}).InterfaceDescription"
    )
    return ""


def _get_dns_servers() -> list[str]:
    """Get configured DNS servers."""
    out = _ps(
        "Get-DnsClientServerAddress | Where-Object {$_.ServerAddresses} | "
        "Select-Object -ExpandProperty ServerAddresses | Select-Object -Unique"
    )
    servers = []
    for line in out.strip().splitlines():
        s = line.strip()
        if s and re.match(r"^\d+\.\d+\.\d+\.\d+$", s):
            servers.append(s)
    return servers[:3]


def _dns_resolve_time(domain: str = "google.com", dns_server: str = "") -> float | None:
    """Measure DNS resolution time in ms."""
    target = dns_server if dns_server else ""
    script = (
        f"$sw = [System.Diagnostics.Stopwatch]::StartNew(); "
        f"try {{ [System.Net.Dns]::GetHostAddresses('{domain}') | Out-Null }} "
        f"catch {{ }}; $sw.Stop(); $sw.ElapsedMilliseconds"
    )
    out = _ps(script, timeout=10)
    for line in out.strip().splitlines():
        try:
            return float(line.strip())
        except ValueError:
            continue
    return None


def _measure_mtu(host: str = "8.8.8.8") -> int | None:
    """Detect path MTU using ping with don't-fragment flag."""
    out = _ps(
        f"ping {host} -f -l 1472 -n 1 2>&1 | Select-String 'needs to be fragmented'",
        timeout=10
    )
    if "fragmented" in out.lower():
        # Try smaller
        out2 = _ps(
            f"ping {host} -f -l 1400 -n 1 2>&1 | Select-String 'Reply from'",
            timeout=10
        )
        if "reply from" in out2.lower():
            return 1400 + 28  # IP + ICMP headers
        return 1400 + 28
    # No fragmentation = MTU is at least 1500
    return 1500


def _tcp_connect_latency(host: str, port: int = 443, attempts: int = 5) -> float | None:
    """Measure TCP handshake latency in ms."""
    latencies = []
    for _ in range(attempts):
        script = (
            f"$sw = [System.Diagnostics.Stopwatch]::StartNew(); "
            f"try {{ "
            f"  $tcp = New-Object System.Net.Sockets.TcpClient; "
            f"  $tcp.Connect('{host}', {port}); "
            f"  $sw.Stop(); "
            f"  $sw.ElapsedMilliseconds; "
            f"  $tcp.Close() "
            f"}} catch {{ $sw.Stop(); -1 }}"
        )
        out = _ps(script, timeout=10)
        for line in out.strip().splitlines():
            try:
                v = float(line.strip())
                if v >= 0:
                    latencies.append(v)
            except ValueError:
                continue
        time.sleep(0.2)
    return statistics.mean(latencies) if latencies else None


@dataclass
class NetworkMeasurement:
    """Complete network measurement results."""
    # Gateway
    gateway_ip: str = ""
    gateway_ping_ms: float = 0.0
    gateway_jitter_ms: float = 0.0
    gateway_loss_pct: float = 0.0

    # DNS
    dns_servers: list[str] = field(default_factory=list)
    dns_resolution_ms: float = 0.0

    # Public internet
    internet_host: str = "8.8.8.8"
    internet_ping_ms: float = 0.0
    min_ping_ms: float = 0.0
    max_ping_ms: float = 0.0
    internet_jitter_ms: float = 0.0
    internet_loss_pct: float = 0.0

    # Game server (Cloudflare as proxy for low-latency endpoint)
    game_server_host: str = "1.1.1.1"
    game_ping_ms: float = 0.0
    game_jitter_ms: float = 0.0
    game_loss_pct: float = 0.0

    # TCP
    tcp_connect_ms: float = 0.0

    # MTU
    mtu: int = 1500

    # Classification
    network_quality: str = "unknown"  # excellent, good, fair, poor
    local_vs_network: str = ""  # explanation of where latency comes from

    # Raw data
    gateway_latencies: list[float] = field(default_factory=list)
    internet_latencies: list[float] = field(default_factory=list)
    game_latencies: list[float] = field(default_factory=list)


def measure_network() -> NetworkMeasurement:
    """Run the full network measurement suite."""
    m = NetworkMeasurement()

    # Gateway
    m.gateway_ip = _get_default_gateway()
    if m.gateway_ip:
        m.gateway_latencies = _ping_host_ps(m.gateway_ip, count=10)
        if m.gateway_latencies:
            m.gateway_ping_ms = round(statistics.mean(m.gateway_latencies), 1)
            m.gateway_jitter_ms = round(
                statistics.stdev(m.gateway_latencies)
                if len(m.gateway_latencies) > 1 else 0.0, 1
            )
            m.gateway_loss_pct = round(
                (1 - len(m.gateway_latencies) / 10) * 100, 1
            )

    # DNS
    m.dns_servers = _get_dns_servers()
    dns_time = _dns_resolve_time()
    if dns_time is not None:
        m.dns_resolution_ms = round(dns_time, 1)

    # Internet (8.8.8.8)
    m.internet_latencies = _ping_host_ps(m.internet_host, count=10)
    if m.internet_latencies:
        m.internet_ping_ms = round(statistics.mean(m.internet_latencies), 1)
        m.min_ping_ms = round(min(m.internet_latencies), 1)
        m.max_ping_ms = round(max(m.internet_latencies), 1)
        m.internet_jitter_ms = round(
            statistics.stdev(m.internet_latencies)
            if len(m.internet_latencies) > 1 else 0.0, 1
        )
        m.internet_loss_pct = round(
            (1 - len(m.internet_latencies) / 10) * 100, 1
        )

    # Game server proxy (Cloudflare)
    m.game_latencies = _ping_host_ps(m.game_server_host, count=10)
    if m.game_latencies:
        m.game_ping_ms = round(statistics.mean(m.game_latencies), 1)
        m.game_jitter_ms = round(
            statistics.stdev(m.game_latencies)
            if len(m.game_latencies) > 1 else 0.0, 1
        )
        m.game_loss_pct = round(
            (1 - len(m.game_latencies) / 10) * 100, 1
        )

    # TCP connect
    tcp = _tcp_connect_latency("google.com", 443, attempts=3)
    if tcp is not None:
        m.tcp_connect_ms = round(tcp, 1)

    # MTU
    mtu = _measure_mtu()
    if mtu is not None:
        m.mtu = mtu

    # Classify network quality
    m.network_quality = _classify_network(m)

    # Local vs network explanation
    m.local_vs_network = _explain_latency_source(m)

    return m


def _classify_network(m: NetworkMeasurement) -> str:
    """Classify overall network quality based on measurements."""
    avg_ping = m.internet_ping_ms or m.game_ping_ms
    jitter = m.internet_jitter_ms or m.game_jitter_ms
    loss = m.internet_loss_pct or m.game_loss_pct

    if avg_ping == 0:
        return "unknown"

    score = 100
    # Ping penalty
    if avg_ping > 100:
        score -= 30
    elif avg_ping > 50:
        score -= 15
    elif avg_ping > 20:
        score -= 5

    # Jitter penalty
    if jitter > 20:
        score -= 30
    elif jitter > 10:
        score -= 15
    elif jitter > 5:
        score -= 5

    # Loss penalty
    if loss > 5:
        score -= 30
    elif loss > 1:
        score -= 15
    elif loss > 0:
        score -= 5

    if score >= 85:
        return "excellent"
    elif score >= 70:
        return "good"
    elif score >= 50:
        return "fair"
    else:
        return "poor"


def _explain_latency_source(m: NetworkMeasurement) -> str:
    """Explain whether latency is local system or network."""
    parts = []

    if m.gateway_ping_ms > 5:
        parts.append(
            f"Gateway latency ({m.gateway_ping_ms:.0f}ms) suggests local network congestion."
        )
    elif m.gateway_ping_ms > 0 and m.gateway_ping_ms <= 2:
        parts.append(
            f"Gateway latency ({m.gateway_ping_ms:.0f}ms) is excellent — local network is clean."
        )

    if m.internet_ping_ms > 0 and m.gateway_ping_ms > 0:
        internet_minus_gateway = m.internet_ping_ms - m.gateway_ping_ms
        if internet_minus_gateway > 30:
            parts.append(
                f"ISP/routing adds ~{internet_minus_gateway:.0f}ms beyond your local network."
            )

    if m.internet_jitter_ms > 10:
        parts.append(
            f"High jitter ({m.internet_jitter_ms:.0f}ms) indicates inconsistent routing or congestion."
        )

    if m.dns_resolution_ms > 100:
        parts.append(
            f"Slow DNS ({m.dns_resolution_ms:.0f}ms) adds initial connection delay."
        )

    if not parts:
        if m.internet_ping_ms > 0 and m.internet_ping_ms < 20:
            parts.append("Network latency is low — delays are likely system-side (DPC, scheduling).")
        elif m.internet_ping_ms >= 20:
            parts.append("Moderate network latency — some delay is ISP/routing-related.")
        else:
            parts.append("Network measurements incomplete — limited analysis available.")

    return " ".join(parts)
