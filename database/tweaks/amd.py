"""Category: AMD — Radeon driver and AMD Software guidance."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("AMD", win_default="7,8,10,11")
CATEGORY = "AMD"

TWEAKS = validate_module("amd", [
])
