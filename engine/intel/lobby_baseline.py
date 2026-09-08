"""Lobby baseline — captures the network connection pattern while in lobby.

Used to detect when the user enters matchmaking (new endpoints appear)
and when a match starts (significant endpoint changes).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from engine.intel.network_observer import NetworkObserver, TrackedEndpoint
from engine.intel.game_state_machine import NetworkSnapshot


@dataclass
class LobbyBaseline:
    """The network connection pattern during LOBBY state."""
    captured_at: float = 0.0
    endpoint_keys: set[str] = field(default_factory=set)
    total_endpoints: int = 0
    tcp_endpoints: int = 0
    udp_endpoints: int = 0
    endpoint_details: dict[str, TrackedEndpoint] = field(default_factory=dict)
    is_valid: bool = False

    def to_snapshot(self) -> NetworkSnapshot:
        return NetworkSnapshot(
            timestamp=self.captured_at,
            total_endpoints=self.total_endpoints,
            tcp_endpoints=self.tcp_endpoints,
            udp_endpoints=self.udp_endpoints,
            new_endpoints=0,
            removed_endpoints=0,
            active_connections=self.total_endpoints,
            endpoint_keys=set(self.endpoint_keys),
        )


class LobbyBaselineTracker:
    """Tracks and captures the lobby network baseline.

    When the game enters LOBBY state, this tracker captures the current
    network snapshot as the baseline. All subsequent network changes are
    measured against this baseline.
    """

    def __init__(self):
        self._baseline: Optional[LobbyBaseline] = None
        self._capture_count = 0
        self._last_capture_time = 0.0

    @property
    def baseline(self) -> Optional[LobbyBaseline]:
        return self._baseline

    @property
    def has_baseline(self) -> bool:
        return self._baseline is not None and self._baseline.is_valid

    def capture_from_observer(self, observer: NetworkObserver, include_udp: bool = True):
        """Capture the current network state as the lobby baseline.

        When include_udp=True, includes UDP sockets (game traffic) in the
        baseline. This is important because game servers communicate over UDP.
        """
        if include_udp:
            endpoints = observer.get_active_game_endpoints()
        else:
            endpoints = observer.get_active_remote_endpoints()

        bl = LobbyBaseline()
        bl.captured_at = time.time()
        bl.total_endpoints = len(endpoints)
        bl.tcp_endpoints = sum(1 for e in endpoints if e.protocol == "TCP")
        bl.udp_endpoints = sum(1 for e in endpoints if e.protocol == "UDP")
        bl.endpoint_keys = {e.key for e in endpoints}
        bl.endpoint_details = {e.key: e for e in endpoints}
        bl.is_valid = True

        self._baseline = bl
        self._capture_count += 1
        self._last_capture_time = bl.captured_at

    def compute_delta(
        self, current_endpoints: list[TrackedEndpoint]
    ) -> dict:
        """Compare current endpoints against the lobby baseline.

        Returns dict with:
            new_keys: endpoints not in baseline (appeared during matchmaking/match)
            removed_keys: baseline endpoints that disappeared
            unchanged_keys: endpoints that existed in both
            baseline_count: how many endpoints were in the baseline
            current_count: how many endpoints exist now
        """
        if not self.has_baseline:
            return {
                "new_keys": set(),
                "removed_keys": set(),
                "unchanged_keys": set(),
                "baseline_count": 0,
                "current_count": len(current_endpoints),
            }

        current_keys = {e.key for e in current_endpoints}
        bl_keys = self._baseline.endpoint_keys

        new_keys = current_keys - bl_keys
        removed_keys = bl_keys - current_keys
        unchanged_keys = current_keys & bl_keys

        return {
            "new_keys": new_keys,
            "removed_keys": removed_keys,
            "unchanged_keys": unchanged_keys,
            "baseline_count": len(bl_keys),
            "current_count": len(current_keys),
        }

    def is_endpoint_new(self, endpoint_key: str) -> bool:
        """Check if an endpoint appeared after the baseline was captured."""
        if not self.has_baseline:
            return False
        return endpoint_key not in self._baseline.endpoint_keys

    def was_endpoint_in_lobby(self, endpoint_key: str) -> bool:
        """Check if an endpoint existed during the lobby baseline."""
        if not self.has_baseline:
            return False
        return endpoint_key in self._baseline.endpoint_keys

    def invalidate(self):
        """Clear the baseline (e.g., when game restarts)."""
        self._baseline = None

    def get_baseline_age(self) -> float:
        """How long ago the baseline was captured."""
        if self._last_capture_time > 0:
            return time.time() - self._last_capture_time
        return 0.0
