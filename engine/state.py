"""Track which tweaks have been applied so they can be reverted and counted."""
from __future__ import annotations

import json
import os
import time

from rexlog import logger

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STATE_FILE = os.path.join(STATE_DIR, "state.json")

# In-memory copy of state.json. State only ever changes through _save(), so
# the file is read once and served from here afterwards. Without this cache
# the UI's O(N^2) loops re-read the file hundreds of thousands of times and
# freeze the app at startup (window shows "Not Responding" for ~15s).
_CACHE: dict | None = None


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fh:
                _CACHE = json.load(fh)
        except FileNotFoundError:
            _CACHE = {"applied": {}}
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"state: failed to read {STATE_FILE}: {exc}")
            _CACHE = {"applied": {}}
    return _CACHE


def _load_full() -> dict:
    """Same as _load but keeps the whole dict (applied/profile/restart)."""
    return _load()


def _save(state: dict) -> None:
    global _CACHE
    _CACHE = state
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, STATE_FILE)  # atomic on the same volume
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"state: failed to write {STATE_FILE}: {exc}")


def applied_ids() -> set[str]:
    return set(_load().get("applied", {}))


def mark_applied(tweak_id: str) -> None:
    state = _load()
    state.setdefault("applied", {})[tweak_id] = time.strftime("%Y-%m-%d %H:%M")
    _save(state)
    logger.info(f"state: recorded applied tweak {tweak_id}")


def unmark_applied(tweak_id: str) -> None:
    state = _load()
    state.get("applied", {}).pop(tweak_id, None)
    _save(state)
    logger.info(f"state: removed applied tweak {tweak_id}")


def applied_at(tweak_id: str) -> str | None:
    return _load().get("applied", {}).get(tweak_id)


# --- Disabled (user-reverted) tweaks -------------------------------------
# Kept so cards can visually stay in the red "DISABLED" state after a revert,
# even after the page rebuilds its widgets.

def disabled_ids() -> set[str]:
    return set(_load().get("disabled", {}))


def mark_disabled(tweak_id: str) -> None:
    state = _load()
    state.setdefault("disabled", {})[tweak_id] = time.strftime("%Y-%m-%d %H:%M")
    _save(state)
    logger.info(f"state: marked tweak {tweak_id} as disabled")


def unmark_disabled(tweak_id: str) -> None:
    state = _load()
    state.get("disabled", {}).pop(tweak_id, None)
    _save(state)
    logger.info(f"state: removed disabled mark {tweak_id}")


# --- Active game profile -------------------------------------------------

def get_active_profile() -> str | None:
    return _load().get("active_profile")


def set_active_profile(name: str) -> None:
    state = _load()
    state["active_profile"] = name
    _save(state)
    logger.info(f"state: active profile set to {name}")


def clear_active_profile() -> None:
    state = _load()
    state.pop("active_profile", None)
    _save(state)
    logger.info("state: active profile cleared")


# --- NVIDIA driver profile snapshots (exact-reset data) -------------------
# Stored per game id: {game_id: {"profile": name, "applied_at": str,
# "settings": {hex_setting_id: {"name": str, "was_set": bool, "value": int}}}}

def get_nv_profile_snapshot(game_id: str, default=None):
    return _load().get("nv_profiles", {}).get(game_id, default)


def set_nv_profile_snapshot(game_id: str, snapshot: dict) -> None:
    state = _load()
    state.setdefault("nv_profiles", {})[game_id] = snapshot
    _save(state)
    logger.info(f"state: nv snapshot recorded for {game_id}")


def clear_nv_profile_snapshot(game_id: str) -> None:
    state = _load()
    state.get("nv_profiles", {}).pop(game_id, None)
    _save(state)
    logger.info(f"state: nv snapshot cleared for {game_id}")


def nv_snapshot_ids() -> set[str]:
    return set(_load().get("nv_profiles", {}))


# --- Restart requirement ---------------------------------------------------

def is_restart_required() -> bool:
    return bool(_load().get("restart_required"))


def set_restart_required(flag: bool) -> None:
    state = _load()
    state["restart_required"] = bool(flag)
    _save(state)
    logger.info(f"state: restart_required = {flag}")


def clear_restart_required() -> None:
    state = _load()
    state.pop("restart_required", None)
    _save(state)
    logger.info("state: restart_required cleared")


# --- Rex Ultra Mode (dashboard quick-toggle) -------------------------------

def get_ultra_mode() -> bool:
    return bool(_load().get("ultra_mode"))


def set_ultra_mode(on: bool) -> None:
    state = _load()
    state["ultra_mode"] = bool(on)
    _save(state)
    logger.info(f"state: ultra mode = {bool(on)}")


# --- User profile picture (PFP) --------------------------------------------

PFP_FILE = os.path.join(STATE_DIR, "pfp.png")
# Discord avatar is cached SEPARATELY from the user PFP so linking a Discord
# account never overwrites the user's own profile picture.
DISCORD_AVATAR_FILE = os.path.join(STATE_DIR, "discord_avatar.png")


def _normalize_and_save(img, path: str = PFP_FILE, label: str = "pfp") -> str | None:
    """Center-crop to a square, scale to 256px and store to ``path``."""
    try:
        from PySide6.QtCore import Qt
        side = min(img.width(), img.height())
        if side <= 0:
            return None
        x = (img.width() - side) // 2
        y = (img.height() - side) // 2
        img = img.copy(x, y, side, side)
        img = img.scaled(256, 256, Qt.KeepAspectRatio,
                         Qt.SmoothTransformation)
        os.makedirs(STATE_DIR, exist_ok=True)
        if not img.save(path, "PNG"):
            return None
        logger.info(f"{label}: saved picture to {path}")
        return path
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"{label}: failed to save picture: {exc}")
        return None


def set_pfp(source_path: str) -> str | None:
    """Copy + normalize a chosen photo into data/pfp.png (square, 256px).

    Returns the stored path on success, else None. The image is center-cropped
    to a square so the avatar always renders as a clean circle.
    """
    try:
        from PySide6.QtGui import QImage
        img = QImage(source_path)
        if img.isNull():
            logger.warn(f"pfp: could not read {source_path}")
            return None
        return _normalize_and_save(img)
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"pfp: failed to save picture: {exc}")
        return None


def set_pfp_from_bytes(data: bytes) -> str | None:
    """Store an in-memory image as the user's own PFP (app profile picture)."""
    try:
        from PySide6.QtGui import QImage
        img = QImage.fromData(data)
        if img.isNull():
            logger.warn("pfp: decoded image bytes were invalid")
            return None
        return _normalize_and_save(img)
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"pfp: failed to save picture bytes: {exc}")
        return None


def clear_pfp() -> None:
    try:
        if os.path.exists(PFP_FILE):
            os.remove(PFP_FILE)
            logger.info("pfp: removed profile picture")
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"pfp: failed to remove picture: {exc}")


def pfp_path() -> str | None:
    return PFP_FILE if os.path.exists(PFP_FILE) else None


def set_discord_avatar_from_bytes(data: bytes) -> str | None:
    """Cache the Discord avatar SEPARATELY from the user PFP (never overrides it)."""
    try:
        from PySide6.QtGui import QImage
        img = QImage.fromData(data)
        if img.isNull():
            logger.warn("discord-avatar: decoded image bytes were invalid")
            return None
        return _normalize_and_save(img, DISCORD_AVATAR_FILE, "discord-avatar")
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"discord-avatar: failed to save avatar: {exc}")
        return None


def discord_avatar_path() -> str | None:
    return DISCORD_AVATAR_FILE if os.path.exists(DISCORD_AVATAR_FILE) else None


def clear_discord_avatar() -> None:
    try:
        if os.path.exists(DISCORD_AVATAR_FILE):
            os.remove(DISCORD_AVATAR_FILE)
            logger.info("discord-avatar: removed cached avatar")
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"discord-avatar: failed to remove avatar: {exc}")


# --- Display name / handle --------------------------------------------------

def get_handle() -> str:
    return str(_load().get("handle") or "").strip()


def set_handle(name: str) -> None:
    state = _load()
    state["handle"] = str(name).strip()
    _save(state)
    logger.info(f"state: handle set to {name!r}")


# --- Discord verification session ------------------------------------------

def discord_session() -> dict | None:
    """Persisted Discord identity snapshot, or None when not verified."""
    return _load().get("discord")


def set_discord_session(data: dict | None) -> None:
    state = _load()
    if data is None:
        state.pop("discord", None)
    else:
        state["discord"] = data
    _save(state)
    logger.info("state: discord session updated")
