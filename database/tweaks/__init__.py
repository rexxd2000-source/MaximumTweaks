"""Tweak store: imports every category module and merges its tweaks."""
from __future__ import annotations

import importlib
import pkgutil

from ._base import SAFE_ID

TWEAKS = []
CATEGORIES = {}
BY_ID = {}

for _mod in pkgutil.iter_modules(__path__):
    _name = _mod.name
    if _name.startswith("_"):
        continue
    _m = importlib.import_module(f"{__name__}.{_name}")
    _list = getattr(_m, "TWEAKS", None)
    if _list is None:
        continue
    _cat = getattr(_m, "CATEGORY", _name)
    CATEGORIES[_cat] = _name
    for _t in _list:
        _t["module"] = _name
        if not SAFE_ID.match(_t["id"]):
            raise ValueError(f"Unsafe tweak id {_t['id']!r}")
        if _t["id"] in BY_ID:
            raise ValueError(f"Duplicate tweak id {_t['id']!r}")
        BY_ID[_t["id"]] = _t
        TWEAKS.append(_t)

# Guidance-only tweaks (every action is "guidance") are informational: they are
# never auto-applied and get their own badge instead of a recommendation level.
for _t in TWEAKS:
    if all(_a[0] == "guidance" for _a in _t["actions"]):
        _t["guidance"] = True
        _t["recommended"] = "guide"

# Laptop-only tweaks get their own top-level category so hardware categories
# never mix in laptop-specific content.  Guidance tweaks keep their original
# module category so they appear alongside the actionable tweaks they relate to.
_LAPTOP_EXTRA_IDS = {"start-013"}  # dGPU preload tweak (hybrid-graphics only)


def _is_laptop(_t) -> bool:
    if _t.get("when", {}).get("laptop"):
        return True
    _tags = set(_t.get("tags") or [])
    if _tags & {"laptop", "hybrid", "lid"}:
        return True
    return _t["id"] in _LAPTOP_EXTRA_IDS


for _t in TWEAKS:
    if _is_laptop(_t):
        _t["category"] = "Laptop"

TWEAKS.sort(key=lambda t: t["category"])
CATEGORIES["Laptop"] = "laptop"

# Merge per-tweak validation metadata (status/evidence/target/verdict),
# compute registry conflicts and gate Apply-All on the results.
import importlib  # noqa: E402
validation = importlib.import_module("database.validation")
validation.apply(TWEAKS)
