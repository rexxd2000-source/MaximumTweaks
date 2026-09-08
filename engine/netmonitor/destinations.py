"""Gaming destination definitions and auto-discovery."""
from __future__ import annotations

import os
import socket
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GameEndpoint:
    name: str
    category: str
    hostname: str
    port: int = 0
    region: str = ""
    detected: bool = True
    installed: bool = False
    icon_char: str = "\u25c9"
    ips: list[str] = field(default_factory=list)


_GAMING_ENDPOINTS: list[GameEndpoint] = [
    GameEndpoint(
        name="Fortnite",
        category="gaming",
        hostname="fortnite-public-service-prod06.ol.epicgames.com",
        port=443,
        region="Global",
        icon_char="\u25c9",
    ),
    GameEndpoint(
        name="Fortnite (EU)",
        category="gaming",
        hostname="154.247.16.1",
        port=0,
        region="Europe",
        icon_char="\u25c9",
    ),
    GameEndpoint(
        name="Epic Games",
        category="gaming",
        hostname="launcher-public-service-prod06.ol.epicgames.com",
        port=443,
        region="Global",
        icon_char="\u25c9",
    ),
    GameEndpoint(
        name="Discord",
        category="services",
        hostname="discord.com",
        port=443,
        region="Global",
        icon_char="\u260e",
    ),
    GameEndpoint(
        name="Discord Voice",
        category="services",
        hostname="us-east1.discord.gg",
        port=443,
        region="US East",
        icon_char="\u260e",
    ),
    GameEndpoint(
        name="Steam",
        category="gaming",
        hostname="api.steampowered.com",
        port=443,
        region="Global",
        icon_char="\u2b22",
    ),
    GameEndpoint(
        name="Steam Download",
        category="gaming",
        hostname="cm-steam-a1.akamaized.net",
        port=443,
        region="Global",
        icon_char="\u2b22",
    ),
    GameEndpoint(
        name="Riot Games",
        category="gaming",
        hostname="riot-geo.pvp.net",
        port=443,
        region="Global",
        icon_char="\u2694",
    ),
    GameEndpoint(
        name="Valorant",
        category="gaming",
        hostname="ap-prod-registration-top-3-hw3 valorant.secure.dyn.riotcdn.net",
        port=0,
        region="Global",
        icon_char="\u2694",
    ),
    GameEndpoint(
        name="Battle.net",
        category="gaming",
        hostname="level3.blizzard.com",
        port=1119,
        region="Global",
        icon_char="\u2605",
    ),
    GameEndpoint(
        name="EA Servers",
        category="gaming",
        hostname="ea.com",
        port=443,
        region="Global",
        icon_char="\u2605",
    ),
    GameEndpoint(
        name="Cloudflare",
        category="cdn",
        hostname="1.1.1.1",
        port=443,
        region="Global",
        icon_char="\u2601",
    ),
    GameEndpoint(
        name="Google DNS",
        category="cdn",
        hostname="8.8.8.8",
        port=53,
        region="Global",
        icon_char="\u2601",
    ),
    GameEndpoint(
        name="AWS Global",
        category="services",
        hostname="aws.amazon.com",
        port=443,
        region="Global",
        icon_char="\u2601",
    ),
    GameEndpoint(
        name="Microsoft Azure",
        category="services",
        hostname="azure.microsoft.com",
        port=443,
        region="Global",
        icon_char="\u2601",
    ),
]

_INSTALL_CHECKS = {
    "Epic Games": [
        r"C:\Program Files\Epic Games",
        r"C:\Program Files (x86)\Epic Games",
    ],
    "Steam": [
        r"C:\Program Files\Steam",
        r"C:\Program Files (x86)\Steam",
        r"C:\Program Files\Valve\Steam",
    ],
    "Battle.net": [
        r"C:\Program Files\Battle.net",
        r"C:\Program Files (x86)\Battle.net",
    ],
    "Discord": [
        os.path.expandvars(r"%LOCALAPPDATA%\Discord"),
    ],
}


def detect_installed_games() -> dict[str, bool]:
    installed = {}
    for name, paths in _INSTALL_CHECKS.items():
        found = any(os.path.isdir(p) for p in paths)
        installed[name] = found
    return installed


def resolve_endpoint(endpoint: GameEndpoint) -> list[str]:
    if endpoint.ips:
        return endpoint.ips
    if not endpoint.hostname:
        return []
    try:
        results = socket.getaddrinfo(endpoint.hostname, None, socket.AF_INET)
        ips = list({r[4][0] for r in results})
        endpoint.ips = ips
        return ips
    except (socket.gaierror, OSError):
        return []


def quick_ping(hostname: str, timeout: float = 2.0) -> Optional[float]:
    try:
        cmd = ["ping", "-n", "1", "-w", "2000", hostname]
        creation_flags = 0x08000000
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 2,
            creationflags=creation_flags,
        )
        import re
        match = re.search(r"time[=<](\d+)ms", proc.stdout)
        if match:
            return float(match.group(1))
        return None
    except (subprocess.TimeoutExpired, OSError):
        return None


def discover_destinations() -> list[GameEndpoint]:
    installed = detect_installed_games()
    endpoints = []
    for ep in _GAMING_ENDPOINTS:
        ep_copy = GameEndpoint(
            name=ep.name,
            category=ep.category,
            hostname=ep.hostname,
            port=ep.port,
            region=ep.region,
            detected=ep.detected,
            installed=installed.get(ep.name, False),
            icon_char=ep.icon_char,
            ips=list(ep.ips),
        )
        endpoints.append(ep_copy)
    return endpoints


def discover_destinations_threaded(
    callback=None,
) -> list[GameEndpoint]:
    endpoints = discover_destinations()
    if callback:
        callback(endpoints)
    return endpoints
