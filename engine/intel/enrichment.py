"""Network enrichment engine — ASN, RDAP, DNS, GeoIP, BGP.

For each IP, collects: ASN, prefix, geolocation, reverse DNS, BGP path.
All results cached. All results labeled with source and confidence.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.request
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from engine.intel.models import (
    AsnInfo, GeoInfo, BgpInfo, EnrichedEndpoint, NetworkConnection,
    DataSource, Confidence, EndpointClass, NetworkType,
)

_geo_cache: dict[str, GeoInfo] = {}
_asn_cache: dict[str, AsnInfo] = {}
_bgp_cache: dict[str, BgpInfo] = {}
_rdns_cache: dict[str, str] = {}
_CACHE_TTL = 3600
_USER_AGENT = "MaximumTweaks-Intel/1.0"


def _is_cached(cache: dict, key: str) -> bool:
    entry = cache.get(key)
    if entry is None:
        return False
    if hasattr(entry, "sources") and entry.sources:
        age = time.time() - entry.sources[0].timestamp
        return age < _CACHE_TTL
    return True


def _http_json(url: str, timeout: int = 5) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _http_text(url: str, timeout: int = 5) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode().strip()
    except Exception:
        return None


def _is_private_ip(ip: str) -> bool:
    return (
        ip.startswith("127.") or ip.startswith("10.") or
        ip.startswith("192.168.") or ip.startswith("172.") or
        ip == "::1" or ip == "" or ip == "0.0.0.0"
    )


def lookup_geo(ip: str) -> GeoInfo:
    if ip in _geo_cache and _is_cached(_geo_cache, ip):
        return _geo_cache[ip]

    if _is_private_ip(ip):
        result = GeoInfo(source="private", confidence=Confidence.CONFIRMED)
        _geo_cache[ip] = result
        return result

    data = _http_json(f"https://ip-api.com/json/{ip}?fields=status,country,countryCode,regionName,city,lat,lon")
    if data and data.get("status") == "success":
        result = GeoInfo(
            lat=data.get("lat", 0.0),
            lon=data.get("lon", 0.0),
            city=data.get("city", ""),
            region=data.get("regionName", ""),
            country=data.get("country", ""),
            country_code=data.get("countryCode", ""),
            source="ip-api.com",
            confidence=Confidence.MEDIUM,
        )
    else:
        result = GeoInfo(source="unknown", confidence=Confidence.UNKNOWN)

    _geo_cache[ip] = result
    return result


def lookup_asn(ip: str) -> AsnInfo:
    if ip in _asn_cache and _is_cached(_asn_cache, ip):
        return _asn_cache[ip]

    if _is_private_ip(ip):
        result = AsnInfo(source="private", confidence=Confidence.CONFIRMED)
        _asn_cache[ip] = result
        return result

    data = _http_json(f"https://api.bgpview.io/ip/{ip}")
    if data and data.get("status") == "ok":
        prefixes = data.get("data", {}).get("prefixes", [])
        if prefixes:
            p = prefixes[0]
            asn_num = p.get("asn", {}).get("asn", 0)
            asn_name = p.get("asn", {}).get("name", "")
            result = AsnInfo(
                asn=asn_num,
                name=asn_name,
                description=p.get("asn", {}).get("description", ""),
                country=p.get("asn", {}).get("country_code", ""),
                organization=p.get("name", ""),
                prefix=p.get("prefix", ""),
                source="bgpview.io",
                confidence=Confidence.HIGH if asn_num else Confidence.MEDIUM,
            )
            _asn_cache[ip] = result
            return result

    data2 = _http_json(f"https://ip-api.com/json/{ip}?fields=as,isp,org")
    if data2 and data2.get("as"):
        as_str = data2["as"]
        parts = as_str.split(" ", 1)
        asn_num = int(parts[0].replace("AS", "")) if parts[0].startswith("AS") else 0
        asn_name = parts[1] if len(parts) > 1 else data2.get("isp", "")
        result = AsnInfo(
            asn=asn_num,
            name=asn_name,
            source="ip-api.com",
            confidence=Confidence.MEDIUM,
        )
    else:
        result = AsnInfo(source="unknown", confidence=Confidence.UNKNOWN)

    _asn_cache[ip] = result
    return result


def lookup_bgp(ip: str) -> BgpInfo:
    if ip in _bgp_cache and _is_cached(_bgp_cache, ip):
        return _bgp_cache[ip]

    if _is_private_ip(ip):
        result = BgpInfo(source="private", confidence=Confidence.CONFIRMED)
        _bgp_cache[ip] = result
        return result

    data = _http_json(f"https://api.bgpview.io/ip/{ip}")
    if data and data.get("status") == "ok":
        prefixes = data.get("data", {}).get("prefixes", [])
        if prefixes:
            p = prefixes[0]
            origin_asn = p.get("asn", {}).get("asn", 0)
            origin_name = p.get("asn", {}).get("name", "")
            prefix_str = p.get("prefix", "")

            as_path = []
            as_path_names = []
            if prefix_str:
                pdata = _http_json(f"https://api.bgpview.io/prefix/{prefix_str}")
                if pdata and pdata.get("status") == "ok":
                    routes = pdata.get("data", {}).get("routes", [])
                    if routes:
                        as_path = routes[0].get("as_path", [])
                        as_path_names = routes[0].get("as_path_name", [])

            result = BgpInfo(
                prefix=prefix_str,
                origin_asn=origin_asn,
                origin_name=origin_name,
                as_path=as_path,
                as_path_names=as_path_names,
                source="bgpview.io",
                confidence=Confidence.HIGH if origin_asn else Confidence.MEDIUM,
            )
        else:
            result = BgpInfo(source="bgpview.io", confidence=Confidence.UNKNOWN)
    else:
        result = BgpInfo(source="unknown", confidence=Confidence.UNKNOWN)

    _bgp_cache[ip] = result
    return result


def lookup_rdns(ip: str) -> str:
    if ip in _rdns_cache:
        return _rdns_cache[ip]

    if _is_private_ip(ip):
        _rdns_cache[ip] = ""
        return ""

    try:
        hostname = socket.gethostbyaddr(ip)[0]
        _rdns_cache[ip] = hostname
        return hostname
    except (socket.herror, socket.gaierror, OSError):
        _rdns_cache[ip] = ""
        return ""


def detect_user_location() -> tuple[float, float, str, str]:
    """Returns (lat, lon, city, country_code) — coarse only, never precise."""
    data = _http_json("https://ip-api.com/json/?fields=lat,lon,city,country,countryCode")
    if data:
        return (
            data.get("lat", 0.0),
            data.get("lon", 0.0),
            data.get("city", ""),
            data.get("countryCode", ""),
        )
    return (0.0, 0.0, "", "")


def detect_isp() -> AsnInfo:
    data = _http_json("https://ip-api.com/json/?fields=as,isp,org")
    if data and data.get("as"):
        as_str = data["as"]
        parts = as_str.split(" ", 1)
        asn_num = int(parts[0].replace("AS", "")) if parts[0].startswith("AS") else 0
        asn_name = parts[1] if len(parts) > 1 else data.get("isp", "")
        return AsnInfo(
            asn=asn_num,
            name=asn_name,
            source="ip-api.com",
            confidence=Confidence.HIGH,
        )
    return AsnInfo(source="unknown", confidence=Confidence.UNKNOWN)


def enrich_endpoint(
    ip: str,
    port: int = 0,
    protocol: str = "",
    process_name: str = "",
    pid: int = 0,
) -> EnrichedEndpoint:
    geo = lookup_geo(ip)
    asn = lookup_asn(ip)
    bgp = lookup_bgp(ip)
    rdns = lookup_rdns(ip)

    conf = Confidence.HIGH if asn.asn else Confidence.MEDIUM

    return EnrichedEndpoint(
        ip=ip,
        port=port,
        protocol=protocol,
        hostname=rdns,
        reverse_dns=rdns,
        asn=asn,
        geo=geo,
        bgp=bgp,
        confidence=conf,
        first_seen=time.time(),
        last_seen=time.time(),
        observation_count=1,
        associated_process=process_name,
        process_pid=pid,
        sources=[DataSource.now("enrichment_engine", "bulk")],
    )


def enrich_connections_batch(
    connections: list[NetworkConnection],
    max_workers: int = 8,
) -> list[EnrichedEndpoint]:
    seen_ips: dict[str, NetworkConnection] = {}
    for conn in connections:
        if conn.remote_ip and conn.remote_ip not in seen_ips:
            seen_ips[conn.remote_ip] = conn

    enriched: list[EnrichedEndpoint] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                enrich_endpoint,
                conn.remote_ip,
                conn.remote_port,
                conn.protocol,
                conn.process_name,
                conn.pid,
            ): conn.remote_ip
            for conn in seen_ips.values()
        }
        for future in as_completed(futures):
            try:
                enriched.append(future.result())
            except Exception:
                pass

    return enriched
