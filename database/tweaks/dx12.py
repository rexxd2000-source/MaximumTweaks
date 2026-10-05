"""Category: DirectX 12 — modern graphics pipeline notes and toggles."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("DirectX 12", win_default="10,11")
CATEGORY = "DirectX 12"
_ALL_GPU = {"gpu": ["nvidia", "amd", "intel"]}

TWEAKS = validate_module("dx12", [
])
