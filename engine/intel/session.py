"""Tracks one game session: launch -> lobby -> matchmaking -> in-game -> end.

Records network snapshots, scores endpoints, and keeps a timeline.
"""
from __future__ import annotations

import time
from typing import Optional

from engine.intel.models import (
    GameType, GameState, GameSession, SessionSnapshot, MeasuredRoute,
    EnrichedEndpoint, Confidence, DataSource, RouteChangeType,
    SessionTimelineEvent, ConnectionRecord,
)
from engine.intel.connections import get_connections_for_pid, get_all_connections
from engine.intel.games import detect_running_games, get_primary_game, DetectedGame
from engine.intel.enrichment import enrich_endpoint
from engine.intel.traceroute import compare_routes
from engine.intel.endpoint_classifier import EndpointClassifier


class SessionState:
    NONE = "none"
    DETECTED = "detected"
    ACTIVE = "active"
    ENDED = "ended"


class GameSessionTracker:
    """Tracks game sessions, scores endpoints, maintains timeline."""

    def __init__(self):
        self._current_game: Optional[DetectedGame] = None
        self._session = GameSession()
        self._state = SessionState.NONE
        self._snapshots: list[SessionSnapshot] = []
        self._route_history: list = []
        self._last_route: Optional[MeasuredRoute] = None
        self._last_poll: float = 0
        self._poll_interval: float = 5.0
        self._classifier: Optional[EndpointClassifier] = None
        self._prev_game_state: GameState = GameState.UNKNOWN
        self._match_start_time: float = 0.0
        self._endpoint_change_count: int = 0

    @property
    def session(self) -> GameSession:
        return self._session

    @property
    def state(self) -> str:
        return self._state

    @property
    def route_history(self) -> list:
        return self._route_history

    @property
    def is_active(self) -> bool:
        return self._state in (SessionState.DETECTED, SessionState.ACTIVE)

    @property
    def classifier(self) -> Optional[EndpointClassifier]:
        return self._classifier

    def poll(self) -> dict:
        now = time.time()
        if (now - self._last_poll) < self._poll_interval:
            return self._summary()

        self._last_poll = now

        games = detect_running_games()
        primary = get_primary_game(games)

        if primary is None:
            if self._state != SessionState.NONE:
                self._on_game_ended()
            return self._summary()

        if self._current_game is None or self._current_game.pid != primary.pid:
            self._on_game_detected(primary)
        else:
            self._update_session(primary)

        return self._summary()

    def force_poll(self) -> dict:
        self._last_poll = 0
        return self.poll()

    def _on_game_detected(self, game: DetectedGame) -> None:
        self._current_game = game
        self._state = SessionState.DETECTED

        self._classifier = EndpointClassifier(game.game)

        self._session = GameSession(
            game=game.game,
            game_state=game.game_state,
            process_name=game.process_name,
            pid=game.pid,
            session_start=time.time(),
            last_update=time.time(),
        )

        self._session.add_timeline_event(
            "game_detected",
            f"{game.display_name} detected (PID {game.pid})",
            game_state=game.game_state,
        )

        self._snapshots.clear()
        self._route_history.clear()
        self._last_route = None
        self._match_start_time = 0.0
        self._endpoint_change_count = 0

        try:
            conns = get_connections_for_pid(game.pid)
            remote_conns = [c for c in conns if c.is_remote]

            if remote_conns and self._classifier:
                self._classifier.update_observations(remote_conns)

            self._enrich_game_connections(remote_conns)
            self._pick_primary_endpoint()

            self._session.add_timeline_event(
                "connections_discovered",
                f"{len(remote_conns)} remote connections found",
            )
        except Exception:
            pass

        self._take_snapshot()

    def _update_session(self, game: DetectedGame) -> None:
        self._session.last_update = time.time()
        self._session.process_name = game.process_name

        old_state = self._session.game_state
        new_state = game.game_state

        if new_state != old_state and new_state != GameState.UNKNOWN:
            self._session.game_state = new_state
            self._session.add_timeline_event(
                "state_changed",
                f"Game state: {old_state.value} -> {new_state.value}",
                game_state=new_state,
            )

            if new_state == GameState.IN_MATCH and self._match_start_time == 0:
                self._match_start_time = time.time()
                if self._classifier:
                    self._classifier.set_match_start(self._match_start_time)
                self._session.add_timeline_event(
                    "match_started",
                    "Match detected - tracking game session endpoint",
                )

        try:
            conns = get_connections_for_pid(game.pid)
            remote_conns = [c for c in conns if c.is_remote]

            if remote_conns and self._classifier:
                self._classifier.update_observations(remote_conns)

            old_primary_ip = self._session.primary_endpoint.ip
            self._enrich_game_connections(remote_conns)
            self._pick_primary_endpoint()

            new_primary_ip = self._session.primary_endpoint.ip
            if old_primary_ip and new_primary_ip and old_primary_ip != new_primary_ip:
                self._endpoint_change_count += 1
                self._session.add_timeline_event(
                    "endpoint_changed",
                    f"Primary endpoint changed: {old_primary_ip} -> {new_primary_ip}",
                    endpoint_ip=new_primary_ip,
                )

            if remote_conns:
                if self._state == SessionState.DETECTED:
                    self._state = SessionState.ACTIVE
        except Exception:
            pass

        self._take_snapshot()

    def _on_game_ended(self) -> None:
        if self._current_game:
            self._session.add_timeline_event(
                "game_ended",
                f"{self._session.game.value} session ended",
            )

        self._state = SessionState.ENDED
        self._current_game = None

        if self._classifier:
            self._classifier.clear_match()

        self._take_snapshot()

    def _take_snapshot(self) -> None:
        snapshot = SessionSnapshot(
            timestamp=time.time(),
            endpoint_ip=self._session.primary_endpoint.ip,
            latency_ms=self._session.latency_ms,
            game_state=self._session.game_state,
        )

        if self._snapshots:
            prev = self._snapshots[-1]
            snapshot.endpoint_changed = prev.endpoint_ip != snapshot.endpoint_ip
            if snapshot.endpoint_changed:
                self._session.route_changes += 1

            if self._last_route and prev.route.hops:
                changed, desc = compare_routes(prev.route, self._last_route)
                snapshot.route_changed = changed
                if changed:
                    self._session.route_changes += 1

            snapshot.latency_delta_ms = snapshot.latency_ms - prev.latency_ms

        self._snapshots.append(snapshot)
        self._session.snapshots = self._snapshots[-100:]

    def set_route(self, route: MeasuredRoute) -> None:
        if self._last_route and self._last_route.hops:
            changed, desc = compare_routes(self._last_route, route)
            if changed:
                self._route_history.append({
                    "timestamp": time.time(),
                    "change_type": RouteChangeType.PATH_CHANGED,
                    "description": desc,
                    "previous_hops": len(self._last_route.hops),
                    "current_hops": len(route.hops),
                    "previous_latency": self._last_route.total_latency_ms,
                    "current_latency": route.total_latency_ms,
                })
                self._session.route_changes += 1
                self._session.add_timeline_event(
                    "route_changed",
                    desc,
                    route_changed=True,
                    latency_ms=route.total_latency_ms,
                )

        self._last_route = route
        self._session.measured_route = route
        self._session.latency_ms = route.total_latency_ms
        self._session.jitter_ms = route.jitter_ms
        self._session.packet_loss_pct = route.packet_loss_pct

    def _enrich_game_connections(self, conns) -> None:
        seen_ips: dict[str, EnrichedEndpoint] = {}
        for ep in self._session.all_endpoints:
            seen_ips[ep.ip] = ep

        for conn in conns:
            if not conn.remote_ip or conn.remote_ip in ("0.0.0.0", "127.0.0.1", "::1", ""):
                continue
            if conn.remote_ip not in seen_ips:
                try:
                    enriched = enrich_endpoint(
                        conn.remote_ip, conn.remote_port, conn.protocol,
                        conn.process_name, conn.pid,
                    )
                    seen_ips[conn.remote_ip] = enriched
                except Exception:
                    pass
            else:
                seen_ips[conn.remote_ip].last_seen = time.time()
                seen_ips[conn.remote_ip].observation_count += 1

        self._session.all_endpoints = list(seen_ips.values())

    def _pick_primary_endpoint(self) -> None:
        endpoints = self._session.all_endpoints
        if not endpoints:
            return

        if self._classifier and self._session.pid:
            result = self._classifier.get_primary_endpoint(endpoints, self._session.pid)
            if result:
                ep, scoring = result
                self._session.primary_endpoint = ep
                return

        valid = [ep for ep in endpoints if ep.is_active and ep.asn and ep.asn.asn]
        if valid:
            self._session.primary_endpoint = valid[0]
            return

        remote = [ep for ep in endpoints if ep.ip not in ("0.0.0.0", "127.0.0.1")]
        if remote:
            self._session.primary_endpoint = remote[0]

    def _summary(self) -> dict:
        return {
            "state": self._state,
            "game": self._session.game.value,
            "game_state": self._session.game_state.value,
            "process": self._session.process_name,
            "pid": self._session.pid,
            "primary_endpoint": self._session.primary_endpoint.ip,
            "endpoint_count": len(self._session.all_endpoints),
            "route_hops": self._session.measured_route.hop_count,
            "latency_ms": self._session.latency_ms,
            "route_changes": self._session.route_changes,
            "snapshot_count": len(self._snapshots),
            "duration": self._session.duration_seconds,
            "timeline_events": len(self._session.timeline),
            "endpoint_changes": self._endpoint_change_count,
        }

    def reset(self) -> None:
        self._current_game = None
        self._session = GameSession()
        self._state = SessionState.NONE
        self._snapshots.clear()
        self._route_history.clear()
        self._last_route = None
        self._last_poll = 0
        self._classifier = None
        self._prev_game_state = GameState.UNKNOWN
        self._match_start_time = 0.0
        self._endpoint_change_count = 0
