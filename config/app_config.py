"""Rex Tweaks global configuration and path helpers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Rex Tweaks"
APP_VERSION = "1.0.0"
APP_TAGLINE = "Detect -> Analyze -> Recommend -> Optimize -> Measure -> Revert"
ENGINE_NAME = "Rex Engine"

# Set to your repository URL to enable the "Open GitHub" button in the sidebar.
GITHUB_URL = "https://github.com/rexxd2000-source/RexTweaks"

# Repo owner/repo for update checks (used by build scripts/README only).
GITHUB_REPO = "rexxd2000-source/RexTweaks"

# ---- Live updater ----------------------------------------------------------
# The app checks for a "latest" GitHub Release (tag name doubles as the
# version, asset must be named exactly `UPDATE_EXE_NAME`) unless
# UPDATE_MANIFEST_URL points at a plain JSON manifest, which takes priority:
#     { "version": "1.1.0", "notes": "...", "url": ".../RexTweaks.exe" }
# Leave both empty to disable update checks entirely.
UPDATE_MANIFEST_URL = ""
UPDATE_EXE_NAME = "RexTweaks.exe"  # must match the build name in RexTweaks.spec

# Minimal supported Windows build (Win10 1903 / 19041+ preferred)
MIN_WIN_BUILD = 18362


def project_root() -> Path:
    """Absolute path to the RexTweaks package root (folder containing main.py).

    In a frozen (PyInstaller) build the source tree lives in a temp extraction
    dir that is wiped on exit, so ROOT resolves to the folder that holds the
    .exe — that is where Logs/ and data/ persist.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    here = Path(__file__).resolve().parent.parent  # config -> RexTweaks
    if here.name.lower() == "rextweaks":
        return here
    # Fallback: folder that contains this package
    return Path(__file__).resolve().parent.parent


ROOT = project_root()

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
    "assets": ROOT / "assets",
    "config": ROOT / "config",
    "reports": ROOT / "reports",
}

STATE_FILE = ROOT / "config" / "state.json"
DB_JSON_EXPORT = ROOT / "database" / "tweaks.json"
BACKUP_INDEX = ROOT / "backups" / "index.json"
LOG_FILE = ROOT / "Logs" / "rextweaks.log"

RISK_LEVELS = ("safe", "low", "moderate", "advanced")
IMPACT_LEVELS = ("very low", "low", "moderate", "high", "extreme")
REC_FLAGS = ("recommended", "optional", "experimental", "advanced", "not_recommended")
WINDOWS_VERSIONS = ("7", "8", "10", "11")

# Active theme values used by the UI.
THEME = {
    "accent": "#00F2FE",
    "accent2": "#94A3B8",
    "accent_hover": "#3CF4FF",
    "accent_press": "#00AEB8",
    "accent_dark": "#031518",
    "success": "#00F2FE",
    "green": "#00F2FE",
    "red": "#F87979",
    "amber": "#F0B54D",
    "orange": "#F0B54D",
    "purple": "#00F2FE",
    "info": "#00F2FE",
    "bg": "#090B0E",
    "bg_alt": "#0C0F13",
    "sidebar": "#07090B",
    "card": "#11141A",
    "card_alt": "#151A21",
    "card_hover": "#1A2029",
    "border": "#1D222A",
    "border_soft": "#171C23",
    "text": "#F2F5F9",
    "text_dim": "#94A3B8",
    "text_faint": "#5B6675",
    "danger": "#F87979",
    "warning": "#F0B54D",
    "glow_green": "rgba(0, 242, 254, 0.10)",
    "glow_red": "rgba(248, 121, 121, 0.08)",
    "glow_accent": "rgba(0, 242, 254, 0.10)",
    "glow": "rgba(0, 242, 254, 0.15)",
}


ICONS = {
    "dashboard": "\u25c8",   # ◆
    "search": "\u2315",      # ⌕
    "windows": "\u26fa",     # ⛺
    "system": "\u2699",      # ⚙
    "cpu": "\u2b22",         # ⬢
    "gpu": "\u25c6",         # ◆
    "ram": "\u2588",         # █
    "storage": "\u25b6",     # ▶
    "network": "\u2637",     # ☷
    "input": "\u21a8",       # ↨
    "mouse": "\u21a8",       # ↨
    "keyboard": "\u2328",    # ⌨
    "aim": "\u2694",         # ⚔
    "performance": "\u26a1", # ⚡
    "games": "\u2605",       # ★
    "fortnite": "\u25c9",    # ◉
    "tweaks": "\u2630",      # ☰
    "gaming": "\u2605",      # ★
    "services": "\u2693",    # ⚓
    "power": "\u26a1",       # ⚡
    "tools": "\u26cf",       # ⛏
    "profiles": "\u2654",    # ♔
    "reports": "\u2711",     # ✑
    "logs": "\u2709",        # ✉
    "shield": "\u26d1",      # ⛑
    "wrench": "\u26b8",      # ⚸
    "flag": "\u2691",        # ⚑
    "settings": "\u2699",    # ⚙
    "discord": "\u25c9",     # ◉
}

ADMIN_NOTE = (
    "This operation requires administrator privileges. "
    "Rex Tweaks will ask Windows to relaunch itself elevated."
)

# ---------------------------------------------------------------------------
# Discord identity verification.
#
# The desktop app never holds the Discord Client Secret. All OAuth2 plus the
# guild-membership / Verified-role checks happen inside the separate
# `auth_backend/` FastAPI service; the desktop only knows where that service
# lives and polls it for the result.
#     local dev:   http://127.0.0.1:8000
#     production:  https://your-auth-domain.example.com
# ---------------------------------------------------------------------------
AUTH_SERVER_URL = "http://127.0.0.1:8000"

# Discord CDN (used to fetch the user's avatar once identity is confirmed).
DISCORD_CDN = "https://cdn.discordapp.com"

# Official community invite link (enables the Join button / sidebar).
DISCORD_INVITE_URL = "https://discord.gg/NKnkgKzex"
