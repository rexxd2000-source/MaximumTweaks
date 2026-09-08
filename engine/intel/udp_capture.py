"""Packet-capture based UDP game-server discovery using Npcap/scapy.

Windows blocks SIO_RCVALL for desktop Win32 apps since Win10 1903.
This module uses scapy (which requires Npcap) to sniff UDP packets
and identify the game server IP from traffic matching the game's local
UDP ports.

On first run the bundled Npcap installer is offered via a one-click
UI prompt so end-users never have to set it up manually.

Requires:
  - Npcap (auto-installed from bundled npcap-*.exe if missing)
  - scapy installed (pip install scapy)
"""
from __future__ import annotations

import ctypes
import ipaddress
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Optional

from engine.intel.npcap_installer import is_npcap_installed, find_bundled_installer


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def has_npcap() -> bool:
    return is_npcap_installed()


def has_scapy() -> bool:
    try:
        import scapy  # noqa: F401
        return True
    except ImportError:
        return False


@dataclass
class GameServerEndpoint:
    ip: str = ""
    port: int = 0
    protocol: str = "UDP"
    first_seen: float = 0.0
    last_seen: float = 0.0
    packet_count: int = 0


class UdpCapture:
    """Sniffs UDP packets via scapy/Npcap to discover game server IPs."""

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._servers: dict[tuple[str, int], GameServerEndpoint] = {}
        self._local_udp_ports: set[int] = set()
        self._has_admin = is_admin()
        self._has_npcap = has_npcap()
        self._has_scapy = has_scapy()
        self._capture_started = False
        self._start_error: str = ""
        self._total_packets_seen: int = 0
        self._udp_packets_seen: int = 0
        self._game_matched_packets: int = 0
        self._last_packet_time: float = 0.0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._sample_ports: list[tuple[int, int]] = []
        self._port_hit_59991: int = 0
        self._ipv6_udp_count: int = 0

    @property
    def has_admin(self) -> bool:
        return self._has_admin

    @property
    def is_capturing(self) -> bool:
        return self._capture_started

    @property
    def start_error(self) -> str:
        return self._start_error

    @property
    def total_packets_seen(self) -> int:
        return self._total_packets_seen

    @property
    def udp_packets_seen(self) -> int:
        return self._udp_packets_seen

    @property
    def game_matched_packets(self) -> int:
        return self._game_matched_packets

    @property
    def last_packet_time(self) -> float:
        return self._last_packet_time

    def set_local_udp_ports(self, ports: set[int]):
        self._local_udp_ports = set(ports)

    def start(self) -> bool:
        if self._capture_started:
            return True
        if not self._has_admin:
            self._start_error = "not running as Administrator"
            return False
        if not self._has_scapy:
            self._start_error = "scapy not installed (pip install scapy)"
            return False
        if not self._has_npcap:
            installer = find_bundled_installer()
            if installer:
                self._start_error = f"NEED_NPCAP|{installer}"
            else:
                self._start_error = "Npcap not installed — download from https://npcap.com"
            return False

        try:
            from scapy.config import conf
            conf.use_pcap = True
            from scapy.all import sniff, IP, UDP
            self._sniff_fn = sniff
            self._IP = IP
            self._UDP = UDP
        except Exception as e:
            self._start_error = f"scapy init failed: {e}"
            return False

        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="udp-capture"
        )
        self._thread.start()
        self._capture_started = True
        self._start_error = ""
        return True

    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._capture_started = False

    def get_game_servers(self) -> list[GameServerEndpoint]:
        with self._lock:
            return sorted(
                list(self._servers.values()),
                key=lambda e: e.packet_count, reverse=True
            )

    def get_best_server(self, local_udp_ports: Optional[set[int]] = None) -> Optional[GameServerEndpoint]:
        servers = self.get_game_servers()
        return servers[0] if servers else None

    def get_capture_stats(self) -> str:
        with self._lock:
            n_servers = len(self._servers)
        sample = self._sample_ports[:10]
        sample_str = " ".join(f"{s}:{d}" for s, d in sample) if sample else "(none)"
        return (f"total={self._total_packets_seen} udp={self._udp_packets_seen} "
                f"matched={self._game_matched_packets} servers={n_servers} "
                f"port59991={self._port_hit_59991} ipv6_udp={self._ipv6_udp_count} "
                f"sample={sample_str}")

    def clear(self):
        with self._lock:
            self._servers.clear()
        self._total_packets_seen = 0
        self._udp_packets_seen = 0
        self._game_matched_packets = 0
        self._last_packet_time = 0.0

    def _capture_loop(self):
        IP_cls = self._IP
        UDP_cls = self._UDP
        sniff = self._sniff_fn

        try:
            from scapy.all import IPv6
            self._IPv6 = IPv6
        except ImportError:
            self._IPv6 = None

        def _process(pkt):
            if not self._running:
                return True

            if not pkt.haslayer(UDP_cls):
                return

            self._total_packets_seen += 1
            udp = pkt[UDP_cls]
            src_port = udp.sport
            dst_port = udp.dport
            self._udp_packets_seen += 1
            self._last_packet_time = time.time()

            if len(self._sample_ports) < 50:
                self._sample_ports.append((src_port, dst_port))

            game_ports = self._local_udp_ports
            if not game_ports:
                return

            if src_port in game_ports or dst_port in game_ports:
                if src_port == 59991 or dst_port == 59991:
                    self._port_hit_59991 += 1

            src_is_game = src_port in game_ports
            dst_is_game = dst_port in game_ports

            if not src_is_game and not dst_is_game:
                return

            self._game_matched_packets += 1

            if pkt.haslayer(IP_cls):
                ip = pkt[IP_cls]
                src_ip = ip.src
                dst_ip = ip.dst
            elif self._IPv6 and pkt.haslayer(self._IPv6):
                ip6 = pkt[self._IPv6]
                src_ip = ip6.src
                dst_ip = ip6.dst
                self._ipv6_udp_count += 1
            else:
                return

            if src_is_game:
                server_ip = dst_ip
                server_port = dst_port
            else:
                server_ip = src_ip
                server_port = src_port

            try:
                srv = ipaddress.ip_address(server_ip)
                if srv.is_private or srv.is_loopback or srv.is_link_local:
                    return
                if srv.packed[0] == 100 and (srv.packed[1] & 0xC0) == 64:
                    return
            except ValueError:
                return

            now = time.time()
            key = (server_ip, server_port)
            with self._lock:
                if key in self._servers:
                    ep = self._servers[key]
                    ep.last_seen = now
                    ep.packet_count += 1
                else:
                    self._servers[key] = GameServerEndpoint(
                        ip=server_ip,
                        port=server_port,
                        protocol="UDP",
                        first_seen=now,
                        last_seen=now,
                        packet_count=1,
                    )

        try:
            sniff(
                prn=_process,
                store=False,
                stop_filter=lambda _: not self._running,
            )
        except Exception as e:
            self._start_error = f"sniff failed: {e}"
            self._capture_started = False
            self._running = False
