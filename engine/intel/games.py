"""Game process detection — robust Windows process discovery.

Detects: Fortnite, VALORANT, Call of Duty, CS2.
Also detects routing optimizers (ExitLag, NoPing, Mudfish, wtfast).
"""
from __future__ import annotations

import time
from typing import Optional
from dataclasses import dataclass, field

from engine.intel.models import GameType, GameState, Confidence, DataSource


# ── Game Definitions ─────────────────────────────────────────────────────────

@dataclass
class GameDefinition:
    game: GameType
    display_name: str
    process_names: list[str] = field(default_factory=list)
    process_prefixes: list[str] = field(default_factory=list)
    process_substrings: list[str] = field(default_factory=list)
    executable_paths: list[str] = field(default_factory=list)
    launcher_processes: list[str] = field(default_factory=list)
    default_region: str = ""
    known_ports: list[int] = field(default_factory=list)
    udp_ports: list[int] = field(default_factory=list)
    tcp_ports: list[int] = field(default_factory=list)


GAME_DEFINITIONS: dict[GameType, GameDefinition] = {
    GameType.FORTNITE: GameDefinition(
        game=GameType.FORTNITE,
        display_name="Fortnite",
        process_names=[
            "FortniteClient-Win64-Shipping.exe",
            "FortniteClient-Win64-Shipping_EAC_EOS.exe",
            "FortniteLauncher.exe",
            "FortniteBootstrapper.exe",
            "EasyAntiCheat_EOS.exe",
        ],
        process_prefixes=["FortniteClient-Win64-Shipping", "Fortnite"],
        process_substrings=["fortnite"],
        executable_paths=["Epic Games\\Fortnite", "Epic Games\\FortniteGame"],
        launcher_processes=["EpicGamesLauncher.exe", "EpicWebHelper.exe"],
        default_region="",
        known_ports=[5222, 5795, 5800, 5801, 5900, 9960, 9999],
        udp_ports=[5222, 5795, 5800, 5801, 5900, 9960, 9999],
        tcp_ports=[443, 5222, 5795, 9960, 9999],
    ),
    GameType.VALORANT: GameDefinition(
        game=GameType.VALORANT,
        display_name="VALORANT",
        process_names=[
            "VALORANT-Win64-Shipping.exe",
            "VALORANT-Win64-Shipping_Be.exe",
            "RiotClientServices.exe",
            "vgtray.exe",
            "vanguard.exe",
        ],
        process_prefixes=["VALORANT-Win64-Shipping"],
        process_substrings=["valorant", "riot"],
        executable_paths=["Riot Games\\VALORANT", "Riot Games\\Riot Client"],
        launcher_processes=["RiotClientServices.exe"],
        default_region="",
        known_ports=[7000, 7100, 7200, 7300, 7400],
        udp_ports=[7000, 7100, 7200, 7300, 7400],
        tcp_ports=[443, 7000],
    ),
    GameType.CALL_OF_DUTY: GameDefinition(
        game=GameType.CALL_OF_DUTY,
        display_name="Call of Duty",
        process_names=[
            "cod.exe",
            "codcrashhandler.exe",
            "ModernWarfare.exe",
            "Warzone.exe",
        ],
        process_prefixes=["cod"],
        process_substrings=["call of duty", "modernwarfare", "warzone"],
        executable_paths=["Call of Duty", "Modern Warfare", "Warzone"],
        launcher_processes=["steam.exe", "Battle.net.exe"],
        default_region="",
        known_ports=[3074, 3075, 3076],
        udp_ports=[3074, 3075, 3076],
        tcp_ports=[443, 3074],
    ),
    GameType.CS2: GameDefinition(
        game=GameType.CS2,
        display_name="Counter-Strike 2",
        process_names=[
            "cs2.exe",
            "cs2_win64.exe",
            "csgo.exe",
        ],
        process_prefixes=["cs2"],
        process_substrings=["counter-strike", "csgo"],
        executable_paths=["Counter-Strike Global Offensive", "steamapps\\common\\Counter-Strike"],
        launcher_processes=["steam.exe"],
        default_region="",
        known_ports=list(range(27015, 27021)),
        udp_ports=list(range(27015, 27021)),
        tcp_ports=[27015, 27016, 443],
    ),
}


# ── Optimizer Definitions ────────────────────────────────────────────────────

@dataclass
class OptimizerDefinition:
    name: str
    process_names: list[str]
    display_name: str


OPTIMIZER_DEFINITIONS: list[OptimizerDefinition] = [
    OptimizerDefinition("exitlag", ["ExitLag.exe", "ExitLagService.exe"], "ExitLag"),
    OptimizerDefinition("noPing", ["NoPing.exe", "NoPingService.exe"], "NoPing"),
    OptimizerDefinition("mudfish", ["Mudfish.exe", "MudfishNode.exe"], "Mudfish"),
    OptimizerDefinition("wtfast", ["wtfast.exe", "wtfastgu.exe"], "WTFAST"),
]


# ── Detected Entities ────────────────────────────────────────────────────────

@dataclass
class DetectedGame:
    game: GameType
    process_name: str
    pid: int
    is_active: bool
    confidence: Confidence = Confidence.HIGH
    source: DataSource = field(default_factory=DataSource.now)
    process_path: str = ""
    detection_time: float = 0.0
    has_network: bool = False
    remote_endpoints: int = 0
    udp_endpoints: int = 0
    tcp_endpoints: int = 0
    game_state: GameState = GameState.UNKNOWN

    @property
    def display_name(self) -> str:
        defn = GAME_DEFINITIONS.get(self.game)
        return defn.display_name if defn else self.game.value.replace("_", " ").title()

    @property
    def state_label(self) -> str:
        labels = {
            GameState.NOT_INSTALLED: "NOT INSTALLED",
            GameState.NOT_RUNNING: "NOT RUNNING",
            GameState.LAUNCHING: "LAUNCHING",
            GameState.RUNNING: "RUNNING",
            GameState.LOBBY: "LOBBY",
            GameState.MATCHMAKING: "MATCHMAKING",
            GameState.IN_MATCH: "IN MATCH",
            GameState.NETWORK_ACTIVE: "NETWORK ACTIVE",
            GameState.NETWORK_INACTIVE: "NETWORK INACTIVE",
            GameState.UNKNOWN: "UNKNOWN",
        }
        return labels.get(self.game_state, "UNKNOWN")

    @property
    def state_color(self) -> str:
        colors = {
            GameState.NOT_INSTALLED: "#514A70",
            GameState.NOT_RUNNING: "#514A70",
            GameState.LAUNCHING: "#FFB454",
            GameState.RUNNING: "#34d399",
            GameState.LOBBY: "#60a5fa",
            GameState.MATCHMAKING: "#FFB454",
            GameState.IN_MATCH: "#34d399",
            GameState.NETWORK_ACTIVE: "#34d399",
            GameState.NETWORK_INACTIVE: "#FF6F6F",
            GameState.UNKNOWN: "#514A70",
        }
        return colors.get(self.game_state, "#514A70")


@dataclass
class DetectedOptimizer:
    name: str
    display_name: str
    process_name: str
    pid: int
    confidence: Confidence = Confidence.HIGH
    source: DataSource = field(default_factory=DataSource.now)


# ── Process Matching ─────────────────────────────────────────────────────────

_FALSE_POSITIVES = frozenset({
    "crashreportclient.exe",
    "crashhandler.exe",
    "unrealengineditor.exe",
    "eacportschecker.exe",
    "dotnet.exe",
    "msbuild.exe",
})


def _match_process(name: str, exe_path: str, game_def: GameDefinition) -> tuple[bool, bool, Confidence]:
    """Returns (is_game_binary, is_launcher, confidence)."""
    name_lower = name.lower()
    path_lower = exe_path.lower()

    if name_lower in _FALSE_POSITIVES:
        return False, False, Confidence.UNKNOWN

    for pn in game_def.process_names:
        if name_lower == pn.lower():
            return True, False, Confidence.CONFIRMED

    for prefix in game_def.process_prefixes:
        if name_lower.startswith(prefix.lower()):
            return True, False, Confidence.HIGH

    for sub in game_def.process_substrings:
        if len(sub) >= 5 and sub.lower() in name_lower:
            return True, False, Confidence.MEDIUM

    for lp in game_def.launcher_processes:
        if name_lower == lp.lower():
            return False, True, Confidence.MEDIUM

    for ep in game_def.executable_paths:
        if ep.lower() in path_lower and ("\\binaries\\" in path_lower or "/binaries/" in path_lower):
            return True, False, Confidence.MEDIUM

    return False, False, Confidence.UNKNOWN


# ── Public API ───────────────────────────────────────────────────────────────

def detect_running_games() -> list[DetectedGame]:
    """Scan all processes for supported games. Returns sorted by relevance."""
    try:
        import psutil
    except ImportError:
        return []

    detected: list[DetectedGame] = []
    seen_pids: set[int] = set()

    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            info = proc.info
            pid = info.get("pid", 0)
            name = info.get("name", "")
            exe = info.get("exe", "") or ""

            if not name or pid in seen_pids:
                continue

            for game_type, game_def in GAME_DEFINITIONS.items():
                is_game, is_launcher, conf = _match_process(name, exe, game_def)
                if is_game or is_launcher:
                    detected.append(DetectedGame(
                        game=game_type,
                        process_name=name,
                        pid=pid,
                        is_active=is_game,
                        confidence=conf,
                        source=DataSource.now("process_api", "psutil"),
                        process_path=exe,
                        detection_time=time.time(),
                    ))
                    seen_pids.add(pid)
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    _check_network_activity(detected)

    priority = {GameType.FORTNITE: 0, GameType.VALORANT: 1, GameType.CALL_OF_DUTY: 2, GameType.CS2: 3}
    detected.sort(key=lambda g: (not g.is_active, not g.has_network, priority.get(g.game, 99)))

    return detected


def detect_running_optimizers() -> list[DetectedOptimizer]:
    """Scan for routing optimizer processes."""
    try:
        import psutil
    except ImportError:
        return []

    found: list[DetectedOptimizer] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            for opt_def in OPTIMIZER_DEFINITIONS:
                if name in [pn.lower() for pn in opt_def.process_names]:
                    found.append(DetectedOptimizer(
                        name=opt_def.name,
                        display_name=opt_def.display_name,
                        process_name=proc.info["name"],
                        pid=proc.info["pid"],
                        confidence=Confidence.CONFIRMED,
                        source=DataSource.now("process_api", "psutil"),
                    ))
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def get_primary_game(detected: list[DetectedGame]) -> Optional[DetectedGame]:
    """Select the most relevant detected game."""
    if not detected:
        return None

    active_with_net = [g for g in detected if g.is_active and g.has_network]
    if active_with_net:
        return max(active_with_net, key=lambda g: g.remote_endpoints)

    active = [g for g in detected if g.is_active]
    if active:
        return max(active, key=lambda g: (
            g.confidence in (Confidence.CONFIRMED, Confidence.HIGH),
            g.remote_endpoints,
        ))

    return detected[0] if detected else None


def is_game_running(detected: list[DetectedGame], game: GameType) -> bool:
    return any(g.game == game and g.is_active for g in detected)


def _check_network_activity(games: list[DetectedGame]) -> None:
    """Check if detected game processes have network activity."""
    try:
        import psutil
    except ImportError:
        return

    try:
        connections = list(psutil.net_connections(kind="inet"))
    except (psutil.AccessDenied, OSError):
        return

    game_pids = {g.pid: g for g in games}

    for conn in connections:
        pid = conn.pid
        if pid not in game_pids:
            continue

        remote = conn.raddr
        if not remote or not remote.ip:
            continue

        ip = remote.ip
        if ip in ("0.0.0.0", "127.0.0.1", "::1", "", "::"):
            continue

        game = game_pids[pid]
        game.has_network = True
        game.remote_endpoints += 1

        if hasattr(conn, "type"):
            if conn.type == 2:
                game.udp_endpoints += 1
            elif conn.type == 1:
                game.tcp_endpoints += 1

    for g in games:
        if g.has_network and g.game_state == GameState.UNKNOWN:
            g.game_state = GameState.NETWORK_ACTIVE
        elif g.is_active and g.game_state == GameState.UNKNOWN:
            g.game_state = GameState.RUNNING
