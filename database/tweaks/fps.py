"""Category: FPS — frame rate guidance and measurement."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("FPS", win_default="7,8,10,11")
CATEGORY = "FPS"

TWEAKS = validate_module("fps", [
])
