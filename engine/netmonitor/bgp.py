"""BGP intelligence — real ASN, prefix, and routing data via public APIs."""
from __future__ import annotations

import json
import socket
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional


_CACHE: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 3600


def _get(url: str, timeout: float = 8.0) -> Optional[dict]:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MaximumTweaks/2.0 (Network Intelligence)")
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


# ── Data classes ──────────────────────────────────────────────────────────

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
    traffic_estimate: str = ""
    visible: bool = True
    source: str = ""

    @property
    def display(self) -> str:
        if self.asn:
            return f"AS{self.asn}"
        return ""


@dataclass
class PrefixInfo:
    prefix: str = ""
    origin_asn: int = 0
    origin_name: str = ""
    description: str = ""
    country: str = ""
    rpki_status: str = ""
    seen_by: list[str] = field(default_factory=list)
    source: str = ""


@dataclass
class BgpPath:
    prefix: str = ""
    origin_asn: int = 0
    as_path: list[int] = field(default_factory=list)
    as_path_names: dict[int, str] = field(default_factory=dict)
    next_hop: str = ""
    communities: list[str] = field(default_factory=list)
    source: str = ""
    confidence: str = "observed"
    explanation: str = ""

    @property
    def as_path_str(self) -> str:
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
    relationship: str = ""  # upstream, downstream, peer
    source: str = ""


@dataclass
class NetworkIntel:
    ip: str = ""
    hostname: str = ""
    asn: AsnInfo = field(default_factory=AsnInfo)
    prefix: PrefixInfo = field(default_factory=PrefixInfo)
    bgp_path: BgpPath = field(default_factory=BgpPath)
    upstreams: list[AsnRelationship] = field(default_factory=list)
    peers: list[AsnRelationship] = field(default_factory=list)
    geo_lat: float = 0.0
    geo_lon: float = 0.0
    geo_city: str = ""
    geo_region: str = ""
    geo_country: str = ""
    geo_accuracy: str = ""
    reverse_dns: str = ""
    data_sources: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


# ── IP info via ipinfo.io ────────────────────────────────────────────────

def lookup_ipinfo(ip: str) -> Optional[dict]:
    ck = f"ipinfo_{ip}"
    cached = _cached(ck)
    if cached is not None:
        return cached
    data = _get(f"https://ipinfo.io/{ip}/json")
    if data and "bogon" not in data:
        _cache(ck, data)
        return data
    return None


# ── IP geo via ip-api.com ────────────────────────────────────────────────

def lookup_ipapi(ip: str) -> Optional[dict]:
    ck = f"ipapi_{ip}"
    cached = _cached(ck)
    if cached is not None:
        return cached
    data = _get(f"https://ip-api.com/json/{ip}?fields=66846719")
    if data and data.get("status") == "success":
        _cache(ck, data)
        return data
    return None


# ── BGP data via bgpview.io ──────────────────────────────────────────────

def bgpview_ip(ip: str) -> Optional[dict]:
    ck = f"bgpview_ip_{ip}"
    cached = _cached(ck)
    if cached is not None:
        return cached
    data = _get(f"https://api.bgpview.io/ip/{ip}")
    if data and data.get("status") == "ok" and data.get("data"):
        _cache(ck, data["data"])
        return data["data"]
    return None


def bgpview_asn_upstreams(asn: int) -> list[dict]:
    ck = f"bgpview_up_{asn}"
    cached = _cached(ck)
    if cached is not None:
        return cached
    data = _get(f"https://api.bgpview.io/asn/{asn}/upstreams")
    if data and data.get("status") == "ok" and data.get("data"):
        result = data["data"].get("upstreams", [])
        _cache(ck, result)
        return result
    return []


def bgpview_asn_peers(asn: int) -> list[dict]:
    ck = f"bgpview_peer_{asn}"
    cached = _cached(ck)
    if cached is not None:
        return cached
    data = _get(f"https://api.bgpview.io/asn/{asn}/peers")
    if data and data.get("status") == "ok" and data.get("data"):
        result = data["data"].get("peer_count", [])
        if isinstance(result, list):
            _cache(ck, result)
            return result
    return []


def bgpview_asn_prefixes(asn: int) -> list[dict]:
    ck = f"bgpview_pfx_{asn}"
    cached = _cached(ck)
    if cached is not None:
        return cached
    data = _get(f"https://api.bgpview.io/asn/{asn}/prefixes")
    if data and data.get("status") == "ok" and data.get("data"):
        result = data["data"].get("ipv4_prefixes", []) + data["data"].get("ipv6_prefixes", [])
        _cache(ck, result)
        return result
    return []


def bgpview_prefix_roots(prefix: str) -> list[dict]:
    ck = f"bgpview_roots_{prefix}"
    cached = _cached(ck)
    if cached is not None:
        return cached
    data = _get(f"https://api.bgpview.io/prefix/{prefix}/roots")
    if data and data.get("status") == "ok" and data.get("data"):
        result = data["data"].get("rirs", [])
        _cache(ck, result)
        return result
    return []


# ── ASN info via bgpview ─────────────────────────────────────────────────

def bgpview_asn_info(asn: int) -> Optional[dict]:
    ck = f"bgpview_asn_{asn}"
    cached = _cached(ck)
    if cached is not None:
        return cached
    data = _get(f"https://api.bgpview.io/asn/{asn}")
    if data and data.get("status") == "ok" and data.get("data"):
        _cache(ck, data["data"])
        return data["data"]
    return None


# ── Reverse DNS ──────────────────────────────────────────────────────────

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


# ── DNS resolve ──────────────────────────────────────────────────────────

def resolve_host(hostname: str) -> list[str]:
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_INET)
        return list({r[4][0] for r in results})
    except (socket.gaierror, OSError):
        return []


# ── Combined intelligence lookup ─────────────────────────────────────────

def get_network_intel(ip: str) -> NetworkIntel:
    intel = NetworkIntel(ip=ip)
    intel.hostname = reverse_dns(ip)
    if intel.hostname:
        intel.data_sources.append("reverse_dns")

    info_ipinfo = lookup_ipinfo(ip)
    info_ipapi = lookup_ipapi(ip)

    if info_ipinfo:
        intel.data_sources.append("ipinfo.io")
        org = info_ipinfo.get("org", "")
        if org and "AS" in org:
            try:
                asn_str = org.split(" ")[0].replace("AS", "")
                intel.asn.asn = int(asn_str)
                intel.asn.name = org[len(org.split(" ")[0]) + 1:]
            except (ValueError, IndexError):
                pass
        intel.asn.country = info_ipinfo.get("country", "")
        intel.geo_city = info_ipinfo.get("city", "")
        intel.geo_region = info_ipinfo.get("region", "")
        loc = info_ipinfo.get("loc", "")
        if loc and "," in loc:
            try:
                parts = loc.split(",")
                intel.geo_lat = float(parts[0])
                intel.geo_lon = float(parts[1])
                intel.geo_accuracy = "approximate"
            except (ValueError, IndexError):
                pass

    if info_ipapi:
        intel.data_sources.append("ip-api.com")
        if not intel.asn.asn:
            asn_raw = info_ipapi.get("as", "")
            if asn_raw and " " in asn_raw:
                try:
                    intel.asn.asn = int(asn_raw.split(" ")[0].replace("AS", ""))
                    intel.asn.name = info_ipapi.get("asOrganization", "")
                except (ValueError, IndexError):
                    pass
        if not intel.asn.isp:
            pass
        intel.asn.isp = info_ipapi.get("isp", "")
        if not intel.geo_lat:
            intel.geo_lat = info_ipapi.get("lat", 0.0)
            intel.geo_lon = info_ipapi.get("lon", 0.0)
            intel.geo_accuracy = "approximate"
        if not intel.geo_city:
            intel.geo_city = info_ipapi.get("city", "")
            intel.geo_region = info_ipapi.get("regionName", "")
            intel.geo_country = info_ipapi.get("country", "")

    if intel.asn.asn:
        intel.data_sources.append("bgpview.io")

        asn_data = bgpview_asn_info(intel.asn.asn)
        if asn_data:
            if not intel.asn.name:
                intel.asn.name = asn_data.get("name", "")
            intel.asn.description = asn_data.get("description", "")
            intel.asn.registry = asn_data.get("registry", "")
            intel.asn.domains = asn_data.get("domains", [])
            intel.asn.prefixes_v4 = asn_data.get("prefixes_v4", 0)
            intel.asn.prefixes_v6 = asn_data.get("prefixes_v6", 0)
            intel.asn.visible = asn_data.get("visible", True)

        upstreams_raw = bgpview_asn_upstreams(intel.asn.asn)
        for u in upstreams_raw:
            rel = AsnRelationship(
                asn=u.get("asn", 0),
                name=u.get("name", ""),
                relationship="upstream",
                source="bgpview.io",
            )
            intel.upstreams.append(rel)

        peers_raw = bgpview_asn_peers(intel.asn.asn)
        for pe in peers_raw:
            if isinstance(pe, dict):
                rel = AsnRelationship(
                    asn=pe.get("asn", 0),
                    name=pe.get("name", ""),
                    relationship="peer",
                    source="bgpview.io",
                )
                intel.peers.append(rel)

        prefixes = bgpview_asn_prefixes(intel.asn.asn)
        if prefixes:
            for pfx in prefixes[:5]:
                if pfx.get("prefix"):
                    intel.prefix.prefix = pfx["prefix"]
                    intel.prefix.origin_asn = intel.asn.asn
                    intel.prefix.origin_name = intel.asn.name
                    break

        if intel.prefix.prefix:
            intel.bgp_path.prefix = intel.prefix.prefix
            intel.bgp_path.origin_asn = intel.asn.asn
            intel.bgp_path.as_path_names[intel.asn.asn] = intel.asn.name
            for u in intel.upstreams:
                if u.asn:
                    intel.bgp_path.as_path.append(u.asn)
                    intel.bgp_path.as_path_names[u.asn] = u.name
            intel.bgp_path.source = "bgpview.io"
            intel.bgp_path.confidence = "observed"
            intel.bgp_path.explanation = (
                "BGP observed path — this shows the autonomous systems that "
                "route announcements for this prefix pass through, not the "
                "exact physical path of your packets."
            )

    if not intel.asn.asn:
        intel.data_sources.append("no_asn_data")

    return intel
