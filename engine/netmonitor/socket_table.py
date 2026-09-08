"""Windows UDP socket-table isolation of the active game process.

We query the OS network table (`GetExtendedUdpTable` with
UDP_TABLE_OWNER_PID) and keep only the UDP endpoints OWNED BY the game
process itself (e.g. FortniteClient-Win64-Shipping.exe). Those rows prove
the game holds live UDP sockets, tell us exactly which local IP the match
traffic leaves from (a socket bound to a concrete adapter address = engaged
session; a 0.0.0.0 row = passive listener), and give us the game's client
ports — which we feed straight into the traceroute/RTT probe filters.

Note on the Windows UDP table: `MIB_UDPROW_OWNER_PID` is a 12-byte record
(local addr, local port, owning PID). It does NOT expose the remote peer —
connected UDP peers are not published, and games mostly use unconnected
sendto() anyway, so the destination server is identified separately by the
passive capture signature matcher (targeting.py). psutil is used only for
PID <-> process-name lookup; the socket table itself is read via ctypes.
"""
from __future__ import annotations

import ctypes
import socket
import sys
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Optional

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency
    psutil = None


# UDP_TABLE_CLASS values (iphlpapi.h).
UDP_TABLE_BASIC = 0
UDP_TABLE_OWNER_PID = 1


# Game -> process-name fragments (case-insensitive). The first hit wins.
GAME_PROCESS_MAP: dict[str, list[str]] = {
    "Fortnite": [
        "FortniteClient-Win64-Shipping.exe",
        "FortniteClient-Win64-Shipping",
    ],
    # Extend with more titles as they are added: e.g. "Apex": ["r5apex.exe"].
}


@dataclass
class UdpRow:
    local_ip: str = ""
    local_port: int = 0
    pid: int = 0

    @property
    def bound(self) -> bool:
        """True if this socket is bound to a concrete adapter address
        (engaged session) rather than the wildcard listen address."""
        ip = self.local_ip
        return bool(ip) and ip != "0.0.0.0" and not ip.startswith("127.")


@dataclass
class ProcessSockets:
    """Consolidated game-socket view for one game process."""
    ip: str = ""
    client_ports: list[int] = field(default_factory=list)
    pid: int = 0
    proc_name: str = ""
    row_count: int = 0
    bound_rows: int = 0

    @property
    def in_match(self) -> bool:
        """True when at least one UDP socket is bound to a concrete adapter
        address (live, engaged session) instead of just listening."""
        return self.bound_rows > 0


@dataclass
class GameSocketState:
    """Snapshot of the game's UDP socket usage across all its processes."""
    running: bool = False
    pids: list[int] = field(default_factory=list)
    client_ports: list[int] = field(default_factory=list)
    local_ips: list[str] = field(default_factory=list)
    bound_ip: str = ""
    total_rows: int = 0
    in_match: bool = False

    def describe(self) -> str:
        if not self.running:
            return "game process not running"
        if self.in_match:
            return (
                f"{len(self.client_ports)} live UDP socket(s), engaged on "
                f"{self.bound_ip or 'adapter'}"
            )
        if self.total_rows:
            return (
                f"{self.total_rows} UDP socket row(s), listening only "
                "(no engaged match session yet)"
            )
        return "process up, no UDP sockets"


class _MibUdpRowOwnerPid(ctypes.Structure):
    # Actual Windows record: dwLocalAddr | dwLocalPort | dwOwningPid = 12 B.
    _fields_ = [
        ("local_addr", wintypes.DWORD),
        ("local_port", wintypes.DWORD),
        ("owning_pid", wintypes.DWORD),
    ]


def _port_from_dword(dword: int) -> int:
    """Local port is stored big-endian (to match socket orders)."""
    return (dword & 0xFF) << 8 | ((dword >> 8) & 0xFF)


def _addr_to_str(dword: int) -> str:
    """Decode a network-order IP DWORD into 'a.b.c.d'."""
    return "%d.%d.%d.%d" % (
        dword & 0xFF, (dword >> 8) & 0xFF, (dword >> 16) & 0xFF, (dword >> 24) & 0xFF,
    )


def get_udp_socket_table() -> list[UdpRow]:
    """Return all UDP endpoints with owning PIDs via GetExtendedUdpTable."""
    if sys.platform != "win32":
        return []
    rows: list[UdpRow] = []
    try:
        iphlpapi = ctypes.windll.iphlpapi
        get_ext = iphlpapi.GetExtendedUdpTable
        get_ext.restype = wintypes.ULONG
        get_ext.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.ULONG),
            wintypes.BOOL,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
        ]
    except (AttributeError, OSError):
        return rows

    size = wintypes.ULONG(0)
    rc = get_ext(None, ctypes.byref(size),
                 False, socket.AF_INET, UDP_TABLE_OWNER_PID, 0)
    if rc == 122 and size.value > 0:
        buf = (ctypes.c_ubyte * size.value)()
        rc = get_ext(ctypes.addressof(buf), ctypes.byref(size),
                     False, socket.AF_INET, UDP_TABLE_OWNER_PID, 0)
        if rc == 0:
            stride = ctypes.sizeof(_MibUdpRowOwnerPid)
            # Buffer layout: DWORD dwNumEntries, then 12-byte rows.
            num_entries = int(ctypes.c_uint32.from_buffer_copy(
                bytes(buf[:4])).value)
            table = ctypes.cast(ctypes.addressof(buf) + 4,
                                ctypes.POINTER(_MibUdpRowOwnerPid))
            count = min(num_entries, max(0, (size.value - 4) // stride))
            for i in range(count):
                row = table[i]
                rows.append(UdpRow(
                    local_ip=_addr_to_str(row.local_addr),
                    local_port=(
                        _port_from_dword(int(row.local_port))
                        if int(row.local_port) else 0
                    ),
                    pid=int(row.owning_pid),
                ))
    return rows


def _inet_from_ntohl(ntoh_l: int) -> str:
    return socket.inet_ntoa((ntoh_l & 0xFFFFFFFF).to_bytes(4, "little"))


def find_game_pids(game: str) -> list[tuple[int, str]]:
    """PIDs + process names matching the game's executable fragments."""
    fragments = GAME_PROCESS_MAP.get(game)
    if not fragments or psutil is None:
        return []
    hits: list[tuple[int, str]] = []
    frags_l = [f.lower() for f in fragments]
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
            except Exception:
                continue
            if name and any(f in name for f in frags_l):
                hits.append((proc.info["pid"], proc.info.get("name") or ""))
    except Exception:
        pass
    return hits


def process_udp_sockets(pids: list[int]) -> list[UdpRow]:
    """UDP-table rows whose owner PID is one of `pids`."""
    if not pids:
        return []
    pid_set = set(pids)
    return [r for r in get_udp_socket_table() if r.pid in pid_set]


def sockets_for_game(
    game: str, pids: Optional[list[int]] = None
) -> list[ProcessSockets]:
    """UDP endpoints of the game process(es), one record per process.

    `.ip` carries the process's bound adapter address when it has an engaged
    (non-wildcard) socket, otherwise "". `.client_ports` are the local ports
    the game sends from — usable as probe filters for traceroute/RTT.
    """
    if not pids:
        pids = [p for p, _n in find_game_pids(game)]
    if not pids:
        return []
    proc_names = {pid: name for pid, name in find_game_pids(game)}
    rows = process_udp_sockets(pids)

    by_proc: dict[int, ProcessSockets] = {}
    for r in rows:
        s = by_proc.setdefault(
            r.pid, ProcessSockets(pid=r.pid, proc_name=proc_names.get(r.pid, ""))
        )
        if r.local_port and r.local_port not in s.client_ports:
            s.client_ports.append(r.local_port)
        s.row_count += 1
        if r.bound:
            s.bound_rows += 1
            if not s.ip:
                s.ip = r.local_ip
        elif not s.ip:
            s.ip = ""

    out = [s for s in by_proc.values() if s.row_count]
    out.sort(key=lambda s: (s.in_match, s.row_count), reverse=True)
    return out


def game_socket_state(
    game: str, pids: Optional[list[int]] = None
) -> GameSocketState:
    """Aggregate the game's live UDP socket usage across all its processes."""
    if not pids:
        pids = [p for p, _n in find_game_pids(game)]
    rows = process_udp_sockets(pids)
    client_ports: list[int] = []
    local_ips: list[str] = []
    bound_ip = ""
    for r in rows:
        if r.local_port and r.local_port not in client_ports:
            client_ports.append(r.local_port)
        ip = r.local_ip
        if not ip or ip.startswith("0."):
            continue
        if ip not in local_ips:
            local_ips.append(ip)
        if not r.bound:
            continue
        if not bound_ip:
            bound_ip = ip
    client_ports.sort()
    return GameSocketState(
        running=bool(pids),
        pids=sorted(pids),
        client_ports=client_ports,
        local_ips=sorted(local_ips),
        bound_ip=bound_ip,
        total_rows=len(rows),
        in_match=bool(bound_ip),
    )


def signature_port_hit(sock: ProcessSockets, control_ports: set[int]) -> bool:
    """True if the socket record reflects a live, engaged match session.

    Windows exposes no remote endpoint for UDP, so "engaged" = the game holds
    at least one socket bound to a concrete adapter address with the client
    ports we can attach probes to.
    """
    return bool(sock.in_match and sock.client_ports)


def supported_by_socket_table() -> list[str]:
    return sorted(GAME_PROCESS_MAP.keys())