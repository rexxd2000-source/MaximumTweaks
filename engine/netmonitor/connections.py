"""Active connection enumeration — discover real network connections on the system."""
from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from engine.netmonitor.bgp import NetworkIntel, get_network_intel


@dataclass
class ActiveConnection:
    local_ip: str = ""
    local_port: int = 0
    remote_ip: str = ""
    remote_port: int = 0
    protocol: str = "TCP"
    state: str = ""
    pid: int = 0
    process_name: str = ""
    intel: Optional[NetworkIntel] = field(default_factory=lambda: None, repr=False)
    app_category: str = ""
    service_name: str = ""
    confidence: str = "measured"

    @property
    def display_name(self) -> str:
        if self.service_name:
            return self.service_name
        if self.process_name:
            return self.process_name
        return f"{self.remote_ip}:{self.remote_port}"


_SERVICE_MAP = {
    "discord": "Discord",
    "slack": "Slack",
    "teams": "Microsoft Teams",
    "zoom": "Zoom",
    "skype": "Skype",
    "spotify": "Spotify",
    "steam": "Steam",
    "epic": "Epic Games",
    "fortnite": "Fortnite",
    "battle": "Battle.net",
    "riot": "Riot Games",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "msedge": "Microsoft Edge",
    "brave": "Brave Browser",
    "opera": "Opera Browser",
    "code": "VS Code",
    "cursor": "Cursor",
    "docker": "Docker",
    "git": "Git",
    "node": "Node.js",
    "python": "Python",
    "curl": "curl",
    "putty": "PuTTY",
    "filezilla": "FileZilla",
    "vlc": "VLC",
    "obs": "OBS Studio",
    "discord Nitro": "Discord",
    "devenv": "Visual Studio",
}

_CATEGORY_MAP = {
    "discord": "communication",
    "teams": "communication",
    "zoom": "communication",
    "skype": "communication",
    "slack": "communication",
    "chrome": "browser",
    "firefox": "browser",
    "msedge": "browser",
    "brave": "browser",
    "opera": "browser",
    "steam": "gaming",
    "epic": "gaming",
    "fortnite": "gaming",
    "battle": "gaming",
    "riot": "gaming",
    "spotify": "streaming",
    "vlc": "streaming",
    "obs": "streaming",
    "code": "development",
    "cursor": "development",
    "docker": "development",
    "node": "development",
    "python": "development",
    "git": "development",
}


def _classify_process(name: str) -> tuple[str, str]:
    lower = name.lower().replace(".exe", "")
    for key, svc in _SERVICE_MAP.items():
        if key in lower:
            cat = _CATEGORY_MAP.get(key, "other")
            return svc, cat
    return name, "other"


def get_active_connections() -> list[ActiveConnection]:
    connections = []
    try:
        creation_flags = 0x08000000
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | "
             "Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,OwningProcess | "
             "ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=10,
            creationflags=creation_flags,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            import json
            data = json.loads(proc.stdout.strip())
            if isinstance(data, dict):
                data = [data]
            for entry in data:
                remote = entry.get("RemoteAddress", "")
                if not remote or remote == "0.0.0.0" or remote == "::" or remote.startswith("127."):
                    continue
                if remote.startswith("169.254."):
                    continue
                pid = entry.get("OwningProcess", 0)
                proc_name = _get_process_name(pid)
                svc, cat = _classify_process(proc_name)
                conn = ActiveConnection(
                    local_ip=entry.get("LocalAddress", ""),
                    local_port=int(entry.get("LocalPort", 0)),
                    remote_ip=remote,
                    remote_port=int(entry.get("RemotePort", 0)),
                    protocol="TCP",
                    state="ESTABLISHED",
                    pid=pid,
                    process_name=proc_name,
                    app_category=cat,
                    service_name=svc,
                )
                connections.append(conn)
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, ValueError):
        pass

    seen_ips = set()
    unique = []
    for c in connections:
        key = c.remote_ip
        if key not in seen_ips:
            seen_ips.add(key)
            unique.append(c)

    return unique


def enrich_connection(conn: ActiveConnection) -> ActiveConnection:
    try:
        conn.intel = get_network_intel(conn.remote_ip)
    except Exception:
        pass
    return conn


def enrich_connections_threaded(
    connections: list[ActiveConnection],
    on_result=None,
    max_workers: int = 5,
) -> list[ActiveConnection]:
    results = []
    lock = threading.Lock()

    def enrich_one(c):
        enriched = enrich_connection(c)
        with lock:
            results.append(enriched)
        if on_result:
            on_result(enriched)

    threads = []
    for conn in connections[:20]:
        t = threading.Thread(target=enrich_one, args=(conn,), daemon=True)
        threads.append(t)
        if len(threads) >= max_workers:
            for th in threads:
                th.start()
            for th in threads:
                th.join(timeout=15)
            threads = []

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    return results


def _get_process_name(pid: int) -> str:
    if not pid:
        return ""
    try:
        creation_flags = 0x08000000
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).ProcessName"],
            capture_output=True, text=True, timeout=5,
            creationflags=creation_flags,
        )
        name = proc.stdout.strip()
        return name if name else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""
