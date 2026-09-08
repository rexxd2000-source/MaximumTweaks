"""Detects LOBBY → MATCHMAKING → IN MATCH → ENDED transitions.

Driven by network behavior and process state; states are INFERRED, never
from internal game data. Transitions need confirmation across consecutive
snapshots before they are committed, so transient churn or single background
connections cannot cause false transitions. Matchmaking and match-start
timestamps are tracked for downstream scoring.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class GameState(Enum):
    NOT_RUNNING = "not_running"
    LOBBY = "lobby"
    MATCHMAKING = "matchmaking"
    LOADING = "loading"
    IN_MATCH = "in_match"
    MATCH_ENDED = "match_ended"
    UNKNOWN = "unknown"


class StateTransition(Enum):
    NONE = "none"
    ENTERED_LOBBY = "entered_lobby"
    ENTERED_MATCHMAKING = "entered_matchmaking"
    MATCH_FOUND = "match_found"
    ENTERED_LOADING = "entered_loading"
    ENTERED_MATCH = "entered_match"
    MATCH_ENDED = "match_ended"
    PROCESS_LOST = "process_lost"


@dataclass
class StateChangeEvent:
    timestamp: float = 0.0
    from_state: GameState = GameState.UNKNOWN
    to_state: GameState = GameState.UNKNOWN
    transition: StateTransition = StateTransition.NONE
    evidence: list[str] = field(default_factory=list)
    is_inferred: bool = True


@dataclass
class NetworkSnapshot:
    """A snapshot of network state at a point in time, used for state inference."""
    timestamp: float = 0.0
    total_endpoints: int = 0
    tcp_endpoints: int = 0
    udp_endpoints: int = 0
    new_endpoints: int = 0
    removed_endpoints: int = 0
    active_connections: int = 0
    endpoint_keys: set[str] = field(default_factory=set)
    udp_port_count: int = 0


class GameStateMachine:
    """Detects game state transitions using network behavior signals.

    State machine:
        NOT_RUNNING → LOBBY      (game process detected)
        LOBBY → MATCHMAKING      (significant new endpoints appear, >= 2,
                                  not just a single background connection)
        MATCHMAKING → IN_MATCH   (major endpoint restructuring: many new and/or
                                  many removed, followed by stability; requires
                                  at least MIN_MATCHMAKING_TIME seconds in
                                  MATCHMAKING first)
        IN_MATCH → MATCH_ENDED   (major endpoint drop relative to the in-match
                                  peak, or connection count collapses)
        MATCH_ENDED → LOBBY      (network stabilizes back to a lobby-like
                                  pattern)

    Every inferred transition must be observed on CONSECUTIVE_CONFIRMATIONS
    consecutive snapshots before it is committed. All states are INFERRED
    from network observation. The system never claims to read internal game
    state.
    """

    LOBBY_NEW_ENDPOINT_THRESHOLD = 2
    MIN_MATCHMAKING_TIME = 10.0
    RESTRUCTURE_NEW_MIN = 3
    RESTRUCTURE_NEW_MIN_WITH_REMOVALS = 1
    RESTRUCTURE_REMOVED_MIN = 2
    STABILITY_CHURN_LIMIT = 1
    MATCH_END_REMOVED_MIN = 3
    MATCH_END_DROP_RATIO = 0.5
    MATCH_END_CONFIRM_RATIO = 0.65
    CONNECTION_DROP_RATIO = 0.35
    POST_MATCH_MIN_TIME = 5.0
    BASELINE_TOLERANCE_FLOOR = 4
    LOBBY_BASELINE_SURGE_MIN = 3          # minimum new endpoints above lobby baseline
    LOBBY_BASELINE_SURGE_RATIO = 1.5      # current must be >= 1.5x lobby baseline

    CONFIRMATIONS = {
        GameState.MATCHMAKING: 2,
        GameState.IN_MATCH: 2,
        GameState.MATCH_ENDED: 2,
        GameState.LOBBY: 3,
    }

    def __init__(self):
        self._state = GameState.NOT_RUNNING
        self._previous_states: list[GameState] = []
        self._state_entry_time: float = 0.0
        self._last_network_snapshot: Optional[NetworkSnapshot] = None
        self._lobby_baseline: Optional[NetworkSnapshot] = None
        self._transition_history: list[StateChangeEvent] = []
        self._matchmaking_time: float = 0.0
        self._match_start_time: float = 0.0
        self._pending_target: Optional[GameState] = None
        self._pending_evidence: list[str] = []
        self._pending_confirmations: int = 0
        self._restructure_detected: bool = False
        self._restructure_evidence: list[str] = []
        self._collapse_detected: bool = False
        self._collapse_evidence: list[str] = []
        self._peak_endpoints: int = 0
        self._peak_connections: int = 0

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def state_entry_time(self) -> float:
        return self._state_entry_time

    @property
    def state_duration(self) -> float:
        return self.get_state_duration()

    @property
    def matchmaking_time(self) -> float:
        """Timestamp when MATCHMAKING was entered (0.0 if never)."""
        return self._matchmaking_time

    @property
    def match_start_time(self) -> float:
        """Timestamp when IN_MATCH was entered (0.0 if never)."""
        return self._match_start_time

    @property
    def is_in_match(self) -> bool:
        return self._state == GameState.IN_MATCH

    @property
    def is_in_lobby(self) -> bool:
        return self._state == GameState.LOBBY

    @property
    def is_matchmaking(self) -> bool:
        return self._state == GameState.MATCHMAKING

    @property
    def transitions(self) -> list[StateChangeEvent]:
        return self._transition_history

    def get_state_duration(self) -> float:
        """Seconds spent in the current state."""
        if self._state_entry_time > 0:
            return time.time() - self._state_entry_time
        return 0.0

    def get_matchmaking_duration(self) -> float:
        """Seconds between entering MATCHMAKING and entering IN_MATCH.

        Returns the elapsed time so far if still in matchmaking;
        returns 0.0 if matchmaking was never entered.
        """
        if self._matchmaking_time <= 0:
            return 0.0
        end = self._match_start_time if self._match_start_time > 0 else time.time()
        return max(0.0, end - self._matchmaking_time)

    def get_match_duration(self) -> float:
        """Seconds since the match started; 0.0 if no match was detected."""
        if self._match_start_time <= 0:
            return 0.0
        return max(0.0, time.time() - self._match_start_time)

    def set_game_running(self, is_running: bool, game_process_name: str = ""):
        """Called when game process is detected or lost.

        Process detection is definitive and commits immediately without
        requiring consecutive-snapshot confirmation.
        """
        if is_running and self._state == GameState.NOT_RUNNING:
            self._transition(GameState.LOBBY, [f"Game process detected: {game_process_name}"])
        elif not is_running and self._state != GameState.NOT_RUNNING:
            self._transition(GameState.NOT_RUNNING, ["Game process lost"])

    def set_lobby_baseline(self, snapshot: NetworkSnapshot):
        """Record the lobby network baseline."""
        self._lobby_baseline = snapshot

    def update_network(self, snapshot: NetworkSnapshot) -> Optional[StateChangeEvent]:
        """Process a new network snapshot and infer state changes.

        Returns the StateChangeEvent if a transition occurred, None otherwise.
        Transitions are only committed after being confirmed on consecutive
        snapshots.
        """
        prev = self._last_network_snapshot
        self._last_network_snapshot = snapshot

        if self._state == GameState.NOT_RUNNING:
            return None

        if self._state == GameState.LOBBY:
            return self._infer_from_lobby(snapshot, prev)

        if self._state == GameState.MATCHMAKING:
            return self._infer_from_matchmaking(snapshot, prev)

        if self._state == GameState.LOADING:
            return self._infer_from_loading(snapshot, prev)

        if self._state == GameState.IN_MATCH:
            return self._infer_from_in_match(snapshot, prev)

        if self._state == GameState.MATCH_ENDED:
            return self._infer_from_match_ended(snapshot, prev)

        return None

    def _infer_from_lobby(
        self, current: NetworkSnapshot, previous: Optional[NetworkSnapshot]
    ) -> Optional[StateChangeEvent]:
        """Detect LOBBY → MATCHMAKING or LOBBY → IN_MATCH (fast path).

        MATCHMAKING path: at least LOBBY_NEW_ENDPOINT_THRESHOLD new endpoints appear.
        A single new endpoint is treated as background noise and ignored.

        IN_MATCH fast path: when a lobby baseline exists and the current endpoint
        count substantially exceeds it (>= LOBBY_BASELINE_SURGE_RATIO), we skip
        matchmaking and jump straight to IN_MATCH. This handles:
        - Fast matchmaking that completes between polls
        - Squad fill / reconnect / party join
        - Games where matchmaking is instant
        """
        new_count = self._effective_new(current, previous)

        # Fast path: big jump from lobby baseline -> directly IN_MATCH
        if self._lobby_baseline is not None and self._lobby_baseline.total_endpoints > 0:
            baseline = self._lobby_baseline.total_endpoints
            surge = current.total_endpoints - baseline
            if surge >= self.LOBBY_BASELINE_SURGE_MIN and current.total_endpoints >= baseline * self.LOBBY_BASELINE_SURGE_RATIO:
                evidence = [
                    f"Endpoint surge from lobby baseline: {baseline} -> {current.total_endpoints} (+{surge})",
                    f"Surge ratio: {current.total_endpoints / baseline:.1f}x baseline",
                    "Inferred: match started (fast path, matchmaking too quick to detect)",
                ]
                return self._propose(GameState.IN_MATCH, evidence)

        # UDP port increase: new UDP sockets indicate game server traffic
        if previous is not None and self._lobby_baseline is not None:
            bl_udp = self._lobby_baseline.udp_endpoints
            cur_udp = current.udp_port_count
            if bl_udp > 0 and cur_udp > bl_udp + 1:
                evidence = [
                    f"UDP port increase from lobby baseline: {bl_udp} -> {cur_udp}",
                    f"New UDP ports indicate game server communication",
                    "Inferred: match started (UDP traffic increase)",
                ]
                return self._propose(GameState.IN_MATCH, evidence)

        if new_count >= self.LOBBY_NEW_ENDPOINT_THRESHOLD:
            evidence = [
                f"Significant new endpoints appeared: +{new_count} "
                f"(threshold {self.LOBBY_NEW_ENDPOINT_THRESHOLD})",
                f"Total endpoints: {current.total_endpoints}",
                "Inferred: matchmaking initiated",
            ]
            return self._propose(GameState.MATCHMAKING, evidence)

        self._clear_pending()
        return None

    def _infer_from_matchmaking(
        self, current: NetworkSnapshot, previous: Optional[NetworkSnapshot]
    ) -> Optional[StateChangeEvent]:
        """Detect MATCHMAKING → IN_MATCH.

        Two phases:
        1. Restructuring: many new endpoints (>= RESTRUCTURE_NEW_MIN) OR
           (new >= RESTRUCTURE_NEW_MIN_WITH_REMOVALS AND removed >=
           RESTRUCTURE_REMOVED_MIN). Only recognized after
           MIN_MATCHMAKING_TIME seconds in matchmaking — real matchmaking
           takes time.
        2. Stability: subsequent snapshots show low churn, confirming the
           new connection pattern has settled into the match server.
        """
        elapsed_mm = self.get_matchmaking_duration()
        new_count = self._effective_new(current, previous)
        removed_count = self._effective_removed(current, previous)

        restructured = (
            new_count >= self.RESTRUCTURE_NEW_MIN
            or (
                new_count >= self.RESTRUCTURE_NEW_MIN_WITH_REMOVALS
                and removed_count >= self.RESTRUCTURE_REMOVED_MIN
            )
        )

        if restructured and elapsed_mm >= self.MIN_MATCHMAKING_TIME:
            self._restructure_detected = True
            self._restructure_evidence = [
                f"Endpoint restructuring: +{new_count} new, -{removed_count} removed",
                f"Matchmaking duration before restructuring: {elapsed_mm:.1f}s",
                f"Total endpoints: {previous.total_endpoints} → {current.total_endpoints}"
                if previous
                else f"Total endpoints: {current.total_endpoints}",
                "Inferred: match found, game server allocated",
            ]
            self._clear_pending()
            return None

        if self._restructure_detected:
            stable = (
                new_count <= self.STABILITY_CHURN_LIMIT
                and removed_count <= self.STABILITY_CHURN_LIMIT
            )
            if stable:
                evidence = list(self._restructure_evidence) + [
                    f"Network stabilized: +{new_count} new, -{removed_count} removed",
                    "Inferred: connected to match server",
                ]
                return self._propose(GameState.IN_MATCH, evidence)

            self._clear_pending()

        return None

    def _infer_from_loading(
        self, current: NetworkSnapshot, previous: Optional[NetworkSnapshot]
    ) -> Optional[StateChangeEvent]:
        """Detect LOADING → IN_MATCH (legacy path; network stabilizes)."""
        if previous is None:
            return None

        if self.get_state_duration() > 5:
            evidence = [
                f"Loading duration: {self.get_state_duration():.1f}s",
                "Inferred: network stabilized, entering match",
            ]
            return self._propose(GameState.IN_MATCH, evidence)

        return None

    def _infer_from_in_match(
        self, current: NetworkSnapshot, previous: Optional[NetworkSnapshot]
    ) -> Optional[StateChangeEvent]:
        """Detect IN_MATCH → MATCH_ENDED.

        Two phases:
        1. Collapse: >= MATCH_END_REMOVED_MIN endpoints removed AND total
           below MATCH_END_DROP_RATIO of the in-match peak, or the active
           connection count collapsing below CONNECTION_DROP_RATIO of its
           peak.
        2. Confirmation: subsequent snapshots show the endpoint count
           remains well below the peak (the drop was not transient).
        """
        if current.total_endpoints > self._peak_endpoints:
            self._peak_endpoints = current.total_endpoints
        if current.active_connections > self._peak_connections:
            self._peak_connections = current.active_connections

        removed_count = self._effective_removed(current, previous)

        endpoint_collapse = (
            removed_count >= self.MATCH_END_REMOVED_MIN
            and self._peak_endpoints > 0
            and current.total_endpoints < self._peak_endpoints * self.MATCH_END_DROP_RATIO
        )
        connection_collapse = (
            self._peak_connections > 0
            and current.active_connections > 0
            and current.active_connections < self._peak_connections * self.CONNECTION_DROP_RATIO
        )

        if endpoint_collapse or connection_collapse:
            self._collapse_detected = True
            self._collapse_evidence = [
                f"Major endpoint drop: -{removed_count} removed",
                f"Total endpoints: {self._peak_endpoints} (peak) → {current.total_endpoints}",
                f"Active connections: {self._peak_connections} (peak) → {current.active_connections}",
                "Inferred: match ended",
            ]
            self._clear_pending()
            return None

        if self._collapse_detected:
            confirmed = (
                current.total_endpoints < self._peak_endpoints * self.MATCH_END_CONFIRM_RATIO
                or (
                    self._peak_connections > 0
                    and current.active_connections > 0
                    and current.active_connections
                    < self._peak_connections * self.CONNECTION_DROP_RATIO
                )
            )
            if confirmed:
                evidence = list(self._collapse_evidence) + [
                    "Endpoint count remains well below in-match peak",
                ]
                return self._propose(GameState.MATCH_ENDED, evidence)

            self._collapse_detected = False
            self._collapse_evidence = []

        self._clear_pending()
        return None

    def _infer_from_match_ended(
        self, current: NetworkSnapshot, previous: Optional[NetworkSnapshot]
    ) -> Optional[StateChangeEvent]:
        """Detect MATCH_ENDED → LOBBY.

        Signal: after POST_MATCH_MIN_TIME seconds, the network stabilizes
        back to a lobby-like pattern (low churn, endpoint count near the
        lobby baseline when one exists).
        """
        if self.get_state_duration() < self.POST_MATCH_MIN_TIME:
            return None

        new_count = self._effective_new(current, previous)
        removed_count = self._effective_removed(current, previous)

        stable = (
            new_count <= self.STABILITY_CHURN_LIMIT
            and removed_count <= self.STABILITY_CHURN_LIMIT
        )

        baseline_ok = True
        baseline = self._lobby_baseline
        if baseline is not None and baseline.total_endpoints > 0:
            tolerance = max(
                self.BASELINE_TOLERANCE_FLOOR, int(baseline.total_endpoints * 0.5)
            )
            baseline_ok = abs(current.total_endpoints - baseline.total_endpoints) <= tolerance

        if stable and baseline_ok:
            evidence = [
                f"Post-match network stabilized: +{new_count} new, -{removed_count} removed",
                f"Total endpoints: {current.total_endpoints}",
                "Inferred: returned to lobby",
            ]
            return self._propose(GameState.LOBBY, evidence)

        self._clear_pending()
        return None

    def _propose(self, target: GameState, evidence: list[str]) -> Optional[StateChangeEvent]:
        """Propose a transition, committing only after consecutive confirmations."""
        if self._pending_target is target:
            self._pending_confirmations += 1
        else:
            self._pending_target = target
            self._pending_evidence = list(evidence)
            self._pending_confirmations = 1

        required = self.CONFIRMATIONS.get(target, 2)
        if self._pending_confirmations >= required:
            committed_evidence = list(self._pending_evidence) + [
                f"Confirmed on {self._pending_confirmations} consecutive snapshots"
            ]
            self._clear_pending()
            return self._transition(target, committed_evidence)

        return None

    def _clear_pending(self):
        """Discard an unconfirmed transition proposal."""
        self._pending_target = None
        self._pending_evidence = []
        self._pending_confirmations = 0

    @staticmethod
    def _effective_new(
        current: NetworkSnapshot, previous: Optional[NetworkSnapshot]
    ) -> int:
        """New-endpoint count, falling back to total delta when unset."""
        if current.new_endpoints > 0:
            return current.new_endpoints
        if previous is not None:
            return max(0, current.total_endpoints - previous.total_endpoints)
        return 0

    @staticmethod
    def _effective_removed(
        current: NetworkSnapshot, previous: Optional[NetworkSnapshot]
    ) -> int:
        """Removed-endpoint count, falling back to total delta when unset."""
        if current.removed_endpoints > 0:
            return current.removed_endpoints
        if previous is not None:
            return max(0, previous.total_endpoints - current.total_endpoints)
        return 0

    def _transition(self, new_state: GameState, evidence: list[str]) -> StateChangeEvent:
        """Execute a state transition."""
        old_state = self._state
        transition = self._determine_transition(old_state, new_state)

        event = StateChangeEvent(
            timestamp=time.time(),
            from_state=old_state,
            to_state=new_state,
            transition=transition,
            evidence=evidence,
            is_inferred=True,
        )

        self._previous_states.append(old_state)
        self._state = new_state
        self._state_entry_time = time.time()
        self._transition_history.append(event)

        if new_state == GameState.MATCHMAKING:
            self._matchmaking_time = event.timestamp
        elif new_state == GameState.IN_MATCH:
            self._match_start_time = event.timestamp
            last = self._last_network_snapshot
            self._peak_endpoints = last.total_endpoints if last else 0
            self._peak_connections = last.active_connections if last else 0
        elif new_state == GameState.MATCH_ENDED:
            self._restructure_detected = False
            self._restructure_evidence = []

        self._clear_pending()
        self._restructure_detected = False
        self._restructure_evidence = []
        self._collapse_detected = False
        self._collapse_evidence = []

        if len(self._transition_history) > 100:
            self._transition_history = self._transition_history[-100:]

        return event

    def _determine_transition(
        self, from_state: GameState, to_state: GameState
    ) -> StateTransition:
        mapping = {
            (GameState.NOT_RUNNING, GameState.LOBBY): StateTransition.ENTERED_LOBBY,
            (GameState.LOBBY, GameState.MATCHMAKING): StateTransition.ENTERED_MATCHMAKING,
            (GameState.LOBBY, GameState.IN_MATCH): StateTransition.ENTERED_MATCH,
            (GameState.MATCHMAKING, GameState.IN_MATCH): StateTransition.MATCH_FOUND,
            (GameState.MATCHMAKING, GameState.LOADING): StateTransition.ENTERED_LOADING,
            (GameState.LOADING, GameState.IN_MATCH): StateTransition.ENTERED_MATCH,
            (GameState.IN_MATCH, GameState.MATCH_ENDED): StateTransition.MATCH_ENDED,
            (GameState.MATCH_ENDED, GameState.LOBBY): StateTransition.ENTERED_LOBBY,
        }
        return mapping.get((from_state, to_state), StateTransition.NONE)

    def reset(self):
        """Reset the state machine to initial state."""
        self._state = GameState.NOT_RUNNING
        self._previous_states.clear()
        self._state_entry_time = 0.0
        self._last_network_snapshot = None
        self._lobby_baseline = None
        self._transition_history.clear()
        self._matchmaking_time = 0.0
        self._match_start_time = 0.0
        self._clear_pending()
        self._restructure_detected = False
        self._restructure_evidence = []
        self._collapse_detected = False
        self._collapse_evidence = []
        self._peak_endpoints = 0
        self._peak_connections = 0

    @property
    def state_label(self) -> str:
        labels = {
            GameState.NOT_RUNNING: "NOT RUNNING",
            GameState.LOBBY: "LOBBY",
            GameState.MATCHMAKING: "MATCHMAKING",
            GameState.LOADING: "LOADING",
            GameState.IN_MATCH: "IN MATCH",
            GameState.MATCH_ENDED: "MATCH ENDED",
            GameState.UNKNOWN: "UNKNOWN",
        }
        return labels.get(self._state, "UNKNOWN")

    @property
    def state_color(self) -> str:
        colors = {
            GameState.NOT_RUNNING: "#514A70",
            GameState.LOBBY: "#60a5fa",
            GameState.MATCHMAKING: "#FFB454",
            GameState.LOADING: "#C9C0FF",
            GameState.IN_MATCH: "#34d399",
            GameState.MATCH_ENDED: "#FF6F6F",
            GameState.UNKNOWN: "#514A70",
        }
        return colors.get(self._state, "#514A70")
