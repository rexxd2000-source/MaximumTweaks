"""Accurate game-server targeting for Route Analyzer.

Resolves the *live match server* the game is actually talking to, instead of
guessing from DNS / last-connected IP / netstat (which can hit a CDN edge,
a backend API, a voice server, or an ExitLag-style relay candidate).

Approach
--------
1. Capture live UDP traffic on the active interface (Npcap scapy backend).
2. Aggregate per remote IP: total bytes, packet count, distinct remote ports,
   plus per-IP byte counts over short time windows.
3. Match known per-game port signatures (e.g. Fortnite exposes base,
   base+6000 and a fixed control port 22222 on one IP).
4. Exclude noise (DNS/mDNS/SSDP/NetBIOS/NTP, QUIC/CDN :443, ...) and relay
   candidates (2+ IPs with near-identical byte-samples growing in lockstep).
5. Lock the signature match as the Route Analyzer target.
"""
from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from engine.netmonitor.types import ProbeMethod


# ────────────────────────────────────────────────────────────────────────
#  Passive noise — ports we should never treat as game-server traffic.
# ────────────────────────────────────────────────────────────────────────
_SCAPY_LAYERS_CACHE = [None, None]

_DIAG_LOG = os.path.join(
    os.environ.get("TEMP", "."), "opencode", "detect_trace.log")


def _diag(msg: str):
    try:
        with open(_DIAG_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.time():.3f} {msg}\n")
    except Exception:
        pass


def _SCAPY_LAYERS():
    """Lazily resolve the scapy IP/UDP layer classes once (import is heavy)."""
    if _SCAPY_LAYERS_CACHE[0] is None:
        try:
            from scapy.layers.inet import IP, UDP
            _SCAPY_LAYERS_CACHE[0] = IP
            _SCAPY_LAYERS_CACHE[1] = UDP
        except Exception:
            return None, None
    return tuple(_SCAPY_LAYERS_CACHE)


NOISE_PORTS: set[int] = {
    53,      # DNS
    67, 68,  # DHCP
    123,     # NTP
    137, 138, 139,  # NetBIOS name/datagram
    500, 4500,      # IPsec / NAT-T
    5353,    # mDNS
    5355,    # LLMNR
    1900,    # SSDP/UPnP
    3702,    # WS-Discovery
    443,     # QUIC — CDN/web traffic masquerading as UDP
    2427, 2727,     # SIP/media (softphones)
    4444, 4445,     # misc chat/media helpers
    11111, 25565,   # false positives occasionally sourced by launchers
}

# Ports a single IP uses for outbound-local ephemeral *responses* that still
# look "remote" if we mis-handle direction — rarely the game server.
_EPHEMERAL_UP = range(49152, 65536)


# ────────────────────────────────────────────────────────────────────────
#  Data structures
# ────────────────────────────────────────────────────────────────────────
@dataclass
class _IpFlow:
    ip: str
    bytes_total: int = 0
    packets: int = 0
    ports: set[int] = field(default_factory=set)
    local_ports: set[int] = field(default_factory=set)
    windows: list[tuple[float, int, int]] = field(default_factory=list)

    def snapshot(self, ts: float):
        self.windows.append((ts, self.bytes_total, self.packets))
        keep = 200
        if len(self.windows) > keep:
            self.windows = self.windows[-keep:]


@dataclass
class GameSignature:
    game: str
    # Fixed control port always present on the match server (e.g. 22222).
    control_ports: set[int]
    # Ports arrive in (base, base + offset) pairs.
    offset: int = 6000
    min_unique_remote_ports: int = 3

    def match(self, ports: set[int]) -> tuple[bool, int, list[int]]:
        """Return (matched, score, matched_remote_ports)."""
        if len(ports) < self.min_unique_remote_ports:
            return False, 0, []
        for base in ports:
            pair = base + self.offset
            if pair in ports:
                have_ctrl = self.control_ports & ports
                if have_ctrl:
                    matched = sorted(have_ctrl) + [base, pair]
                    return True, 3, matched
        if self.control_ports & ports:
            return True, 1, sorted(self.control_ports & ports)
        return False, 0, []


GAME_SIGNATURES: dict[str, GameSignature] = {
    # Confirmed across multiple live matches — server exposes base,
    # base+6000 and a fixed control port 22222 on one IP.
    "Fortnite": GameSignature(
        game="Fortnite",
        control_ports={22222},
        offset=6000,
        min_unique_remote_ports=3,
    ),
}


@dataclass
class TargetMatch:
    found: bool = False
    game: str = ""
    ip: str = ""
    remote_ports: list[int] = field(default_factory=list)
    client_ports: list[int] = field(default_factory=list)
    confidence: str = "none"          # none | signature | control | candidate
    reason: str = ""
    protocol: ProbeMethod = ProbeMethod.UDP
    candidate_count: int = 0
    relay_candidates: list[str] = field(default_factory=list)
    duration: float = 0.0
    socket_state: str = ""
    iface: Optional[str] = None  # proven sniff device (see resolve_game_server)


# ────────────────────────────────────────────────────────────────────────
#  Capture
# ────────────────────────────────────────────────────────────────────────
def _win_index_for_ip(remote_ip: Optional[str]) -> Optional[int]:
    """OS interface index that carries traffic toward `remote_ip`
    (GetBestInterface). Used to bind sniffing to the interface that actually
    carries the game-server path."""
    if not remote_ip:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        best = ctypes.windll.iphlpapi.GetBestInterface
        best.argtypes = [ctypes.c_ulong, ctypes.POINTER(wintypes.DWORD)]
        best.restype = wintypes.DWORD
        idx = wintypes.DWORD()
        ip = socket.inet_aton(remote_ip)
        rc = best(int.from_bytes(ip, "big"), ctypes.byref(idx))
        if rc == 0:
            return int(idx.value)
    except (AttributeError, OSError):
        pass
    return None


def _pick_interface(
    remote_ip: Optional[str] = None, local_bound_ip: Optional[str] = None
) -> Optional[str]:
    """Best effort: the Npcap device carrying traffic toward `remote_ip`,
    or hosting the game's bound local address `local_bound_ip`,
    falling back to the primary IPv4 adapter."""
    local = _get_local_ip()
    _diag(f"[_pick_interface] local={local} bound={local_bound_ip}")
    try:
        from scapy.arch.windows import get_windows_if_list
    except Exception as exc:
        _diag(f"[_pick_interface] get_windows_if_list import failed: {exc!r}")
        return None
    try:
        entries = list(get_windows_if_list())
        _diag(f"[_pick_interface] {len(entries)} devices: "
              + "; ".join(f"{e.get('name','?')}[idx={e.get('index','?')}]" for e in entries[:10]))
        if local_bound_ip and local_bound_ip != local:
            for entry in entries:
                guid = entry.get("guid") or (entry.get("guids") or [None])[0]
                if not guid:
                    continue
                ips = entry.get("ips") or []
                if local_bound_ip in ips:
                    return f"\\Device\\NPF_{guid}"
        target_index = _win_index_for_ip(remote_ip)
        if target_index is not None:
            for entry in entries:
                index = entry.get("index")
                if index is None:
                    index = entry.get("win_index")
                if int(index) == target_index:
                    guid = entry.get("guid") or (entry.get("guids") or [None])[0]
                    if guid:
                        return f"\\Device\\NPF_{guid}"
        for entry in entries:
            guid = entry.get("guid") or (entry.get("guids") or [None])[0]
            ips = entry.get("ips") or []
            if not guid:
                continue
            if any(ip == local for ip in ips):
                return f"\\Device\\NPF_{guid}"
        # Fallback: first device with any IPv4 address.
        for entry in entries:
            guid = entry.get("guid") or (entry.get("guids") or [None])[0]
            if guid and any("." in ip for ip in (entry.get("ips") or [])):
                return f"\\Device\\NPF_{guid}"
    except Exception:
        pass
    _diag(f"[_pick_interface] -> None (no matching Npcap device)")
    return None


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


_WORKER = threading.local()


def _capture(
    local_ip: str,
    duration: float,
    stop_event=None,
    iface: Optional[str] = None,
) -> dict[str, _IpFlow]:
    """Sniff UDP on the active interface and aggregate per remote IP."""
    flows: dict[str, _IpFlow] = {}
    _diag(f"[_capture] begin local={local_ip} iface={iface} dur={duration}")
    try:
        from scapy.layers.inet import IP, UDP
        from scapy.all import sniff
    except Exception as exc:
        _diag(f"[_capture] scapy import failed: {exc!r}")
        return flows

    def handle(pkt):
        if stop_event is not None and stop_event.is_set():
            return
        if IP not in pkt or UDP not in pkt:
            return
        src = pkt[IP].src
        dst = pkt[IP].dst
        sport = int(pkt[UDP].sport)
        dport = int(pkt[UDP].dport)
        size = int(getattr(pkt[IP], "len", 0)) or 0

        # Determine which end is remote. Game CLIENTS sendto() unconnected UDP,
        # so outbound src:sport is the client, dst:dport the server, and
        # inbound is mirrored. Normalize so "remote port" = the far end's port.
        if src == local_ip:
            remote_ip, remote_port = dst, dport
            if remote_port in NOISE_PORTS:
                return
        elif dst == local_ip:
            remote_ip, remote_port = src, sport
            if remote_port in NOISE_PORTS:
                return
            # The client-side local port the game socket sends from — used to
            # re-probe the exact live flow during traceroute.
            try:
                flow_local = flows.get(remote_ip)
                if flow_local is not None:
                    flow_local.local_ports.add(dport)
            except Exception:
                pass
        else:
            return

        if remote_ip.startswith(("224.", "239.", "255.255.255.")):
            return
        if remote_ip == local_ip:
            return

        flow = flows.get(remote_ip)
        if flow is None:
            flow = _IpFlow(ip=remote_ip)
            flows[remote_ip] = flow
        flow.bytes_total += size
        flow.packets += 1
        flow.ports.add(remote_port)

    if iface is None:
        iface = _pick_interface()
    _diag(f"[_capture] sniff start iface={iface}")
    try:
        sniff(
            prn=handle,
            store=0,
            timeout=max(1.0, duration),
            filter="udp",
            iface=iface,
            stop_filter=(
                lambda p: bool(stop_event is not None and stop_event.is_set())
            ),
        )
        _diag("[_capture] sniff primary returned")
    except Exception as exc:
        _diag(f"[_capture] sniff primary failed: {exc!r}")
        try:
            sniff(
                prn=handle,
                store=0,
                timeout=max(1.0, duration),
                filter="udp",
            )
            _diag("[_capture] sniff fallback returned")
        except Exception as exc2:
            _diag(f"[_capture] sniff fallback failed: {exc2!r}")
            pass

    # Tag each flow's growth windows with a snapshot for lockstep detection.
    now = time.time()
    for flow in flows.values():
        flow.snapshot(now)
    _diag(f"[_capture] done: {len(flows)} flows")
    return flows


# ────────────────────────────────────────────────────────────────────────
#  Filters
# ────────────────────────────────────────────────────────────────────────
def _is_relay(flows: dict[str, _IpFlow]) -> list[str]:
    """ExitLag-style route optimizers test several relay candidates at once:
    2-3 IPs whose byte counts stay near-identical across time windows and
    grow in lockstep. Return the IPs that look like such a relay group.

    A strict signature match is never flagged as a relay here — callers pass
    only candidate IPs that did not produce a clean signature hit.
    """
    candidates = [f for f in flows.values() if f.packets >= 3]
    if len(candidates) < 2:
        return []

    def _near(a: int, b: int, tol: float = 0.12) -> bool:
        bigger = max(a, b)
        return bigger > 0 and abs(a - b) <= bigger * tol

    flags: set[str] = set()
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a, b = candidates[i], candidates[j]
            # Compare per-window byte growth lockstep.
            windows = min(len(a.windows), len(b.windows))
            if windows >= 2:
                lock = 0
                growth_windows = windows - 1
                for k in range(1, windows):
                    da = a.windows[k][1] - a.windows[k - 1][1]
                    db = b.windows[k][1] - b.windows[k - 1][1]
                    if da > 0 and db > 0 and _near(da, db):
                        lock += 1
                # The whole observed growth profile must match — a single
                # coincidental matching segment is how coincidental bursts
                # get misread as relays (false Path-HIGH). Require a strict
                # majority (and all of it when barely observable).
                need = max(2, growth_windows // 2 + 1)
                if lock >= need:
                    flags.add(a.ip)
                    flags.add(b.ip)
            else:
                # Too few windows to observe growth — fall back to identical
                # burst totals. ExitLag tests N relays with the exact same
                # tiny probe burst on each (same pkt count AND same bytes),
                # which is the strongest lockstep tell.
                if a.packets == b.packets and a.bytes_total == b.bytes_total:
                    flags.add(a.ip)
                    flags.add(b.ip)
    return sorted(flags)


def _looks_desktop_multi(candidate: _IpFlow) -> bool:
    """Anything with a single remote port that isn't part of a multi-port
    game signature is very likely voice chat or a steady media stream."""
    return len(candidate.ports) <= 1


def _finalize_udp_target(match: TargetMatch) -> TargetMatch:
    """Bug 18 hard guard: a game server is confirmed ONLY over UDP.

    The per-game port signature (control port + base/base+6000 pair) is a UDP
    signature by construction. Any future code path that surfaces a non-UDP
    candidate as "the game server" is rejected here, immediately — a TCP
    connection to the same range is a CDN/backend/telemetry endpoint, never
    the in-match server, regardless of traffic volume.
    """
    if match.found and match.protocol is not ProbeMethod.UDP:
        _diag(
            f"[finalize] REJECTED non-UDP target "
            f"{match.ip} protocol={match.protocol!r}"
        )
        return TargetMatch(
            game=match.game,
            ip="",
            reason=(
                f"Rejected non-UDP candidate {match.ip} "
                f"(protocol={match.protocol!r}) — game servers are UDP-only "
                "by port-signature definition"
            ),
            candidate_count=match.candidate_count,
            protocol=ProbeMethod.UDP,
        )
    return match


# ────────────────────────────────────────────────────────────────────────
#  Main resolver
# ────────────────────────────────────────────────────────────────────────
def resolve_game_server(
    game: str,
    duration: float = 8.0,
    stop_event: Optional[threading.Event] = None,
    bypass_relay_filter: bool = False,
    use_socket_table: bool = True,
) -> TargetMatch:
    """Find the live match server for `game`.

    Two-stage resolution:
      1. Windows socket-table isolation (default on): query GetExtendedUdpTable
         for the endpoints OWNED BY the game process itself. Windows exposes
         each UDP socket's local address/port/PID only (the remote peer is not
         published for UDP), so this stage asserts the game holds live match
         sockets, extracts its exact client ports, and picks the Npcap
         interface that carries the match traffic — no DNS guessing.
      2. Passive UDP capture on that interface: aggregate flows, match
         per-game port signatures, filter relay candidates, and lock the remote
         server the game actually talks to. Flows on the socket-table client
         ports rank first.

    Returns a TargetMatch — set .ip into the Route Analyzer destination and
    run the traceroute with the socket-table/capture ports attached.
    """
    start = time.time()
    _diag(f"[resolve_game_server] begin game={game} duration={duration} sock_table={use_socket_table}")
    sig = next((s for k, s in GAME_SIGNATURES.items() if k.lower() == game.lower()), None)
    if sig is None:
        supported = ", ".join(sorted(GAME_SIGNATURES))
        return TargetMatch(
            game=game,
            reason=f"No port signature profiled for '{game}'. Supported: {supported}.",
        )

    # ── Stage 0: OS socket-table isolation of the game process ──
    # Windows publishes only each UDP socket's LOCAL address/port/PID — the
    # remote peer is not exposed. So this stage proves the game holds live
    # UDP sockets, extracts its exact client ports and the local adapter the
    # match traffic leaves from, and feeds those directly into the capture
    # filter + probe port selection below (no DNS guess, no relay pollution).
    sock_state_seen = False
    sock_report = ""
    sock_iface: Optional[str] = None
    game_client_ports: Optional[set[int]] = None
    if use_socket_table:
        try:
            from engine.netmonitor.socket_table import find_game_pids, game_socket_state

            pids = [pid for pid, _n in find_game_pids(game)]
            state = game_socket_state(game, pids=pids)
            sock_state_seen = bool(state.running)
            sock_report = state.describe()
            if state.in_match:
                game_client_ports = set(state.client_ports) or None
                sock_iface = _pick_interface(local_bound_ip=state.bound_ip)
            elif state.running:
                sock_iface = _pick_interface()
        except Exception:
            sock_report = ""

    local_ip = _get_local_ip()
    # The interface that actually carries the match traffic — the live-RTT
    # monitor and the traceroute MUST reuse exactly this device, or they sniff
    # a captured-but-invisible copy (ExitLag virtual adapters are the classic
    # trap: GetBestInterface() picks one, the game is on another).
    used_iface = sock_iface or _pick_interface()
    flows = _capture(
        local_ip, duration, stop_event, iface=used_iface,
    )
    elapsed = time.time() - start

    relay_ips = _is_relay(flows) if not bypass_relay_filter else []
    relay_set = set(relay_ips)

    best: Optional[_IpFlow] = None
    best_score = 0
    best_ports: list[int] = []
    matched_confidence = "none"

    _sock_conf = ""
    if sock_state_seen and sock_report:
        _sock_conf = f" [socket-table: {sock_report}]"

    def _game_port_score(flow: _IpFlow) -> int:
        if game_client_ports is None:
            return 0
        return 1 if (flow.local_ports & game_client_ports) else 0

    # Strict server lock: when the OS socket table proved the game process
    # holds live client ports, ONLY flows bound to those exact local ports may
    # vote for a server. Nothing else in the window is the match traffic —
    # ranking it by bytes would let a big download or relay shadow the game.
    flows_list = list(flows.values())
    if game_client_ports:
        scoped = [f for f in flows_list if f.local_ports & game_client_ports]
        if scoped:
            flows_list = scoped

    ordered = sorted(
        flows_list,
        key=lambda f: (_game_port_score(f), f.bytes_total),
        reverse=True,
    )

    for flow in ordered:
        if flow.ip in relay_set:
            continue
        hit, score, ports = sig.match(flow.ports)
        if hit:
            # Signature hit beats everything — lock it.
            if score >= 3:
                return _finalize_udp_target(TargetMatch(
                    found=True,
                    game=sig.game,
                    ip=flow.ip,
                    remote_ports=ports,
                    client_ports=sorted(flow.local_ports),
                    confidence="signature",
                    reason=(
                        f"Matched {sig.game} server on {flow.ip} — "
                        f"ports {'/'.join(str(p) for p in ports)} "
                        f"({flow.packets} pkts, {flow.bytes_total} B)"
                        f"{_sock_conf}"
                        f"  \u2014 confidence: HIGH"
                    ),
                    protocol=ProbeMethod.UDP,
                    candidate_count=len(flows),
                    relay_candidates=relay_ips,
                    duration=elapsed,
                    iface=used_iface,
                ))
            if score > best_score and score > 1:
                best = flow
                best_score = score
                best_ports = ports
                matched_confidence = "control"

    if best is not None:
        return _finalize_udp_target(TargetMatch(
            found=True,
            game=sig.game,
            ip=best.ip,
            remote_ports=best_ports,
            client_ports=sorted(best.local_ports),
            confidence=matched_confidence,
            reason=(
                f"Control port on {best.ip} — {'/'.join(str(p) for p in best_ports)} "
                f"({best.packets} pkts, {best.bytes_total} B)"
                f"{_sock_conf}"
                f"  \u2014 confidence: MEDIUM"
            ),
            protocol=ProbeMethod.UDP,
            candidate_count=len(flows),
            relay_candidates=relay_ips,
            duration=elapsed,
            iface=used_iface,
        ))

    # No signature hit — surface the host with the most game-like traffic,
    # excluding obvious desktop media/voice (single remote port) relays.
    fallback: Optional[_IpFlow] = None
    for flow in ordered:
        if flow.ip in relay_set:
            continue
        if _looks_desktop_multi(flow):
            continue
        fallback = flow
        break

    if fallback is not None:
        return _finalize_udp_target(TargetMatch(
            found=True,
            game=sig.game,
            ip=fallback.ip,
            remote_ports=sorted(fallback.ports),
            client_ports=sorted(fallback.local_ports),
            confidence="candidate",
            reason=(
                f"No exact signature — best candidate {fallback.ip} "
                f"(ports {'/'.join(str(p) for p in sorted(fallback.ports))}, "
                f"{fallback.packets} pkts)"
                f"{_sock_conf}"
                f"  \u2014 confidence: LOW"
            ),
            protocol=ProbeMethod.UDP,
            candidate_count=len(flows),
            relay_candidates=relay_ips,
            duration=elapsed,
            iface=used_iface,
        ))

    return TargetMatch(
        game=sig.game,
        reason=(
            "No game server traffic captured. Start a live match, then retry. "
            "Excluded: "
            + (f"relay candidates {'/'.join(relay_ips)}" if relay_ips else "none")
            + (f"; socket-table: {sock_report}" if sock_report else "")
            + "  \u2014 confidence: NONE"
        ),
        candidate_count=len(flows),
        relay_candidates=relay_ips,
        duration=elapsed,
        protocol=ProbeMethod.UDP,
        socket_state=sock_report,
        iface=used_iface,
    )


def supported_games() -> list[str]:
    return sorted(GAME_SIGNATURES.keys())


# ────────────────────────────────────────────────────────────────────────
#  Live match RTT monitor
#
#  The destination hop's latency must mirror what the player actually sees
#  in-match. This monitor passively pairs outbound game packets with the
#  server's responses on the SAME remote port the live socket uses, so the
#  reported ms is the real end-to-end match latency — never a copy of an
#  intermediate router's response time.
# ────────────────────────────────────────────────────────────────────────
class GameRttMonitor:
    """Passively measures live latency/jitter/loss to an active game server."""

    def __init__(
        self,
        server_ip: str,
        remote_ports: list[int],
        local_ip: Optional[str] = None,
        iface: Optional[str] = None,
        on_stats=None,
    ):
        self._server = server_ip
        self._remote_ports = set(int(p) for p in remote_ports if p)
        self._local_ip = local_ip or _get_local_ip()
        self._iface = iface
        self._on_stats = on_stats
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._samples: list[float] = []
        self._pending: dict[int, list[tuple[float, int]]] = {}
        self._sent = 0
        self._matched = 0
        self._max_samples = 400
        # EMA of the trimmed per-publish medians (Part 2): the game's own ping
        # readout is smoothed over a short rolling window — mirror that so the
        # displayed number moves like the in-game counter, not per-packet.
        self._ema: Optional[float] = None
        # EMA of the per-publish BEST round trip — empirically equals the
        # game's own HUD ping on this rig (game 144 vs best 143.5). Unreal
        # displays a smoothed best-case RTT, NOT the window median.
        self._best_ema: Optional[float] = None
        # Causal game-port SYN round trips: (time, rtt_ms). The ONLY trustworthy
        # server RTT — passive newest-outbound pairing of the fire-and-forget
        # stream converges on the packet-cadence midpoint, not the ping.
        self._active_rtt: list[tuple[float, float]] = []
        self._active_ports: list[int] = []
        # Newest time a probe actually got an answer. Gates the active source:
        # the 90s stats window keeps the median robust, but after ~30s without
        # a single probe reply the match is gone — fall back to flow cadence
        # instead of pinning a stale ping.
        self._last_answered: float = 0.0
        self._last_pub_source = "none"

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        _diag(
            f"[GameRttMonitor] start server={self._server} "
            f"ports={sorted(self._remote_ports)} iface={self._iface}"
        )
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        # Causal probe runs ALWAYS (not only when the sniffer goes silent):
        # it is the authoritative server RTT source.
        self._probe_thread = threading.Thread(
            target=self._active_probe_loop, daemon=True
        )
        self._probe_thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        if getattr(self, "_probe_thread", None):
            try:
                self._probe_thread.join(timeout=3)
            except Exception:
                pass
            self._probe_thread = None

    def is_active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _port_filter(self) -> str:
        base = f"udp and host {self._server}"
        ports = sorted(self._remote_ports)
        if ports:
            base += " and (" + " or ".join(f"port {p}" for p in ports) + ")"
        return base

    def _run(self):
        last_publish = [0.0]
        ip_layer, udp_layer = _SCAPY_LAYERS()
        if ip_layer is None:
            return
        try:
            from scapy.all import sniff
            from engine.netmonitor.targeting import _pick_interface

            current = self._iface
            fallback = _pick_interface(local_bound_ip=self._local_ip)
            if fallback and fallback == current:
                fallback = None

            def cb(pkt):
                self._handle(pkt)
                now = time.time()
                if now - last_publish[0] >= 1.0:
                    last_publish[0] = now
                    self._publish()

            # Reuse the resolver's proven device. If it silently sees nothing
            # for a full window (ExitLag virtual-adapter trap), fall back once
            # to the local-bound NIC before parking the monitor.
            quiet_windows = 0
            while not self._stop.is_set():
                _diag(f"[GameRttMonitor] sniff on {current}")
                try:
                    sniff(
                        prn=cb,
                        store=0,
                        filter=self._port_filter(),
                        iface=current,
                        timeout=20.0,
                        stop_filter=lambda p: self._stop.is_set(),
                    )
                except Exception as exc:
                    _diag(f"[GameRttMonitor] sniff {current} failed: {exc!r}")
                if self._stop.is_set():
                    break
                if self._matched > 0:
                    # Stream alive — keep this exactly device, reset quiet tally.
                    quiet_windows = 0
                    continue
                quiet_windows += 1
                if quiet_windows == 1 and fallback:
                    _diag(
                        f"[GameRttMonitor] no match on {current} in 20s "
                        f"— switching to {fallback}"
                    )
                    current = fallback
                    fallback = None
                    continue
                _diag(
                    "[GameRttMonitor] no match on any listening device "
                    "— active probe (already running) is the RTT source"
                )
                break
        except Exception:
            pass

    def _active_probe_loop(self):
        """Causal game-port SYN round trip — the AUTHORITATIVE server ping.

        Proof (this rig, 34.18.196.132): ICMP echo -> nothing, UDP game ports ->
        nothing, but TCP SYN to 9028 -> 142ms reply, matching the in-game ping.
        Passive newest-outbound pairing of the fire-and-forget stream converges
        on the packet-cadence midpoint (~25ms for a 45/s stream), which is NOT
        the server RTT. So a SYN round trip to the game's own ports is the only
        true readout. Probe every remote port, remember which answered, and
        re-scan periodically (a port can start/stop answering).
        """
        import random as _random
        from scapy.layers.inet import IP, TCP
        from scapy.sendrecv import sr1

        src = self._local_ip or ""
        if not src or src == "0.0.0.0":
            try:
                from engine.netmonitor.traceroute import _local_adapter_ip
                src = _local_adapter_ip() or self._local_ip or ""
            except Exception:
                pass
        if not src or src == "0.0.0.0":
            _diag("[GameRttMonitor] active probe: no local source IP")
            return

        ports_all = sorted(self._remote_ports) or [22222]
        scan_idx = 0
        _diag(
            f"[GameRttMonitor] active probe -> {self._server} ports={ports_all} "
            f"src={src} gentle cadence (~3.5s, 1 SYN)"
        )
        while not self._stop.is_set():
            scan_idx += 1
            with self._lock:
                active_ports = list(self._active_ports)
            if not active_ports or scan_idx % 12 == 0:
                # Full liveness sweep: ONE SYN per known port.
                probe_ports = ports_all
            else:
                # Gentle posture: one SYN to a single currently-answering port.
                # Sustained multi-port SYN bursts (2/port/2s) tripped the
                # server's DDoS filter, which throttled RSTs to 200-450 ms —
                # a probe artifact, not the path RTT. Sparse single-port
                # probing keeps the filter quiet and the samples honest.
                probe_ports = [active_ports[(scan_idx - 1) % len(active_ports)]]
            hits: list[tuple[float, float]] = []
            answered: set[int] = set()
            t0 = time.time()
            for port in probe_ports:
                if self._stop.is_set():
                    break
                try:
                    ts = time.time()
                    pkt = IP(src=src, dst=self._server) / TCP(
                        sport=_random.randint(30000, 60000),
                        dport=port, flags="S"
                    )
                    resp = sr1(pkt, timeout=1.2, verbose=0, retry=0)
                    if resp is not None and getattr(resp, "src", "") == self._server:
                        rtt = (time.time() - ts) * 1000.0
                        if 0.0 <= rtt <= 1500.0:
                            hits.append((time.time(), rtt))
                            answered.add(port)
                except Exception:
                    pass
            now = time.time()
            if hits:
                with self._lock:
                    self._active_rtt = (self._active_rtt + hits)[-128:]
                    self._active_ports = [p for p in ports_all if p in answered]
                    self._last_answered = time.time()
                _diag(
                    f"[GameRttMonitor] active probe rtt="
                    f"{[f'{h[1]:.1f}' for h in hits[:8]]}ms "
                    f"ports={sorted(answered)}"
                )
            # Age out stale active samples — a gone match must not keep a stale
            # ping pinned in the UI. 90s window (vs 30s) so the throttled-noise
            # robust median has enough samples to stay honest at gentle cadence
            # (1 SYN / ~3.5s -> ~25 samples/window).
            with self._lock:
                self._active_rtt = [
                    h for h in self._active_rtt if now - h[0] <= 90.0
                ]
            elapsed = time.time() - t0
            import random as _jr
            time.sleep(max(0.8, 3.5 - elapsed + _jr.random() * 1.2))

    # Part 2 just-in-time pairing window. The live match stream is heavily
    # outbound-skewed (many fire-and-forget game datagrams per ack), so
    # FIFO-oldest pairing systematically inflated RTT by a full ack cadence
    # (measured ~1.5s -> fake 1490ms "ping"). Unreal acks the LATEST request:
    # pair each inbound with the newest unmatched outbound on the SAME port
    # inside this plausibility window.
    _PAIR_WINDOW_MS = 600.0

    def _handle(self, pkt):
        ip_layer, udp_layer = _SCAPY_LAYERS()
        if ip_layer is None:
            return
        if ip_layer not in pkt or udp_layer not in pkt:
            return
        src = pkt[ip_layer].src
        dst = pkt[ip_layer].dst
        sport = int(pkt[udp_layer].sport)
        dport = int(pkt[udp_layer].dport)
        ts = float(getattr(pkt, "time", time.time()))

        if src == self._local_ip and dst == self._server:
            with self._lock:
                q = self._pending.setdefault(dport, [])
                q.append(ts)
                self._sent += 1
                if len(q) > 1024:
                    del q[: len(q) - 1024]
            # Periodic prune of ancient outbounds so loss counting stays honest.
            if self._sent % 200 == 0:
                with self._lock:
                    cutoff = time.time() - 2.5
                    for p, plist in list(self._pending.items()):
                        while plist and plist[0] < cutoff:
                            plist.pop(0)
                        if not plist:
                            del self._pending[p]
            return
        if not (dst == self._local_ip and src == self._server):
            return

        with self._lock:
            q = self._pending.get(sport)
            if not q:
                return
            cutoff = ts - self._PAIR_WINDOW_MS / 1000.0
            rtt = None
            idx = -1
            # Newest outbound first — that is the request this ack answers.
            for k in range(len(q) - 1, -1, -1):
                ot = q[k]
                if ot < cutoff:
                    break
                delta = (ts - ot) * 1000.0
                # 15ms floor: sub-15ms deltas are cadence coincidences (an ack
                # landing right after an unrelated outbound), not round-trips —
                # on this tunneled 136ms link a real ack can never be that fast.
                if 15.0 <= delta <= self._PAIR_WINDOW_MS:
                    rtt = delta
                    idx = k
                    break
            if rtt is not None:
                del q[idx]
                self._samples.append(rtt)
                self._matched += 1
                if not q:
                    del self._pending[sport]
                if len(self._samples) > self._max_samples:
                    self._samples = self._samples[-self._max_samples:]

    def _smooth(self, stats):
        """EMA-smooth the per-window trimmed median so the readout tracks the
        game's own stable ping display (Part 2): recent samples weigh in but
        the number does not jump per-packet. The raw median stays available
        internally; every public field path returns the smoothed value."""
        if getattr(stats, "median_ms", 0) > 0:
            raw = stats.median_ms
            if self._ema is None:
                self._ema = raw
            else:
                self._ema = 0.3 * raw + 0.7 * self._ema
            stats.median_ms = self._ema
        return stats

    def _mirror_best(self, stats):
        """Mirror an EMA around the per-window BEST causal round trip.

        The game's HUD ping is a smoothed best-case RTT, so the closest honest
        equivalent in our data is the smoothed trimmed floor (stats.min_ms) —
        already throttle-artifact-robust (boxplot fence, one-sided lower-half
        guard). On the SA->Doha rig the result tracked the in-game counter to
        within a millisecond (144 vs 143.5) while the window median sat ~8 ms
        higher under active traffic.
        """
        if stats.min_ms and stats.min_ms > 0:
            if self._best_ema is None:
                self._best_ema = stats.min_ms
            else:
                self._best_ema = 0.3 * stats.min_ms + 0.7 * self._best_ema
            stats.best_ms = self._best_ema
        return stats

    def _zero_loss(self, stats):
        """Passive single-bound observation watches the stream the game itself
        already sends; it cannot attribute packet loss to the path (a 9:1
        fire-and-forget cadence is Unreal's packet structure, not packet loss).
        So the live stream reports loss as NOT MEASURED (0.0) — confidence is
        earned from round-trip volume + stability, never a bogus loss ratio."""
        stats.loss_pct = 0.0
        return stats

    def _publish(self):
        with self._lock:
            now = time.time()
            self._active_rtt = [
                h for h in self._active_rtt if now - h[0] <= 90.0
            ]
            active = sorted(h[1] for h in self._active_rtt)
            samples = sorted(self._samples)
            matched = self._matched
            sent = self._sent
        if active and now - self._last_answered <= 30.0:
            stats = _rtt_stats(active, sent, matched, "active_game_port")
        else:
            # No causal reply yet: the passive pairing is packet-cadence, NOT a
            # server RTT (measured 25ms cadence vs 142ms real). Report it as
            # flow timing — the engine never headlines a cadence value.
            stats = _rtt_stats(samples, sent, matched, "flow_cadence")
        if stats.source != self._last_pub_source:
            self._ema = None  # re-seed the smooth on a source switch
            self._best_ema = None
            self._last_pub_source = stats.source
        raw_med = stats.median_ms
        stats = self._zero_loss(self._smooth(stats))
        stats = self._mirror_best(stats)
        _diag(
            f"[GameRttMonitor] publish sent={sent} matched={matched} "
            f"src={stats.source} samples={stats.samples} raw_med={raw_med:.1f} "
            f"ema={stats.median_ms:.1f} "
            f"min={stats.min_ms:.1f} max={stats.max_ms:.1f} "
            f"best={stats.best_ms:.1f} "
            f"jitter={stats.jitter_ms:.1f} loss=not-measured "
            f"active_hits={len(active)}"
        )
        if self._on_stats:
            try:
                self._on_stats(stats)
            except Exception as exc:
                _diag(f"[GameRttMonitor] on_stats callback failed: {exc!r}")

    def get_stats(self):
        with self._lock:
            now = time.time()
            self._active_rtt = [
                h for h in self._active_rtt if now - h[0] <= 90.0
            ]
            active = sorted(h[1] for h in self._active_rtt)
            samples = sorted(self._samples)
            matched = self._matched
            sent = self._sent
        if active and now - self._last_answered <= 30.0:
            stats = _rtt_stats(active, sent, matched, "active_game_port")
        else:
            stats = _rtt_stats(samples, sent, matched, "flow_cadence")
        if stats.source != self._last_pub_source:
            self._ema = None
            self._best_ema = None
            self._last_pub_source = stats.source
        return self._mirror_best(self._zero_loss(self._smooth(stats)))


def _rtt_stats(samples: list[float], sent: int, matched: int, source: str):
    """Build a LiveRttStats from sorted sample latencies + send/match counts."""
    from engine.netmonitor.types import LiveRttStats
    if not samples:
        return LiveRttStats(source="none")
    work = sorted(samples)
    n = len(work)
    # Throttle rejection: game-server DDoS filters routinely delay RST replies
    # to probe SYNs (measured 143-165 ms honest vs 200-450 ms throttled on the
    # SAME server — the game itself keeps ~140 ms). Those slow replies are an
    # artifact of our probe method, not the path, so a standard boxplot fence
    # (1.5*IQR above Q3, symmetric below Q1) is applied before trimming.
    if n >= 12:
        q1 = work[n // 4]
        q3 = work[(3 * n) // 4]
        iqr = q3 - q1
        if iqr > 0:
            lo_f = q1 - 1.5 * iqr
            hi_f = q3 + 1.5 * iqr
            work = [v for v in work if lo_f <= v <= hi_f] or work
            n = len(work)
    if n >= 20:
        # Bug 19: FIFO pairing on an asymmetric/out-of-order match stream admits
        # artifacts (a few stale mispairs). Never let the decile outliers drive
        # the headline — trim 10% off each end when the set is large enough.
        kill = n // 10
        work = work[kill: n - kill] or work
    n = len(work)
    q2 = work[n // 2]
    median = q2
    # One-sided contamination guard: a throttle/filter can only DELAY our
    # probe replies, never speed them up, so a fatter upper tail means probe
    # artifacts, not a slower path — the game client's own counter (steady
    # ~140 ms) confirms the fast cluster is the true round trip. When the
    # lower-half median sits markedly (>=15%) below the overall median, report
    # the lower half's central tendency (the honest round trip) instead of a
    # median dragged into the slow cluster.
    if n >= 10:
        lo = work[: (n + 1) // 2]
        if len(lo) >= 3:
            lo_med = lo[len(lo) // 2]
            if lo_med < q2 * 0.85:
                median = lo_med
    avg = sum(work) / len(work)
    mad = sorted(abs(x - median) for x in work)
    jitter = mad[len(mad) // 2]
    # Report the honest spread around the robust median: min/max bounded by
    # the trimmed set AND by 3x the robust jitter, so a handful of stale
    # mispairs can never present a "max 1600ms" against a 136ms match (Bug 19).
    spread = max(jitter, 5.0) * 3.0
    lo = max(work[0], median - spread)
    hi = min(work[-1], median + spread)
    if work[0] == work[-1]:
        lo = hi = work[0]
    loss = 0.0
    if sent:
        unanswered = max(0, sent - matched)
        loss = min(100.0, unanswered / max(sent, 1) * 100.0)
    return LiveRttStats(
        source=source,
        median_ms=median,
        avg_ms=avg,
        min_ms=lo,
        max_ms=hi,
        jitter_ms=jitter,
        loss_pct=loss,
        samples=n,
        updated=time.time(),
    )