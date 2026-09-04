"""Data structures for the network monitoring / route analysis engine."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ProbeMethod(Enum):
    ICMP = "icmp"
    TCP = "tcp"
    UDP = "udp"
    UNKNOWN = "unknown"


class HopStatus(Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    PRIVATE = "private"
    LOCAL = "local"


class RouteHealth(Enum):
    GOOD = "good"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class HopRole(Enum):
    LOCAL = "local"
    GATEWAY = "gateway"
    ISP_ACCESS = "isp_access"
    ISP_CORE = "isp_core"
    TRANSIT = "transit"
    PEERING = "peering"
    CDN = "cdn"
    EDGE = "edge"
    DESTINATION = "destination"
    UNKNOWN = "unknown"


class ViewMode(Enum):
    BASIC = "basic"
    ADVANCED = "advanced"


@dataclass
class HopGeo:
    country: str = ""
    region: str = ""
    city: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    approximate: bool = True
    # False when a plausibility/region check rejected the claimed location
    # (measured latency below the fiber floor, or cloud range reassignment).
    verified: bool = True
    hint: str = ""
    # Where the city name came from: ""/geo_db (third-party database,
    # unverifiable), "hostname" (ISP's own rDNS PoP code - authoritative),
    # "isp_prefix" (hand-verified ISP table), "afrinic" (RIR allocation)
    city_source: str = ""


@dataclass
class GeoPoint:
    """Coordinate pair for speed-of-light distance math."""
    latitude: float = 0.0
    longitude: float = 0.0
    city: str = ""
    country: str = ""


@dataclass
class HopNetwork:
    asn: int = 0
    as_org: str = ""
    isp: str = ""
    network_name: str = ""
    network_type: str = ""
    is_private: bool = False
    is_cgnat: bool = False


@dataclass
class HopProbes:
    sent: int = 0
    received: int = 0
    lost: int = 0
    timeouts: int = 0
    packet_loss_pct: float = 0.0
    min_latency: float = 0.0
    max_latency: float = 0.0
    avg_latency: float = 0.0
    jitter: float = 0.0
    latency_samples: list[float] = field(default_factory=list)
    timestamps: list[float] = field(default_factory=list)
    raw_hint: str = ""


@dataclass
class Hop:
    number: int
    ip: str = ""
    hostname: str = ""
    status: HopStatus = HopStatus.UNKNOWN
    role: HopRole = HopRole.UNKNOWN
    probes: HopProbes = field(default_factory=HopProbes)
    network: HopNetwork = field(default_factory=HopNetwork)
    geo: HopGeo = field(default_factory=HopGeo)
    method: ProbeMethod = ProbeMethod.ICMP
    is_last_hop: bool = False
    raw_response: str = ""

    @property
    def latency(self) -> float:
        return self.probes.avg_latency

    @property
    def jitter(self) -> float:
        return self.probes.jitter

    @property
    def packet_loss(self) -> float:
        return self.probes.packet_loss_pct

    @property
    def display_name(self) -> str:
        if self.hostname:
            return self.hostname
        if self.ip:
            return self.ip
        return "*"

    @property
    def location_str(self) -> str:
        parts = []
        if self.geo.city:
            parts.append(self.geo.city)
        if self.geo.region:
            parts.append(self.geo.region)
        if self.geo.country:
            parts.append(self.geo.country)
        return ", ".join(parts) if parts else ""

    @property
    def location_label(self) -> str:
        """Honest display location.

        Anycast hops (CDN/game edges like Google, Cloudflare, Akamai) are
        announced from many PoPs at once — a geo-DB city for them is a guess
        of where traffic *might* egress, never the actual path, so it must
        not be presented as the routing location. We render:
          * the regional path anchor when one was pinned ("Doha (near POP)"), or
          * the network org ("Google LLC", "Anycast Edge") otherwise.
        """
        if not self.geo.verified:
            # Physics/region gate rejected this hop's claimed city (a router
            # 4 ms away can't sit 1,000 km away in a geo-DB city like "Port
            # Elizabeth" — ip-api guesses HQ/registered office for ISP ranges).
            # Never present a rejected city as fact: use the network org / IP.
            org = (self.network.as_org or self.network.network_name or "").strip()
            if org:
                return org
            return self.ip or "location unverified"
        if 0 < self.latency < 15.0 and (
            self.network.network_type in ("isp", "backbone", "edge")
        ):
            # Sub-15ms in-country hop (typically an ISP/backbone router 0-700 km
            # away). A geo-DB city here is registered-office granularity, not
            # the router's real location (measured: ip-api flips these between
            # "Johannesburg" and "Port Elizabeth" for the same SA ranges) — show
            # the network org, never a city. EXCEPTION: when the city came from
            # the ISP's own hostname / ISP table, it IS the real PoP and is kept.
            name = getattr(self.geo, "city_source", "") or ""
            if name in ("", "geo_db"):
                org = (self.network.as_org or self.network.network_name or "").strip()
                return org or (self.ip or "network hop")
        if self.network.network_type in ("anycast", "anycast_edge"):
            if self.geo.city and "near POP" in self.geo.city:
                parts = [self.geo.city]
                if self.geo.country:
                    parts.append(self.geo.country)
                return ", ".join(parts)
            org = (self.network.as_org or self.network.network_name or "").strip()
            return org or "Anycast Edge"
        return self.location_str


@dataclass
class LiveRttStats:
    """Real-time latency measured from the live game's own socket traffic.

    This is the authoritative number the player sees in-match — it is NOT a
    fabric of an intermediate hop's latency. When present it mirrors the
    match metrics exactly (pairing outbound client packets with the server's
    responses on the same remote port).
    """
    source: str = "none"   # "live_game_traffic" | "probe" | "none"
    median_ms: float = 0.0
    avg_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    # EMA-smoothed BEST round trip of the causal probes. Empirically this is
    # the number the game's own HUD ping display mirrors (SA->Doha rig:
    # game "144" vs best "143.5"; game "139" vs best "145.6") — Unreal shows
    # a smoothed best-case RTT rather than the traffic-inflated window median.
    best_ms: float = 0.0
    jitter_ms: float = 0.0
    loss_pct: float = 0.0
    samples: int = 0
    updated: float = 0.0


@dataclass
class Route:
    route_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    destination: str = ""
    destination_ip: str = ""
    destination_ips: list[str] = field(default_factory=list)
    protocol: ProbeMethod = ProbeMethod.ICMP
    hops: list[Hop] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    scan_duration: float = 0.0
    total_hops: int = 0
    max_ttl: int = 30
    live_rtt: Optional[LiveRttStats] = None
    rtt_source: str = "probe"  # "live_game" | "probe"
    # Real re-measurement through an active VPN/GPN tunnel (never a static
    # mock). Populated only when a genuine tunnel instance routes the server.
    tunnel_route: Optional["Route"] = None
    tunnel_info: Optional[dict] = None
    # Speed-of-light plausibility gate.
    latency_floor_ms: float = 0.0      # ~= 2 * fiber_distance / c_glass
    fiber_distance_km: float = 0.0
    physics_implausible: bool = False
    physics_reason: str = ""
    # Trace-to-trace swing of the headline number across recent scans
    # (engine-fed). Confidence must drop when the number itself is unstable —
    # a wildly-varying RTT can never be "high confidence".
    hist_lat_range_ms: float = 0.0
    # Ground-truth cross-check against the OS's own tracert run to the same
    # destination (engine-fed once per session): how many of the OS's public
    # hop IPs our probe path reproduced, in order.
    os_tracert_match: Optional[dict] = None
    # True when the terminal hop never answered ANY probe (probe-silent server:
    # cloud-zone hosts, firewalled game pools). The trace terminates at the
    # server IP but has NO trustworthy end-to-end latency — the hop-average of
    # intermediate routers is not the server RTT, and showing it fabricates a
    # "ping" (e.g. 25 ms of the SA Internet edge for a Doha server measured at
    # ~136 ms in-game). Such routes are honest only via the live match stream.
    probe_silent_endpoint: bool = False
    # BGP routing intelligence for the international leg (spec: BGP
    # looking-glass data, honestly labeled as BGP-sourced — never live
    # traceroute latency). Engine-fed once per session; empty dict = no data.
    #   {"resolved": bool, "source": str,
    #    "isp":  {ip, asn, name, country}|None,
    #    "dest": {ip, asn, name, country, city}|None}
    bgp_path: dict = field(default_factory=dict)

    @property
    def avg_latency(self) -> float:
        if not self.hops:
            return 0.0
        valid = [
            h for h in self.hops
            if (h.status == HopStatus.HEALTHY or h.status == HopStatus.PRIVATE)
            and h.latency > 0
        ]
        return sum(h.latency for h in valid) / len(valid) if valid else 0.0

    @property
    def total_latency(self) -> float:
        # Prefer the real-time match measurement — it is the true server RTT.
        if self.live_rtt and self.live_rtt.median_ms > 0:
            return self.live_rtt.median_ms
        if not self.hops:
            return 0.0
        dest = self.hops[-1] if self.hops else None
        if dest and dest.latency > 0 and (
            dest.status == HopStatus.HEALTHY or dest.status == HopStatus.PRIVATE
        ):
            return dest.latency
        # No average-of-hops fallback: for a probe-silent server that number is
        # the intermediate (SA-edge) latency, presented as the server's ping —
        # exactly the "25 ms to Doha" fabric. Only a real measurement of the
        # endpoint counts; until then the total is 0 and the UI says so.
        return 0.0

    @property
    def route_jitter(self) -> float:
        if self.live_rtt and self.live_rtt.jitter_ms > 0:
            return self.live_rtt.jitter_ms
        valid = [h for h in self.hops if h.status == HopStatus.HEALTHY]
        return max((h.jitter for h in valid), default=0.0)

    @property
    def probe_totals(self) -> tuple[int, int]:
        """(sent, received) probes across all hops. When live RTT driving the
        headline exists its sample count replaces the hop probe basis — the
        headline number's confidence must be about *its own* measurement, not
        an unrelated traceroute's."""
        sent = sum(h.probes.sent for h in self.hops)
        received = sum(h.probes.received for h in self.hops)
        if self.live_rtt and self.live_rtt.samples > 0:
            live_loss = max(0.0, min(100.0, self.live_rtt.loss_pct))
            sent = self.live_rtt.samples
            received = int(round(sent * (1 - live_loss / 100.0)))
        return sent, received

    @property
    def confidence(self) -> tuple[str, str]:
        """(tier, basis_text) for whatever number total_latency reports.

        A timeout is never reported as latency, but a headline built from a
        minority of samples must still be labelled. The shown LOSS% and the
        "answered" basis come from the SAME source so they can never contradict:
          * live-match stream → both from the live RTT sample set;
          * otherwise → both from the destination hop's own probe counters
        (that hop is what total_latency actually reports). A final hop losing
        more than half its probes, or a headline that swings heavily between
        scans, can never earn HIGH confidence (Bug 17).
        """
        tier = "none"
        basis = "no probes"

        if self.live_rtt and self.live_rtt.samples > 0:
            sent = self.live_rtt.samples
            loss = max(0.0, min(100.0, float(self.live_rtt.loss_pct)))
            received = max(0, sent - int(round(sent * loss / 100.0)))
            answered = (received / sent * 100.0) if sent else 0.0
            basis = f"based on {received}/{sent} live match samples"
        else:
            dest = self.hops[-1] if self.hops else None
            if dest is not None and dest.probes.sent > 0:
                sent = dest.probes.sent
                received = dest.probes.received
                answered = (received / sent * 100.0) if sent else 0.0
                basis = (
                    f"based on {received}/{sent} final-hop probes"
                    f" ({answered:.0f}% answered)"
                )
                if answered < 50.0:
                    return "low", basis + " \u2014 final hop lost most probes"
            else:
                sent = sum(h.probes.sent for h in self.hops)
                received = sum(h.probes.received for h in self.hops)
                answered = (received / sent * 100.0) if sent else 0.0
                basis = f"based on {received}/{sent} probes ({answered:.0f}% answered)"
            if sent <= 0:
                return "none", basis

        if answered > 50.0:
            tier = "high"
        elif answered >= 15.0:
            tier = "medium"
        else:
            tier = "low"

        # Trace-to-trace variance cap: a value that swings wildly between
        # consecutive scans must not present as trustworthy (Bug 17).
        rng = self.hist_lat_range_ms
        if rng > 0:
            med = self.total_latency if self.total_latency > 0 else 1.0
            if rng > max(150.0, med * 0.6):
                tier = "low"
                basis += f" \u2014 unstable ({rng:.0f} ms swing across scans)"
            elif rng > max(60.0, med * 0.3) and tier == "high":
                tier = "medium"
                basis += f" \u2014 variable ({rng:.0f} ms swing)"
        return tier, basis

    @property
    def route_packet_loss(self) -> float:
        if self.live_rtt and self.live_rtt.samples > 0:
            return self.live_rtt.loss_pct
        dest = self.hops[-1] if self.hops else None
        if dest:
            return dest.packet_loss
        return 0.0

    @property
    def health(self) -> RouteHealth:
        loss = self.route_packet_loss
        jitter = self.route_jitter
        lat = self.total_latency
        if loss > 15 or lat > 300:
            return RouteHealth.CRITICAL
        if loss > 5 or jitter > 30 or lat > 150:
            return RouteHealth.DEGRADED
        if self.hops:
            return RouteHealth.GOOD
        return RouteHealth.UNKNOWN

    @property
    def path_summary(self) -> str:
        names = ["PC"]
        for h in self.hops:
            name = h.display_name
            loc = h.location_label
            if loc and len(loc) < 22:
                name = loc
            names.append(name)
        if not names[-1] == self.destination:
            names.append(self.destination)
        return " → ".join(names)


@dataclass
class RouteChange:
    timestamp: float = field(default_factory=time.time)
    change_type: str = ""
    description: str = ""
    old_route_id: str = ""
    new_route_id: str = ""
    hop_delta: int = 0
    latency_delta: float = 0.0
    affected_hops: list[int] = field(default_factory=list)


@dataclass
class RouteComparison:
    current: Optional[Route] = None
    previous: Optional[Route] = None
    hop_delta: int = 0
    latency_delta: float = 0.0
    jitter_delta: float = 0.0
    loss_delta: float = 0.0
    changed_hops: list[int] = field(default_factory=list)
    new_hops: list[int] = field(default_factory=list)
    removed_hops: list[int] = field(default_factory=list)


@dataclass
class RouteEvent:
    timestamp: float = field(default_factory=time.time)
    level: str = "info"
    message: str = ""
    details: str = ""


@dataclass
class DnsInfo:
    resolver: str = ""
    hostname: str = ""
    ipv4: list[str] = field(default_factory=list)
    ipv6: list[str] = field(default_factory=list)
    response_time: float = 0.0
    multiple_endpoints: bool = False


@dataclass
class MonitorState:
    destination: str = ""
    destination_ip: str = ""
    active_route: Optional[Route] = None
    previous_route: Optional[Route] = None
    route_history: list[Route] = field(default_factory=list)
    changes: list[RouteChange] = field(default_factory=list)
    events: list[RouteEvent] = field(default_factory=list)
    dns_info: Optional[DnsInfo] = None
    monitoring: bool = False
    scan_count: int = 0
    last_scan_time: float = 0.0
    hop_latency_history: dict[int, list[tuple[float, float]]] = field(
        default_factory=dict
    )
    live_target_ip: str = ""
    live_remote_ports: list[int] = field(default_factory=list)
    live_client_ports: list[int] = field(default_factory=list)
    live_target_ports_text: str = ""
    # The locked live target stopped receiving traffic (match ended / server
    # rotated). Signals the UI to re-run the detection pipeline fresh.
    live_stale: bool = False

    @property
    def has_live_target(self) -> bool:
        return bool(self.live_target_ip and self.live_remote_ports)

    @property
    def comparison(self) -> RouteComparison:
        if not self.active_route:
            return RouteComparison()
        comp = RouteComparison(
            current=self.active_route,
            previous=self.previous_route,
        )
        if self.previous_route:
            cur_ids = {h.ip: h.number for h in self.active_route.hops}
            prev_ids = {h.ip: h.number for h in self.previous_route.hops}
            cur_lats = {h.ip: h.latency for h in self.active_route.hops}
            prev_lats = {h.ip: h.latency for h in self.previous_route.hops}
            comp.hop_delta = len(self.active_route.hops) - len(
                self.previous_route.hops
            )
            comp.latency_delta = (
                self.active_route.total_latency
                - self.previous_route.total_latency
            )
            comp.jitter_delta = (
                self.active_route.route_jitter
                - self.previous_route.route_jitter
            )
            comp.loss_delta = (
                self.active_route.route_packet_loss
                - self.previous_route.route_packet_loss
            )
            for ip in cur_ids:
                if ip in prev_ids:
                    lat_diff = cur_lats.get(ip, 0) - prev_lats.get(ip, 0)
                    if abs(lat_diff) > 10:
                        comp.changed_hops.append(cur_ids[ip])
            for ip in cur_ids:
                if ip not in prev_ids:
                    comp.new_hops.append(cur_ids[ip])
            for ip in prev_ids:
                if ip not in cur_ids:
                    comp.removed_hops.append(prev_ids[ip])
        return comp
