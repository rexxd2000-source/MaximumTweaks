"""Maximum Tweaks global configuration and path helpers."""
from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

APP_NAME = "Maximum Tweaks"
APP_VERSION = "2.4.3"
APP_TAGLINE = "Detect -> Analyze -> Recommend -> Optimize -> Measure -> Revert"
ENGINE_NAME = "Maximum Engine"
BOT_NAME = "Maximum"

# AI provider keys: env var first, else a <KEY>.txt file placed next to the
# exe after install. Secrets are never embedded in the frozen EXE.
def _load_secret(name: str) -> str:
    token = os.environ.get(name, "").strip()
    if token:
        return token
    try:  # e.g. GEMINI_API_KEY.txt next to the exe
        exe_dir = Path(sys.executable).resolve().parent
        side = exe_dir / (name + ".txt")
        if side.is_file():
            return side.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


# AI Assistant providers. Keys are loaded by _load_secret; with none set the
# assistant falls back to the built-in offline demo router.
GROQ_API_KEY = _load_secret("GROQ_API_KEY")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"

# Gemini free tier (key at https://aistudio.google.com/apikey), used when set.
GEMINI_API_KEY = _load_secret("GEMINI_API_KEY")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_MODEL = "gemini-3.5-flash"

# Cerebras free tier (cloud.cerebras.ai); used first, Gemini/Groq fall back.
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

# Read from the GITHUB_TOKEN env var only; never embedded in the EXE. Public
# repos need no token for update checks.
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
    """Current Windows account/PC username, sanitized for display."""
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
    dir that is wiped on exit, so ROOT resolves to the folder holding the exe —
    that is where Logs/ and data/ persist.
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
    "maxlog": ROOT / "maxlog",
    "logs": ROOT / "Logs",
    "assets": _assets_dir(),
    "config": ROOT / "config",
    "reports": ROOT / "reports",
}

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
    "dashboard": "\u25c8",
    "search": "\u2315",
    "windows": "\u26fa",
    "system": "\u2699",
    "cpu": "\u2b22",
    "gpu": "\u25c6",
    "ram": "\u2588",
    "storage": "\u25b6",
    "network": "\u2637",
    "input": "\u21a8",
    "mouse": "\u21a8",
    "keyboard": "\u2328",
    "aim": "\u2694",
    "performance": "\u26a1",
    "games": "\u2605",
    "fortnite": "\u25c9",
    "tweaks": "\u2630",
    "gaming": "\u2605",
    "services": "\u2693",
    "power": "\u26a1",
    "tools": "\u26cf",
    "profiles": "\u2654",
    "reports": "\u2711",
    "logs": "\u2709",
    "shield": "\u26d1",
    "wrench": "\u26b8",
    "flag": "\u2691",
    "settings": "\u2699",
}

ADMIN_NOTE = (
    "This operation requires administrator privileges. "
    "Maximum Tweaks will ask Windows to relaunch itself elevated."
)

# Official community invite link (enables the Join button / sidebar).
DISCORD_INVITE_URL = "https://discord.gg/CFeTWgGdU"


# License activation (the only access control). A key binds to a device via
# the license backend; sessions persist across reboots and updates.
LICENSE_API_URL = "https://maximumtweaks.onrender.com"


