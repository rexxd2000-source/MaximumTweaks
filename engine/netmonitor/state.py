"""Route state engine — tracks changes, history, and comparisons."""
from __future__ import annotations

import time
from typing import Optional

from engine.netmonitor.types import (
    MonitorState, Route, RouteChange, RouteEvent, HopStatus,
)


class RouteStateEngine:
    def __init__(self, max_history: int = 20, max_events: int = 500):
        self.state = MonitorState()
        self._max_history = max_history
        self._max_events = max_events
        self._callbacks: list = []

    def on_change(self, callback):
        self._callbacks.append(callback)

    def update_route(self, new_route: Route) -> list[RouteChange]:
        changes: list[RouteChange] = []
        self.state.scan_count += 1
        self.state.last_scan_time = time.time()

        if self.state.active_route is None:
            self.state.active_route = new_route
            self.state.previous_route = None
            self._add_event("info", f"Initial route discovered: {new_route.total_hops} hops")
            return changes

        old_route = self.state.active_route
        route_changes = self._detect_changes(old_route, new_route)

        if route_changes:
            self.state.previous_route = old_route
            self.state.active_route = new_route
            self._record_history(old_route)
            self.state.changes.extend(route_changes)
            changes = route_changes
            for c in route_changes:
                self._add_event("warning", c.description)
        else:
            self._update_in_place(new_route)

        for hop in self.state.active_route.hops:
            if hop.ip:
                if hop.number not in self.state.hop_latency_history:
                    self.state.hop_latency_history[hop.number] = []
                self.state.hop_latency_history[hop.number].append(
                    (time.time(), hop.latency)
                )
                max_samples = 200
                if len(self.state.hop_latency_history[hop.number]) > max_samples:
                    self.state.hop_latency_history[hop.number] = \
                        self.state.hop_latency_history[hop.number][-max_samples:]

        for cb in self._callbacks:
            try:
                cb(changes, self.state)
            except Exception:
                pass

        return changes

    def _detect_changes(self, old: Route, new: Route) -> list[RouteChange]:
        changes = []

        old_ips = [h.ip for h in old.hops if h.ip]
        new_ips = [h.ip for h in new.hops if h.ip]

        if old_ips != new_ips:
            old_set = set(old_ips)
            new_set = set(new_ips)
            added = new_set - old_set
            removed = old_set - new_set
            affected = []
            for h in new.hops:
                if h.ip in added or h.ip in removed:
                    affected.append(h.number)

            hop_delta = len(new.hops) - len(old.hops)
            changes.append(RouteChange(
                change_type="path_change",
                description=(
                    f"Route changed: {old.total_hops} → {new.total_hops} hops "
                    f"({hop_delta:+d})"
                ),
                old_route_id=old.route_id,
                new_route_id=new.route_id,
                hop_delta=hop_delta,
                latency_delta=new.total_latency - old.total_latency,
                affected_hops=affected,
            ))

        lat_delta = new.total_latency - old.total_latency
        if abs(lat_delta) > 30 and not changes:
            changes.append(RouteChange(
                change_type="latency_shift",
                description=(
                    f"Latency shifted: {old.total_latency:.0f} → "
                    f"{new.total_latency:.0f} ms ({lat_delta:+.0f} ms)"
                ),
                old_route_id=old.route_id,
                new_route_id=new.route_id,
                latency_delta=lat_delta,
            ))

        old_loss = old.route_packet_loss
        new_loss = new.route_packet_loss
        if old_loss < 5 and new_loss >= 10 and not changes:
            changes.append(RouteChange(
                change_type="packet_loss",
                description=(
                    f"Packet loss increased: {old_loss:.0f}% → {new_loss:.0f}%"
                ),
                old_route_id=old.route_id,
                new_route_id=new.route_id,
            ))

        for old_h, new_h in zip(old.hops, new.hops):
            if old_h.ip == new_h.ip:
                lat_diff = new_h.latency - old_h.latency
                if abs(lat_diff) > 50:
                    changes.append(RouteChange(
                        change_type="hop_latency",
                        description=(
                            f"Hop {new_h.number} latency: "
                            f"{old_h.latency:.0f} → {new_h.latency:.0f} ms"
                        ),
                        affected_hops=[new_h.number],
                        latency_delta=lat_diff,
                    ))

        return changes

    def _update_in_place(self, new_route: Route):
        if not self.state.active_route:
            self.state.active_route = new_route
            return
        for new_h in new_route.hops:
            for old_h in self.state.active_route.hops:
                if new_h.ip == old_h.ip and new_h.number == old_h.number:
                    old_h.probes = new_h.probes
                    old_h.status = new_h.status
                    old_h.hostname = new_h.hostname or old_h.hostname
                    break

    def _record_history(self, route: Route):
        self.state.route_history.append(route)
        if len(self.state.route_history) > self._max_history:
            self.state.route_history = self.state.route_history[-self._max_history:]

    def _add_event(self, level: str, message: str):
        self.state.events.append(RouteEvent(
            timestamp=time.time(),
            level=level,
            message=message,
        ))
        if len(self.state.events) > self._max_events:
            self.state.events = self.state.events[-self._max_events:]

    def get_previous_comparison(self):
        return self.state.comparison

    def get_route_history(self) -> list[Route]:
        return list(self.state.route_history)

    def get_events(self, limit: int = 100) -> list[RouteEvent]:
        return self.state.events[-limit:]

    def get_latency_history(
        self, hop_number: int, window: float = 300
    ) -> list[tuple[float, float]]:
        samples = self.state.hop_latency_history.get(hop_number, [])
        cutoff = time.time() - window
        return [(t, v) for t, v in samples if t >= cutoff]
