"""Cloud-provider geo override from the providers' OWN published feeds.

ip-api's geo DB is frequently wrong for cloud ranges, and hand-curated
CIDR->city overrides turned out to be worse (a guessed 'GCP us-west1 /
Stockton' label for 34.18.0.0/16 was overriding the *correct* ip-api/Doha
answer - the whole 34.18.0.0/16 range is Google's me-central1 Middle East
pool). So instead of guessing, provider_geo() consults a snapshot of what
the providers actually publish:

  GCP : https://www.gstatic.com/ipranges/cloud.json     (1003 IPv4 prefixes)
  AWS : https://ip-ranges.amazonaws.com/ip-ranges.json  (10520 IPv4 prefixes)

The snapshot lives in cloud_regions.json next to this file and is bundled
into the EXE. Membership is authoritative (verified=True). A city/coords
pin is applied ONLY when the region is in the confident REGION_COORDS table
of the generator; otherwise the hop is labeled just "GCP <scope>" / "AWS
<region>" with no fabricated city. Anycast pools (scope "global"/"GLOBAL")
are never pinned to a single city.
"""
from __future__ import annotations

import ipaddress
import json
import os
import sys
from typing import Optional

from engine.netmonitor.types import HopGeo

_ANYCAST_SCOPES = {"global", "GLOBAL", "anycast"}


def _data_path() -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "engine", "netmonitor", "cloud_regions.json")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloud_regions.json")


def _load_provider_ranges():
    """Return (ranges, coords). Millisecond cost, once, at import. If the
    snapshot is missing/currupt we degrade gracefully to no overrides."""
    ranges: list[tuple[ipaddress.IPv4Network, str, str]] = []
    coords: dict = {}
    try:
        with open(_data_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        coords = data.get("coords") or {}
        for cidr, provider, scope in data.get("ranges") or []:
            ranges.append((ipaddress.ip_network(cidr), provider, scope))
        if not ranges:
            return [], {}
    except Exception:
        return [], {}
    ranges.sort(key=lambda r: r[0].prefixlen, reverse=True)
    return ranges, coords


# (network, provider, scope) sorted most-specific-first. First hit wins.
_PROVIDER_NETS, _REGION_COORDS = _load_provider_ranges()

# Public/peering/edge ranges that are NOT game-server datacenters. ip-api
# labels most of these with the provider's corporate HQ city (e.g. Google's
# peering block 72.14.216.130 showing "Mountain View, California" while a
# South-African hop measures 28 ms to it). After the provider-range override
# misses, any hop inside these must be de-geolocated: no city/region/coords,
# honest label via the AS org only (Bug 3).
_PUBLIC_EDGE_RANGES: list[tuple[str, str]] = [
    # Google (search/edge/peering/DNS — everything outside the GCP 34.x/35.x DC pools).
    ("72.14.192.0/18", "Google public range"),
    ("66.249.0.0/18", "Google public range"),
    ("66.102.0.0/20", "Google public range"),
    ("64.233.160.0/19", "Google public range"),
    ("74.125.0.0/16", "Google public range"),
    ("72.14.0.0/17", "Google public range"),
    ("8.8.4.0/24", "Google DNS (anycast)"),
    ("8.8.8.0/24", "Google DNS (anycast)"),
    ("172.217.0.0/16", "Google public range"),
    ("172.253.0.0/16", "Google public range"),
    ("142.250.0.0/15", "Google public range"),
    ("216.58.192.0/19", "Google public range"),
    ("209.85.128.0/17", "Google public range"),
    ("108.177.0.0/17", "Google public range"),
    ("199.97.0.0/16", "Google backbone"),
    # CloudFront / Akamai / Meta anycast edges — a single city is always wrong.
    ("13.32.0.0/15", "CloudFront edge"),
    ("13.224.0.0/14", "CloudFront edge"),
    ("52.84.0.0/15", "CloudFront edge"),
    ("54.230.0.0/16", "CloudFront edge"),
    ("205.251.192.0/19", "CloudFront edge"),
    ("23.32.0.0/11", "Akamai edge"),
    ("104.109.0.0/16", "Akamai edge"),
    ("157.240.0.0/16", "Meta CDN (anycast)"),
]

_PUBLIC_EDGE_NETS = [(ipaddress.ip_network(cidr), label) for cidr, label in _PUBLIC_EDGE_RANGES]

# Orgs whose public (non-datacenter) ranges get an HQ city from ip-api that is
# almost never the endpoint location — same "no fake HQ pin" rule as above.
_EDGE_ORG_KEYWORDS: list[tuple[str, str]] = [
    ("google", "Google public range"),
    ("amazon", "CloudFront edge"),
    ("cloudfront", "CloudFront edge"),
    ("akamai", "Akamai edge"),
    ("fastly", "Fastly edge"),
    ("facebook", "Meta CDN"),
    ("meta", "Meta CDN"),
]


def cloud_edge_hint(ip: str, as_org: str = "") -> str:
    """Honest label for a public/peering/edge hop that we deliberately do NOT
    geolocate. Returns "" when the hop is a datacenter range, private, or an
    ordinary ISP — those keep their normal handling."""
    if not ip:
        return ""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ""
    if addr.version != 4:
        return ""
    # Curated provider (datacenter) ranges win over any edge label — a GCP/AWS
    # pool is a real, published location, not an "edge/HQ" guess.
    for net, _provider, _scope in _PROVIDER_NETS:
        if addr in net:
            return ""
    for net, label in _PUBLIC_EDGE_NETS:
        if addr in net:
            return label
    org_l = (as_org or "").lower()
    for kw, label in _EDGE_ORG_KEYWORDS:
        if kw in org_l:
            return label
    return ""


# AS-organization keywords that mark a cloud/anycast range regardless of IP.
_CLOUD_ORG_KEYWORDS: list[tuple[str, str]] = [
    ("google", "GCP"),
    ("amazon", "AWS"),
    ("aws", "AWS"),
    ("microsoft", "Azure"),
    ("azure", "Azure"),
    ("oracle", "Oracle Cloud"),
    ("digitalocean", "DigitalOcean"),
    ("ovh", "OVH"),
    ("cloudflare", "Cloudflare anycast"),
    ("akamai", "Akamai"),
    ("fastly", "Fastly anycast"),
]


def provider_geo(ip: str, as_org: str = "") -> Optional[HopGeo]:
    """Return a provider-verified HopGeo for `ip` when it falls inside a
    prefix the provider publishes (GCP/AWS authoritative snapshot). Never
    network — pure local table. Anycast scopes return a geo with NO city or
    coordinates (verified, so nothing else gets pinned over it)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if not addr.version == 4:
        return None
    for net, provider, scope in _PROVIDER_NETS:
        if addr in net:
            scope_l = scope.lower()
            if scope_l in _ANYCAST_SCOPES:
                return HopGeo(
                    country="",
                    region="",
                    city="",
                    latitude=0.0,
                    longitude=0.0,
                    approximate=True,
                    verified=True,
                    hint=f"provider-anycast range ({provider} {scope}); "
                    "no single location",
                )
            c = _REGION_COORDS.get(f"{provider}:{scope}") or {}
            lat = float(c.get("lat", 0.0))
            lon = float(c.get("lon", 0.0))
            if not c or not (lat or lon):
                return HopGeo(
                    country=c.get("cc", "") if c else "",
                    region=c.get("region", "") if c else "",
                    city=c.get("city", "") if c else "",
                    latitude=lat,
                    longitude=lon,
                    approximate=True,
                    verified=True,
                    hint=f"provider range ({provider} {scope}) — region known, "
                    "exact city not published",
                )
            return HopGeo(
                country=c["cc"],
                region=c["region"],
                city=c["city"],
                latitude=lat,
                longitude=lon,
                approximate=True,
                verified=True,
                hint=f"provider range ({provider} {scope})",
            )
    return None


def cloud_hint(as_org: str = "") -> str:
    """Hint + provider name when the AS org belongs to a known cloud."""
    if not as_org:
        return ""
    org_l = as_org.lower()
    for kw, name in _CLOUD_ORG_KEYWORDS:
        if kw in org_l:
            return f"cloud range ({name})"
    return ""


def is_cloud_range(as_org: str = "") -> bool:
    return bool(cloud_hint(as_org))


def is_cloud_ip(ip: str) -> bool:
    """True when the address sits inside a major cloud/backbone published
    prefix (GCP/AWS/Azure pools, Google public/backbone, CloudFront, Akamai).

    Proof-driven policy: inside these zones traceroute-class probes are
    deterministically dropped by design (Google never answers TTL-exceeded,
    and its servers never answer ICMP echo) — so the traceroute must skip ICMP
    once the path enters one, and treat deep-hops silence as the block, not as
    a broken path. Uses only the local authoritative ranges (no network calls),
    so it is safe to call during the hot probe loop."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    # Provider (datacenter) pools — the authoritative cloud.json / AWS ranges.
    for net, _provider, _scope in _PROVIDER_NETS:
        if addr in net:
            return True
    # Public/peering/backbone ranges (Google search/backbone, CDN edges).
    for net, _label in _PUBLIC_EDGE_NETS:
        if addr in net:
            return True
    return False