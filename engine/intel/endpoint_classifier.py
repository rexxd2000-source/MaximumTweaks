"""Endpoint classifier — scores and classifies network endpoints.

Determines whether an endpoint is a game session, relay, backend, etc.
based on observable signals. No fabrication — only evidence-based classification.
"""
from __future__ import annotations

import time
from typing import Optional

from engine.intel.models import (
    EnrichedEndpoint, NetworkConnection, ConnectionRecord,
    EndpointScoring, EndpointClass, GameType, Confidence,
    DataSource, DataSourceType,
)


class EndpointClassifier:
    """Scores and classifies observed network endpoints."""

    GAME_SESSION_MIN_SCORE = 60
    RELAY_MIN_SCORE = 40
    BACKEND_SCORE_THRESHOLD = 30

    def __init__(self, game_type: GameType = GameType.FORTNITE):
        self.game_type = game_type
        self._connection_records: dict[str, ConnectionRecord] = {}
        self._match_start_time: float = 0.0
        self._is_in_match: bool = False

    def set_match_start(self, timestamp: float = 0.0):
        self._match_start_time = timestamp or time.time()
        self._is_in_match = True

    def clear_match(self):
        self._is_in_match = False

    def update_observations(self, connections: list[NetworkConnection]) -> dict[str, ConnectionRecord]:
        """Update connection records from fresh observations. Returns all records."""
        for conn in connections:
            if not conn.is_remote:
                continue

            key = f"{conn.remote_ip}:{conn.remote_port}"

            if key not in self._connection_records:
                self._connection_records[key] = ConnectionRecord(
                    remote_ip=conn.remote_ip,
                    remote_port=conn.remote_port,
                    local_port=conn.local_port,
                    protocol=conn.protocol,
                    process_name=conn.process_name,
                    pid=conn.pid,
                )

            self._connection_records[key].record_observation()
            if conn.local_port and conn.local_port not in self._connection_records[key].port_samples:
                self._connection_records[key].port_samples.append(conn.local_port)

        return dict(self._connection_records)

    def score_endpoint(
        self,
        ip: str,
        port: int = 0,
        protocol: str = "",
        game_pid: int = 0,
        enrichment: Optional[EnrichedEndpoint] = None,
    ) -> EndpointScoring:
        """Score an endpoint based on observable signals."""
        score = 0
        signals: list[str] = []
        anti_signals: list[str] = []

        key = f"{ip}:{port}"
        record = self._connection_records.get(key)

        if record:
            if record.pid == game_pid and game_pid > 0:
                score += 25
                signals.append("owned_by_game_pid")

            if record.protocol == "UDP":
                score += 20
                signals.append("udp_protocol")
            elif record.protocol == "TCP":
                score += 5
                signals.append("tcp_protocol")

            if self._is_in_match and self._match_start_time > 0:
                appeared_after_match = record.first_seen >= (self._match_start_time - 10)
                if appeared_after_match:
                    score += 15
                    signals.append("appeared_near_match_start")

            if record.observation_count >= 5:
                score += 10
                signals.append("repeated_observation")

            if record.activity_rate > 0.5:
                score += 10
                signals.append("high_activity_volume")

            if record.age_seconds > 30:
                score += 5
                signals.append("remains_active_during_gameplay")

            if record.age_seconds < 5 and record.observation_count <= 2:
                score -= 10
                anti_signals.append("short_lived_connection")
        else:
            anti_signals.append("no_observation_history")

        if enrichment:
            if enrichment.asn and enrichment.asn.asn:
                if self._is_game_related_asn(enrichment.asn.asn, enrichment.asn.name):
                    score += 10
                    signals.append("game_related_asn")

            if enrichment.reverse_dns:
                if self._is_game_related_hostname(enrichment.reverse_dns):
                    score += 8
                    signals.append("game_related_hostname")

            known_ports = []
            game_def_ports = {
                GameType.FORTNITE: [5222, 5795, 5800, 5801, 5900, 9960, 9999],
                GameType.VALORANT: [7000, 7100, 7200, 7300, 7400],
                GameType.CALL_OF_DUTY: [3074, 3075, 3076],
                GameType.CS2: list(range(27015, 27021)),
            }
            known_ports = game_def_ports.get(self.game_type, [])
            if port in known_ports:
                score += 5
                signals.append("known_game_port")

        classification = self._classify_from_score(score, signals, anti_signals)
        confidence = self._confidence_from_score(score)

        return EndpointScoring(
            ip=ip,
            score=max(0, min(100, score)),
            classification=classification,
            confidence=confidence,
            signals=signals,
            anti_signals=anti_signals,
        )

    def classify_all_endpoints(
        self,
        endpoints: list[EnrichedEndpoint],
        game_pid: int = 0,
    ) -> list[tuple[EnrichedEndpoint, EndpointScoring]]:
        """Classify a batch of endpoints. Returns (endpoint, scoring) pairs sorted by score."""
        scored: list[tuple[EnrichedEndpoint, EndpointScoring]] = []
        for ep in endpoints:
            scoring = self.score_endpoint(
                ep.ip, ep.port, ep.protocol, game_pid, ep,
            )
            ep.classification = scoring.classification
            ep.confidence = scoring.confidence
            ep.classification_evidence = scoring.signals
            scored.append((ep, scoring))

        scored.sort(key=lambda x: x[1].score, reverse=True)
        return scored

    def _classify_from_score(
        self, score: int, signals: list[str], anti_signals: list[str],
    ) -> EndpointClass:
        if score >= self.GAME_SESSION_MIN_SCORE:
            if "udp_protocol" in signals and "owned_by_game_pid" in signals:
                return EndpointClass.GAME_SESSION
            if "appeared_near_match_start" in signals:
                return EndpointClass.GAME_SESSION
            if score >= 70:
                return EndpointClass.GAME_SESSION
            return EndpointClass.GAME_SESSION

        if score >= self.RELAY_MIN_SCORE:
            if "udp_protocol" in signals:
                return EndpointClass.RELAY
            return EndpointClass.BACKEND

        if "short_lived_connection" in anti_signals:
            return EndpointClass.AUTHENTICATION

        if score <= 5 and "tcp_protocol" in signals:
            return EndpointClass.CDN

        if score <= 10:
            return EndpointClass.UNKNOWN

        return EndpointClass.BACKEND

    def _confidence_from_score(self, score: int) -> Confidence:
        if score >= 70:
            return Confidence.HIGH
        if score >= 50:
            return Confidence.MEDIUM
        if score >= 30:
            return Confidence.LOW
        return Confidence.UNKNOWN

    def _is_game_related_asn(self, asn: int, name: str) -> bool:
        name_lower = name.lower()
        game_asn_keywords = {
            GameType.FORTNITE: ["epic", "cloudflare", "amazon", "aws", "microsoft", "azure"],
            GameType.VALORANT: ["riot", "amazon", "aws", "microsoft"],
            GameType.CALL_OF_DUTY: ["activision", "blizzard", "amazon", "aws"],
            GameType.CS2: ["valve", "steam", "amazon", "aws"],
        }
        keywords = game_asn_keywords.get(self.game_type, [])
        return any(kw in name_lower for kw in keywords)

    def _is_game_related_hostname(self, hostname: str) -> bool:
        hostname_lower = hostname.lower()
        game_host_keywords = {
            GameType.FORTNITE: ["epic", "fortnite", "unreal"],
            GameType.VALORANT: ["riot", "valorant"],
            GameType.CALL_OF_DUTY: ["activision", "cod", "codam"],
            GameType.CS2: ["valve", "steam", "cs2"],
        }
        keywords = game_host_keywords.get(self.game_type, [])
        return any(kw in hostname_lower for kw in keywords)

    def get_game_session_endpoints(
        self,
        endpoints: list[EnrichedEndpoint],
        game_pid: int = 0,
    ) -> list[tuple[EnrichedEndpoint, EndpointScoring]]:
        """Get endpoints classified as game sessions, sorted by confidence."""
        classified = self.classify_all_endpoints(endpoints, game_pid)
        return [(ep, sc) for ep, sc in classified if sc.classification == EndpointClass.GAME_SESSION]

    def get_primary_endpoint(
        self,
        endpoints: list[EnrichedEndpoint],
        game_pid: int = 0,
    ) -> Optional[tuple[EnrichedEndpoint, EndpointScoring]]:
        """Get the single most likely game session endpoint."""
        game_eps = self.get_game_session_endpoints(endpoints, game_pid)
        if game_eps:
            return game_eps[0]

        classified = self.classify_all_endpoints(endpoints, game_pid)
        if classified:
            return classified[0]

        return None

    def reset(self):
        self._connection_records.clear()
        self._match_start_time = 0.0
        self._is_in_match = False
