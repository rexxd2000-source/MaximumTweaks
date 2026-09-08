"""Network Intelligence — game network discovery and route analysis engine."""
from engine.intel.process_detector import (
    detect_game_processes, get_game_process, get_all_game_processes,
    is_game_running, get_supported_games, get_game_display_name,
    ProcessInfo, GameBinary,
)
from engine.intel.network_observer import (
    NetworkObserver, TrackedEndpoint, RawConnection,
    get_all_connections, get_connections_for_pid, get_remote_connections_for_pid,
)
from engine.intel.game_state_machine import (
    GameStateMachine, GameState, StateTransition, StateChangeEvent, NetworkSnapshot,
)
from engine.intel.lobby_baseline import LobbyBaselineTracker, LobbyBaseline
from engine.intel.endpoint_scorer import (
    EndpointScorer, EndpointCandidate, EndpointClassification, ScoringSignal,
)
from engine.intel.session_manager import SessionManager, GameSession, SessionEvent
from engine.intel.orchestrator import IntelOrchestrator, IntelSnapshot
from engine.intel.enrichment import (
    lookup_geo, lookup_asn, lookup_bgp, lookup_rdns,
    enrich_endpoint, enrich_connections_batch,
    detect_user_location, detect_isp,
)
from engine.intel.traceroute import measure_route, classify_route

__all__ = [
    "detect_game_processes", "get_game_process", "get_all_game_processes",
    "is_game_running", "get_supported_games", "get_game_display_name",
    "ProcessInfo", "GameBinary",
    "NetworkObserver", "TrackedEndpoint", "RawConnection",
    "get_all_connections", "get_connections_for_pid", "get_remote_connections_for_pid",
    "GameStateMachine", "GameState", "StateTransition", "StateChangeEvent", "NetworkSnapshot",
    "LobbyBaselineTracker", "LobbyBaseline",
    "EndpointScorer", "EndpointCandidate", "EndpointClassification", "ScoringSignal",
    "SessionManager", "GameSession", "SessionEvent",
    "IntelOrchestrator", "IntelSnapshot",
    "lookup_geo", "lookup_asn", "lookup_bgp", "lookup_rdns",
    "enrich_endpoint", "enrich_connections_batch",
    "detect_user_location", "detect_isp",
    "measure_route", "classify_route",
]
