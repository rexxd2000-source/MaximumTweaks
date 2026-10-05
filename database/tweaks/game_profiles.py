"""Category: Game Profiles — per-title guidance for popular competitive games."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Game Profiles", win_default="7,8,10,11")
CATEGORY = "Game Profiles"

TWEAKS = validate_module("game_profiles", [
])
