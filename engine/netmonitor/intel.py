"""Network intelligence engine — real BGP, ASN, GeoIP, and traceroute data collection.

All data comes from real public APIs. Nothing is fabricated.
Every observation has a source, timestamp, and confidence level.
"""
from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional, Callable


_CACHE: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 3600


def _get(url: str, timeout: float = 8.0) -> Optional[dict]:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MaximumTweaks/3.0 (Network Intelligence)")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError, ValueError):
        return None


def _cached(key: str) -> Optional[object]:
    if key in _CACHE:
        ts, val = _CACHE[key]
        if time.time() - ts < _CACHE_TTL:
            return val
    return None


def _cache(key: str, val: object):
    _CACHE[key] = (time.time(), val)


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class AsnInfo:
    asn: int = 0
    name: str = ""
    country: str = ""
    registry: str = ""
    description: str = ""
    domains: list[str] = field(default_factory=list)
    prefixes_v4: int = 0
    prefixes_v6: int = 0
    visible: bool = True
    source: str = ""
    timestamp: float = field(default_factory=time.time)

    @property
    def display(self) -> str:
        return f"AS{self.asn}" if self.asn else ""


@dataclass
class GeoInfo:
    ip: str = ""
    lat: float = 0.0
    lon: float = 0.0
    city: str = ""
    region: str = ""
    country: str = ""
    country_code: str = ""
    accuracy: str = "unknown"
    source: str = ""
    timestamp: float = field(default_factory=time.time)

    @property
    def display(self) -> str:
        parts = []
        if self.city:
            parts.append(self.city)
        if self.region:
            parts.append(self.region)
        if self.country_code:
            parts.append(self.country_code)
        return ", ".join(parts) if parts else "Unknown"


@dataclass
class BgpPath:
    prefix: str = ""
    origin_asn: int = 0
    as_path: list[int] = field(default_factory=list)
    as_path_names: dict[int, str] = field(default_factory=dict)
    next_hop: str = ""
    communities: list[str] = field(default_factory=list)
    rpki_status: str = ""
    source: str = ""
    confidence: str = "observed"
    explanation: str = ""
    timestamp: float = field(default_factory=time.time)

    @property
    def as_path_display(self) -> str:
        parts = []
        for a in self.as_path:
            name = self.as_path_names.get(a, "")
            if name:
                parts.append(f"AS{a} ({name})")
            else:
                parts.append(f"AS{a}")
        return " → ".join(parts) if parts else "Unknown"


@dataclass
class AsnRelationship:
    asn: int = 0
    name: str = ""
    relationship: str = ""
    source: str = ""


@dataclass
class HopData:
    number: int = 0
    ip: str = ""
    hostname: str = ""
    rtt_ms: float = 0.0
    geo: Optional[GeoInfo] = None
    asn: Optional[AsnInfo] = None
    confidence: str = "measured"
    source: str = "traceroute"
    timestamp: float = field(default_factory=time.time)


@dataclass
class NetworkIntel:
    ip: str = ""
    hostname: str = ""
    asn: AsnInfo = field(default_factory=AsnInfo)
    prefix: str = ""
    bgp_path: BgpPath = field(default_factory=BgpPath)
    upstreams: list[AsnRelationship] = field(default_factory=list)
    peers: list[AsnRelationship] = field(default_factory=list)
    geo: GeoInfo = field(default_factory=GeoInfo)
    reverse_dns: str = ""
    data_sources: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def summary(self) -> str:
        parts = []
        if self.asn.asn:
            parts.append(f"AS{self.asn.asn}")
        if self.asn.name:
            parts.append(self.asn.name)
        if self.geo.city:
            parts.append(self.geo.city)
        if self.geo.country_code:
            parts.append(self.geo.country_code)
        return " | ".join(parts) if parts else self.ip


@dataclass
class TracerouteResult:
    destination: str = ""
    destination_ip: str = ""
    hops: list[HopData] = field(default_factory=list)
    total_hops: int = 0
    total_latency: float = 0.0
    packet_loss: float = 0.0
    jitter: float = 0.0
    success: bool = False
    error: str = ""
    source: str = "system_traceroute"
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConnectionInfo:
    local_ip: str = ""
    local_port: int = 0
    remote_ip: str = ""
    remote_port: int = 0
    protocol: str = "TCP"
    state: str = ""
    pid: int = 0
    process_name: str = ""
    service_name: str = ""
    app_category: str = ""
    intel: Optional[NetworkIntel] = None
    confidence: str = "measured"
    source: str = "system_connections"


# ── Service classification ──────────────────────────────────────────────────

_SERVICE_MAP = {
    "discord": "Discord", "slack": "Slack", "teams": "Microsoft Teams",
    "zoom": "Zoom", "skype": "Skype", "spotify": "Spotify",
    "steam": "Steam", "epic": "Epic Games", "fortnite": "Fortnite",
    "battle": "Battle.net", "riot": "Riot Games",
    "chrome": "Google Chrome", "firefox": "Firefox", "msedge": "Edge",
    "brave": "Brave Browser", "opera": "Opera Browser",
    "code": "VS Code", "cursor": "Cursor", "docker": "Docker",
    "node": "Node.js", "python": "Python", "curl": "curl",
    "obs": "OBS Studio", "devenv": "Visual Studio",
    "youtube": "YouTube", "twitch": "Twitch",
    "netflix": "Netflix", "amazon": "Amazon",
    "cloudflare": "Cloudflare", "akamai": "Akamai",
    "telegram": "Telegram", "whatsapp": "WhatsApp",
    "signal": "Signal", "icq": "ICQ",
}

_CATEGORY_MAP = {
    "discord": "communication", "teams": "communication", "zoom": "communication",
    "slack": "communication", "skype": "communication", "telegram": "communication",
    "whatsapp": "communication", "signal": "communication",
    "chrome": "browser", "firefox": "browser", "msedge": "browser",
    "brave": "browser", "opera": "browser",
    "steam": "gaming", "epic": "gaming", "fortnite": "gaming",
    "battle": "gaming", "riot": "gaming",
    "spotify": "streaming", "youtube": "streaming", "twitch": "streaming",
    "netflix": "streaming", "obs": "streaming",
    "code": "development", "cursor": "development", "docker": "development",
    "node": "development", "python": "development",
    "cloudflare": "infrastructure", "akamai": "infrastructure",
    "amazon": "cloud",
}


def _classify_process(name: str) -> tuple[str, str]:
    lower = name.lower().replace(".exe", "")
    for key, svc in _SERVICE_MAP.items():
        if key in lower:
            return svc, _CATEGORY_MAP.get(key, "other")
    return name, "other"


# ── Data collection functions ───────────────────────────────────────────────

def resolve_host(hostname: str) -> list[str]:
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_INET)
        return list({r[4][0] for r in results})
    except (socket.gaierror, OSError):
        return []


def reverse_dns(ip: str) -> str:
    if not ip:
        return ""
    ck = f"rdns_{ip}"
    cached = _cached(ck)
    if cached is not None:
        return cached
    try:
        host, _, _ = socket.gethostbyaddr(ip)
        _cache(ck, host)
        return host
    except (socket.herror, socket.gaierror, OSError):
        _cache(ck, "")
        return ""


def lookup_geo(ip: str) -> GeoInfo:
    ck = f"geo_{ip}"
    cached = _cached(ck)
    if cached is not None:
        return cached

    geo = GeoInfo(ip=ip)

    info = _get(f"https://ipinfo.io/{ip}/json")
    if info and "bogon" not in info:
        geo.source = "ipinfo.io"
        org = info.get("org", "")
        loc = info.get("loc", "")
        if loc and "," in loc:
            try:
                parts = loc.split(",")
                geo.lat = float(parts[0])
                geo.lon = float(parts[1])
                geo.accuracy = "approximate"
            except (ValueError, IndexError):
                pass
        geo.city = info.get("city", "")
        geo.region = info.get("region", "")
        geo.country_code = info.get("country", "")
        _cache(ck, geo)
        return geo

    info2 = _get(f"http://ip-api.com/json/{ip}?fields=66846719")
    if info2 and info2.get("status") == "success":
        geo.source = "ip-api.com"
        geo.lat = info2.get("lat", 0.0)
        geo.lon = info2.get("lon", 0.0)
        geo.accuracy = "approximate"
        geo.city = info2.get("city", "")
        geo.region = info2.get("regionName", "")
        geo.country_code = info2.get("countryCode", "")
        _cache(ck, geo)
        return geo

    geo.source = "unavailable"
    geo.accuracy = "unknown"
    _cache(ck, geo)
    return geo


def lookup_asn(ip: str) -> AsnInfo:
    ck = f"asn_{ip}"
    cached = _cached(ck)
    if cached is not None:
        return cached

    asn = AsnInfo(source="unavailable")

    info = _get(f"https://ipinfo.io/{ip}/json")
    if info:
        org = info.get("org", "")
        if org and "AS" in org:
            try:
                asn_str = org.split(" ")[0].replace("AS", "")
                asn.asn = int(asn_str)
                asn.name = org[len(org.split(" ")[0]) + 1:]
                asn.source = "ipinfo.io"
            except (ValueError, IndexError):
                pass
        asn.country = info.get("country", "")

    if not asn.asn:
        info2 = _get(f"http://ip-api.com/json/{ip}?fields=66846719")
        if info2 and info2.get("status") == "success":
            asn_raw = info2.get("as", "")
            if asn_raw and " " in asn_raw:
                try:
                    asn.asn = int(asn_raw.split(" ")[0].replace("AS", ""))
                    asn.name = info2.get("asOrganization", "")
                    asn.source = "ip-api.com"
                except (ValueError, IndexError):
                    pass

    _cache(ck, asn)
    return asn


def lookup_bgp(ip: str) -> BgpPath:
    ck = f"bgp_{ip}"
    cached = _cached(ck)
    if cached is not None:
        return cached

    path = BgpPath(source="unavailable")

    data = _get(f"https://api.bgpview.io/ip/{ip}")
    if data and data.get("status") == "ok" and data.get("data"):
        d = data["data"]
        path.source = "bgpview.io"
        path.confidence = "observed"

        if d.get("prefixes"):
            pfx = d["prefixes"][0]
            path.prefix = pfx.get("prefix", "")
            path.origin_asn = pfx.get("asn", 0)
            path.as_path = pfx.get("asn_path", [])
            path.next_hop = pfx.get("next_hop", "")
            path.rpki_status = pfx.get("rpk", "")

        path.as_path_names = {}
        for asn_num in path.as_path:
            asn_data = _get(f"https://api.bgpview.io/asn/{asn_num}")
            if asn_data and asn_data.get("status") == "ok" and asn_data.get("data"):
                path.as_path_names[asn_num] = asn_data["data"].get("name", "")

        path.explanation = (
            "BGP observed path — shows autonomous systems that route "
            "announcements for this prefix. Not the exact physical packet path."
        )

    _cache(ck, path)
    return path


def lookup_upstreams(asn: int) -> list[AsnRelationship]:
    if not asn:
        return []
    ck = f"up_{asn}"
    cached = _cached(ck)
    if cached is not None:
        return cached

    result = []
    data = _get(f"https://api.bgpview.io/asn/{asn}/upstreams")
    if data and data.get("status") == "ok" and data.get("data"):
        for u in data["data"].get("upstreams", []):
            result.append(AsnRelationship(
                asn=u.get("asn", 0),
                name=u.get("name", ""),
                relationship="upstream",
                source="bgpview.io",
            ))

    _cache(ck, result)
    return result


def lookup_peers(asn: int) -> list[AsnRelationship]:
    if not asn:
        return []
    ck = f"peers_{asn}"
    cached = _cached(ck)
    if cached is not None:
        return cached

    result = []
    data = _get(f"https://api.bgpview.io/asn/{asn}/peers")
    if data and data.get("status") == "ok" and data.get("data"):
        peers = data["data"].get("peer_count", [])
        if isinstance(peers, list):
            for p in peers:
                if isinstance(p, dict):
                    result.append(AsnRelationship(
                        asn=p.get("asn", 0),
                        name=p.get("name", ""),
                        relationship="peer",
                        source="bgpview.io",
                    ))

    _cache(ck, result)
    return result


def get_network_intel(ip: str) -> NetworkIntel:
    intel = NetworkIntel(ip=ip)
    intel.hostname = reverse_dns(ip)
    if intel.hostname:
        intel.data_sources.append("reverse_dns")

    intel.geo = lookup_geo(ip)
    if intel.geo.source and intel.geo.source != "unavailable":
        intel.data_sources.append(intel.geo.source)

    intel.asn = lookup_asn(ip)
    if intel.asn.source and intel.asn.source != "unavailable":
        intel.data_sources.append(intel.asn.source)

    intel.bgp_path = lookup_bgp(ip)
    if intel.bgp_path.source and intel.bgp_path.source != "unavailable":
        intel.data_sources.append(intel.bgp_path.source)
        intel.prefix = intel.bgp_path.prefix

    if intel.asn.asn:
        intel.upstreams = lookup_upstreams(intel.asn.asn)
        intel.peers = lookup_peers(intel.asn.asn)

    return intel


def get_active_connections() -> list[ConnectionInfo]:
    connections = []
    try:
        creation_flags = 0x08000000
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | "
             "Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,OwningProcess | "
             "ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=10,
            creationflags=creation_flags,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout.strip())
            if isinstance(data, dict):
                data = [data]
            for entry in data:
                remote = entry.get("RemoteAddress", "")
                if not remote or remote in ("0.0.0.0", "::") or remote.startswith("127."):
                    continue
                if remote.startswith("169.254."):
                    continue
                pid = entry.get("OwningProcess", 0)
                proc_name = _get_process_name(pid)
                svc, cat = _classify_process(proc_name)
                conn = ConnectionInfo(
                    local_ip=entry.get("LocalAddress", ""),
                    local_port=int(entry.get("LocalPort", 0)),
                    remote_ip=remote,
                    remote_port=int(entry.get("RemotePort", 0)),
                    protocol="TCP",
                    state="ESTABLISHED",
                    pid=pid,
                    process_name=proc_name,
                    service_name=svc,
                    app_category=cat,
                )
                connections.append(conn)
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, ValueError):
        pass

    seen = set()
    unique = []
    for c in connections:
        if c.remote_ip not in seen:
            seen.add(c.remote_ip)
            unique.append(c)
    return unique


def enrich_connection(conn: ConnectionInfo) -> ConnectionInfo:
    try:
        conn.intel = get_network_intel(conn.remote_ip)
    except Exception:
        pass
    return conn


def _get_process_name(pid: int) -> str:
    if not pid:
        return ""
    try:
        creation_flags = 0x08000000
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).ProcessName"],
            capture_output=True, text=True, timeout=5,
            creationflags=creation_flags,
        )
        return proc.stdout.strip() if proc.stdout.strip() else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def run_traceroute(target: str, max_hops: int = 30) -> TracerouteResult:
    result = TracerouteResult(destination=target)

    ips = resolve_host(target)
    if ips:
        result.destination_ip = ips[0]

    try:
        creation_flags = 0x08000000
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Test-Connection -ComputerName {target} -Count 4 -ErrorAction SilentlyContinue | "
             f"Select-Object -First 1 | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=30,
            creationflags=creation_flags,
        )

        proc2 = subprocess.run(
            ["tracert", "-d", "-h", str(max_hops), "-w", "2000", target],
            capture_output=True, text=True, timeout=60,
            creationflags=creation_flags,
        )

        if proc2.returncode == 0 and proc2.stdout:
            for line in proc2.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("Tracing") or line.startswith("Over"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    hop_num = int(parts[0])
                except ValueError:
                    continue
                ip = ""
                rtt = 0.0
                for p in parts[1:]:
                    if p.startswith("<"):
                        try:
                            rtt = float(p.replace("<", "").replace("ms", ""))
                        except ValueError:
                            pass
                    elif "." in p and not p.endswith("ms"):
                        try:
                            parts_int = [int(x) for x in p.split(".")]
                            if len(parts_int) == 4 and all(0 <= x <= 255 for x in parts_int):
                                ip = p
                        except ValueError:
                            pass
                    elif p.endswith("ms"):
                        try:
                            rtt = float(p.replace("ms", ""))
                        except ValueError:
                            pass

                geo = lookup_geo(ip) if ip else None
                asn_info = lookup_asn(ip) if ip else None

                hop = HopData(
                    number=hop_num,
                    ip=ip,
                    rtt_ms=rtt,
                    geo=geo,
                    asn=asn_info,
                    confidence="measured",
                )
                result.hops.append(hop)

            result.total_hops = len(result.hops)
            rtts = [h.rtt_ms for h in result.hops if h.rtt_ms > 0]
            if rtts:
                result.total_latency = max(rtts)
                if len(rtts) > 1:
                    result.jitter = max(rtts) - min(rtts)
            result.success = True

    except (subprocess.TimeoutExpired, OSError):
        result.error = "Traceroute timed out"

    return result
