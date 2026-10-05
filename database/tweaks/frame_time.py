"""Category: Frame Time — consistency and stutter analysis."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Frame Time", win_default="7,8,10,11")
CATEGORY = "Frame Time"

TWEAKS = validate_module("frame_time", [
])
