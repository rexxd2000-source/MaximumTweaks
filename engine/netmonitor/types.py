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

    @property
    def avg_latency(self) -> float:
        if not self.hops:
            return 0.0
        valid = [h for h in self.hops if h.status == HopStatus.HEALTHY]
        return sum(h.latency for h in valid) / len(valid) if valid else 0.0

    @property
    def total_latency(self) -> float:
        if not self.hops:
            return 0.0
        dest = self.hops[-1] if self.hops else None
        if dest and dest.status == HopStatus.HEALTHY:
            return dest.latency
        return self.avg_latency

    @property
    def route_jitter(self) -> float:
        valid = [h for h in self.hops if h.status == HopStatus.HEALTHY]
        return max((h.jitter for h in valid), default=0.0)

    @property
    def route_packet_loss(self) -> float:
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
            if h.geo.city and len(h.geo.city) < 20:
                name = h.geo.city
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
