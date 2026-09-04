"""Process detector — identifies the ACTUAL game process, not the launcher.

Tracks: process name, PID, executable path, start time, process state.
Distinguishes FortniteClient (game) from EpicGamesLauncher / EpicWebHelper.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class GameBinary(Enum):
    GAME = "game"
    LAUNCHER = "launcher"
    ANTI_CHEAT = "anti_cheat"
    UNKNOWN = "unknown"


@dataclass
class ProcessInfo:
    name: str = ""
    pid: int = 0
    exe_path: str = ""
    cmdline: list[str] = field(default_factory=list)
    start_time: float = 0.0
    binary_type: GameBinary = GameBinary.UNKNOWN
    has_network: bool = False
    remote_endpoints: int = 0
    udp_endpoints: int = 0
    tcp_endpoints: int = 0
    is_alive: bool = False
    cpu_percent: float = 0.0
    memory_mb: float = 0.0

    @property
    def display_name(self) -> str:
        return self.name.replace(".exe", "") if self.name else "Unknown"

    @property
    def age_seconds(self) -> float:
        if self.start_time > 0:
            return time.time() - self.start_time
        return 0.0


# ── Game Process Definitions ─────────────────────────────────────────────────
# Each game defines its GAME process (the actual renderer/networking binary),
# LAUNCHER processes, and ANTI_CHEAT processes.

GAME_PROCESSES = {
    "fortnite": {
        "game": [
            "FortniteClient-Win64-Shipping.exe",
            "FortniteClient-Win64-Shipping_EAC_EOS.exe",
        ],
        "launcher": [
            "FortniteLauncher.exe",
            "FortniteBootstrapper.exe",
            "EpicGamesLauncher.exe",
            "EpicWebHelper.exe",
        ],
        "anti_cheat": [
            "EasyAntiCheat_EOS.exe",
            "EasyAntiCheat.exe",
        ],
        "display_name": "Fortnite",
    },
    "valorant": {
        "game": [
            "VALORANT-Win64-Shipping.exe",
            "VALORANT-Win64-Shipping_Be.exe",
        ],
        "launcher": [
            "RiotClientServices.exe",
        ],
        "anti_cheat": [
            "vgtray.exe",
            "vanguard.exe",
        ],
        "display_name": "VALORANT",
    },
    "cod": {
        "game": [
            "cod.exe",
            "ModernWarfare.exe",
            "Warzone.exe",
        ],
        "launcher": [
            "steam.exe",
            "Battle.net.exe",
            "codcrashhandler.exe",
        ],
        "anti_cheat": [],
        "display_name": "Call of Duty",
    },
    "cs2": {
        "game": [
            "cs2.exe",
            "cs2_win64.exe",
            "csgo.exe",
        ],
        "launcher": [
            "steam.exe",
        ],
        "anti_cheat": [],
        "display_name": "Counter-Strike 2",
    },
}

_FALSE_POSITIVES = frozenset({
    "crashreportclient.exe",
    "crashhandler.exe",
    "unrealengineditor.exe",
    "eacportschecker.exe",
})


def _classify_process(exe_name: str, exe_path: str) -> tuple[str, GameBinary]:
    """Returns (game_key, binary_type) or ("", GameBinary.UNKNOWN)."""
    name_lower = exe_name.lower()
    if name_lower in _FALSE_POSITIVES:
        return "", GameBinary.UNKNOWN

    for game_key, defs in GAME_PROCESSES.items():
        for pat in defs["game"]:
            if name_lower == pat.lower():
                return game_key, GameBinary.GAME
        for pat in defs["game"]:
            prefix = pat.lower().replace(".exe", "")
            if name_lower.startswith(prefix):
                return game_key, GameBinary.GAME

    for game_key, defs in GAME_PROCESSES.items():
        for pat in defs["launcher"]:
            if name_lower == pat.lower():
                return game_key, GameBinary.LAUNCHER
        for pat in defs["anti_cheat"]:
            if name_lower == pat.lower():
                return game_key, GameBinary.ANTI_CHEAT

    return "", GameBinary.UNKNOWN


def detect_game_processes() -> dict[str, list[ProcessInfo]]:
    """Scan all running processes. Returns {game_key: [ProcessInfo, ...]}.

    Only returns processes that have a matching game_key (i.e., are related
    to a supported game). Multiple processes per game are possible
    (game + launcher + anti-cheat).
    """
    if not HAS_PSUTIL:
        return {}

    results: dict[str, list[ProcessInfo]] = {}

    for proc in psutil.process_iter(["pid", "name", "exe", "create_time"]):
        try:
            info = proc.info
            name = info.get("name", "")
            exe = info.get("exe", "") or ""
            pid = info.get("pid", 0)
            create_time = info.get("create_time", 0.0)

            if not name or not pid:
                continue

            game_key, binary_type = _classify_process(name, exe)
            if not game_key:
                continue

            pinfo = ProcessInfo(
                name=name,
                pid=pid,
                exe_path=exe,
                start_time=create_time,
                binary_type=binary_type,
                is_alive=True,
            )

            try:
                pinfo.cpu_percent = proc.cpu_percent(interval=0)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            try:
                pinfo.memory_mb = proc.memory_info().rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            if game_key not in results:
                results[game_key] = []
            results[game_key].append(pinfo)

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return results


def get_game_process(game_key: str) -> Optional[ProcessInfo]:
    """Get the primary GAME binary for a specific game. Returns None if not running.

    Prefers the actual game process over EAC/EOS wrappers. When multiple
    game-type processes exist, selects the one with the most network activity
    or the lowest PID (the original game process).
    """
    all_procs = detect_game_processes()
    procs = all_procs.get(game_key, [])

    game_procs = [p for p in procs if p.binary_type == GameBinary.GAME]
    if not game_procs:
        return None

    if len(game_procs) == 1:
        return game_procs[0]

    # Prefer processes WITHOUT anti-cheat wrappers in the name
    # (e.g., prefer FortniteClient-Win64-Shipping.exe over
    #  FortniteClient-Win64-Shipping_EAC_EOS.exe)
    real_games = [
        p for p in game_procs
        if not any(ac in p.name.lower() for ac in ("_eac", "_be", "anti_cheat", "eac_eos"))
    ]
    if real_games:
        return min(real_games, key=lambda p: p.pid)  # lowest PID = started first

    # Fallback: lowest PID
    return min(game_procs, key=lambda p: p.pid)


def is_game_running(game_key: str) -> bool:
    """Check if a game's actual game process is running."""
    proc = get_game_process(game_key)
    return proc is not None and proc.is_alive


def get_all_game_processes() -> list[ProcessInfo]:
    """Get ALL processes for ALL games, flat list."""
    all_procs = detect_game_processes()
    result = []
    for procs in all_procs.values():
        result.extend(procs)
    return result


def get_supported_games() -> list[str]:
    """Return list of supported game keys."""
    return list(GAME_PROCESSES.keys())


def get_game_display_name(game_key: str) -> str:
    """Return display name for a game key."""
    defs = GAME_PROCESSES.get(game_key, {})
    return defs.get("display_name", game_key.title())
