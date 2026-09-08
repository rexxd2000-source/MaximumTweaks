"""NVIDIA game-profile catalog and apply/reset orchestration.

Data model
----------
Each game maps to a driver profile (matched by display name — the driver
uses the Control Panel style names like "Fortnite", "Counter-strike 2").
If no matching driver profile exists we create one and attach the game's
known executables.

Applying a profile records a snapshot of every setting we touched so the
reset can restore it exactly: a value that existed before is written back,
one that did not exist is removed from the profile (falling back to the
driver's predefined value).

All setting ids / values below were verified against the installed driver
(see _dev/nvprobe8.py); value semantics are the classic NPI ones, which the
current driver still honours for these settings.
"""
from __future__ import annotations

import time

from engine import activity
from engine import nvprofile as nv
from engine import state as state_mgr
from rexlog import logger

# --------------------------------------------------------------------------
# Setting catalog
# --------------------------------------------------------------------------
#  value labels shown in the UI; the applied value comes from "default".

SETTINGS: dict[str, dict] = {
    "pwr_mgmt": {
        "name": "Power management mode",
        "names": ["Power management mode"],
        "desc": "Prefer maximum performance so the GPU stays at full clocks.",
        "kind": "enum",
        "values": {
            "Adaptive": 0x1,
            "Optimal power": 0x2,
            "Prefer maximum performance": 0x3,
        },
        "default": 0x3,
    },
    "max_prerender": {
        "name": "Maximum pre-rendered frames",
        "names": ["Maximum pre-rendered frames"],
        "desc": "One buffered frame lowers input latency (\"Low Latency\").",
        "kind": "int",
        "values": {
            "1 frame": 1,
        },
        "default": 1,
    },
    "threaded_opt": {
        "name": "Threaded optimization",
        "names": ["Threaded optimization"],
        "desc": "Let the driver balance the CPU render threads.",
        "kind": "enum",
        "values": {
            "Off": 0x1,
            "On (Auto)": 0x2,
        },
        "default": 0x2,
    },
    "vsync": {
        "name": "Vertical Sync",
        "names": ["Vertical Sync"],
        "desc": "Force V-Sync off to remove frame-pacing latency.",
        "kind": "enum",
        "values": {
            "Off": 0x60925292,
            "On": 0x08416747,
            "Use the 3D application setting": 0x18888888,
        },
        "default": 0x60925292,
    },
    "tex_aniso_filter_opt": {
        "name": "Texture filtering - Anisotropic filter optimization",
        "names": ["Texture filtering - Anisotropic filter optimization"],
        "desc": "Optimise anisotropic filtering for fill-rate (faster).",
        "kind": "enum",
        "values": {
            "Off": 0x0,
            "On": 0x1,
        },
        "default": 0x1,
    },
    "tex_aniso_sample_opt": {
        "name": "Texture filtering - Anisotropic sample optimization",
        "names": ["Texture filtering - Anisotropic sample optimization"],
        "desc": "Bilinear hit is used where safe (faster).",
        "kind": "enum",
        "values": {
            "Off": 0x0,
            "On": 0x1,
        },
        "default": 0x1,
    },
    "tex_trilinear_opt": {
        "name": "Texture filtering - Trilinear optimization",
        "names": ["Texture filtering - Trilinear optimization"],
        "desc": "Disable trilinear optimisation for sharper sampling.",
        "kind": "enum",
        "values": {
            "Off": 0x0,
            "On": 0x1,
        },
        "default": 0x1,
    },
    "tex_neg_lod": {
        "name": "Texture filtering - Negative LOD bias",
        "names": ["Texture filtering - Negative LOD bias"],
        "desc": "Allow negative LOD bias for crisper mip selection.",
        "kind": "enum",
        "values": {
            "Allow": 0x0,
            "Clamp": 0x1,
        },
        "default": 0x0,
    },
    "shader_cache": {
        "name": "Shader Cache",
        "names": ["Shader Cache"],
        "desc": "Keep compiled shaders on disk to avoid in-game hitches.",
        "kind": "enum",
        "values": {
            "Off": 0x0,
            "On": 0x1,
        },
        "default": 0x1,
    },
    "ao": {
        "name": "Ambient Occlusion",
        "names": ["Ambient Occlusion"],
        "desc": "Disable ambient occlusion for free FPS on light scenes.",
        "kind": "enum",
        "values": {
            "Off": 0x0,
            "Quality": 0x1,
            "Performance": 0x2,
        },
        "default": 0x0,
    },
    "fxaa": {
        "name": "Enable FXAA",
        "names": ["Enable FXAA"],
        "desc": "Disable FXAA — it blurs edges and costs a little GPU time.",
        "kind": "enum",
        "values": {
            "Off": 0x0,
            "On": 0x1,
        },
        "default": 0x0,
    },
    "aa_mode": {
        "name": "Antialiasing - Mode",
        "names": ["Antialiasing - Mode"],
        "desc": "No driver-side MSAA override; in-game AA is untouched.",
        "kind": "enum",
        "values": {
            "Application-controlled": 0x0,
            "Enhance the application setting": 0x1,
            "Override any application setting": 0x2,
            "Off": 0x3,
        },
        "default": 0x3,
    },
}

# --------------------------------------------------------------------------
# Game catalog
# --------------------------------------------------------------------------

GAMES: dict[str, dict] = {
    "gp-001": {
        "name": "Fortnite",
        "profile_candidates": ["Fortnite", "Fortnite Launcher"],
        "exes": [
            "FortniteClient-Win64-Shipping.exe",
            "FortniteClient-Win64-Shipping_EAC.exe",
            "FortniteLauncher.exe",
        ],
    },
    "gp-002": {
        "name": "Valorant",
        "profile_candidates": ["Valorant"],
        "exes": [
            "VALORANT-Win64-Shipping.exe",
            "RiotClientServices.exe",
        ],
    },
    "gp-003": {
        "name": "CS2",
        "profile_candidates": ["Counter-strike 2", "Counter-Strike 2",
                               "Counter-Strike: Global Offensive"],
        "exes": ["cs2.exe", "csgo.exe"],
    },
    "gp-004": {
        "name": "Call of Duty",
        "profile_candidates": [
            "Call of Duty: Modern Warfare",
            "Call of Duty: Black Ops Cold War",
            "Call of Duty: Vanguard",
            "Call of Duty: Modern Warfare II",
            "Call of Duty: Modern Warfare III",
        ],
        "exes": [
            "ModernWarfare.exe", "BlackOpsColdWar.exe", "vanguard.exe",
            "cod.exe", "modernwarfare.exe",
        ],
    },
    "gp-005": {
        "name": "Apex Legends",
        "profile_candidates": ["Apex Legends"],
        "exes": ["r5apex.exe"],
    },
    "gp-006": {
        "name": "Overwatch 2",
        "profile_candidates": ["Overwatch 2", "Overwatch"],
        "exes": ["Overwatch.exe", "Overwatch2.exe"],
    },
    "gp-007": {
        "name": "Minecraft",
        "profile_candidates": ["Minecraft"],
        "exes": ["MinecraftLauncher.exe", "Minecraft.exe"],
    },
    "gp-008": {
        "name": "Rocket League",
        "profile_candidates": ["Rocket League"],
        "exes": ["RocketLeague.exe", "RocketLeagueLauncher.exe"],
    },
    "gp-009": {
        "name": "League of Legends",
        "profile_candidates": ["League of Legends", "League of Legends (TM) Client"],
        "exes": ["League of Legends.exe", "LeagueClient.exe"],
    },
    "gp-010": {
        "name": "Rust",
        "profile_candidates": ["Rust"],
        "exes": ["RustClient.exe"],
    },
    "gp-011": {
        "name": "Escape from Tarkov",
        "profile_candidates": ["Escape from Tarkov"],
        "exes": ["EscapeFromTarkov.exe"],
    },
    "gp-012": {
        "name": "Warzone",
        "profile_candidates": ["Call of Duty: Warzone", "Call of Duty: Warzone 2.0",
                               "Call of Duty: Modern Warfare III"],
        "exes": ["Warzone.exe", "cod.exe", "modernwarfare.exe"],
    },
}

COMPETITIVE_SET: list[tuple[str, int]] = [
    ("pwr_mgmt", 0x3),
    ("max_prerender", 1),
    ("threaded_opt", 0x2),
    ("vsync", 0x60925292),
    ("tex_aniso_filter_opt", 0x1),
    ("tex_aniso_sample_opt", 0x1),
    ("tex_trilinear_opt", 0x1),
    ("tex_neg_lod", 0x0),
    ("shader_cache", 0x1),
    ("ao", 0x0),
    ("fxaa", 0x0),
    ("aa_mode", 0x3),
]

PROFILE_NAMES = {g["name"]: g for g in GAMES.values()}


def game_settings(game_id: str) -> list[tuple[str, int]]:
    """The (setting_key, value) list to apply for a game."""
    return COMPETITIVE_SET


def driver_available() -> bool:
    return nv.Nvapi.available()


def gpu_names() -> list[str]:
    try:
        return nv.Nvapi().gpu_names()
    except nv.NvapiError as exc:  # noqa: BLE001
        logger.warning(f"nvprofiles: gpu_names failed: {exc}")
        return []


def _find_or_create(drs: nv.DrsSession, game: dict):
    """Return (profile_handle, created, used_name)."""
    for name in game["profile_candidates"]:
        h = drs.find_profile(name)
        if h is not None:
            return h, False, name
    name = game["profile_candidates"][0]
    h, created = drs.ensure_profile(name, game.get("exes") or [])
    return h, created, name


def apply_profile(game_id: str) -> dict:
    """Apply the competitive driver profile for a game and snapshot it.

    Returns a report dict: {game_id, profile, created, applied, skipped,
    failed} where ``applied``/``skipped``/``failed`` are lists of
    (setting_name, value) tuples.
    """
    game = GAMES.get(game_id)
    if game is None:
        raise nv.NvapiError(f"Unknown game profile id {game_id!r}")

    report = {"game_id": game_id, "game": game["name"], "profile": None,
              "created": False, "applied": [], "skipped": [], "failed": []}
    nvapi = nv.Nvapi()
    with nvapi.session() as drs:
        hprof, created, used_name = _find_or_create(drs, game)
        report["profile"] = used_name
        report["created"] = created

        snapshot = {}
        for key, value in game_settings(game_id):
            entry = SETTINGS[key]
            setting_id = drs.setting_id(entry["names"])
            if setting_id is None:
                report["skipped"].append((entry["name"], value))
                logger.warning(f"nvprofiles: setting {entry['name']!r} not on this driver")
                continue
            try:
                before = drs.get_setting(hprof, setting_id)
                drs.set_setting_dword(hprof, setting_id, value)
                snapshot[hex(setting_id)] = {
                    "name": entry["name"],
                    "was_set": before is not None,
                    "value": before.current.u32 if before is not None else None,
                }
                report["applied"].append((entry["name"], value))
            except nv.NvapiError as exc:  # noqa: BLE001
                report["failed"].append((entry["name"], str(exc)))
                logger.warning(f"nvprofiles: set {entry['name']} failed: {exc}")

        drs.save()

    state_mgr.set_nv_profile_snapshot(game_id, {
        "profile": used_name,
        "settings": snapshot,
        "applied_at": time.strftime("%Y-%m-%d %H:%M"),
    })
    activity.emit("profile", f"NVIDIA driver profile applied for {game['name']} "
                             f"({len(report['applied'])} settings)")
    logger.info(f"nvprofiles: applied {game['name']} -> {len(report['applied'])} "
                f"settings, {len(report['skipped'])} skipped, "
                f"{len(report['failed'])} failed")
    return report


def reset_profile(game_id: str) -> dict:
    """Restore the exact pre-apply state for a game profile.

    Uses the snapshot stored by :func:`apply_profile`. Returns a report dict
    like ``apply_profile`` (profile name may be None when nothing to reset).
    """
    game = GAMES.get(game_id)
    if game is None:
        raise nv.NvapiError(f"Unknown game profile id {game_id!r}")

    snap = state_mgr.get_nv_profile_snapshot(game_id)
    report = {"game_id": game_id, "game": game["name"], "profile": None,
              "created": False, "applied": [], "skipped": [], "failed": []}
    if not snap or not snap.get("settings"):
        activity.emit("info", f"No NVIDIA profile snapshot found for {game['name']}")
        return report

    nvapi = nv.Nvapi()
    with nvapi.session() as drs:
        hprof = drs.find_profile(snap["profile"]) if snap.get("profile") else None
        if hprof is None:
            for name in game["profile_candidates"]:
                hprof = drs.find_profile(name)
                if hprof is not None:
                    break
        if hprof is None:
            report["failed"].append(("profile", "driver profile no longer exists"))
            state_mgr.clear_nv_profile_snapshot(game_id)
            return report
        report["profile"] = snap["profile"]

        for setting_id_hex, meta in snap["settings"].items():
            setting_id = int(setting_id_hex, 16)
            name = meta.get("name") or setting_id_hex
            try:
                if meta.get("was_set"):
                    drs.set_setting_dword(hprof, setting_id, int(meta["value"]))
                else:
                    drs.delete_setting(hprof, setting_id)
                report["applied"].append((name, meta.get("value")))
            except nv.NvapiError as exc:  # noqa: BLE001
                report["failed"].append((name, str(exc)))

        drs.save()

    state_mgr.clear_nv_profile_snapshot(game_id)
    activity.emit("profile", f"NVIDIA driver profile reset for {game['name']}")
    logger.info(f"nvprofiles: reset {game['name']} -> {len(report['applied'])} restored")
    return report


def profile_status(game_id: str) -> dict:
    """Summary for the UI: applied?, driver present?, profile exists?, gpu."""
    applied = state_mgr.get_nv_profile_snapshot(game_id) is not None
    game = GAMES.get(game_id, {})
    return {
        "game_id": game_id,
        "game": game.get("name", game_id),
        "applied": applied,
        "driver_available": driver_available(),
        "gpu": gpu_names() or [],
        "profile": state_mgr.get_nv_profile_snapshot(game_id, {}).get("profile"),
    }
