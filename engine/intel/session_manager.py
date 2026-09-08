"""Owns the active game session and archives finished ones."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from engine.intel.game_state_machine import GameState, StateChangeEvent
from engine.intel.endpoint_scorer import EndpointCandidate, EndpointClassification
from engine.intel.network_observer import TrackedEndpoint


@dataclass
class SessionEvent:
    timestamp: float = 0.0
    event_type: str = ""
    description: str = ""
    game_state: GameState = GameState.UNKNOWN
    endpoint_ip: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class GameSession:
    session_id: int = 0
    game_key: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    game_state: GameState = GameState.NOT_RUNNING
    timeline: list[SessionEvent] = field(default_factory=list)
    game_endpoint: Optional[EndpointCandidate] = None
    all_candidates: list[EndpointCandidate] = field(default_factory=list)
    lobby_endpoint_count: int = 0
    match_endpoint_count: int = 0
    route_target: str = ""

    @property
    def is_active(self) -> bool:
        return self.end_time <= 0

    @property
    def duration(self) -> float:
        if self.end_time > 0:
            return self.end_time - self.start_time
        return time.time() - self.start_time if self.start_time > 0 else 0

    @property
    def display_id(self) -> str:
        return f"#{self.session_id:03d}"

    def add_event(self, event_type: str, description: str,
                  game_state: GameState = GameState.UNKNOWN, **kw):
        self.timeline.append(SessionEvent(
            timestamp=time.time(),
            event_type=event_type,
            description=description,
            game_state=game_state or self.game_state,
            **kw,
        ))


class SessionManager:
    """Manages the lifecycle of game sessions.

    Creates a new session when a match starts.
    Archives the session when the match ends.
    Tracks the current game session endpoint.
    """

    def __init__(self):
        self._sessions: list[GameSession] = []
        self._current: Optional[GameSession] = None
        self._next_id = 1

    @property
    def current(self) -> Optional[GameSession]:
        return self._current

    @property
    def all_sessions(self) -> list[GameSession]:
        return self._sessions

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def on_state_change(self, event: StateChangeEvent, game_key: str = ""):
        """Handle a game state transition."""
        if event.to_state == GameState.LOBBY and event.from_state in (
            GameState.NOT_RUNNING, GameState.MATCH_ENDED
        ):
            self._start_session(game_key)

        if event.to_state == GameState.IN_MATCH and self._current:
            self._current.add_event(
                "match_started", f"Match started ({event.to_state.value})",
                event.to_state,
            )

        if event.to_state == GameState.MATCH_ENDED and self._current:
            self._current.add_event(
                "match_ended", "Match ended",
                event.to_state,
            )

        if event.to_state == GameState.NOT_RUNNING and self._current:
            self._end_session()

    def _start_session(self, game_key: str = ""):
        if self._current and self._current.is_active:
            self._current.end_time = time.time()
            self._current.add_event("session_archived", "Previous session archived")

        session = GameSession(
            session_id=self._next_id,
            game_key=game_key,
            start_time=time.time(),
            game_state=GameState.LOBBY,
        )
        session.add_event("session_started", f"Session {session.display_id} started")
        self._next_id += 1
        self._current = session
        self._sessions.append(session)

    def _end_session(self):
        if self._current:
            self._current.end_time = time.time()
            self._current.add_event("session_ended", "Game process lost")
            self._current = None

    def set_game_endpoint(self, candidate: EndpointCandidate):
        """Set the game session endpoint for the current session."""
        if self._current:
            self._current.game_endpoint = candidate
            self._current.route_target = candidate.ip
            self._current.add_event(
                "endpoint_selected",
                f"Game endpoint: {candidate.ip} (score={candidate.score})",
                metadata={"ip": candidate.ip, "score": candidate.score,
                          "classification": candidate.classification.value},
            )

    def update_candidates(self, candidates: list[EndpointCandidate]):
        """Update the candidate list for the current session."""
        if self._current:
            self._current.all_candidates = candidates

    def update_state(self, state: GameState):
        if self._current:
            self._current.game_state = state

    def get_previous_session(self) -> Optional[GameSession]:
        if len(self._sessions) >= 2:
            return self._sessions[-2]
        return None

    def reset(self):
        self._sessions.clear()
        self._current = None
        self._next_id = 1
