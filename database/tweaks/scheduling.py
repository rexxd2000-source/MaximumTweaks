"""Category: Scheduling — superseded.

The reaper "CPU & Scheduling" tweak set is shipped verbatim in the CPU
category module (database/tweaks/cpu.py).  This module is intentionally
empty so no additional scheduling tweaks appear in the CPU section.
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Scheduling", win_default="7,8,10,11")

CATEGORY = "Scheduling"

TWEAKS = validate_module("scheduling", [])