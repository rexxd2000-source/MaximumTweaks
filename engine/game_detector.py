"""Detect which supported games are installed on this PC.

Scans known launcher library folders (Steam, Epic, Battle.net, GOG, Riot,
Xbox) across all fixed drives plus Steam's libraryfolders.vdf, looking for
the game executables defined in :mod:`engine.nvprofiles`.

Runs best inside a worker thread (a full scan of several roots can take a
couple of seconds).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from engine import nvprofiles
from rexlog import logger

_VDF_PATH_RE = re.compile(r'"(path)"\s+"([^"]+)"', re.IGNORECASE)
_MAX_DEPTH = 4
_SKIP_DIRS = {"$recycle.bin", "system volume information", "windows", "programdata"}


def _fixed_drives() -> list[str]:
    drives = []
    try:
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if bitmask & (1 << i):
                drives.append(f"{chr(ord('A') + i)}:")
    except Exception:  # noqa: BLE001
        drives = ["C:"]
    return drives


def _steam_library_roots() -> list[str]:
    roots = []
    vdf = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
        / "Steam" / "steamapps" / "libraryfolders.vdf"
    if not vdf.exists():
        return roots
    try:
        text = vdf.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:  # noqa: BLE001
        logger.debug(f"game_detector: read {vdf} failed: {exc}")
        return roots
    for _key, path in _VDF_PATH_RE.findall(text):
        p = Path(path) / "steamapps" / "common"
        if p.exists():
            roots.append(str(p))
    return roots


def _candidate_roots() -> list[str]:
    roots: set[str] = set()
    for drive in _fixed_drives():
        candidates = [
            f"{drive}\\steamapps\\common",
            f"{drive}\\Steam\\steamapps\\common",
            f"{drive}\\Program Files (x86)\\Steam\\steamapps\\common",
            f"{drive}\\Program Files\\Epic Games",
            f"{drive}\\Program Files (x86)\\Epic Games",
            f"{drive}\\Epic Games",
            f"{drive}\\Riot Games",
            f"{drive}\\Program Files\\Riot Vanguard",
            f"{drive}\\XboxGames",
            f"{drive}\\Program Files (x86)\\GOG Galaxy\\Games",
            f"{drive}\\Program Files (x86)\\Battle.net",
            f"{drive}\\Battle.net",
            f"{drive}\\Games",
        ]
        for c in candidates:
            if os.path.isdir(c):
                roots.add(c)
    for root in _steam_library_roots():
        roots.add(root)
    return sorted(roots)


def _exes_by_game() -> dict[str, list[str]]:
    return {
        gid: [e.lower() for e in game.get("exes") or []]
        for gid, game in nvprofiles.GAMES.items()
    }


def detect_games() -> dict[str, bool]:
    """Return {game_id: installed} for every catalogued game."""
    exes_by_game = _exes_by_game()
    found: set[str] = set()
    roots = _candidate_roots()
    logger.info(f"game_detector: scanning {len(roots)} library roots")

    for root in roots:
        base_depth = root.rstrip("\\/").count("\\")
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                rel = Path(dirpath)
                if any(part.lower() in _SKIP_DIRS for part in rel.parts):
                    dirnames[:] = []
                    continue
                if dirpath.count("\\") - base_depth >= _MAX_DEPTH:
                    dirnames[:] = []
                lower = {f.lower() for f in filenames}
                for gid, exes in exes_by_game.items():
                    if gid in found:
                        continue
                    if any(e in lower for e in exes):
                        found.add(gid)
                        logger.debug(f"game_detector: {gid} found under {dirpath}")
                if len(found) == len(exes_by_game):
                    break
        except (OSError, PermissionError):  # noqa: BLE001
            continue
        if len(found) == len(exes_by_game):
            break

    result = {gid: gid in found for gid in nvprofiles.GAMES}
    logger.info(f"game_detector: found {sorted(found)}")
    return result


def scan(progress=None) -> dict[str, bool]:
    """Convenience wrapper with an optional progress callback."""
    result = {}
    games = list(nvprofiles.GAMES)
    for idx, gid in enumerate(games, start=1):
        result[gid] = detect_single(gid)
        if progress:
            progress(idx, len(games), gid, result[gid])
    return result


def detect_single(game_id: str) -> bool:
    """Cheap targeted check for one game (used for a fast per-game refresh)."""
    game = nvprofiles.GAMES.get(game_id)
    if not game:
        return False
    exes = {e.lower() for e in game.get("exes") or []}
    if not exes:
        return False
    for root in _candidate_roots():
        base_depth = root.rstrip("\\/").count("\\")
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                if dirpath.count("\\") - base_depth >= _MAX_DEPTH:
                    dirnames[:] = []
                if any(e in {f.lower() for f in filenames} for e in exes):
                    return True
        except (OSError, PermissionError):  # noqa: BLE001
            continue
    return False
