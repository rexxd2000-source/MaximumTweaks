"""Network intelligence data models."""
from __future__ import annotations

import time
from enum import Enum, auto
from typing import Optional
from dataclasses import dataclass, field


# ── Enums ────────────────────────────────────────────────────────────────────

class Confidence(Enum):
    CONFIRMED = "confirmed"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class GameType(Enum):
    FORTNITE = "fortnite"
    VALORANT = "valorant"
    CALL_OF_DUTY = "call_of_duty"
    CS2 = "cs2"
    OTHER = "other"


class GameState(Enum):
    NOT_INSTALLED = "not_installed"
    NOT_RUNNING = "not_running"
    LAUNCHING = "launching"
    RUNNING = "running"
    LOBBY = "lobby"
    MATCHMAKING = "matchmaking"
    IN_MATCH = "in_match"
    NETWORK_ACTIVE = "network_active"
    NETWORK_INACTIVE = "network_inactive"
    UNKNOWN = "unknown"


class EndpointClass(Enum):
    GAME_SESSION = "game_session"
    RELAY = "relay"
    MATCHMAKING = "matchmaking"
    BACKEND = "backend"
    AUTHENTICATION = "authentication"
    CDN = "cdn"
    VOICE = "voice"
    SOCIAL = "social"
    TELEMETRY = "telemetry"
    UNKNOWN = "unknown"


class HopType(Enum):
    LOCAL_GATEWAY = "local_gateway"
    ISP_ACCESS = "isp_access"
    ISP_BACKBONE = "isp_backbone"
    METRO = "metro"
    TRANSIT = "transit"
    INTERNATIONAL = "international"
    PEERING = "peering"
    IXP = "ixp"
    DESTINATION = "destination"
    RELAY = "relay"
    UNKNOWN = "unknown"


class MeasurementMethod(Enum):
    ICMP = "icmp"
    TCP = "tcp"
    UDP = "udp"
    COMBINED = "combined"


class NetworkType(Enum):
    ACCESS = "access"
    METRO = "metro"
    BACKBONE = "backbone"
    TRANSIT = "transit"
    PEERING = "peering"
    INTERNATIONAL = "international"
    DESTINATION = "destination"
    UNKNOWN = "unknown"


class RouteChangeType(Enum):
    NONE = "none"
    HOP_ADDED = "hop_added"
    HOP_REMOVED = "hop_removed"
    HOP_CHANGED = "hop_changed"
    PATH_CHANGED = "path_changed"
    ENDPOINT_CHANGED = "endpoint_changed"
    LATENCY_INCREASED = "latency_increased"
    LATENCY_DECREASED = "latency_decreased"


class DataSourceType(Enum):
    OBSERVED = "observed"
    MEASURED = "measured"
    INFERRED = "inferred"
    PUBLIC_METADATA = "public_metadata"
    UNKNOWN = "unknown"


class ConnectionOrigin(Enum):
    GAME_PROCESS = "game_process"
    LAUNCHER = "launcher"
    OS = "os"
    OTHER = "other"


# ── Provenance ───────────────────────────────────────────────────────────────

@dataclass
class DataSource:
    """Provenance record for any datum."""
    provider: str = ""
    method: str = ""
    timestamp: float = 0.0
    confidence: Confidence = Confidence.UNKNOWN
    detail: str = ""
    source_type: DataSourceType = DataSourceType.UNKNOWN

    @staticmethod
    def now(provider: str = "", method: str = "",
            source_type: DataSourceType = DataSourceType.OBSERVED) -> DataSource:
        return DataSource(
            provider=provider, method=method,
            timestamp=time.time(), confidence=Confidence.HIGH,
            source_type=source_type,
        )


# ── Network Metadata ─────────────────────────────────────────────────────────

@dataclass
class AsnInfo:
    asn: int = 0
    name: str = ""
    description: str = ""
    country: str = ""
    organization: str = ""
    prefix: str = ""
    source: str = ""
    confidence: Confidence = Confidence.UNKNOWN
    network_type: NetworkType = NetworkType.UNKNOWN

    @property
    def display_name(self) -> str:
        if self.asn and self.name:
            return f"AS{self.asn} {self.name}"
        if self.asn:
            return f"AS{self.asn}"
        return "Unknown ASN"


@dataclass
class GeoInfo:
    lat: float = 0.0
    lon: float = 0.0
    city: str = ""
    region: str = ""
    country: str = ""
    country_code: str = ""
    source: str = ""
    confidence: Confidence = Confidence.UNKNOWN

    @property
    def display_location(self) -> str:
        parts = [p for p in (self.city, self.region, self.country) if p]
        return ", ".join(parts) if parts else "Unknown"

    @property
    def has_valid_coords(self) -> bool:
        return (self.lat != 0.0 or self.lon != 0.0) and (-90 <= self.lat <= 90) and (-180 <= self.lon <= 180)


@dataclass
class BgpInfo:
    prefix: str = ""
    origin_asn: int = 0
    origin_name: str = ""
    as_path: list[int] = field(default_factory=list)
    as_path_names: list[str] = field(default_factory=list)
    rpki_status: str = ""
    description: str = ""
    source: str = ""
    confidence: Confidence = Confidence.UNKNOWN

    @property
    def as_path_display(self) -> str:
        if not self.as_path:
            return ""
        return " → ".join(f"AS{a}" for a in self.as_path)


@dataclass
class ReverseDns:
    hostname: str = ""
    source: str = ""
    confidence: Confidence = Confidence.UNKNOWN


# ── Raw Connection ───────────────────────────────────────────────────────────

@dataclass
class NetworkConnection:
    pid: int = 0
    process_name: str = ""
    process_path: str = ""
    local_ip: str = ""
    local_port: int = 0
    remote_ip: str = ""
    remote_port: int = 0
    protocol: str = ""
    state: str = ""
    timestamp: float = 0.0
    origin: ConnectionOrigin = ConnectionOrigin.OTHER

    @property
    def key(self) -> str:
        return f"{self.local_ip}:{self.local_port}-{self.remote_ip}:{self.remote_port}-{self.protocol}"

    @property
    def is_remote(self) -> bool:
        return bool(self.remote_ip) and self.remote_ip not in (
            "0.0.0.0", "127.0.0.1", "::1", "", "::"
        )

    @property
    def is_established(self) -> bool:
        return self.state in ("ESTABLISHED", "STATELESS") or self.protocol == "UDP"


# ── Enriched Endpoint ────────────────────────────────────────────────────────

@dataclass
class EnrichedEndpoint:
    ip: str = ""
    port: int = 0
    protocol: str = ""
    hostname: str = ""
    reverse_dns: str = ""
    asn: AsnInfo = field(default_factory=AsnInfo)
    geo: GeoInfo = field(default_factory=GeoInfo)
    bgp: BgpInfo = field(default_factory=BgpInfo)
    game: GameType = GameType.OTHER
    classification: EndpointClass = EndpointClass.UNKNOWN
    classification_evidence: list[str] = field(default_factory=list)
    confidence: Confidence = Confidence.UNKNOWN
    first_seen: float = 0.0
    last_seen: float = 0.0
    observation_count: int = 0
    associated_process: str = ""
    process_pid: int = 0
    sources: list[DataSource] = field(default_factory=list)
    provider: str = ""

    @property
    def display_label(self) -> str:
        return self.reverse_dns or self.hostname or self.ip

    @property
    def is_active(self) -> bool:
        return self.last_seen > 0 and (time.time() - self.last_seen) < 120


# ── Endpoint Scoring ─────────────────────────────────────────────────────────

@dataclass
class EndpointScoring:
    """Scoring signals for classifying an endpoint."""
    ip: str = ""
    score: int = 0
    classification: EndpointClass = EndpointClass.UNKNOWN
    confidence: Confidence = Confidence.UNKNOWN
    signals: list[str] = field(default_factory=list)
    anti_signals: list[str] = field(default_factory=list)

    HIGH_VALUE_SIGNALS: list[str] = field(default_factory=lambda: [
        "owned_by_game_pid", "udp_protocol", "appeared_near_match_start",
        "remains_active_during_gameplay", "high_activity_volume",
        "repeated_observation",
    ])
    MEDIUM_VALUE_SIGNALS: list[str] = field(default_factory=lambda: [
        "game_related_asn", "game_related_hostname",
        "relevant_network_prefix", "geographic_region_correlation",
        "repeated_across_sessions",
    ])
    LOW_VALUE_SIGNALS: list[str] = field(default_factory=lambda: [
        "authentication_only", "short_lived_connection",
        "cdn_like_behavior", "launcher_connection",
    ])


# ── Route Hop ────────────────────────────────────────────────────────────────

@dataclass
class RouteHop:
    number: int = 0
    ip: str = ""
    rtt_ms: float = 0.0
    rtt_delta_ms: float = 0.0
    asn: AsnInfo = field(default_factory=AsnInfo)
    geo: GeoInfo = field(default_factory=GeoInfo)
    reverse_dns: str = ""
    hop_type: HopType = HopType.UNKNOWN
    network_type: NetworkType = NetworkType.UNKNOWN
    measurement: MeasurementMethod = MeasurementMethod.ICMP
    confidence: Confidence = Confidence.UNKNOWN
    timestamp: float = 0.0
    sources: list[DataSource] = field(default_factory=list)

    @property
    def location_display(self) -> str:
        if self.confidence == Confidence.UNKNOWN:
            return "Location unknown"
        return self.geo.display_location or "Location unknown"

    @property
    def type_label(self) -> str:
        labels = {
            HopType.LOCAL_GATEWAY: "Local Gateway",
            HopType.ISP_ACCESS: "ISP Access",
            HopType.ISP_BACKBONE: "ISP Backbone",
            HopType.METRO: "Metro Network",
            HopType.TRANSIT: "Transit",
            HopType.INTERNATIONAL: "International Transit",
            HopType.PEERING: "Peering",
            HopType.IXP: "IXP",
            HopType.DESTINATION: "Destination",
            HopType.RELAY: "Relay",
            HopType.UNKNOWN: "Unknown",
        }
        return labels.get(self.hop_type, "Unknown")

    @property
    def classification(self) -> str:
        if self.hop_type in (HopType.LOCAL_GATEWAY, HopType.ISP_ACCESS):
            return "gateway"
        if self.hop_type in (HopType.PEERING, HopType.IXP):
            return "ixp"
        if self.hop_type == HopType.DESTINATION:
            return "destination"
        return "transit"


# ── Measured Route ───────────────────────────────────────────────────────────

@dataclass
class MeasuredRoute:
    destination_ip: str = ""
    destination_port: int = 0
    protocol: str = ""
    hops: list[RouteHop] = field(default_factory=list)
    measurement: MeasurementMethod = MeasurementMethod.ICMP
    total_latency_ms: float = 0.0
    total_hops: int = 0
    packet_loss_pct: float = 0.0
    jitter_ms: float = 0.0
    timestamp: float = 0.0
    sources: list[DataSource] = field(default_factory=list)
    data_availability: dict[str, str] = field(default_factory=dict)

    @property
    def hop_count(self) -> int:
        return len(self.hops)

    @property
    def destination(self) -> str:
        return self.destination_ip

    @property
    def as_path(self) -> list[int]:
        seen = set()
        result = []
        for hop in self.hops:
            if hop.asn.asn and hop.asn.asn not in seen:
                seen.add(hop.asn.asn)
                result.append(hop.asn.asn)
        return result

    @property
    def source(self) -> DataSource:
        return self.sources[0] if self.sources else DataSource.now()


# ── BGP Route ────────────────────────────────────────────────────────────────

@dataclass
class BgpRoute:
    prefix: str = ""
    origin_asn: int = 0
    origin_name: str = ""
    as_path: list[int] = field(default_factory=list)
    as_path_names: list[str] = field(default_factory=list)
    source: str = ""
    confidence: Confidence = Confidence.UNKNOWN
    timestamp: float = 0.0


# ── Route Classification ─────────────────────────────────────────────────────

@dataclass
class RouteClassification:
    route_type: str = ""
    confidence: Confidence = Confidence.UNKNOWN
    description: str = ""
    hop_breakdown: dict = field(default_factory=dict)
    as_path_summary: str = ""
    cable_used: list[str] = field(default_factory=list)


# ── User Location ────────────────────────────────────────────────────────────

@dataclass
class UserLocation:
    city: str = ""
    region: str = ""
    country: str = ""
    country_code: str = ""
    lat: float = 0.0
    lon: float = 0.0
    isp: str = ""
    isp_asn: int = 0
    confidence: Confidence = Confidence.UNKNOWN
    source: str = ""

    @property
    def coarse_display(self) -> str:
        parts = [p for p in (self.city, self.region, self.country) if p][:2]
        return ", ".join(parts) if parts else "Unknown"


# ── Connection Record (for tracking) ─────────────────────────────────────────

@dataclass
class ConnectionRecord:
    """A tracked connection with timing and observation history."""
    remote_ip: str = ""
    remote_port: int = 0
    local_port: int = 0
    protocol: str = ""
    process_name: str = ""
    pid: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    observation_count: int = 0
    activity_samples: list[float] = field(default_factory=list)
    port_samples: list[int] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.last_seen > 0 and (time.time() - self.last_seen) < 30

    @property
    def age_seconds(self) -> float:
        if self.first_seen <= 0:
            return 0.0
        return time.time() - self.first_seen

    @property
    def activity_rate(self) -> float:
        if len(self.activity_samples) < 2:
            return 0.0
        window = 60.0
        recent = [t for t in self.activity_samples if (time.time() - t) < window]
        return len(recent) / window if window > 0 else 0.0

    def record_observation(self):
        self.last_seen = time.time()
        self.observation_count += 1
        if not self.first_seen:
            self.first_seen = self.last_seen
        self.activity_samples.append(self.last_seen)
        cutoff = time.time() - 300
        self.activity_samples = [t for t in self.activity_samples if t > cutoff]


# ── Session Timeline ─────────────────────────────────────────────────────────

@dataclass
class SessionTimelineEvent:
    timestamp: float = 0.0
    event_type: str = ""
    description: str = ""
    game_state: GameState = GameState.UNKNOWN
    endpoint_ip: str = ""
    route_changed: bool = False
    latency_ms: float = 0.0
    metadata: dict = field(default_factory=dict)


# ── Session Snapshot ─────────────────────────────────────────────────────────

@dataclass
class SessionSnapshot:
    timestamp: float = 0.0
    endpoint_ip: str = ""
    route: MeasuredRoute = field(default_factory=MeasuredRoute)
    latency_ms: float = 0.0
    endpoint_changed: bool = False
    route_changed: bool = False
    latency_delta_ms: float = 0.0
    game_state: GameState = GameState.UNKNOWN


# ── Route Comparison ─────────────────────────────────────────────────────────

@dataclass
class RouteComparison:
    change_type: RouteChangeType = RouteChangeType.NONE
    previous: MeasuredRoute = field(default_factory=MeasuredRoute)
    current: MeasuredRoute = field(default_factory=MeasuredRoute)
    latency_delta_ms: float = 0.0
    description: str = ""
    timestamp: float = 0.0


# ── Game Session ─────────────────────────────────────────────────────────────

@dataclass
class GameSession:
    game: GameType = GameType.OTHER
    game_state: GameState = GameState.NOT_RUNNING
    process_name: str = ""
    pid: int = 0
    region: str = ""
    primary_endpoint: EnrichedEndpoint = field(default_factory=EnrichedEndpoint)
    all_endpoints: list[EnrichedEndpoint] = field(default_factory=list)
    measured_route: MeasuredRoute = field(default_factory=MeasuredRoute)
    bgp_route: BgpRoute = field(default_factory=BgpRoute)
    latency_ms: float = 0.0
    jitter_ms: float = 0.0
    packet_loss_pct: float = 0.0
    route_stable: bool = True
    route_changes: int = 0
    is_optimizer_active: bool = False
    optimizer_name: str = ""
    session_start: float = 0.0
    last_update: float = 0.0
    snapshots: list[SessionSnapshot] = field(default_factory=list)
    timeline: list[SessionTimelineEvent] = field(default_factory=list)
    connection_records: dict[str, ConnectionRecord] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        if self.session_start > 0:
            return time.time() - self.session_start
        return 0.0

    def add_timeline_event(self, event_type: str, description: str,
                           game_state: GameState = GameState.UNKNOWN,
                           endpoint_ip: str = "", route_changed: bool = False,
                           latency_ms: float = 0.0, **metadata):
        event = SessionTimelineEvent(
            timestamp=time.time(),
            event_type=event_type,
            description=description,
            game_state=game_state or self.game_state,
            endpoint_ip=endpoint_ip,
            route_changed=route_changed,
            latency_ms=latency_ms,
            metadata=metadata,
        )
        self.timeline.append(event)
        if len(self.timeline) > 500:
            self.timeline = self.timeline[-500:]


# ── Network Intelligence Snapshot (top-level output) ─────────────────────────

@dataclass
class NetworkIntelligenceSnapshot:
    game: GameType = GameType.OTHER
    game_running: bool = False
    game_state: GameState = GameState.UNKNOWN
    game_process: str = ""
    game_pid: int = 0
    region: str = ""
    user_location: UserLocation = field(default_factory=UserLocation)
    isp: AsnInfo = field(default_factory=AsnInfo)
    session: GameSession = field(default_factory=GameSession)
    all_connections: list[EnrichedEndpoint] = field(default_factory=list)
    game_connections: list[EnrichedEndpoint] = field(default_factory=list)
    route: MeasuredRoute = field(default_factory=MeasuredRoute)
    bgp: BgpRoute = field(default_factory=BgpRoute)
    route_history: list[RouteComparison] = field(default_factory=list)
    is_optimizer_active: bool = False
    optimizer_name: str = ""
    measurement_method: MeasurementMethod = MeasurementMethod.ICMP
    confidence: Confidence = Confidence.UNKNOWN
    timestamp: float = 0.0
    data_sources: list[DataSource] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
