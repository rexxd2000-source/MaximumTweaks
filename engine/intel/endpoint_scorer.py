"""Endpoint scorer — multi-signal scoring for game session candidates."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from engine.intel.network_observer import TrackedEndpoint
from engine.intel.lobby_baseline import LobbyBaselineTracker
from engine.intel.game_state_machine import GameState


class EndpointClassification(Enum):
    GAME_SESSION = "game_session"
    LIKELY_GAME_SESSION = "likely_game_session"
    RELAY = "relay"
    MATCHMAKING = "matchmaking"
    BACKEND = "backend"
    AUTHENTICATION = "authentication"
    CDN = "cdn"
    VOICE = "voice"
    TELEMETRY = "telemetry"
    UNKNOWN = "unknown"


@dataclass
class ScoringSignal:
    name: str = ""
    points: int = 0
    description: str = ""
    is_positive: bool = True


@dataclass
class EndpointCandidate:
    ip: str = ""
    port: int = 0
    protocol: str = ""
    score: int = 0
    classification: EndpointClassification = EndpointClassification.UNKNOWN
    confidence: str = "unknown"
    positive_signals: list[ScoringSignal] = field(default_factory=list)
    negative_signals: list[ScoringSignal] = field(default_factory=list)
    first_seen: float = 0.0
    last_seen: float = 0.0
    observation_count: int = 0
    activity_rate: float = 0.0
    was_in_lobby: bool = False
    appeared_during_matchmaking: bool = False
    remained_during_gameplay: bool = False

    @property
    def signal_summary(self) -> list[str]:
        lines = []
        for s in self.positive_signals:
            lines.append(f"+{s.points} {s.description}")
        for s in self.negative_signals:
            lines.append(f"{s.points} {s.description}")
        return lines

    @property
    def is_usable(self) -> bool:
        """Routable public IP that we can traceroute to."""
        if not self.ip:
            return False
        return _is_routable_public_ip(self.ip)


_CDN_KEYWORDS = frozenset({
    "cloudflare", "akamai", "cloudfront", "fastly", "stackpath",
    "incapsula", "imperva", "maxcdn", "keycdn", "bunny",
})

# Known CDN/cloud front ranges — these are edge nodes, not game servers
_CDN_IP_PREFIXES = frozenset({
    "104.16.", "104.17.", "104.18.", "104.19.",
    "172.64.", "172.65.", "172.66.", "172.67.",
    "103.21.", "103.22.", "103.31.",
})


def _is_routable_public_ip(ip: str) -> bool:
    """Check if an IP is a routable public address (not private/loopback/CGNAT)."""
    if not ip:
        return False

    # Loopback / unspecified
    if ip in ("0.0.0.0", "127.0.0.1", "::1", "", "::"):
        return False

    parts = ip.split(".")
    if len(parts) != 4:
        return False

    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False

    # Private ranges (RFC 1918)
    if a == 10:
        return False
    if a == 172 and 16 <= b <= 31:
        return False
    if a == 192 and b == 168:
        return False

    # Loopback (127.x.x.x)
    if a == 127:
        return False

    # CGNAT (RFC 6598) — 100.64.0.0/10
    if a == 100 and 64 <= b <= 127:
        return False

    # Link-local (169.254.x.x)
    if a == 169 and b == 254:
        return False

    # Multicast (224.0.0.0 - 239.255.255.255)
    if 224 <= a <= 239:
        return False

    # Broadcast
    if ip == "255.255.255.255":
        return False

    return True


def _is_cdn_asn(asn_name: str) -> bool:
    low = asn_name.lower()
    return any(kw in low for kw in _CDN_KEYWORDS)


def _is_cdn_ip(ip: str) -> bool:
    """Check if IP is in a known CDN IP range (Cloudflare, etc.)."""
    return any(ip.startswith(prefix) for prefix in _CDN_IP_PREFIXES)


def _is_https_only_connection(port: int) -> bool:
    """Port 443 connections are almost always CDN/backend, not game servers."""
    return port == 443


class EndpointScorer:
    """Scores endpoint candidates based on multiple correlated signals.

    Positive signals:
        +30  Associated with game process PID
        +25  Appeared around match-start transition
        +25  Remained active during gameplay
        +15  UDP protocol (real-time gameplay indicator)
        +10  Sustained activity during gameplay
        +10  Repeated observation (seen multiple times)
        +10  Observed consistently through the match

    Negative signals:
        -25  Already active before matchmaking (lobby baseline)
        -20  Very short-lived (< 30 seconds total)
        -20  Clearly CDN/backend infrastructure
        -15  Associated with launcher instead of game process
    """

    def __init__(self):
        self._candidates: dict[str, EndpointCandidate] = {}
        self._matchmaking_time: float = 0.0
        self._match_start_time: float = 0.0
        self._gameplay_start_time: float = 0.0

    def set_match_timing(self, matchmaking_time: float = 0.0, match_start_time: float = 0.0):
        self._matchmaking_time = matchmaking_time
        self._match_start_time = match_start_time

    def score_endpoint(
        self,
        endpoint: TrackedEndpoint,
        lobby_baseline: Optional[LobbyBaselineTracker] = None,
        game_state: GameState = GameState.UNKNOWN,
        is_game_process: bool = True,
        asn_name: str = "",
        reverse_dns: str = "",
    ) -> EndpointCandidate:
        """Score a single endpoint candidate against all known signals."""
        candidate = EndpointCandidate(
            ip=endpoint.remote_ip,
            port=endpoint.remote_port,
            protocol=endpoint.protocol,
            first_seen=endpoint.first_seen,
            last_seen=endpoint.last_seen,
            observation_count=endpoint.observation_count,
            activity_rate=endpoint.activity_rate,
        )

        score = 0
        pos = []
        neg = []

        # +30: Associated with game process
        if is_game_process:
            score += 30
            pos.append(ScoringSignal("game_process", 30, "Associated with game process", True))

        # -25: Was in lobby baseline
        if lobby_baseline and lobby_baseline.has_baseline:
            if lobby_baseline.was_endpoint_in_lobby(endpoint.key):
                score -= 25
                neg.append(ScoringSignal("in_lobby_baseline", -25, "Active before matchmaking", False))
                candidate.was_in_lobby = True
            else:
                candidate.was_in_lobby = False

        # +25: Appeared around match start
        if self._match_start_time > 0:
            match_window = 30.0
            if abs(endpoint.first_seen - self._match_start_time) < match_window:
                score += 25
                pos.append(ScoringSignal("appeared_match_start", 25, "Appeared around match start", True))
                candidate.appeared_during_matchmaking = True

        # +25: Remained active during gameplay
        if game_state == GameState.IN_MATCH and endpoint.is_active:
            score += 25
            pos.append(ScoringSignal("active_during_gameplay", 25, "Active during gameplay", True))
            candidate.remained_during_gameplay = True

        # +15: UDP protocol
        if endpoint.protocol == "UDP":
            score += 15
            pos.append(ScoringSignal("udp_protocol", 15, "UDP protocol", True))

        # +10: Sustained activity
        if endpoint.observation_count >= 5:
            score += 10
            pos.append(ScoringSignal("sustained_activity", 10, "Sustained activity", True))

        # +10: Repeated observation
        if endpoint.observation_count >= 3:
            score += 10
            pos.append(ScoringSignal("repeated_observation", 10, "Repeatedly observed", True))

        # +10: Consistent through match
        if endpoint.age_seconds > 60 and endpoint.is_active:
            score += 10
            pos.append(ScoringSignal("consistent_through_match", 10, "Consistent through match", True))

        # -20: Short-lived
        if endpoint.age_seconds < 30 and endpoint.observation_count <= 2:
            score -= 20
            neg.append(ScoringSignal("short_lived", -20, "Short-lived connection", False))

        # -20: CDN/backend
        if _is_cdn_asn(asn_name):
            score -= 20
            neg.append(ScoringSignal("cdn_backend", -20, "CDN/backend infrastructure", False))

        # Also check RDNS for CDN indicators
        if reverse_dns:
            rdns_low = reverse_dns.lower()
            if any(kw in rdns_low for kw in ("cloudfront", "cloudflare", "akamai", "fastly")):
                score -= 20
                neg.append(ScoringSignal("cdn_rdns", -20, "CDN detected via reverse DNS", False))

        # -30: CGNAT or private IP (should not be treated as game server)
        if not _is_routable_public_ip(endpoint.remote_ip):
            score -= 30
            neg.append(ScoringSignal("non_public_ip", -30, "CGNAT/private IP (not a server)", False))

        candidate.score = score
        candidate.positive_signals = pos
        candidate.negative_signals = neg
        candidate.classification = self._classify(score, pos, neg, endpoint)
        candidate.confidence = self._confidence(score)

        return candidate

    def _classify(
        self,
        score: int,
        pos: list[ScoringSignal],
        neg: list[ScoringSignal],
        endpoint: TrackedEndpoint,
    ) -> EndpointClassification:
        if score >= 60:
            return EndpointClassification.GAME_SESSION
        if score >= 40:
            return EndpointClassification.LIKELY_GAME_SESSION
        if endpoint.protocol == "UDP" and score >= 20:
            return EndpointClassification.RELAY
        if any(s.name == "in_lobby_baseline" for s in neg):
            if score < 0:
                return EndpointClassification.BACKEND
        if any(s.name in ("cdn_backend", "cdn_rdns") for s in neg):
            return EndpointClassification.CDN
        return EndpointClassification.UNKNOWN

    def _confidence(self, score: int) -> str:
        if score >= 60:
            return "high"
        if score >= 40:
            return "medium"
        if score >= 20:
            return "low"
        return "unknown"

    def score_all(
        self,
        endpoints: list[TrackedEndpoint],
        lobby_baseline: Optional[LobbyBaselineTracker] = None,
        game_state: GameState = GameState.UNKNOWN,
        asn_lookup: callable = None,
        rdns_lookup: callable = None,
    ) -> list[EndpointCandidate]:
        """Score all endpoints and return sorted by score descending."""
        candidates = []
        for ep in endpoints:
            asn_name = ""
            rdns = ""
            if asn_lookup:
                try:
                    asn_info = asn_lookup(ep.remote_ip)
                    if asn_info:
                        asn_name = asn_info.name if hasattr(asn_info, "name") else str(asn_info)
                except Exception:
                    pass
            if rdns_lookup:
                try:
                    rdns = rdns_lookup(ep.remote_ip) or ""
                except Exception:
                    pass

            candidate = self.score_endpoint(
                ep, lobby_baseline, game_state,
                is_game_process=True,
                asn_name=asn_name,
                reverse_dns=rdns,
            )
            if candidate.is_usable:
                candidates.append(candidate)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def get_best_candidate(self, candidates: list[EndpointCandidate]) -> Optional[EndpointCandidate]:
        """Return the highest-scoring candidate, or None."""
        usable = [c for c in candidates if c.is_usable]
        if not usable:
            return None
        return max(usable, key=lambda c: c.score)

    def reset(self):
        self._candidates.clear()
        self._matchmaking_time = 0.0
        self._match_start_time = 0.0
        self._gameplay_start_time = 0.0
