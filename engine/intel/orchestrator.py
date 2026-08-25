"""Orchestrator — the main network intelligence pipeline.

Architecture:
    Game Process → Process Identification → Live Network Observation →
    TCP + UDP Endpoints → Lobby Baseline → Matchmaking Detection →
    Match-Start Correlation → Endpoint Candidates → Candidate Scoring →
    Current Game Session Endpoint → ASN/BGP/RDNS/Geo →
    Route Measurement → ISP/Transit/Hop Analysis → Globe

Runs as a background QThread. Emits signals to the UI.
"""
from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass, field
from typing import Optional, Callable

from PySide6.QtCore import QThread, Signal

from engine.intel.process_detector import (
    detect_game_processes, get_game_process, get_game_display_name,
    ProcessInfo, GameBinary,
)
from engine.intel.network_observer import NetworkObserver, TrackedEndpoint
from engine.intel.game_state_machine import GameStateMachine, GameState, NetworkSnapshot
from engine.intel.lobby_baseline import LobbyBaselineTracker
from engine.intel.endpoint_scorer import EndpointScorer, EndpointCandidate
from engine.intel.session_manager import SessionManager
from engine.intel.udp_capture import UdpCapture, GameServerEndpoint


@dataclass
class IntelSnapshot:
    """Complete snapshot of the network intelligence pipeline state."""
    game_key: str = ""
    game_display: str = ""
    game_process: Optional[ProcessInfo] = None
    game_state: GameState = GameState.NOT_RUNNING
    state_label: str = "NOT RUNNING"
    state_color: str = "#5F6178"
    session_id: str = ""
    user_lat: float = 0.0
    user_lon: float = 0.0
    user_city: str = ""
    user_country: str = ""
    user_isp: str = ""
    user_isp_asn: int = 0
    game_endpoint: Optional[EndpointCandidate] = None
    all_candidates: list[EndpointCandidate] = field(default_factory=list)
    all_endpoints: list[TrackedEndpoint] = field(default_factory=list)
    lobby_baseline_count: int = 0
    current_endpoint_count: int = 0
    udp_port_count: int = 0
    timeline: list = field(default_factory=list)
    route_target: str = ""
    game_server_detected: bool = False
    captured_game_server: Optional[GameServerEndpoint] = None
    udp_capture_active: bool = False
    udp_capture_admin: bool = False
    npcap_missing: bool = False
    npcap_installer_path: str = ""
    status: str = "SCANNING"
    debug_lines: list[str] = field(default_factory=list)
    timestamp: float = 0.0


class IntelOrchestrator(QThread):
    """Main network intelligence pipeline.

    Polls every N seconds:
    1. Detect game process
    2. Observe network connections for game PID
    3. Update game state machine
    4. Score endpoint candidates
    5. Select game session endpoint
    6. Emit complete snapshot to UI
    """

    snapshot_updated = Signal(object)
    status_update = Signal(str)
    debug_info = Signal(str)

    def __init__(self, poll_interval: float = 3.0, parent=None):
        super().__init__(parent)
        self._poll_interval = poll_interval
        self._running = False
        self._game_key: str = ""
        self._game_process: Optional[ProcessInfo] = None
        self._observer: Optional[NetworkObserver] = None
        self._state_machine = GameStateMachine()
        self._baseline = LobbyBaselineTracker()
        self._scorer = EndpointScorer()
        self._session_mgr = SessionManager()
        self._udp_capture = UdpCapture()
        self._snapshot = IntelSnapshot()
        self._baseline_captured = False
        self._last_poll = 0.0
        self._debug_lines: list[str] = []

    @property
    def snapshot(self) -> IntelSnapshot:
        return self._snapshot

    def run(self):
        self._running = True
        while self._running:
            try:
                self._poll()
            except Exception as e:
                self._add_debug(f"Poll error: {e}")
                self.status_update.emit(f"Error: {e}")
            time.sleep(self._poll_interval)

    def stop(self):
        self._running = False
        self._udp_capture.stop()
        self.wait(5000)

    def _poll(self):
        self._debug_lines.clear()
        now = time.time()

        # Step 1: Detect game process
        game_proc = get_game_process(self._game_key) if self._game_key else None
        if not game_proc:
            for key in ["fortnite", "valorant", "cod", "cs2"]:
                game_proc = get_game_process(key)
                if game_proc:
                    self._game_key = key
                    break

        if not game_proc:
            if self._game_process:
                self._state_machine.set_game_running(False)
                self._snapshot.game_state = GameState.NOT_RUNNING
                self._snapshot.status = "NO GAME"
                self._snapshot.game_process = None
                self._snapshot.route_target = ""
                self._snapshot.game_endpoint = None
                self._snapshot.captured_game_server = None
                self._game_process = None
                self._observer = None
                self._udp_capture.stop()
                self._udp_capture.clear()
            return

        # Check if process changed (game restarted)
        if self._game_process and self._game_process.pid != game_proc.pid:
            self._add_debug(f"Game PID changed: {self._game_process.pid} -> {game_proc.pid}")
            self._reset_pipeline()

        self._game_process = game_proc
        self._snapshot.game_process = game_proc
        self._snapshot.game_key = self._game_key
        self._snapshot.game_display = get_game_display_name(self._game_key)

        self._add_debug(f"Game: {game_proc.display_name} PID={game_proc.pid} ({game_proc.name})")
        self._state_machine.set_game_running(True, game_proc.name)

        # Reset per-poll snapshot flags
        self._snapshot.npcap_missing = False
        self._snapshot.npcap_installer_path = ""

        # Start UDP capture if not already running
        if not self._udp_capture.is_capturing and self._udp_capture.has_admin:
            if self._udp_capture.start():
                self._add_debug("UDP raw capture started (admin mode)")
            else:
                err = self._udp_capture.start_error
                if err.startswith("NEED_NPCAP|"):
                    installer = err.split("|", 1)[1]
                    self._snapshot.npcap_missing = True
                    self._snapshot.npcap_installer_path = installer
                    self._add_debug("UDP capture: Npcap not installed — bundled installer available")
                else:
                    self._add_debug(f"UDP raw capture failed to start: {err}")
        elif not self._udp_capture.has_admin:
            self._add_debug("UDP raw capture: requires Administrator")

        # Step 2: Observe network
        if not self._observer or self._observer.pid != game_proc.pid:
            self._observer = NetworkObserver(game_proc.pid)

        endpoints = self._observer.poll()

        # Raw counts BEFORE any filtering
        raw_tcp = sum(1 for e in endpoints if e.protocol == "TCP")
        raw_udp = sum(1 for e in endpoints if e.protocol == "UDP")
        self._add_debug(f"RAW: {raw_tcp} TCP, {raw_udp} UDP for PID {game_proc.pid}")

        # System-wide counts for reference
        from engine.intel.network_observer import get_all_connections
        sys_conns = get_all_connections()
        sys_tcp = sum(1 for c in sys_conns if c.protocol == "TCP")
        sys_udp = sum(1 for c in sys_conns if c.protocol == "UDP")
        self._add_debug(f"SYSTEM: {sys_tcp} TCP, {sys_udp} UDP total")

        # After game-endpoint filtering
        active = self._observer.get_active_game_endpoints()
        udp_count = self._observer.get_udp_port_count()
        tcp_count = self._observer.get_established_tcp_count()
        self._add_debug(f"Active: {len(active)} total ({tcp_count} TCP, {udp_count} UDP ports)")

        # Feed game's UDP ports to capture
        game_udp_ports = set()
        for ep in endpoints:
            if ep.protocol == "UDP":
                game_udp_ports.add(ep.local_port)
        self._udp_capture.set_local_udp_ports(game_udp_ports)

        # Log individual connections for debugging (first 10 TCP, all UDP)
        for ep in endpoints[:10]:
            if ep.protocol == "TCP":
                self._add_debug(f"  TCP local:{ep.local_port} -> {ep.remote_ip}:{ep.remote_port} "
                               f"[obs:{ep.observation_count}] active:{ep.is_active}")
            elif ep.protocol == "UDP":
                age = f"{ep.age_seconds:.0f}s" if ep.first_seen else "?"
                self._add_debug(f"  UDP local:{ep.local_port} remote:{ep.remote_ip or '?'}:{ep.remote_port or '?'} "
                               f"[obs:{ep.observation_count}, age:{age}] active:{ep.is_active}")

        # Step 3: Update state machine
        # New endpoints = connections that appeared in the last 15s.
        lobby_baseline_count = self._baseline.baseline.total_endpoints if self._baseline.has_baseline else 0
        new_recent = len(self._observer.get_new_endpoints_since(now - 15.0))  # 15s window
        new_count = new_recent

        self._add_debug(f"Endpoint delta: baseline={lobby_baseline_count} current={len(active)} "
                       f"new_recent(15s)={new_recent}")

        snapshot = NetworkSnapshot(
            timestamp=now,
            total_endpoints=len(active),
            tcp_endpoints=tcp_count,
            udp_endpoints=udp_count,
            new_endpoints=new_count,
            udp_port_count=udp_count,
        )

        if not self._baseline_captured and self._state_machine.is_in_lobby:
            self._baseline.capture_from_observer(self._observer, include_udp=True)
            self._baseline_captured = True
            udp_bl = self._observer.get_udp_port_count()
            self._add_debug(f"Lobby baseline: {self._baseline.baseline.total_endpoints} endpoints ({udp_bl} UDP ports)")

        transition = self._state_machine.update_network(snapshot)
        if transition:
            self._add_debug(f"State: {transition.from_state.value} -> {transition.to_state.value}")
            self._session_mgr.on_state_change(transition, self._game_key)

            if transition.to_state == GameState.MATCHMAKING:
                self._scorer.set_match_timing(matchmaking_time=now)
                self._add_debug("Matchmaking detected - recording timing")

            if transition.to_state == GameState.IN_MATCH:
                self._scorer.set_match_timing(match_start_time=now)
                self._add_debug("Match detected - scoring endpoints")

                # Direct LOBBY → IN_MATCH: also record as matchmaking start
                if transition.from_state == GameState.LOBBY:
                    self._scorer.set_match_timing(matchmaking_time=now, match_start_time=now)
                    self._add_debug("Direct lobby→match transition (fast matchmaking)")

        # Step 4: Score candidates (always, not just when IN_MATCH)
        if active:
            candidates = self._scorer.score_all(
                active,
                lobby_baseline=self._baseline,
                game_state=self._state_machine.state,
            )
            self._snapshot.all_candidates = candidates
            self._session_mgr.update_candidates(candidates)

            # Step 5: Select best candidate (always, so UI shows data even in LOBBY)
            best = self._scorer.get_best_candidate(candidates)
            if best:
                prev = self._snapshot.game_endpoint
                if not prev or prev.ip != best.ip:
                    self._session_mgr.set_game_endpoint(best)
                    self._add_debug(f"Game endpoint: {best.ip} score={best.score} "
                                   f"class={best.classification.value}")

            # Log all candidate IPs for debugging
            for c in candidates[:8]:
                self._add_debug(f"  Candidate: {c.ip}:{c.port} score={c.score} "
                               f"{c.protocol} {c.classification.value}")

        # Build snapshot
        self._snapshot.game_state = self._state_machine.state
        self._snapshot.state_label = self._state_machine.state_label
        self._snapshot.state_color = self._state_machine.state_color
        self._snapshot.all_endpoints = active
        self._snapshot.lobby_baseline_count = self._baseline.baseline.total_endpoints if self._baseline.has_baseline else 0
        self._snapshot.current_endpoint_count = len(active)
        self._snapshot.udp_port_count = udp_count
        self._snapshot.session_id = self._session_mgr.current.display_id if self._session_mgr.current else ""
        self._snapshot.timeline = self._session_mgr.current.timeline if self._session_mgr.current else []
        self._snapshot.debug_lines = list(self._debug_lines)
        self._snapshot.timestamp = now
        self._snapshot.status = self._state_machine.state_label

        # Route target priority:
        # 1. Raw UDP capture (actual game server if visible)
        # 2. Most stable TCP connection by observation count (longest-lived = game server)
        captured = self._udp_capture.get_best_server(game_udp_ports) if game_udp_ports else None
        self._snapshot.captured_game_server = captured
        self._snapshot.udp_capture_active = self._udp_capture.is_capturing
        self._snapshot.udp_capture_admin = self._udp_capture.has_admin

        # Debug: raw capture status
        all_captured = self._udp_capture.get_game_servers() if self._udp_capture.is_capturing else []
        if self._udp_capture.is_capturing:
            stats = self._udp_capture.get_capture_stats()
            self._add_debug(f"  CAPTURE stats: {stats}")
            if all_captured:
                for srv in all_captured[:4]:
                    age = time.time() - srv.last_seen
                    self._add_debug(f"  CAPTURED: {srv.ip}:{srv.port} "
                                   f"({srv.packet_count} pkts, age:{age:.0f}s)")
            else:
                self._add_debug("  CAPTURED: (no game server packets matched)")
        elif self._udp_capture.has_admin:
            self._add_debug(f"  CAPTURE: start failed — {self._udp_capture.start_error}")
        else:
            self._add_debug("  CAPTURE: requires Administrator — run as Admin to capture game server")

        # Filter: skip CGNAT, Cloudflare CDN, private IPs
        def _is_traceable(ip_str):
            try:
                ip = ipaddress.ip_address(ip_str)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    return False
                if ip.packed[0] == 100 and (ip.packed[1] & 0xC0) == 64:
                    return False  # CGNAT
                if ip.packed[0] == 104 and ip.packed[1] in (18, 19):
                    return False  # Cloudflare CDN
                return True
            except ValueError:
                return False

        # Find the most stable (highest obs count) TCP connection to a traceable IP
        # This is the actual game server, not a CDN/CDN edge node
        stable_tcp = None
        if active:
            for ep in active:
                if ep.protocol != "TCP" or not ep.remote_ip:
                    continue
                if not _is_traceable(ep.remote_ip):
                    continue
                if stable_tcp is None or ep.observation_count > stable_tcp.observation_count:
                    stable_tcp = ep

        # Debug: list TCP connections by obs count
        tcp_sorted = sorted(
            [ep for ep in (active or []) if ep.protocol == "TCP" and ep.remote_ip],
            key=lambda e: e.observation_count, reverse=True,
        )
        for ep in tcp_sorted[:6]:
            traceable = "traceable" if _is_traceable(ep.remote_ip) else "filtered"
            self._add_debug(f"  TCP: {ep.remote_ip}:{ep.remote_port} "
                           f"[obs:{ep.observation_count}] {traceable}")

        if captured:
            self._snapshot.route_target = captured.ip
            self._snapshot.game_server_detected = True
            self._add_debug(f"Route target: {captured.ip}:{captured.port} "
                           f"(game server via UDP capture, {captured.packet_count} pkts)")
        elif stable_tcp:
            self._snapshot.route_target = stable_tcp.remote_ip
            self._snapshot.game_server_detected = True
            self._add_debug(f"Route target: {stable_tcp.remote_ip}:{stable_tcp.remote_port} "
                           f"(most stable TCP, obs:{stable_tcp.observation_count})")
        else:
            self._snapshot.route_target = ""
            self._snapshot.game_server_detected = False
            self._add_debug("Route target: (no traceable TCP connections found)")
        self._snapshot.debug_lines = list(self._debug_lines)
        self._snapshot.timestamp = now
        self._snapshot.status = self._state_machine.state_label

        self.snapshot_updated.emit(self._snapshot)
        self.status_update.emit(self._snapshot.status)

    def set_user_location(self, lat: float, lon: float, city: str = "", country: str = "", isp: str = "", asn: int = 0):
        self._snapshot.user_lat = lat
        self._snapshot.user_lon = lon
        self._snapshot.user_city = city
        self._snapshot.user_country = country
        self._snapshot.user_isp = isp
        self._snapshot.user_isp_asn = asn

    def _add_debug(self, line: str):
        ts = time.strftime("%H:%M:%S")
        self._debug_lines.append(f"[{ts}] {line}")

    def _reset_pipeline(self):
        self._observer = None
        self._baseline.invalidate()
        self._baseline_captured = False
        self._scorer.reset()
        self._state_machine.reset()
        self._session_mgr.reset()
        self._udp_capture.stop()
        self._udp_capture.clear()

    def reset(self):
        self._reset_pipeline()
        self._game_process = None
        self._game_key = ""
        self._snapshot = IntelSnapshot()
