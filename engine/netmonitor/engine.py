"""Main orchestrator — ties all network monitor components together."""
from __future__ import annotations

import threading
import time
from typing import Optional, Callable

from engine.netmonitor.types import (
    Hop, MonitorState, ProbeMethod, Route, RouteEvent, ViewMode,
)
from engine.netmonitor.traceroute import run_traceroute
from engine.netmonitor.ping import PingMonitor
from engine.netmonitor.resolver import (
    resolve_dns, resolve_hop, classify_hop_role,
    get_local_ip, get_default_gateway, get_dns_resolver,
)
from engine.netmonitor.state import RouteStateEngine
from engine.netmonitor.health import HealthAnalyzer
from engine.netmonitor.explainer import RouteExplainer


class NetworkMonitorEngine:
    def __init__(self):
        self.state_engine = RouteStateEngine()
        self.health = HealthAnalyzer()
        self.explainer = RouteExplainer()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ping_monitor: Optional[PingMonitor] = None
        self._lock = threading.Lock()
        self._on_route_update: list[Callable] = []
        self._on_event: list[Callable] = []
        self._scan_interval = 30.0
        self.view_mode = ViewMode.BASIC

    @property
    def state(self) -> MonitorState:
        return self.state_engine.state

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def on_route_update(self, callback: Callable):
        self._on_route_update.append(callback)

    def on_event(self, callback: Callable):
        self._on_event.append(callback)

    def set_scan_interval(self, seconds: float):
        self._scan_interval = max(10.0, seconds)

    def start_monitoring(self, destination: str):
        if self.running:
            self.stop()

        self._stop.clear()
        self.state_engine.state.destination = destination
        self.state_engine.state.monitoring = True

        try:
            resolved = resolve_dns(destination)
            self.state_engine.state.dns_info = resolved
            if resolved.ipv4:
                self.state_engine.state.destination_ip = resolved.ipv4[0]
        except Exception:
            pass

        self._emit_event("info", f"Monitoring started: {destination}")
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True
        )
        self._thread.start()

        self._start_ping(destination)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        if self._ping_monitor:
            self._ping_monitor.stop()
            self._ping_monitor = None
        self.state_engine.state.monitoring = False
        self._emit_event("info", "Monitoring stopped")

    def run_single_scan(self, destination: str) -> Route:
        route = self._perform_scan(destination)
        return route

    def get_state(self) -> MonitorState:
        return self.state_engine.state

    def get_route(self) -> Optional[Route]:
        return self.state_engine.state.active_route

    def get_previous_route(self) -> Optional[Route]:
        return self.state_engine.state.previous_route

    def get_comparison(self):
        return self.state_engine.get_previous_comparison()

    def get_events(self, limit: int = 100) -> list[RouteEvent]:
        return self.state_engine.get_events(limit)

    def get_latency_history(
        self, hop_number: int, window: float = 300
    ) -> list[tuple[float, float]]:
        return self.state_engine.get_latency_history(hop_number, window)

    def get_ping_samples(self) -> list[tuple[float, float]]:
        if self._ping_monitor:
            return self._ping_monitor.get_samples()
        return []

    def get_basic_view(self) -> dict:
        route = self.get_route()
        if not route:
            return {}
        return self.explainer.basic_view(route, self.state_engine.state)

    def get_advanced_view(self) -> dict:
        route = self.get_route()
        if not route:
            return {}
        return self.explainer.advanced_view(route, self.state_engine.state)

    def _monitor_loop(self):
        while not self._stop.is_set():
            try:
                self._perform_scan()
            except Exception as exc:
                self._emit_event("error", f"Scan error: {exc}")
            self._stop.wait(self._scan_interval)

    def _perform_scan(self, destination: str = None) -> Optional[Route]:
        dest = destination or self.state_engine.state.destination
        if not dest:
            return None

        start_time = time.time()

        def on_hop(num, data):
            pass

        route = run_traceroute(
            dest,
            max_hops=30,
            timeout=5.0,
            callback=on_hop,
            stop_event=self._stop,
        )

        self._emit_event("info", f"Scan completed: {route.total_hops} hops, "
                         f"{route.total_latency:.0f} ms")

        hops_to_resolve = [h for h in route.hops if h.ip and not h.network.is_private]
        resolve_batch_size = 10
        for i in range(0, len(hops_to_resolve), resolve_batch_size):
            if self._stop.is_set():
                break
            batch = hops_to_resolve[i:i + resolve_batch_size]
            for hop in batch:
                if self._stop.is_set():
                    break
                try:
                    hostname, network, geo = resolve_hop(hop.ip)
                    hop.hostname = hostname or hop.hostname
                    hop.network.asn = network.asn or hop.network.asn
                    hop.network.as_org = network.as_org or hop.network.as_org
                    hop.network.isp = network.isp or hop.network.isp
                    hop.network.network_name = network.network_name or hop.network.network_name
                    hop.geo = geo
                    hop.role = classify_hop_role(
                        hop.number,
                        route.total_hops,
                        hop.ip,
                        hop.network,
                        hop.geo,
                        hop.is_last_hop,
                    )
                except Exception:
                    pass

        changes = self.state_engine.update_route(route)

        if changes:
            for c in changes:
                self._emit_event("warning", c.description)

        for cb in self._on_route_update:
            try:
                cb(route, changes)
            except Exception:
                pass

        return route

    def _start_ping(self, target: str):
        if self._ping_monitor:
            self._ping_monitor.stop()

        def on_sample(ts, lat):
            pass

        def on_event(evt):
            self._emit_event(evt.level, evt.message)

        self._ping_monitor = PingMonitor(
            target=target,
            interval=2.0,
            count=3600,
            on_sample=on_sample,
            on_event=on_event,
        )
        self._ping_monitor.start()

    def _emit_event(self, level: str, message: str):
        evt = RouteEvent(
            timestamp=time.time(),
            level=level,
            message=message,
        )
        self.state_engine.state.events.append(evt)
        for cb in self._on_event:
            try:
                cb(evt)
            except Exception:
                pass
