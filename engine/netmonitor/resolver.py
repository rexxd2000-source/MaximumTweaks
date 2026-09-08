"""IP/ASN/Geo resolver — reverse DNS, ASN lookup, geolocation."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import urllib.request
import urllib.error
from typing import Optional

from engine.netmonitor.types import HopGeo, HopNetwork, DnsInfo


_GEO_CACHE: dict[str, dict] = {}
_ASN_CACHE: dict[str, dict] = {}
_DNS_CACHE: dict[str, list] = {}
_CACHE_TTL = 3600

# Persisted geolocation cache. ip-api's answers for the same IP can vary
# between calls (registered-office / HQ noise), which made a hop's label
# flip-flop between runs. Once an IP is resolved, it is pinned to that answer
# for a week and reused from disk so the SAME IP always renders the SAME label.
_GEO_CACHE_TTL = 604800  # 7 days — determinism across traces and restarts
_GEO_CACHE_FILE: str | None = None
_GEO_CACHE_LOCK = threading.Lock()


def _geo_cache_path() -> str:
    global _GEO_CACHE_FILE
    if _GEO_CACHE_FILE is None:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        _GEO_CACHE_FILE = os.path.join(base, "MaximumTweaks", "geo_cache.json")
    return _GEO_CACHE_FILE


def _load_geo_cache() -> None:
    try:
        with open(_geo_cache_path(), encoding="utf-8") as fh:
            data = json.loads(fh.read() or "{}")
        for key, val in (data or {}).items():
            if isinstance(val, dict) and ("country" in val or "city" in val):
                _GEO_CACHE[key] = val
    except Exception:
        pass  # cold start / corrupt file: rebuild from live lookups


def _save_geo_cache() -> None:
    try:
        path = _geo_cache_path()
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with _GEO_CACHE_LOCK, open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_GEO_CACHE, ensure_ascii=False))
    except Exception:
        pass


_load_geo_cache()

# ASNs that announce Anycast. Geolocating these to a single city (e.g. a
# Google anycast IP pinned to Mountain View HQ) is wrong — the real PoP is
# wherever the player's traffic egresses regionally (NAPAfrica/JINX, etc).
# Note: 396982 (game host pools) is deliberately NOT here — those addresses
# resolve to a concrete cloud region (e.g. Doha) worth showing as-is.
_ANYCAST_ASNS: set[int] = {
    15169,   # Google (also 36040, 19527, 41264)
    36040,
    19527,
    13335,   # Cloudflare
    209242,
    16509,   # Amazon
    14618,
    20940,   # Akamai
    35994,
    16625,
    54113,   # Fastly
    36459,
    13414,   # Facebook/Meta edge
    32934,
}


def is_anycast_asn(asn: int) -> bool:
    return asn in _ANYCAST_ASNS


def tag_anycast(network: HopNetwork, is_endpoint: bool = False) -> bool:
    """Mark `network.network_type` for anycast ASNs.

    Endpoints keep their resolved geo (regional for honest host pools), but the
    type still flags that the location is an approximation — display code must
    never present an anycast city as the actual routing location.
    Returns True when tagged.
    """
    if network.asn and is_anycast_asn(network.asn):
        network.network_type = "anycast_edge" if is_endpoint else "anycast"
        return True
    return False


def anycast_pin(network: HopNetwork, hop, route) -> None:
    """Re-anchor an anycast hop's geo to the nearest *path* anchor so the
    label reflects the regional peering point instead of the DB's HQ city.

    Strategy: if a later public hop on the same route has a known city, use
    the *next* such hop (the exit toward the server) and mark it approximate.
    Otherwise — no trustworthy regional anchor — we NEVER present a geo-DB HQ
    city (e.g. "Mountain View") as fact: the city becomes "Anycast Edge" and
    the coordinates are cleared so no fake marker is pinned on the map.
    """
    if network.network_type != "anycast":
        return
    hops = [h for h in route.hops if h.ip and not _is_private_ip(h.ip) and h.geo.city]
    try:
        idx = next(i for i, h in enumerate(hops) if h.ip == hop.ip)
    except StopIteration:
        idx = -1
    if idx >= 0 and idx + 1 < len(hops):
        nxt = hops[idx + 1]
        if nxt.geo.city and "near POP" not in nxt.geo.city:
            hop.geo.city = f"{nxt.geo.city} (near POP)"
            hop.geo.country = nxt.geo.country or hop.geo.country
            hop.geo.latitude = nxt.geo.latitude
            hop.geo.longitude = nxt.geo.longitude
            hop.geo.approximate = True
            return
    # No regional anchor → refuse to fake a geo-DB HQ location.
    hop.geo.city = "Anycast Edge"
    hop.geo.region = ""
    hop.geo.country = ""
    hop.geo.latitude = 0.0
    hop.geo.longitude = 0.0
    hop.geo.approximate = True


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
        if time.time() - cached.get("_ts", 0) < _GEO_CACHE_TTL:
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
        _save_geo_cache()  # persist: same IP must stay the same label forever
        return HopGeo(
            country=data.get("country", ""),
            region=data.get("regionName", ""),
            city=data.get("city", ""),
            latitude=data.get("lat", 0.0),
            longitude=data.get("lon", 0.0),
            approximate=True,
        )
    return HopGeo()


_PUB_GEO_CACHE: tuple[Optional[HopGeo], float] = (None, 0.0)


def get_public_geo() -> HopGeo:
    """Geolocate the caller itself (ip-api no-IP lookup), cached one hour.

    This is the only trustworthy user anchor for physics/plausibility checks —
    a LAN IP like 192.168.x never exists in the geo DB and must not be used.
    """
    global _PUB_GEO_CACHE
    cached, ts = _PUB_GEO_CACHE
    if cached is not None and time.time() - ts < _CACHE_TTL:
        return cached
    data = _api_get("http://ip-api.com/json/?fields=66846719")
    if data and data.get("status") == "success":
        geo = HopGeo(
            country=data.get("country", ""),
            region=data.get("regionName", ""),
            city=data.get("city", ""),
            latitude=data.get("lat", 0.0),
            longitude=data.get("lon", 0.0),
            approximate=True,
        )
        _PUB_GEO_CACHE = (geo, time.time())
        return geo
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
        # status..lot+timezone, isp, org, as, asname, reverse — the mask MUST
        # include `as` (4096) + `org` (2048) or ASN detection is always 0.
        f"http://ip-api.com/json/{ip}?fields=32767"
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
