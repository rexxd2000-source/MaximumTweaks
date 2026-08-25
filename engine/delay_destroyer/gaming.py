"""Gaming environment analysis — detect games, overlays, and resource contention.

Analyzes the system when a game is running to identify factors that
may affect in-game latency and responsiveness.
"""
from __future__ import annotations

import ctypes
import re
import subprocess
from dataclasses import dataclass, field

import psutil


# Known game executable names (lowercase)
_KNOWN_GAMES = {
    "fortniteclient-win64-shipping.exe": "Fortnite",
    "valorant-win64-shipping.exe": "Valorant",
    "valorant.exe": "Valorant",
    "csgo.exe": "Counter-Strike 2",
    "cs2.exe": "Counter-Strike 2",
    "r5apex.exe": "Apex Legends",
    "eagamestrial.exe": "Apex Legends",
    "overwatch.exe": "Overwatch 2",
    "overwatch2.exe": "Overwatch 2",
    "cod.exe": "Call of Duty",
    "modernwarfare.exe": "Call of Duty: MW",
    "warzone.exe": "Call of Duty: Warzone",
    " destiny2.exe": "Destiny 2",
    "rocketleague.exe": "Rocket League",
    "league of legends.exe": "League of Legends",
    "leagueclient.exe": "League of Legends",
    "dota2.exe": "Dota 2",
    "pubg.exe": "PUBG",
    "tslgame.exe": "PUBG",
    "rainbowsix.exe": "Rainbow Six Siege",
    "rainbowsix_vulkan.exe": "Rainbow Six Siege",
    "rust.exe": "Rust",
    "among us.exe": "Among Us",
    "minecraft.exe": "Minecraft",
    "javaw.exe": "Minecraft",
    "robloxplayerbeta.exe": "Roblox",
    "gtav.exe": "GTA V",
    "gta5.exe": "GTA V",
    "eldenring.exe": "Elden Ring",
    "cyberpunk2077.exe": "Cyberpunk 2077",
    "hogwartslegacy.exe": "Hogwarts Legacy",
    "starfield.exe": "Starfield",
}

# Known overlay processes
_OVERLAY_PROCESSES = {
    "discord.exe": "Discord Overlay",
    "steamwebhelper.exe": "Steam Overlay",
    "gameoverlayui.exe": "Steam Overlay",
    "nvidia overlay": "NVIDIA ShadowPlay",
    "nvcontainer.exe": "NVIDIA Container",
    "ghub.exe": "Logitech G Hub",
    "ghub_updater.exe": "Logitech G Hub",
    "razer synapse": "Razer Synapse",
    "razercentral.exe": "Razer Central",
    "msiafterburner.exe": "MSI Afterburner",
    "rtss.exe": "RivaTuner Statistics",
    "rivatuner.exe": "RivaTuner Statistics",
    "xbox游戏栏": "Xbox Game Bar",
    "gamebar.exe": "Xbox Game Bar",
    "gamebarftserver.exe": "Xbox Game Bar",
    "obs.exe": "OBS Studio",
    "obs64.exe": "OBS Studio",
    "streamlabs.exe": "Streamlabs OBS",
    "elsdog.exe": "ElsDogg (Capture)",
    " Medal.exe": "Medal.tv",
    "outplayed.exe": "Outplayed (Overwolf)",
    "overwolf.exe": "Overwolf",
    "epicgameslauncher.exe": "Epic Games Launcher",
    "origin.exe": "EA Origin",
    "eaapp.exe": "EA App",
    "ubisoftconnect.exe": "Ubisoft Connect",
    "gog galaxy.exe": "GOG Galaxy",
    "battle.net.exe": "Battle.net",
    "blizzard.exe": "Battle.net",
}

# Recording software
_RECORDING_PROCESSES = {
    "obs.exe": "OBS Studio",
    "obs64.exe": "OBS Studio",
    "streamlabs.exe": "Streamlabs OBS",
    " Medal.exe": "Medal.tv",
    "outplayed.exe": "Outplayed",
    "nvcpl.dll": "NVIDIA ShadowPlay",
    "share.exe": "NVIDIA Share",
    "xbox游戏栏": "Xbox Game DVR",
    "gamebar.exe": "Xbox Game DVR",
}


@dataclass
class GameProcess:
    """A detected game process."""
    name: str
    display_name: str
    pid: int
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    priority: str = ""
    affinity_mask: int = 0
    thread_count: int = 0
    status: str = ""


@dataclass
class OverlayInfo:
    """A detected overlay or background application."""
    name: str
    display_name: str
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    category: str = "overlay"  # overlay, recording, launcher


@dataclass
class GamingAnalysis:
    """Complete gaming environment analysis."""
    game_detected: bool = False
    games: list[GameProcess] = field(default_factory=list)
    overlays: list[OverlayInfo] = field(default_factory=list)
    recording_software: list[OverlayInfo] = field(default_factory=list)
    launchers: list[OverlayInfo] = field(default_factory=list)

    # Resource contention
    total_background_cpu: float = 0.0
    total_background_mb: float = 0.0
    background_process_count: int = 0

    # Game Mode / HAGS / fullscreen
    game_mode_enabled: bool = False
    hags_enabled: bool = False
    fullscreen_optimizations: bool = True
    xbox_game_bar_enabled: bool = False
    game_dvr_enabled: bool = False

    # Recommendations
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


def _ps(script: str, timeout: int = 15) -> str:
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000,
        )
        return proc.stdout or ""
    except Exception:
        return ""


def _reg_value(hive: str, subkey: str, name: str, default=None):
    import winreg
    try:
        root = (winreg.HKEY_LOCAL_MACHINE if hive == "HKLM"
                else winreg.HKEY_CURRENT_USER if hive == "HKCU"
                else winreg.HKEY_USERS)
        with winreg.OpenKey(root, subkey) as key:
            value, _kind = winreg.QueryValueEx(key, name)
            return value
    except OSError:
        return default


def detect_games() -> list[GameProcess]:
    """Detect running game processes."""
    games = []
    for proc in psutil.process_iter(["name", "pid", "cpu_percent", "memory_info",
                                      "status", "nice", "num_threads"]):
        try:
            info = proc.info
            name = (info.get("name") or "").lower()
            if name in _KNOWN_GAMES:
                mem_mb = 0
                if info.get("memory_info"):
                    mem_mb = round(info["memory_info"].rss / (1024 * 1024), 1)
                try:
                    proc.cpu_percent(interval=0)
                except Exception:
                    pass
                games.append(GameProcess(
                    name=info["name"],
                    display_name=_KNOWN_GAMES[name],
                    pid=info["pid"],
                    cpu_percent=info.get("cpu_percent", 0) or 0,
                    memory_mb=mem_mb,
                    priority=str(info.get("nice", "")),
                    thread_count=info.get("num_threads", 0),
                    status=info.get("status", ""),
                ))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return games


def detect_overlays() -> list[OverlayInfo]:
    """Detect running overlay and background applications."""
    overlays = []
    for proc in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
        try:
            info = proc.info
            name = (info.get("name") or "").lower()
            for key, display in _OVERLAY_PROCESSES.items():
                if key.lower() in name:
                    mem_mb = 0
                    if info.get("memory_info"):
                        mem_mb = round(info["memory_info"].rss / (1024 * 1024), 1)
                    cat = "overlay"
                    if key in _RECORDING_PROCESSES:
                        cat = "recording"
                    elif "launcher" in display.lower() or "games" in display.lower():
                        cat = "launcher"
                    overlays.append(OverlayInfo(
                        name=info["name"],
                        display_name=display,
                        cpu_percent=info.get("cpu_percent", 0) or 0,
                        memory_mb=mem_mb,
                        category=cat,
                    ))
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return overlays


def _check_windows_gaming_settings() -> dict:
    """Check Windows gaming-related settings."""
    settings = {}

    # Game Mode
    gm = _reg_value(
        "HKCU",
        r"Software\Microsoft\GameBar",
        "AllowAutoGameMode"
    )
    settings["game_mode_enabled"] = gm == 1

    # HAGS
    hags = _reg_value(
        "HKLM",
        r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
        "HwSchMode"
    )
    settings["hags_enabled"] = hags == 2

    # Fullscreen optimizations
    fso = _reg_value(
        "HKCU",
        r"System\GameConfigStore",
        "GameDVR_FSEBehaviorMode"
    )
    settings["fullscreen_optimizations"] = fso != 2

    # Xbox Game Bar
    gbx = _reg_value(
        "HKCU",
        r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
        "AppCaptureEnabled"
    )
    settings["xbox_game_bar_enabled"] = gbx == 1

    # Game DVR
    gdv = _reg_value(
        "HKCU",
        r"System\GameConfigStore",
        "GameDVR_Enabled"
    )
    settings["game_dvr_enabled"] = gdv == 1

    return settings


def analyze_gaming_environment(scan=None) -> GamingAnalysis:
    """Run full gaming environment analysis."""
    a = GamingAnalysis()

    # Detect games
    a.games = detect_games()
    a.game_detected = len(a.games) > 0

    # Detect overlays
    all_overlays = detect_overlays()
    a.overlays = [o for o in all_overlays if o.category == "overlay"]
    a.recording_software = [o for o in all_overlays if o.category == "recording"]
    a.launchers = [o for o in all_overlays if o.category == "launcher"]

    # Background resource usage
    total_cpu = 0.0
    total_mem = 0.0
    bg_count = 0
    game_pids = {g.pid for g in a.games}
    for proc in psutil.process_iter(["pid", "cpu_percent", "memory_info", "name"]):
        try:
            info = proc.info
            if info["pid"] in game_pids:
                continue
            cpu = info.get("cpu_percent", 0) or 0
            mem = 0
            if info.get("memory_info"):
                mem = info["memory_info"].rss / (1024 * 1024)
            total_cpu += cpu
            total_mem += mem
            bg_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    a.total_background_cpu = round(total_cpu, 1)
    a.total_background_mb = round(total_mem, 1)
    a.background_process_count = bg_count

    # Windows gaming settings
    settings = _check_windows_gaming_settings()
    a.game_mode_enabled = settings.get("game_mode_enabled", False)
    a.hags_enabled = settings.get("hags_enabled", False)
    a.fullscreen_optimizations = settings.get("fullscreen_optimizations", True)
    a.xbox_game_bar_enabled = settings.get("xbox_game_bar_enabled", False)
    a.game_dvr_enabled = settings.get("game_dvr_enabled", False)

    # Generate findings
    if a.game_detected:
        for g in a.games:
            a.findings.append(
                f"Game detected: {g.display_name} — "
                f"{g.cpu_percent:.0f}% CPU, {g.memory_mb:.0f}MB RAM"
            )

    if a.overlays:
        names = ", ".join(o.display_name for o in a.overlays)
        a.findings.append(f"Overlays active: {names}")
        a.recommendations.append(
            "Disable in-game overlays to reduce GPU/CPU overhead during gameplay."
        )

    if a.recording_software:
        names = ", ".join(o.display_name for o in a.recording_software)
        a.findings.append(f"Recording software active: {names}")
        a.recommendations.append(
            "Recording software uses GPU encoding and disk I/O. "
            "Disable or use hardware encoding if experiencing stutters."
        )

    if a.total_background_cpu > 15:
        a.findings.append(
            f"Background processes using {a.total_background_cpu:.0f}% CPU total."
        )
        a.recommendations.append(
            "High background CPU usage can cause frame drops. "
            "Close unnecessary applications while gaming."
        )

    if a.xbox_game_bar_enabled:
        a.findings.append("Xbox Game Bar is enabled.")
        a.recommendations.append(
            "Xbox Game Bar overlay and DVR can add GPU overhead. "
            "Disable if not using recording features."
        )

    if a.game_dvr_enabled:
        a.findings.append("Game DVR recording is enabled.")
        a.recommendations.append(
            "Game DVR continuously records gameplay, using disk I/O and GPU. "
            "Disable for competitive gaming."
        )

    if not a.hags_enabled:
        a.findings.append("Hardware-Accelerated GPU Scheduling is disabled.")
        a.recommendations.append(
            "HAGS allows the GPU to manage its own scheduling, which can "
            "reduce latency on supported hardware (NVIDIA RTX 20+, AMD RX 6000+)."
        )

    return a
