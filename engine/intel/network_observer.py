"""Network observer — continuous TCP + UDP monitoring per game PID.

Uses Windows IP Helper APIs (GetExtendedTcpTable / GetExtendedUdpTable) via ctypes
for reliable process-to-endpoint mapping. Falls back to psutil when needed.

Tracks connection lifecycle: first_seen, last_seen, observation_count, activity_rate.
Distinguishes TCP from UDP. Maintains a rolling history of observations.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

AF_INET = socket.AF_INET
TCP_TABLE_OWNER_PID_ALL = 5
UDP_TABLE_OWNER_PID = 1
NO_ERROR = 0
ERROR_INSUFFICIENT_BUFFER = 122

iphlpapi = ctypes.windll.iphlpapi


class MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("dwState", wintypes.DWORD),
        ("dwLocalAddr", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("dwRemoteAddr", wintypes.DWORD),
        ("dwRemotePort", wintypes.DWORD),
        ("dwOwningPid", wintypes.DWORD),
    ]


class MIB_UDPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("dwLocalAddr", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("dwOwningPid", wintypes.DWORD),
    ]


_proc_name_cache: dict[int, str] = {}
_proc_path_cache: dict[int, str] = {}


def _int_to_ip(addr_int: int) -> str:
    return socket.inet_ntoa(struct.pack("!I", socket.htonl(addr_int & 0xFFFFFFFF)))


def _htons_port(port_netorder: int) -> int:
    return socket.ntohs(port_netorder & 0xFFFF)


def _tcp_state_name(state: int) -> str:
    return {
        1: "LISTEN", 2: "SYN_SENT", 3: "SYN_RECEIVED", 4: "ESTABLISHED",
        5: "FIN_WAIT1", 6: "FIN_WAIT2", 7: "CLOSE_WAIT", 8: "CLOSING",
        9: "LAST_ACK", 10: "TIME_WAIT", 11: "DELETE_TCB",
    }.get(state, f"UNKNOWN({state})")


def _get_process_name(pid: int) -> str:
    if pid in _proc_name_cache:
        return _proc_name_cache[pid]
    if not HAS_PSUTIL:
        _proc_name_cache[pid] = ""
        return ""
    try:
        p = psutil.Process(pid)
        name = p.name()
        _proc_name_cache[pid] = name
        try:
            _proc_path_cache[pid] = p.exe()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
        return name
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        _proc_name_cache[pid] = ""
        return ""


def _get_process_path(pid: int) -> str:
    if pid in _proc_path_cache:
        return _proc_path_cache[pid]
    _get_process_name(pid)
    return _proc_path_cache.get(pid, "")


# ── Raw connection snapshot ──────────────────────────────────────────────────

@dataclass
class RawConnection:
    pid: int = 0
    process_name: str = ""
    process_path: str = ""
    local_ip: str = ""
    local_port: int = 0
    remote_ip: str = ""
    remote_port: int = 0
    protocol: str = ""  # "TCP" or "UDP"
    state: str = ""     # TCP state or "STATELESS" for UDP
    timestamp: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.local_port}-{self.remote_ip}:{self.remote_port}-{self.protocol}"

    @property
    def is_remote(self) -> bool:
        return bool(self.remote_ip) and self.remote_ip not in (
            "0.0.0.0", "127.0.0.1", "::1", "", "::"
        )

    @property
    def is_established(self) -> bool:
        # UDP is always considered "established" (stateless)
        if self.protocol == "UDP":
            return True
        # TCP: only ESTABLISHED and SYN_SENT are truly active
        return self.state in ("ESTABLISHED", "SYN_SENT")


def _get_tcp_connections() -> list[RawConnection]:
    connections: list[RawConnection] = []
    buf_size = wintypes.DWORD(0)
    ret = iphlpapi.GetExtendedTcpTable(
        None, ctypes.byref(buf_size), True, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0
    )
    if ret != ERROR_INSUFFICIENT_BUFFER:
        return connections

    buf = ctypes.create_string_buffer(buf_size.value)
    ret = iphlpapi.GetExtendedTcpTable(
        buf, ctypes.byref(buf_size), True, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0
    )
    if ret != NO_ERROR:
        return connections

    count = struct.unpack("I", buf[:4])[0]
    offset = 4
    row_size = ctypes.sizeof(MIB_TCPROW_OWNER_PID)

    for _ in range(count):
        row = MIB_TCPROW_OWNER_PID.from_buffer_copy(buf[offset:offset + row_size])
        offset += row_size

        proc_name = _get_process_name(row.dwOwningPid)
        connections.append(RawConnection(
            pid=row.dwOwningPid,
            process_name=proc_name,
            process_path=_get_process_path(row.dwOwningPid),
            local_ip=_int_to_ip(row.dwLocalAddr),
            local_port=_htons_port(row.dwLocalPort),
            remote_ip=_int_to_ip(row.dwRemoteAddr),
            remote_port=_htons_port(row.dwRemotePort),
            protocol="TCP",
            state=_tcp_state_name(row.dwState),
            timestamp=time.time(),
        ))

    return connections


def _get_udp_connections() -> list[RawConnection]:
    connections: list[RawConnection] = []
    buf_size = wintypes.DWORD(0)
    ret = iphlpapi.GetExtendedUdpTable(
        None, ctypes.byref(buf_size), True, AF_INET, UDP_TABLE_OWNER_PID, 0
    )
    if ret != ERROR_INSUFFICIENT_BUFFER:
        return connections

    buf = ctypes.create_string_buffer(buf_size.value)
    ret = iphlpapi.GetExtendedUdpTable(
        buf, ctypes.byref(buf_size), True, AF_INET, UDP_TABLE_OWNER_PID, 0
    )
    if ret != NO_ERROR:
        return connections

    count = struct.unpack("I", buf[:4])[0]
    offset = 4
    row_size = ctypes.sizeof(MIB_UDPROW_OWNER_PID)

    for _ in range(count):
        row = MIB_UDPROW_OWNER_PID.from_buffer_copy(buf[offset:offset + row_size])
        offset += row_size

        proc_name = _get_process_name(row.dwOwningPid)
        connections.append(RawConnection(
            pid=row.dwOwningPid,
            process_name=proc_name,
            process_path=_get_process_path(row.dwOwningPid),
            local_ip=_int_to_ip(row.dwLocalAddr),
            local_port=_htons_port(row.dwLocalPort),
            remote_ip="0.0.0.0",
            remote_port=0,
            protocol="UDP",
            state="STATELESS",
            timestamp=time.time(),
        ))

    return connections


def get_all_connections() -> list[RawConnection]:
    """Get ALL TCP + UDP connections system-wide."""
    _proc_name_cache.clear()
    tcp, udp = [], []
    try:
        tcp = _get_tcp_connections()
    except Exception:
        pass
    try:
        udp = _get_udp_connections()
    except Exception:
        pass
    return tcp + udp


def get_connections_for_pid(pid: int) -> list[RawConnection]:
    """Get all connections (TCP + UDP) for a specific PID."""
    return [c for c in get_all_connections() if c.pid == pid]


def get_remote_connections_for_pid(pid: int) -> list[RawConnection]:
    """Get only remote (non-loopback) connections for a PID."""
    return [c for c in get_connections_for_pid(pid) if c.is_remote]


# ── Tracked endpoint (with observation history) ──────────────────────────────

@dataclass
class TrackedEndpoint:
    """A single remote endpoint being tracked over time."""
    remote_ip: str = ""
    remote_port: int = 0
    local_port: int = 0
    protocol: str = ""
    first_seen: float = 0.0
    last_seen: float = 0.0
    observation_count: int = 0
    activity_samples: list[float] = field(default_factory=list)
    was_active_before_matchmaking: bool = False
    appeared_at: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.remote_ip}:{self.remote_port}-{self.protocol}"

    @property
    def is_active(self) -> bool:
        return self.last_seen > 0 and (time.time() - self.last_seen) < 30

    @property
    def age_seconds(self) -> float:
        if self.first_seen > 0:
            return time.time() - self.first_seen
        return 0.0

    @property
    def activity_rate(self) -> float:
        if len(self.activity_samples) < 2:
            return 0.0
        window = 60.0
        recent = [t for t in self.activity_samples if (time.time() - t) < window]
        return len(recent) / window if window > 0 else 0.0

    def record_observation(self):
        self.last_seen = time.time()
        self.observation_count += 1
        if not self.first_seen:
            self.first_seen = self.last_seen
            self.appeared_at = self.last_seen
        self.activity_samples.append(self.last_seen)
        cutoff = time.time() - 300
        self.activity_samples = [t for t in self.activity_samples if t > cutoff]


class NetworkObserver:
    """Continuously observes network connections for a specific game PID.

    Each poll:
    1. Reads all TCP + UDP connections via Windows IP Helper
    2. Filters to the target PID
    3. Updates tracked endpoints with observation timestamps
    4. Returns the current endpoint snapshot
    """

    def __init__(self, pid: int):
        self._pid = pid
        self._endpoints: dict[str, TrackedEndpoint] = {}
        self._snapshot_count = 0
        self._last_snapshot_time = 0.0

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def endpoints(self) -> dict[str, TrackedEndpoint]:
        return self._endpoints

    @property
    def snapshot_count(self) -> int:
        return self._snapshot_count

    def poll(self) -> list[TrackedEndpoint]:
        """Take a network snapshot. Returns all tracked endpoints."""
        now = time.time()
        self._snapshot_count += 1
        self._last_snapshot_time = now

        # Get ALL connections (TCP + UDP) for this PID — do NOT filter to
        # remote-only here, because UDP connections have remote_ip=0.0.0.0
        # and would be lost. Filtering happens at the caller level.
        connections = get_connections_for_pid(self._pid)

        seen_keys: set[str] = set()
        for conn in connections:
            ep = TrackedEndpoint(
                remote_ip=conn.remote_ip,
                remote_port=conn.remote_port,
                local_port=conn.local_port,
                protocol=conn.protocol,
            )
            key = ep.key
            seen_keys.add(key)

            if key in self._endpoints:
                existing = self._endpoints[key]
                existing.record_observation()
            else:
                ep.first_seen = now
                ep.last_seen = now
                ep.observation_count = 1
                ep.activity_samples = [now]
                self._endpoints[key] = ep

        # Mark endpoints not seen in this snapshot (but don't remove yet)
        for key, ep in self._endpoints.items():
            if key not in seen_keys:
                pass  # last_seen remains unchanged

        return list(self._endpoints.values())

    def get_active_endpoints(self) -> list[TrackedEndpoint]:
        """Return currently active endpoints (seen in last 30s)."""
        return [ep for ep in self._endpoints.values() if ep.is_active]

    def get_active_remote_endpoints(self) -> list[TrackedEndpoint]:
        """Return active endpoints with valid remote IPs (TCP only)."""
        return [
            ep for ep in self._endpoints.values()
            if ep.is_active and ep.remote_ip not in (
                "0.0.0.0", "127.0.0.1", "::1", "", "::"
            )
        ]

    def get_active_game_endpoints(self) -> list[TrackedEndpoint]:
        """Return all active endpoints including UDP (game traffic).

        UDP connections have no remote IP visible via Windows IP Helper,
        but they represent real game server communication. Includes
        only endpoints with established/active TCP states or UDP sockets.
        """
        result = []
        for ep in self._endpoints.values():
            if not ep.is_active:
                continue
            if ep.protocol == "UDP":
                result.append(ep)
            elif ep.remote_ip not in ("0.0.0.0", "127.0.0.1", "::1", "", "::"):
                result.append(ep)
        return result

    def get_udp_port_count(self) -> int:
        """Number of active UDP sockets (indicates game traffic)."""
        return sum(1 for ep in self._endpoints.values()
                   if ep.is_active and ep.protocol == "UDP")

    def get_established_tcp_count(self) -> int:
        """Number of active established TCP connections."""
        return sum(1 for ep in self._endpoints.values()
                   if ep.is_active and ep.protocol == "TCP"
                   and ep.remote_ip not in ("0.0.0.0", "127.0.0.1", "::1", "", "::"))

    def get_new_endpoints_since(self, timestamp: float) -> list[TrackedEndpoint]:
        """Endpoints that first appeared after the given timestamp."""
        return [
            ep for ep in self._endpoints.values()
            if ep.first_seen > timestamp
        ]

    def get_endpoints_active_at(self, timestamp: float) -> list[TrackedEndpoint]:
        """Endpoints that were active at a specific point in time."""
        result = []
        for ep in self._endpoints.values():
            if ep.first_seen <= timestamp and ep.last_seen >= timestamp:
                result.append(ep)
        return result

    def reset(self):
        """Clear all tracking state."""
        self._endpoints.clear()
        self._snapshot_count = 0
        self._last_snapshot_time = 0.0

    def update_pid(self, new_pid: int):
        """Switch to tracking a different PID (e.g., game restarted)."""
        self._pid = new_pid
        self.reset()
