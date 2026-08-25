"""IP/ASN/Geo resolver — reverse DNS, ASN lookup, geolocation."""
from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.request
import urllib.error
from typing import Optional

from engine.netmonitor.types import HopGeo, HopNetwork, DnsInfo


_GEO_CACHE: dict[str, dict] = {}
_ASN_CACHE: dict[str, dict] = {}
_DNS_CACHE: dict[str, list] = {}
_CACHE_TTL = 3600


def _api_get(url: str, timeout: float = 5.0) -> Optional[dict]:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MaximumTweaks-NetMonitor/1.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None


def reverse_dns(ip: str) -> str:
    if not ip or _is_private_ip(ip):
        return ""
    cache_key = ip
    if cache_key in _DNS_CACHE:
        return _DNS_CACHE[cache_key][0] if _DNS_CACHE[cache_key] else ""
    try:
        host, _, _ = socket.gethostbyaddr(ip)
        _DNS_CACHE[cache_key] = [host]
        return host
    except (socket.herror, socket.gaierror, OSError):
        _DNS_CACHE[cache_key] = [""]
        return ""


def resolve_dns(hostname: str) -> DnsInfo:
    info = DnsInfo(hostname=hostname)
    start = time.time()
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_INET)
        info.ipv4 = list({r[4][0] for r in results})
    except (socket.gaierror, OSError):
        pass
    try:
        results6 = socket.getaddrinfo(hostname, None, socket.AF_INET6)
        info.ipv6 = list({r[4][0] for r in results6})
    except (socket.gaierror, OSError):
        pass
    info.response_time = (time.time() - start) * 1000
    if info.ipv4:
        info.ipv4 = info.ipv4
    info.multiple_endpoints = len(info.ipv4) > 1 or len(info.ipv6) > 0
    return info


def lookup_geo(ip: str) -> HopGeo:
    if not ip or _is_private_ip(ip):
        return HopGeo()
    if ip in _GEO_CACHE:
        cached = _GEO_CACHE[ip]
        if time.time() - cached.get("_ts", 0) < _CACHE_TTL:
            return HopGeo(
                country=cached.get("country", ""),
                region=cached.get("regionName", ""),
                city=cached.get("city", ""),
                latitude=cached.get("lat", 0.0),
                longitude=cached.get("lon", 0.0),
                approximate=True,
            )

    data = _api_get(f"http://ip-api.com/json/{ip}?fields=66846719")
    if data and data.get("status") == "success":
        _GEO_CACHE[ip] = {**data, "_ts": time.time()}
        return HopGeo(
            country=data.get("country", ""),
            region=data.get("regionName", ""),
            city=data.get("city", ""),
            latitude=data.get("lat", 0.0),
            longitude=data.get("lon", 0.0),
            approximate=True,
        )
    return HopGeo()


def lookup_asn(ip: str) -> HopNetwork:
    if not ip or _is_private_ip(ip):
        return HopNetwork(is_private=_is_private_ip(ip))
    if ip in _ASN_CACHE:
        cached = _ASN_CACHE[ip]
        if time.time() - cached.get("_ts", 0) < _CACHE_TTL:
            return HopNetwork(
                asn=cached.get("asn", 0),
                as_org=cached.get("org", ""),
                isp=cached.get("isp", ""),
                network_name=cached.get("asOrganization", cached.get("org", "")),
                is_private=_is_private_ip(ip),
            )

    data = _api_get(
        f"http://ip-api.com/json/{ip}?fields=49377"
    )
    if data and data.get("status") == "success":
        _ASN_CACHE[ip] = {**data, "_ts": time.time()}
        asn_raw = data.get("as", "")
        asn_num = 0
        if asn_raw and " " in asn_raw:
            asn_str = asn_raw.split(" ")[0].replace("AS", "")
            try:
                asn_num = int(asn_str)
            except ValueError:
                pass
        return HopNetwork(
            asn=asn_num,
            as_org=data.get("org", ""),
            isp=data.get("isp", ""),
            network_name=data.get("asOrganization", data.get("org", "")),
            is_private=False,
        )
    return HopNetwork()


def resolve_hop(ip: str) -> tuple[str, HopNetwork, HopGeo]:
    hostname = reverse_dns(ip)
    network = lookup_asn(ip)
    geo = lookup_geo(ip)
    return hostname, network, geo


def classify_hop_role(
    hop_number: int,
    total_hops: int,
    ip: str,
    network: HopNetwork,
    geo: HopGeo,
    is_last: bool,
) -> str:
    if is_last or hop_number == total_hops:
        return "destination"
    if _is_private_ip(ip):
        if hop_number <= 2:
            return "gateway"
        return "local"
    if hop_number <= 2:
        return "gateway"
    if network.asn and any(
        kw in (network.as_org + network.isp).lower()
        for kw in ["cloudflare", "akamai", "cloudfront", "fastly", "edgecast"]
    ):
        return "cdn"
    if network.asn:
        if any(
            kw in (network.as_org + network.isp).lower()
            for kw in ["transit", "backbone", "tier 1", "global"]
        ):
            return "transit"
        if hop_number <= total_hops * 0.3:
            return "isp_access"
        elif hop_number <= total_hops * 0.6:
            return "isp_core"
        else:
            return "transit"
    return "unknown"


def _is_private_ip(ip: str) -> bool:
    if not ip:
        return False
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        first = int(parts[0])
        second = int(parts[1])
        if first == 10 or first == 127:
            return True
        if first == 172 and 16 <= second <= 31:
            return True
        if first == 192 and second == 168:
            return True
        if first == 169 and second == 254:
            return True
        if first == 0:
            return True
        if first == 100 and 64 <= second <= 127:
            return True
    except ValueError:
        pass
    return False


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def get_default_gateway() -> str:
    try:
        creation_flags = 0x08000000
        proc = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creation_flags,
        )
        for line in proc.stdout.split("\n"):
            if "Default Gateway" in line and ":" in line:
                gw = line.split(":")[-1].strip()
                if gw and gw != "None":
                    return gw
    except (subprocess.TimeoutExpired, OSError):
        pass
    return ""


def get_dns_resolver() -> str:
    try:
        creation_flags = 0x08000000
        proc = subprocess.run(
            ["ipconfig", "/all"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creation_flags,
        )
        in_adapter = False
        for line in proc.stdout.split("\n"):
            if "adapter" in line.lower():
                in_adapter = True
            if in_adapter and "DNS Servers" in line and ":" in line:
                dns = line.split(":")[-1].strip()
                if dns:
                    return dns
    except (subprocess.TimeoutExpired, OSError):
        pass
    return "8.8.8.8"
