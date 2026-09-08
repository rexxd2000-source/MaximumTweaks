"""Route measurement engine - traceroute with hop-by-hop enrichment.

Uses system tracert. Each hop gets ASN, GeoIP, reverse DNS.
All hops labeled with confidence and source.
"""
from __future__ import annotations

import subprocess
import re
import time
from typing import Optional, Callable

from engine.intel.models import (
    MeasuredRoute, RouteHop, HopType, MeasurementMethod, Confidence,
    DataSource, NetworkType, GeoInfo, AsnInfo, RouteClassification,
    DataSourceType,
)
from engine.intel.enrichment import lookup_geo, lookup_asn, lookup_rdns


_TRACERT_TIMEOUT = re.compile(r"^\s*(\d+)\s+\*\s+\*\s+\*")


def _classify_hop(
    hop_number: int, total_hops: int, geo: GeoInfo,
    asn: AsnInfo, rtt: float, prev_rtt: float, rdns: str,
) -> tuple[HopType, NetworkType, Confidence]:
    if hop_number == 1:
        return HopType.LOCAL_GATEWAY, NetworkType.ACCESS, Confidence.HIGH

    if hop_number == total_hops and hop_number > 1:
        return HopType.DESTINATION, NetworkType.DESTINATION, Confidence.HIGH

    asn_text = (asn.name + " " + asn.description).lower()
    if any(kw in asn_text for kw in ("backbone", "transit", "global", "tier 1")):
        return HopType.TRANSIT, NetworkType.BACKBONE, Confidence.MEDIUM

    if any(kw in asn_text for kw in ("internet exchange", "ixp", "peering")):
        return HopType.IXP, NetworkType.PEERING, Confidence.MEDIUM

    if any(kw in asn_text for kw in ("mobile", "broadband", "dsl", "fiber", "cable")):
        return HopType.ISP_ACCESS, NetworkType.ACCESS, Confidence.MEDIUM

    if geo.city and asn.asn:
        return HopType.TRANSIT, NetworkType.TRANSIT, Confidence.LOW

    if asn.asn:
        return HopType.TRANSIT, NetworkType.UNKNOWN, Confidence.LOW

    if hop_number <= 3 and rtt > 0 and rtt < 30:
        return HopType.ISP_ACCESS, NetworkType.ACCESS, Confidence.MEDIUM

    if prev_rtt > 0 and rtt > 0 and (rtt - prev_rtt) > 40 and hop_number > 2:
        return HopType.INTERNATIONAL, NetworkType.INTERNATIONAL, Confidence.LOW

    return HopType.TRANSIT, NetworkType.UNKNOWN, Confidence.LOW


def _parse_tracert_output(output: str) -> list[tuple[int, str, float]]:
    hops: list[tuple[int, str, float]] = []
    lines = output.split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("tracing") or line.lower().startswith("over a"):
            continue

        if _TRACERT_TIMEOUT.match(line):
            hop_num = int(line.split()[0])
            hops.append((hop_num, "", 0.0))
            continue

        tokens = line.split()
        if len(tokens) < 4:
            continue

        rtts: list[float] = []
        ip_candidate = ""

        for token in tokens[1:]:
            token_clean = token.strip("<").strip("ms").strip()
            if not token_clean or token_clean == "ms":
                continue
            if token_clean == "*":
                continue

            try:
                val = float(token_clean)
                rtts.append(val)
                continue
            except ValueError:
                pass

            if token_clean.startswith("[") and token_clean.endswith("]"):
                ip_candidate = token_clean[1:-1]
                continue

            if re.match(r"^[\d\.\-a-zA-Z:]+$", token_clean) and "." in token_clean:
                ip_candidate = token_clean

        if not ip_candidate:
            continue

        try:
            hop_num = int(tokens[0])
        except (ValueError, IndexError):
            continue

        avg_rtt = sum(rtts) / len(rtts) if rtts else 0.0
        hops.append((hop_num, ip_candidate, avg_rtt))

    return hops


def measure_route(
    destination: str,
    method: MeasurementMethod = MeasurementMethod.ICMP,
    timeout: int = 30,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> MeasuredRoute:
    """Blocking traceroute measurement. Call from a worker thread."""
    route = MeasuredRoute(
        destination_ip=destination,
        measurement=method,
        timestamp=time.time(),
        sources=[DataSource.now("traceroute", method.value, DataSourceType.MEASURED)],
    )

    if progress_cb:
        progress_cb(f"Starting traceroute to {destination}...")

    try:
        cmd = ["tracert", "-d", "-w", "1000", "-h", "15", destination]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        output = result.stdout
    except subprocess.TimeoutExpired:
        route.sources.append(DataSource.now("traceroute", "timeout", DataSourceType.MEASURED))
        if progress_cb:
            progress_cb("Traceroute timed out")
        return route
    except Exception as e:
        route.sources.append(DataSource.now("traceroute", f"error: {e}", DataSourceType.MEASURED))
        return route

    parsed = _parse_tracert_output(output)
    if not parsed:
        route.sources.append(DataSource.now("traceroute", "No hops parsed", DataSourceType.MEASURED))
        if progress_cb:
            progress_cb("No hops parsed from traceroute")
        return route

    total_hops = len(parsed)

    if progress_cb:
        progress_cb(f"Parsed {total_hops} hops, enriching...")

    prev_rtt = 0.0
    for hop_num, ip, avg_rtt in parsed:
        hop = RouteHop(
            number=hop_num,
            ip=ip,
            rtt_ms=avg_rtt,
            measurement=method,
            timestamp=time.time(),
        )

        if ip:
            hop.geo = lookup_geo(ip)
            hop.asn = lookup_asn(ip)
            hop.reverse_dns = lookup_rdns(ip)
            hop.sources = [
                DataSource.now("ip-api.com", "geo", DataSourceType.PUBLIC_METADATA),
                DataSource.now("bgpview.io", "asn", DataSourceType.PUBLIC_METADATA),
            ]

        hop.hop_type, hop.network_type, hop.confidence = _classify_hop(
            hop_num, total_hops, hop.geo, hop.asn, avg_rtt, prev_rtt, hop.reverse_dns,
        )

        hop.rtt_delta_ms = avg_rtt - prev_rtt if prev_rtt > 0 and avg_rtt > 0 else 0.0
        prev_rtt = avg_rtt

        route.hops.append(hop)

    if progress_cb:
        progress_cb("Enriching route metadata...")

    last_rtt_hop = [h for h in route.hops if h.rtt_ms > 0]
    if last_rtt_hop:
        route.total_latency_ms = last_rtt_hop[-1].rtt_ms

    route.total_hops = len(route.hops)

    route.data_availability["route"] = "measured via tracert"
    route.data_availability["latency"] = "measured"
    route.data_availability["asn"] = "from bgpview.io"
    route.data_availability["geo"] = "from ip-api.com"

    if progress_cb:
        progress_cb(f"Route complete: {route.total_hops} hops, {route.total_latency_ms:.0f}ms")

    return route


def compare_routes(prev: MeasuredRoute, curr: MeasuredRoute) -> tuple[bool, str]:
    """Compare two routes. Returns (changed, description)."""
    if not prev.hops or not curr.hops:
        return False, ""

    descriptions: list[str] = []

    if len(prev.hops) != len(curr.hops):
        descriptions.append(f"Hop count changed: {len(prev.hops)} -> {len(curr.hops)}")

    min_len = min(len(prev.hops), len(curr.hops))
    for i in range(min_len):
        p_hop = prev.hops[i]
        c_hop = curr.hops[i]
        if p_hop.ip != c_hop.ip:
            descriptions.append(f"Hop {i+1} changed: {p_hop.ip} -> {c_hop.ip}")
        elif abs(p_hop.rtt_ms - c_hop.rtt_ms) > 5.0:
            descriptions.append(
                f"Hop {i+1} latency: {p_hop.rtt_ms:.0f}ms -> {c_hop.rtt_ms:.0f}ms "
                f"(+{c_hop.rtt_ms - p_hop.rtt_ms:.0f}ms)"
            )

    if descriptions:
        return True, "; ".join(descriptions)
    return False, "No changes detected"


def classify_route(route: MeasuredRoute) -> RouteClassification:
    """Classify a measured route type."""
    if not route.hops:
        return RouteClassification(route_type="unknown", confidence=Confidence.UNKNOWN)

    hop_breakdown: dict[str, int] = {}
    for hop in route.hops:
        cls = hop.classification
        hop_breakdown[cls] = hop_breakdown.get(cls, 0) + 1

    total = len(route.hops)
    transit_count = sum(v for k, v in hop_breakdown.items() if k in ("transit",))
    gateway_count = hop_breakdown.get("gateway", 0)
    ixp_count = hop_breakdown.get("ixp", 0)
    dest_count = hop_breakdown.get("destination", 0)

    if total <= 3 and dest_count > 0:
        return RouteClassification(
            route_type="direct",
            confidence=Confidence.HIGH,
            description=f"Very short path ({total} hops) - likely direct peering or same city",
            hop_breakdown=hop_breakdown,
        )

    if ixp_count > 0 and transit_count > 2:
        return RouteClassification(
            route_type="peering",
            confidence=Confidence.MEDIUM,
            description=f"Route passes through IXP ({ixp_count} peering hops, {transit_count} transit)",
            hop_breakdown=hop_breakdown,
        )

    if transit_count > 3:
        return RouteClassification(
            route_type="transit",
            confidence=Confidence.MEDIUM,
            description=f"Heavy transit path ({transit_count} transit hops)",
            hop_breakdown=hop_breakdown,
        )

    if gateway_count >= 1 and dest_count > 0:
        return RouteClassification(
            route_type="standard",
            confidence=Confidence.HIGH,
            description=f"Standard ISP route ({gateway_count} gateway, {transit_count} transit)",
            hop_breakdown=hop_breakdown,
        )

    unique_asns = route.as_path
    as_summary = " -> ".join(f"AS{a}" for a in unique_asns[:6])

    return RouteClassification(
        route_type="multi-hop",
        confidence=Confidence.LOW,
        description=f"Multi-hop path ({total} hops)",
        hop_breakdown=hop_breakdown,
        as_path_summary=as_summary,
    )
