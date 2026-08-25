"""Windows network connection discovery — TCP and UDP via IP Helper APIs.

Uses ctypes to call GetExtendedTcpTable / GetExtendedUdpTable directly.
Falls back to psutil for process name resolution.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import socket
import struct
import time
from typing import Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from engine.intel.models import NetworkConnection, ConnectionOrigin

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


_proc_cache: dict[int, str] = {}
_proc_path_cache: dict[int, str] = {}


def _int_to_ip(addr_int: int) -> str:
    return socket.inet_ntoa(struct.pack("!I", socket.htonl(addr_int & 0xFFFFFFFF)))


def _htons_port(port_netorder: int) -> int:
    return socket.ntohs(port_netorder & 0xFFFF)


def _tcp_state_name(state: int) -> str:
    states = {
        1: "LISTEN", 2: "SYN_SENT", 3: "SYN_RECEIVED", 4: "ESTABLISHED",
        5: "FIN_WAIT1", 6: "FIN_WAIT2", 7: "CLOSE_WAIT", 8: "CLOSING",
        9: "LAST_ACK", 10: "TIME_WAIT", 11: "DELETE_TCB",
    }
    return states.get(state, f"UNKNOWN({state})")


def _get_process_name(pid: int) -> str:
    if pid in _proc_cache:
        return _proc_cache[pid]
    if not HAS_PSUTIL:
        _proc_cache[pid] = ""
        return ""
    try:
        p = psutil.Process(pid)
        name = p.name()
        _proc_cache[pid] = name
        try:
            _proc_path_cache[pid] = p.exe()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
        return name
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        _proc_cache[pid] = ""
        return ""


def _get_process_path(pid: int) -> str:
    if pid in _proc_path_cache:
        return _proc_path_cache[pid]
    _get_process_name(pid)
    return _proc_path_cache.get(pid, "")


def _get_tcp_connections() -> list[NetworkConnection]:
    connections: list[NetworkConnection] = []
    buf_size = wintypes.DWORD(0)
    ret = iphlpapi.GetExtendedTcpTable(None, ctypes.byref(buf_size), True, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0)
    if ret != ERROR_INSUFFICIENT_BUFFER:
        return connections

    buf = ctypes.create_string_buffer(buf_size.value)
    ret = iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(buf_size), True, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0)
    if ret != NO_ERROR:
        return connections

    count = struct.unpack("I", buf[:4])[0]
    offset = 4
    row_size = ctypes.sizeof(MIB_TCPROW_OWNER_PID)

    for _ in range(count):
        row = MIB_TCPROW_OWNER_PID.from_buffer_copy(buf[offset:offset + row_size])
        offset += row_size

        proc_name = _get_process_name(row.dwOwningPid)
        connections.append(NetworkConnection(
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


def _get_udp_connections() -> list[NetworkConnection]:
    connections: list[NetworkConnection] = []
    buf_size = wintypes.DWORD(0)
    ret = iphlpapi.GetExtendedUdpTable(None, ctypes.byref(buf_size), True, AF_INET, UDP_TABLE_OWNER_PID, 0)
    if ret != ERROR_INSUFFICIENT_BUFFER:
        return connections

    buf = ctypes.create_string_buffer(buf_size.value)
    ret = iphlpapi.GetExtendedUdpTable(buf, ctypes.byref(buf_size), True, AF_INET, UDP_TABLE_OWNER_PID, 0)
    if ret != NO_ERROR:
        return connections

    count = struct.unpack("I", buf[:4])[0]
    offset = 4
    row_size = ctypes.sizeof(MIB_UDPROW_OWNER_PID)

    for _ in range(count):
        row = MIB_UDPROW_OWNER_PID.from_buffer_copy(buf[offset:offset + row_size])
        offset += row_size

        proc_name = _get_process_name(row.dwOwningPid)
        connections.append(NetworkConnection(
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


def get_all_connections() -> list[NetworkConnection]:
    _proc_cache.clear()
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


def get_connections_for_pid(pid: int) -> list[NetworkConnection]:
    return [c for c in get_all_connections() if c.pid == pid]


def get_connections_for_process(name: str) -> list[NetworkConnection]:
    name_lower = name.lower()
    return [c for c in get_all_connections() if c.process_name.lower() == name_lower]


def get_established_remote_endpoints() -> list[NetworkConnection]:
    return [
        c for c in get_all_connections()
        if c.protocol == "TCP" and c.state == "ESTABLISHED" and c.is_remote
    ]
