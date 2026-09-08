"""Maximum Tweaks global configuration and path helpers."""
from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

APP_NAME = "Maximum Tweaks"
APP_VERSION = "2.4.1"
APP_TAGLINE = "Detect -> Analyze -> Recommend -> Optimize -> Measure -> Revert"
ENGINE_NAME = "Maximum Engine"
BOT_NAME = "Maximum"

# ---- AI Assistant keys (env var, else <KEY>.txt next to the exe, else
# offline demo router) ------------------------------------------------------
# SECURITY: secrets are NEVER embedded in the frozen EXE. No client config
# file (_secrets.py or similar) is ever read, and nothing under sys._MEIPASS
# is consulted. Values come only from the process environment or a runtime
# sidecar file the operator places next to the exe AFTER install (that file
# is not shipped and cannot be extracted from the download).
def _load_secret(name: str) -> str:
    token = os.environ.get(name, "").strip()
    if token:
        return token
    try:  # drop a file named GEMINI_API_KEY.txt next to the exe (runtime-only)
        exe_dir = Path(sys.executable).resolve().parent
        side = exe_dir / (name + ".txt")
        if side.is_file():
            return side.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


# ---- AI Assistant (Groq) ---------------------------------------------------
# The Maximum chat bot calls Groq's OpenAI-compatible endpoint. Set the
# GROQ_API_KEY environment variable or _secrets.py (leave empty for the
# offline demo router).
GROQ_API_KEY = _load_secret("GROQ_API_KEY")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"

# ---- AI Assistant (Gemini fallback) ----------------------------------------
# Google's Gemini free tier (get a key at https://aistudio.google.com/apikey)
# has much higher daily limits than Groq, so it acts as the primary provider
# when set. Leave empty to use Groq only.
GEMINI_API_KEY = _load_secret("GEMINI_API_KEY")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_MODEL = "gemini-3.5-flash"

# ---- AI Assistant (Cerebras primary) ---------------------------------------
# Cerebras' free tier (no card, cloud.cerebras.ai) allows ~30 req/min and
# ~14,400 req/day — effectively unlimited for a personal assistant. OpenAI
# compatible; used first, Gemini/Groq act as automatic fallbacks.
CEREBRAS_API_KEY = _load_secret("CEREBRAS_API_KEY")
CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
CEREBRAS_MODEL = "gpt-oss-120b"

# Launch countdown target (local time). The dashboard shows a countdown to
# this moment; the update goes live here too.
LAUNCH_DATETIME = "2026-08-14 16:00:00"

# Set to your repository URL to enable the "Open GitHub" button in the sidebar.
GITHUB_URL = "https://github.com/rexxd2000-source/MaximumTweaks"

# Repo owner/repo for update checks (used by build scripts/README only).
GITHUB_REPO = "rexxd2000-source/MaximumTweaks"

# Update auth token: read from the GITHUB_TOKEN env var ONLY. It is never
# read from any file (_secrets.py or otherwise) and never embedded in the EXE,
# because a private/repo token must not be extractable by anyone who downloads
# the app. With a PUBLIC repo (the default) release reads/downloads work with
# no token at all; set GITHUB_TOKEN in the running environment only if you
# deliberately host updates on a PRIVATE repo.
def _load_github_token() -> str:
    return os.environ.get("GITHUB_TOKEN", "").strip()


GITHUB_TOKEN = _load_github_token()

# ---- Live updater ----------------------------------------------------------
# The app checks for a "latest" GitHub Release (tag name doubles as the
# version, asset must be named exactly `UPDATE_EXE_NAME`) unless
# UPDATE_MANIFEST_URL points at a plain JSON manifest, which takes priority:
#     { "version": "1.1.0", "notes": "...", "url": ".../MaximumTweaks.exe" }
# Leave both empty to disable update checks entirely.
UPDATE_MANIFEST_URL = ""
UPDATE_EXE_NAME = "MaximumTweaks.exe"  # must match the build name in MaximumTweaks.spec

# Minimal supported Windows build (Win10 1903 / 19041+ preferred)
MIN_WIN_BUILD = 18362


def current_windows_user() -> str:
    """The current Windows account/PC username, sanitized for display.

    Detected automatically (never hardcoded) so it works on every machine
    that runs the app. Falls back to a neutral label if it cannot resolve.
    """
    raw = ""
    try:
        raw = getpass.getuser()
    except Exception:  # noqa: BLE001
        raw = ""
    if not raw:
        raw = (os.environ.get("USERNAME") or "").strip()
    if not raw:
        raw = (os.environ.get("COMPUTERNAME") or "").strip()
    name = re.sub(r"[^\w .\-()@]+", " ", raw, flags=re.UNICODE).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:32] or "User"


def project_root() -> Path:
    """Absolute path to the MaximumTweaks package root (folder containing main.py).

    In a frozen (PyInstaller) build the source tree lives in a temp extraction
    dir that is wiped on exit, so ROOT resolves to the folder that holds the
    .exe Ã¢â‚¬â€ that is where Logs/ and data/ persist.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    here = Path(__file__).resolve().parent.parent  # config -> MaximumTweaks
    if here.name.lower() == "maximumtweaks":
        return here
    # Fallback: folder that contains this package
    return Path(__file__).resolve().parent.parent


ROOT = project_root()


def _assets_dir() -> Path:
    """Read-only artwork. In frozen builds the assets are bundled by the spec
    into the PyInstaller extraction dir (sys._MEIPASS), not next to the exe;
    in dev they live in the source tree."""
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        bundled = Path(meipass) / "assets"
        if bundled.is_dir():
            return bundled
    return ROOT / "assets"


DIRS = {
    "engine": ROOT / "engine",
    "ui": ROOT / "ui",
    "tweaks": ROOT / "tweaks",
    "database": ROOT / "database",
    "hardware": ROOT / "hardware",
    "recommendations": ROOT / "recommendations",
    "profiles": ROOT / "profiles",
    "tools": ROOT / "tools",
    "backups": ROOT / "backups",
    "rexlog": ROOT / "rexlog",
    "logs": ROOT / "Logs",
    "assets": _assets_dir(),
    "config": ROOT / "config",
    "reports": ROOT / "reports",
}

DB_JSON_EXPORT = ROOT / "database" / "tweaks.json"
BACKUP_INDEX = ROOT / "backups" / "index.json"
LOG_FILE = ROOT / "Logs" / "maximumtweaks.log"

RISK_LEVELS = ("safe", "low", "moderate", "advanced")
IMPACT_LEVELS = ("very low", "low", "moderate", "high", "extreme")
REC_FLAGS = ("recommended", "optional", "experimental", "advanced", "guide", "not_recommended")
WINDOWS_VERSIONS = ("7", "8", "10", "11")

# Active theme values used by the UI.
THEME = {
    "accent": "#8B6BFF",
    "accent2": "#C9C0FF",
    "accent_hover": "#9C80FF",
    "accent_press": "#6D4FE0",
    "accent_dark": "#0B0814",
    "success": "#3DDC97",
    "green": "#3DDC97",
    "red": "#FF6F6F",
    "amber": "#FFB454",
    "orange": "#FFB454",
    "purple": "#C9C0FF",
    "info": "#4BE8D8",
    "blue": "#6C93FF",
    "pink": "#E879C9",
    "cyan": "#4BE8D8",
    "bg": "#08060F",
    "bg_alt": "#0B0814",
    "sidebar": "#090711",
    "card": "#0C0A16",
    "card_alt": "#12101F",
    "card_hover": "#171428",
    "border": "#1D1B28",
    "border_soft": "#141120",
    "text": "#F6F4FC",
    "text_dim": "#928AAD",
    "text_faint": "#514A70",
    "danger": "#FF6F6F",
    "warning": "#FFB454",
    "glow_green": "rgba(61, 220, 151, 0.10)",
    "glow_red": "rgba(255, 111, 111, 0.08)",
    "glow_accent": "rgba(139, 107, 255, 0.10)",
    "glow": "rgba(139, 107, 255, 0.15)",
}


ICONS = {
    "dashboard": "\u25c8",   # Ã¢â€”â€ 
    "search": "\u2315",      # Ã¢Å’â€¢
    "windows": "\u26fa",     # Ã¢â€ºÂº
    "system": "\u2699",      # Ã¢Å¡â„¢
    "cpu": "\u2b22",         # Ã¢Â¬Â¢
    "gpu": "\u25c6",         # Ã¢â€”â€ 
    "ram": "\u2588",         # Ã¢â€“Ë†
    "storage": "\u25b6",     # Ã¢â€“Â¶
    "network": "\u2637",     # Ã¢ËœÂ·
    "input": "\u21a8",       # Ã¢â€ Â¨
    "mouse": "\u21a8",       # Ã¢â€ Â¨
    "keyboard": "\u2328",    # Ã¢Å’Â¨
    "aim": "\u2694",         # Ã¢Å¡â€
    "performance": "\u26a1", # Ã¢Å¡Â¡
    "games": "\u2605",       # Ã¢Ëœâ€¦
    "fortnite": "\u25c9",    # Ã¢â€”â€°
    "tweaks": "\u2630",      # Ã¢ËœÂ°
    "gaming": "\u2605",      # Ã¢Ëœâ€¦
    "services": "\u2693",    # Ã¢Å¡â€œ
    "power": "\u26a1",       # Ã¢Å¡Â¡
    "tools": "\u26cf",       # Ã¢â€ºÂ
    "profiles": "\u2654",    # Ã¢â„¢â€
    "reports": "\u2711",     # Ã¢Å“â€˜
    "logs": "\u2709",        # Ã¢Å“â€°
    "shield": "\u26d1",      # Ã¢â€ºâ€˜
    "wrench": "\u26b8",      # Ã¢Å¡Â¸
    "flag": "\u2691",        # Ã¢Å¡â€˜
    "settings": "\u2699",    # Ã¢Å¡â„¢
}

ADMIN_NOTE = (
    "This operation requires administrator privileges. "
    "Maximum Tweaks will ask Windows to relaunch itself elevated."
)

# Official community invite link (enables the Join button / sidebar).
DISCORD_INVITE_URL = "https://discord.gg/CFeTWgGdU"


# License activation (the ONLY access-control method for Maximum Tweaks).
#
# The desktop app sends the customer-entered key plus a hashed device
# fingerprint to the license backend and stores the resulting session locally.
# Once a key is activated it is bound to that PC and stays authorized across
# reboots and app updates — no re-entry, no token-clock logouts.
#     production:  https://maximumtweaks.onrender.com
# ---------------------------------------------------------------------------
LICENSE_API_URL = "https://maximumtweaks.onrender.com"
















