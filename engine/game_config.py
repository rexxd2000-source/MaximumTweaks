"""Game configuration reader/writer for per-game fine-tuning.

Handles reading/writing game-specific config files (e.g. Fortnite's
GameUserSettings.ini) so users can fine-tune resolution, FPS, rendering
mode, audio, and Reflex settings from within Maximum Tweaks.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from rexlog import logger


class GameConfig:
    """Base class for game-specific config parsing."""

    GAME_ID: str = ""
    NAME: str = ""
    SETTINGS: dict[str, dict] = {}

    @classmethod
    def find_config(cls) -> Path | None:
        return None

    @classmethod
    def read(cls) -> dict:
        return {}

    @classmethod
    def write(cls, values: dict) -> dict:
        return {"ok": True, "applied": [], "failed": []}


class FortniteConfig(GameConfig):
    """Fortnite GameUserSettings.ini parser/writer."""

    GAME_ID = "gp-001"
    NAME = "Fortnite"
    SETTINGS = {
        "resolution_w": {"label": "Width", "kind": "int", "default": 1920},
        "resolution_h": {"label": "Height", "kind": "int", "default": 1080},
        "fps_limit": {"label": "FPS Limit", "kind": "enum",
                      "options": ["Uncapped", "60", "120", "144", "165",
                                  "240", "360"]},
        "rendering_mode": {"label": "Rendering Mode", "kind": "enum",
                           "options": ["Performance Mode", "DirectX 11",
                                       "DirectX 12"]},
        "audio_quality": {"label": "Audio Quality", "kind": "enum",
                          "options": ["Low", "Medium", "High"]},
        "reflex": {"label": "Reflex Low Latency", "kind": "enum",
                   "options": ["Off", "On", "On + Boost"]},
        "fullscreen_opts": {"label": "Disable Fullscreen Optimizations",
                            "kind": "bool", "default": False},
        "run_admin": {"label": "Run as Administrator", "kind": "bool",
                      "default": False},
    }

    @classmethod
    def find_config(cls) -> Path | None:
        """Locate Fortnite's GameUserSettings.ini."""
        candidates = [
            Path.home() / "AppData/Local/FortniteGame/Saved/Config/WindowsClient",
            Path.home() / "AppData/Local/FortniteGame/Saved/Config/WindowsNoEditor",
        ]
        # Also scan other drives.
        import string
        for letter in string.ascii_uppercase:
            root = Path(f"{letter}:/")
            if not root.exists():
                continue
            candidates.append(
                root / "Program Files/Epic Games/Fortnite/FortniteGame/"
                "Saved/Config/WindowsClient")
        for d in candidates:
            ini = d / "GameUserSettings.ini"
            if ini.exists():
                return ini
        return None

    @classmethod
    def _parse_ini(cls, path: Path) -> dict[str, dict[str, str]]:
        """Parse an Unreal-style .ini into {section: {key: value}}."""
        sections: dict[str, dict[str, str]] = {}
        current = ""
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith(";") or line.startswith("#"):
                continue
            m = re.match(r"^\[(.+)\]\s*$", line)
            if m:
                current = m.group(1).strip()
                if current not in sections:
                    sections[current] = {}
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                sections.setdefault(current, {})[k.strip()] = v.strip()
        return sections

    @classmethod
    def read(cls) -> dict:
        ini_path = cls.find_config()
        if ini_path is None:
            return {k: s.get("default", "") for k, s in cls.SETTINGS.items()}
        try:
            sections = cls._parse_ini(ini_path)
        except Exception:
            return {k: s.get("default", "") for k, s in cls.SETTINGS.items()}
        # Fortnite uses [/Script/FortniteGame.FortGameUserSettings] as main section
        game = sections.get("/Script/FortniteGame.FortGameUserSettings", {})
        scalability = sections.get("ScalabilityGroups", {})
        result = {}
        result["resolution_w"] = game.get("ResolutionSizeX", "1920")
        result["resolution_h"] = game.get("ResolutionSizeY", "1080")
        fps_raw = game.get("FrameRateLimit", "0.000000")
        try:
            fps_val = int(float(fps_raw))
        except (ValueError, TypeError):
            fps_val = 0
        fps_map = {0: "Uncapped", 60: "60", 120: "120", 144: "144",
                   165: "165", 240: "240", 360: "360"}
        result["fps_limit"] = fps_map.get(fps_val, str(fps_val))
        # Rendering mode: Fortnite doesn't have an explicit DX12 flag in config.
        # FullscreenMode: 0=Windowed Fullscreen (Performance), 1=Windowed, 2=Fullscreen
        # The actual rendering mode (Perf/DX11/DX12) is set in-game.
        fullscreen_mode = game.get("FullscreenMode", "0")
        if fullscreen_mode == "2":
            result["rendering_mode"] = "DirectX 11"  # Fullscreen mode is typically DX11
        else:
            result["rendering_mode"] = "Performance Mode"  # Windowed Fullscreen
        # Audio quality from AudioQualityLevel (0=Low, 1=Medium, 2=High)
        aq = game.get("AudioQualityLevel", "0")
        aq_map = {"0": "Low", "1": "Medium", "2": "High"}
        result["audio_quality"] = aq_map.get(aq, "High")
        # Reflex: look for bLatencyTweak1 (0=Off, 1=On, 2=On+Boost)
        reflex_raw = game.get("bLatencyTweak1", "0")
        if isinstance(reflex_raw, str) and reflex_raw.lower() == "true":
            reflex_raw = "1"
        elif isinstance(reflex_raw, str) and reflex_raw.lower() == "false":
            reflex_raw = "0"
        reflex_map = {"0": "Off", "1": "On", "2": "On + Boost"}
        result["reflex"] = reflex_map.get(reflex_raw, "Off")
        # Fullscreen optimizations: not directly exposed in Fortnite config
        result["fullscreen_opts"] = False
        result["run_admin"] = False
        return result

    @classmethod
    def write(cls, values: dict) -> dict:
        ini_path = cls.find_config()
        if ini_path is None:
            return {"ok": False, "applied": [], "failed": ["Config file not found"]}
        report = {"ok": True, "applied": [], "failed": []}
        try:
            text = ini_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return {"ok": False, "applied": [], "failed": [str(exc)]}

        # Fortnite uses [/Script/FortniteGame.FortGameUserSettings] as main section
        FORTNITE_SECTION = "/Script/FortniteGame.FortGameUserSettings"

        def _set(section: str, key: str, val: str):
            nonlocal text
            pattern = rf"^(\s*{re.escape(key)}\s*=\s*)(.+)$"
            repl = rf"\g<1>{val}"
            sec_pat = rf"^\[{re.escape(section)}\]"
            in_sec = False
            new_lines = []
            for line in text.splitlines():
                if re.match(sec_pat, line.strip()):
                    in_sec = True
                if in_sec and re.match(pattern, line, re.IGNORECASE):
                    line = re.sub(pattern, repl, line, flags=re.IGNORECASE)
                new_lines.append(line)
            text = "\n".join(new_lines)

        # Resolution.
        w = str(values.get("resolution_w", "1920"))
        h = str(values.get("resolution_h", "1080"))
        _set(FORTNITE_SECTION, "ResolutionSizeX", w)
        _set(FORTNITE_SECTION, "ResolutionSizeY", h)
        report["applied"].append(f"Resolution {w}x{h}")

        # FPS limit.
        fps_map = {"Uncapped": "0.000000", "60": "60.000000",
                    "120": "120.000000", "144": "144.000000",
                    "165": "165.000000", "240": "240.000000",
                    "360": "360.000000"}
        fps_val = fps_map.get(values.get("fps_limit", "Uncapped"), "0.000000")
        _set(FORTNITE_SECTION, "FrameRateLimit", fps_val)
        report["applied"].append(f"FPS limit {values.get('fps_limit', 'Uncapped')}")

        # Rendering mode: Fortnite uses FullscreenMode (0=Windowed Fullscreen, 2=Fullscreen)
        # The actual rendering mode (Perf/DX11/DX12) is set in-game, not in config.
        mode = values.get("rendering_mode", "Performance Mode")
        if mode == "DirectX 11":
            _set(FORTNITE_SECTION, "FullscreenMode", "2")
        else:  # Performance Mode or DirectX 12 -> Windowed Fullscreen
            _set(FORTNITE_SECTION, "FullscreenMode", "0")
        report["applied"].append(f"Rendering mode {mode}")

        # Audio quality.
        aq_map = {"Low": "0", "Medium": "1", "High": "2"}
        aq_val = aq_map.get(values.get("audio_quality", "High"), "2")
        _set(FORTNITE_SECTION, "AudioQualityLevel", aq_val)
        report["applied"].append(f"Audio quality {values.get('audio_quality', 'High')}")

        # Reflex.
        reflex_map = {"Off": "0", "On": "1", "On + Boost": "2"}
        reflex_val = reflex_map.get(values.get("reflex", "Off"), "0")
        _set(FORTNITE_SECTION, "bLatencyTweak1", reflex_val)
        report["applied"].append(f"Reflex {values.get('reflex', 'Off')}")

        # Fullscreen optimizations: not directly exposed in Fortnite config
        report["applied"].append("Fullscreen optimizations (set in-game)")

        try:
            ini_path.write_text(text, encoding="utf-8")
        except Exception as exc:
            report["ok"] = False
            report["failed"].append(str(exc))

        return report


# Registry of supported game configs.
CONFIGS: dict[str, type[GameConfig]] = {
    "gp-001": FortniteConfig,
}


# ---------------- low-level ini helpers ----------------

_INI_KV = re.compile(r"^(?P<key>[^=;]+?)\s*=\s*(?P<value>.*?)\s*$")
_INI_SECTION = re.compile(r"^\s*\[(?P<section>.+)\]\s*$")


def read_ini_value(path: str, section: str, key: str) -> str | None:
    """Read one ``key=value`` from an ini file (None if not found)."""
    path = os.path.expandvars(os.path.expanduser(path))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    target = section.strip().lower()
    cur = None
    for raw in lines:
        line = raw.strip()
        m = _INI_SECTION.match(line)
        if m:
            cur = m.group("section").strip().lower()
            continue
        if cur != target or not line or line.startswith((";", "#")):
            continue
        kv = _INI_KV.match(line)
        if kv and kv.group("key").strip().lower() == key.strip().lower():
            return kv.group("value").strip()
    return None


def set_ini_value(path: str, section: str, key: str, value: str) -> tuple[bool, str]:
    """Set ``key=value`` under ``[section]`` in an ini file.

    Missing sections and keys are inserted; existing lines are updated in
    place. Returns (ok, detail). Used by the ``ini`` action kind.
    """
    path = os.path.expandvars(os.path.expanduser(path))
    target = section.strip()
    target_low = target.lower()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        else:
            text = ""
        out = []
        cur = None
        found_sec = False
        matched = False
        for line in text.splitlines():
            m = _INI_SECTION.match(line)
            if m:
                if cur is not None and cur.lower() == target_low and not matched:
                    out.append(f"{key}={value}")
                    matched = True
                cur = m.group("section").strip()
                if cur.lower() == target_low:
                    found_sec = True
                out.append(line)
                continue
            if cur is not None and cur.lower() == target_low and not line.startswith((";", "#")):
                kv = _INI_KV.match(line.strip())
                if kv and kv.group("key").strip().lower() == key.strip().lower():
                    out.append(f"{key}={value}")
                    matched = True
                    continue
            out.append(line)
        if cur is not None and cur.lower() == target_low and not matched:
            out.append(f"{key}={value}")
            matched = True
        if not found_sec:
            if text and not text.endswith("\n"):
                out.append("")
            out.append(f"[{target}]")
            out.append(f"{key}={value}")
            matched = True
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
        from engine import state_checker  # deferred: avoids import cycle
        state_checker.invalidate_ini(path)
        return True, f"{key}={value} in {os.path.basename(path)}"
    except OSError as exc:
        return False, str(exc)


def delete_ini_value(path: str, section: str, key: str) -> tuple[bool, str]:
    """Remove ``key=value`` from ``[section]`` in an ini file.

    Idempotent: succeeds even if the key is already absent (the game then
    falls back to its built-in default). Returns (ok, detail). Used by the
    ``inidel`` action kind as the clean revert for ``ini`` tweaks.
    """
    path = os.path.expandvars(os.path.expanduser(path))
    target_low = section.strip().lower()
    key_low = key.strip().lower()
    try:
        if not os.path.exists(path):
            return True, f"{key} not present (nothing to remove)"
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        out = []
        cur = None
        removed = False
        for line in text.splitlines():
            m = _INI_SECTION.match(line)
            if m:
                cur = m.group("section").strip().lower()
                out.append(line)
                continue
            if cur == target_low and not line.startswith((";", "#")):
                kv = _INI_KV.match(line.strip())
                if kv and kv.group("key").strip().lower() == key_low:
                    removed = True
                    continue
            out.append(line)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
        from engine import state_checker  # deferred: avoids import cycle
        state_checker.invalidate_ini(path)
        return True, f"{key} removed from {os.path.basename(path)}" if removed \
            else f"{key} not present (nothing to remove)"
    except OSError as exc:
        return False, str(exc)


def get_config(game_id: str) -> type[GameConfig] | None:
    return CONFIGS.get(game_id)


def read_game_config(game_id: str) -> dict:
    cfg = get_config(game_id)
    if cfg is None:
        return {}
    return cfg.read()


def write_game_config(game_id: str, values: dict) -> dict:
    cfg = get_config(game_id)
    if cfg is None:
        return {"ok": False, "applied": [], "failed": ["No config support for this game"]}
    return cfg.write(values)
