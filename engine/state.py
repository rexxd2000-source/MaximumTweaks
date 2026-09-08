"""Track which tweaks have been applied so they can be reverted and counted."""
from __future__ import annotations

import json
import os
import shutil
import threading
import time

from rexlog import logger
from config.app_config import ROOT


def _state_dir() -> str:
    """Return the persistent state directory.

    In frozen builds, use %APPDATA%/MaximumTweaks so state survives exe
    relocation and version upgrades.  In dev, use <project>/data/.
    """
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        return os.path.join(appdata, "MaximumTweaks", "data")
    return os.path.join(str(ROOT), "data")


import sys  # noqa: E402


STATE_DIR = _state_dir()
STATE_FILE = os.path.join(STATE_DIR, "state.json")

# Legacy path next to the exe — migrate on first run.
_LEGACY_STATE = os.path.join(str(ROOT), "data", "state.json")


def _migrate_legacy_state() -> None:
    """Move state.json from the old exe-relative path to %APPDATA% if needed."""
    if os.path.isfile(_LEGACY_STATE) and not os.path.isfile(STATE_FILE):
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            shutil.move(_LEGACY_STATE, STATE_FILE)
            logger.info(f"state: migrated legacy state from {_LEGACY_STATE}")
        except Exception as exc:
            logger.warn(f"state: failed to migrate legacy state: {exc}")

# Thread safety: protect _CACHE and file writes from concurrent access.
_LOCK = threading.Lock()

# In-memory copy of state.json. State only ever changes through _save(), so
# the file is read once and served from here afterwards. Without this cache
# the UI's O(N^2) loops re-read the file hundreds of thousands of times and
# freeze the app at startup (window shows "Not Responding" for ~15s).
_CACHE: dict | None = None


def _load() -> dict:
    global _CACHE
    with _LOCK:
        if _CACHE is None:
            _migrate_legacy_state()
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


def _save(state: dict) -> bool:
    """Persist state.json atomically. Returns True on success."""
    global _CACHE
    with _LOCK:
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2)
            os.replace(tmp, STATE_FILE)  # atomic on the same volume
            _CACHE = state
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error(f"state: FAILED to write {STATE_FILE}: {exc} "
                         f"(state changes will not survive this session)")
            return False


def applied_ids() -> set[str]:
    return set(_load().get("applied", {}))


def mark_applied(tweak_id: str) -> bool:
    state = _load()
    state.setdefault("applied", {})[tweak_id] = time.strftime("%Y-%m-%d %H:%M")
    ok = _save(state)
    logger.info(f"state: recorded applied tweak {tweak_id} (saved={ok})")
    return ok


def unmark_applied(tweak_id: str) -> bool:
    state = _load()
    state.get("applied", {}).pop(tweak_id, None)
    ok = _save(state)
    logger.info(f"state: removed applied tweak {tweak_id} (saved={ok})")
    return ok


def applied_at(tweak_id: str) -> str | None:
    return _load().get("applied", {}).get(tweak_id)


def is_applied(tweak_id: str) -> bool:
    return tweak_id in _load().get("applied", {})


# --- Disabled (user-reverted) tweaks -------------------------------------
# Kept so cards can visually stay in the red "DISABLED" state after a revert,
# even after the page rebuilds its widgets.

def disabled_ids() -> set[str]:
    return set(_load().get("disabled", {}))


def mark_disabled(tweak_id: str) -> bool:
    state = _load()
    state.setdefault("disabled", {})[tweak_id] = time.strftime("%Y-%m-%d %H:%M")
    ok = _save(state)
    logger.info(f"state: marked tweak {tweak_id} as disabled (saved={ok})")
    return ok


def unmark_disabled(tweak_id: str) -> bool:
    state = _load()
    state.get("disabled", {}).pop(tweak_id, None)
    ok = _save(state)
    logger.info(f"state: removed disabled mark {tweak_id} (saved={ok})")
    return ok


# --- Registry value backups (exact revert) --------------------------------
# Recorded *before* a tweak writes each registry value, so Revert can restore
# the true previous value (or delete a value that did not exist before) instead
# of blindly writing a hardcoded "default".  Per tweak:
#   {target_key: {"hive","path","name","existed", "vtype","data"}}
# ``existed`` False means the value was absent before the tweak ran -> revert
# must delete it.  ``vtype``/``data`` are the raw REG_* type and data string.

def get_reg_backups(tweak_id: str) -> dict | None:
    return _load().get("reg_backups", {}).get(tweak_id)


def save_reg_backups(tweak_id: str, entries: dict) -> bool:
    state = _load()
    state.setdefault("reg_backups", {})[tweak_id] = entries
    ok = _save(state)
    logger.info(f"state: recorded {len(entries)} reg backups for {tweak_id} (saved={ok})")
    return ok


def clear_reg_backups(tweak_id: str) -> bool:
    state = _load()
    state.get("reg_backups", {}).pop(tweak_id, None)
    ok = _save(state)
    logger.info(f"state: cleared reg backups for {tweak_id} (saved={ok})")
    return ok


def reg_backup_ids() -> set[str]:
    return set(_load().get("reg_backups", {}))


# --- File / ini value backups (exact revert) ------------------------------
# ``file`` writes and ``ini`` edits overwrite existing content; the original
# value is snapshotted before apply so Revert restores the user's real previous
# state instead of the hardcoded revert list. Per tweak:
#   file_backups {normpath_lower: {"kind","path","existed","content"}}
#   ini_backups  {path|section|key_lower: {"kind","path","section","key",
#                                           "existed","value"}}

def get_file_backups(tweak_id: str) -> dict | None:
    return _load().get("file_backups", {}).get(tweak_id)


def save_file_backups(tweak_id: str, entries: dict) -> bool:
    state = _load()
    state.setdefault("file_backups", {})[tweak_id] = entries
    ok = _save(state)
    logger.info(f"state: recorded {len(entries)} file backups for {tweak_id} (saved={ok})")
    return ok


def clear_file_backups(tweak_id: str) -> bool:
    state = _load()
    state.get("file_backups", {}).pop(tweak_id, None)
    ok = _save(state)
    logger.info(f"state: cleared file backups for {tweak_id} (saved={ok})")
    return ok


def file_backup_ids() -> set[str]:
    return set(_load().get("file_backups", {}))


def get_ini_backups(tweak_id: str) -> dict | None:
    return _load().get("ini_backups", {}).get(tweak_id)


def save_ini_backups(tweak_id: str, entries: dict) -> bool:
    state = _load()
    state.setdefault("ini_backups", {})[tweak_id] = entries
    ok = _save(state)
    logger.info(f"state: recorded {len(entries)} ini backups for {tweak_id} (saved={ok})")
    return ok


def clear_ini_backups(tweak_id: str) -> bool:
    state = _load()
    state.get("ini_backups", {}).pop(tweak_id, None)
    ok = _save(state)
    logger.info(f"state: cleared ini backups for {tweak_id} (saved={ok})")
    return ok


def ini_backup_ids() -> set[str]:
    return set(_load().get("ini_backups", {}))


# --- Power setting backups (exact revert) ---------------------------------
# Recorded *before* a tweak writes each power setting, so Revert restores
# the true previous value instead of a hardcoded opposite.
# Per tweak: {key: {"setting", "scheme", "subgroup", "guid", "value"}}

def get_power_backups(tweak_id: str) -> dict | None:
    return _load().get("power_backups", {}).get(tweak_id)


def save_power_backups(tweak_id: str, entries: dict) -> bool:
    state = _load()
    state.setdefault("power_backups", {})[tweak_id] = entries
    ok = _save(state)
    logger.info(f"state: recorded {len(entries)} power backups for {tweak_id} (saved={ok})")
    return ok


def clear_power_backups(tweak_id: str) -> bool:
    state = _load()
    state.get("power_backups", {}).pop(tweak_id, None)
    ok = _save(state)
    logger.info(f"state: cleared power backups for {tweak_id} (saved={ok})")
    return ok


# --- Service backup (exact revert) ----------------------------------------
# Per tweak: {svc_name: {"name", "start_type"}}

def get_svc_backups(tweak_id: str) -> dict | None:
    return _load().get("svc_backups", {}).get(tweak_id)


def save_svc_backups(tweak_id: str, entries: dict) -> bool:
    state = _load()
    state.setdefault("svc_backups", {})[tweak_id] = entries
    ok = _save(state)
    logger.info(f"state: recorded {len(entries)} svc backups for {tweak_id} (saved={ok})")
    return ok


def clear_svc_backups(tweak_id: str) -> bool:
    state = _load()
    state.get("svc_backups", {}).pop(tweak_id, None)
    ok = _save(state)
    logger.info(f"state: cleared svc backups for {tweak_id} (saved={ok})")
    return ok


# --- cmd backups (exact revert for parseable commands) --------------------
# Per tweak: {cmd_hash: {"kind", ...parsed fields...}}
# kind is one of: powercfg_setactive, powercfg_value, powercfg_change,
#   powercfg_hibernate, bcdedit, netsh, reg_cmd, powerscheme_delete

def get_cmd_backups(tweak_id: str) -> dict | None:
    return _load().get("cmd_backups", {}).get(tweak_id)


def save_cmd_backups(tweak_id: str, entries: dict) -> bool:
    state = _load()
    state.setdefault("cmd_backups", {})[tweak_id] = entries
    ok = _save(state)
    logger.info(f"state: recorded {len(entries)} cmd backups for {tweak_id} (saved={ok})")
    return ok


def clear_cmd_backups(tweak_id: str) -> bool:
    state = _load()
    state.get("cmd_backups", {}).pop(tweak_id, None)
    ok = _save(state)
    logger.info(f"state: cleared cmd backups for {tweak_id} (saved={ok})")
    return ok


# --- Powerscheme backup (exact revert) ------------------------------------
# Per tweak: {"active_scheme": guid_or_alias, "created_schemes": [guids],
#             "deleted_schemes": [{"guid": ..., "name": ...}]}

def get_powerscheme_backups(tweak_id: str) -> dict | None:
    return _load().get("powerscheme_backups", {}).get(tweak_id)


def save_powerscheme_backups(tweak_id: str, entries: dict) -> bool:
    state = _load()
    state.setdefault("powerscheme_backups", {})[tweak_id] = entries
    ok = _save(state)
    logger.info(f"state: recorded powerscheme backup for {tweak_id} (saved={ok})")
    return ok


def clear_powerscheme_backups(tweak_id: str) -> bool:
    state = _load()
    state.get("powerscheme_backups", {}).pop(tweak_id, None)
    ok = _save(state)
    logger.info(f"state: cleared powerscheme backup for {tweak_id} (saved={ok})")
    return ok


# --- Scheduled task backup (exact revert) ---------------------------------
# Per tweak: {task_name: {"task", "was_enabled"}}

def get_sched_backups(tweak_id: str) -> dict | None:
    return _load().get("sched_backups", {}).get(tweak_id)


def save_sched_backups(tweak_id: str, entries: dict) -> bool:
    state = _load()
    state.setdefault("sched_backups", {})[tweak_id] = entries
    ok = _save(state)
    logger.info(f"state: recorded {len(entries)} sched backups for {tweak_id} (saved={ok})")
    return ok


def clear_sched_backups(tweak_id: str) -> bool:
    state = _load()
    state.get("sched_backups", {}).pop(tweak_id, None)
    ok = _save(state)
    logger.info(f"state: cleared sched backups for {tweak_id} (saved={ok})")
    return ok


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


def recompute_restart_required() -> None:
    """Re-derive the restart flag from the currently applied tweaks.

    Set while any applied tweak carries a ``reboot`` tag, otherwise clear.
    Called after every apply/revert so reverting a reboot-tagged tweak never
    leaves a stale "restart required" flag behind.
    """
    from database import BY_ID  # deferred: avoids import cycle
    needs = any(
        "reboot" in (BY_ID.get(tid) or {}).get("tags", [])
        for tid in applied_ids())
    if needs:
        set_restart_required(True)
    else:
        clear_restart_required()


# --- Ultra Mode (dashboard quick-toggle) -------------------------------

def get_ultra_mode() -> bool:
    return bool(_load().get("ultra_mode"))


def set_ultra_mode(on: bool) -> None:
    state = _load()
    state["ultra_mode"] = bool(on)
    _save(state)
    logger.info(f"state: ultra mode = {bool(on)}")


# --- User profile picture (PFP) --------------------------------------------

PFP_FILE = os.path.join(STATE_DIR, "pfp.png")


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


# --- Display name / handle --------------------------------------------------

def get_handle() -> str:
    return str(_load().get("handle") or "").strip()


def set_handle(name: str) -> None:
    state = _load()
    state["handle"] = str(name).strip()
    _save(state)
    logger.info(f"state: handle set to {name!r}")


# --- GPU Vendor Selection (for GPU category filter) -------------------------

def get_gpu_selection() -> str | None:
    """Persisted GPU vendor selection: 'nvidia', 'amd', or 'integrated'."""
    return _load().get("gpu_selection")


def set_gpu_selection(vendor: str | None) -> None:
    state = _load()
    if vendor is None:
        state.pop("gpu_selection", None)
    else:
        state["gpu_selection"] = vendor
    _save(state)
    logger.info(f"state: gpu selection set to {vendor!r}")


# --- License session --------------------------------------------------------

def license_session() -> dict | None:
    """Persisted license session snapshot (token, owner, device), or None."""
    return _load().get("license")


def set_license_session(data: dict | None) -> None:
    state = _load()
    if data is None:
        state.pop("license", None)
    else:
        state["license"] = data
    _save(state)
    logger.info("state: license session updated")
