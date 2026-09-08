"""Active GPN / VPN tunnel detection for honest route optimization.

The Route Analyzer NEVER shows a synthetic "optimized route". A second,
*real* measured path is only surfaced when an actual tunnel instance is both
present on the machine AND is the interface the OS routes toward the game
server (checked with GetBestRoute2). If no tunnel actively carries that
route, the optimized side is suppressed entirely.
"""
from __future__ import annotations

import ctypes
import socket
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Optional

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None


# Adapter name/description fragments that identify a VPN/GPN/tunnel interface.
# GPN adapters (ExitLag/GearUP/NoPing/WTFast/Booster) present as a *virtual
# NDIS lightweight-filter driver* pseudo-adapter, never as "VPN".
_TUNNEL_KEYWORDS = (
    "tunnel", "tap-windows", "tap-win32", "wintun", "wireguard",
    "nordlynx", "proton vpn", "protonvpn", "proton", "openvpn", "anyconnect",
    "pulse secure", "globalprotect", "zscaler", "forticlient", "cisco",
    "expressvpn", "nordvpn", "surfshark", "mullvad", "amnezia", "vypr",
    "hotspot shield", "fastestvpn", "outline", "tailscale", "zerotier",
    "amneziawg", "gpn", "kill ping", "warp", "ivi", "free vpn",
    "vpn", "vag", "sstp", "l2tp", "pptp", "ipsec", "6to4", "teredo",
    "exitlag", "gearup", "gear up", "booster", "noping", "wtfast",
    "softether", "radmin", "v2ray", "secureline", "windscribe", "hola",
    "lightweight filter", "ndis light", "tunl", "wintap", "vnet",
)


@dataclass
class TunnelInfo:
    active: bool = False
    name: str = ""                 # friendly adapter name
    description: str = ""          # adapter type/description
    ipv4: str = ""
    index: int = -1                # OS interface index (GetBestRoute2 match)
    routes_server: bool = False    # does this tunnel carry the game-server route?
    kind: str = "unknown"          # "vpn" | "gpn" | "tunnel"
    reason: str = ""


def _adapter_index(name: str) -> int:
    try:
        for nic, addrs in psutil.net_if_addrs().items():
            if nic.lower() == name.lower():
                stats = psutil.net_if_stats().get(nic)
                if stats:
                    return int(stats.other if hasattr(stats, "other") else -1)
    except Exception:
        pass
    return -1


def _best_route_iface_index(dest_ip: str) -> Optional[int]:
    """OS interface index that routes traffic toward `dest_ip`
    (GetBestRoute2). Returns None when the OS does not resolve the route."""
    try:
        ip = socket.inet_aton(dest_ip)
        dest = (ip[0] << 24) + (ip[1] << 16) + (ip[2] << 8) + ip[3]
        best = ctypes.windll.iphlpapi.GetBestRoute2
        best.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ]
        best.restype = wintypes.ULONG
        out_ifidx = ctypes.c_ulong(0)
        out_luid = ctypes.c_ulong(0)
        source = ctypes.c_void_p()
        rc = best(None, None, None, dest.to_bytes(4, "big"), 0, 0,
                  ctypes.byref(out_ifidx), ctypes.byref(out_luid))
        _ = source
        if rc == 0:
            return int(out_ifidx.value)
    except (AttributeError, OSError):
        pass
    return None


def _index_to_adapter(index: int) -> Optional[tuple[str, str]]:
    """(friendly_name, description) of the adapter owning an interface index."""
    try:
        for nic, addrs in psutil.net_if_addrs().items():
            try:
                stats = psutil.net_if_stats().get(nic)
                other = int(stats.other) if stats and hasattr(stats, "other") else 0
                if other == index:
                    return nic, (stats._asdict().get("description", "") if stats else "")
            except Exception:
                continue
    except Exception:
        pass
    return None


def detect_tunnel(dest_ip: str = "") -> TunnelInfo:
    """Detect an active tunnel adapter and whether it carries the route to
    `dest_ip`. When `dest_ip` is empty only presence is reported (routes_server
    unchecked). Uses psutil's adapter list + GetBestRoute2 for the routing
    fact."""
    info = TunnelInfo()
    if psutil is None:
        info.reason = "psutil unavailable"
        return info

    route_index = _best_route_iface_index(dest_ip) if dest_ip else None
    if route_index is not None and route_index > 0:
        routed_adapter = _index_to_adapter(route_index)
        routed_desc = (routed_adapter[1] or "") if routed_adapter else ""
        routed_name = (routed_adapter[0] or "") if routed_adapter else ""

    try:
        adapters = psutil.net_if_addrs()
        for nic in adapters:
            desc = ""
            stats = psutil.net_if_stats().get(nic)
            if stats:
                try:
                    desc = stats._asdict().get("description", "") or stats.__str__()
                except Exception:
                    desc = str(stats)
            haystack = (f"{nic} {desc}").lower()
            if not any(kw in haystack for kw in _TUNNEL_KEYWORDS):
                continue
            if not stats or not stats.isup:
                continue
            ipv4 = ""
            for a in adapters[nic]:
                if a.family == socket.AF_INET:
                    ipv4 = a.address or ""
                    break
            if not ipv4:
                continue

            name = nic
            kind = "vpn"
            if any(kw in haystack for kw in ("gpn", "exitlag", "gearup", "gear up",
                                              "booster", "noping", "wtfast", "warp")):
                kind = "gpn"
            elif any(kw in haystack for kw in ("tunnel", "l2tp", "pptp", "6to4", "teredo")):
                kind = "tunnel"

            info.active = True
            info.name = name
            info.description = desc
            info.ipv4 = ipv4
            info.kind = kind
            info.index = int(stats.other) if hasattr(stats, "other") else -1

            if route_index is not None and info.index == route_index:
                info.routes_server = True
                info.reason = (
                    f"Active {kind} '{name}' is the OS interface carrying "
                    f"traffic to {dest_ip}"
                )
            else:
                info.reason = (
                    f"Active {kind} '{name}' present (index {info.index}); "
                    + ("not the server's route" if route_index is not None
                       else "routing check skipped")
                )
            break
    except Exception as exc:
        info.reason = f"tunnel scan failed: {exc}"

    if not info.active:
        info.reason = "no active tunnel/GPN adapter detected"
    return info


def tunnel_list() -> list[dict]:
    """All candidate tunnel adapters (for debug/display)."""
    out = []
    if psutil is None:
        return out
    try:
        for nic in psutil.net_if_addrs():
            haystack = f"{nic} ".lower()
            stats = psutil.net_if_stats().get(nic)
            desc = ""
            if stats:
                try:
                    desc = stats._asdict().get("description", "") or ""
                except Exception:
                    pass
            if any(kw in haystack + " " + desc.lower() for kw in _TUNNEL_KEYWORDS):
                out.append({"name": nic, "description": desc})
    except Exception:
        pass
    return out