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

# Read-only diagnostics and one-shot tools (reports, scans, health checks, GUI
# launchers, adapter/DNS resets, ...) are grouped under Diagnostics / System
# Tools so optimization categories only ever hold tweaks that actually change
# the machine.  Nothing is dropped here - the tweak keeps its id, actions,
# revert path and tier; only the category it is filed under changes.
_DIAGNOSTIC_IDS = frozenset({
    "audio-033", "audio-034", "bios-001", "db-014", "diag-010",
    "diag-new-001", "diag-new-002", "diag-new-003", "diag-new-004",
    "diag-new-005", "dx-001", "dx-003", "eth-012", "eth-013", "expl-014",
    "fpsb-026", "gpu-047", "gpu-048", "mon-003", "mon-014", "mouse-055",
    "mouse-056", "mouse-057", "mouse-058", "net-014",
    "net-015", "net-016", "net-new-001", "net-new-002", "perf-new-001",
    "ram-012", "rep-001", "rep-002", "rep-003", "rep-004", "rep-007",
    "rep-008", "rep-009", "rep-013", "rep-014", "sec-009", "start-001",
    "stor-008", "stor-009", "stor-010", "stor-011", "sys-008", "usb-003",
    "usb-004", "usb-012", "wifi-004", "wifi-008", "wifi-012",
})

_SYSTEM_TOOL_IDS = frozenset({
    "expl-014", "gpu-048", "mouse-055", "mouse-056", "mouse-057",
    "mouse-058",
})

for _t in TWEAKS:
    if _t["id"] in _DIAGNOSTIC_IDS:
        _t["category"] = "System Tools" if _t["id"] in _SYSTEM_TOOL_IDS else "Diagnostics"

# Laptop-only tweaks get their own top-level category so hardware categories
# never mix in laptop-specific content.  Guidance tweaks keep their original
# module category so they appear alongside the actionable tweaks they relate to.
_LAPTOP_EXTRA_IDS = {"start-013"}  # dGPU preload tweak (hybrid-graphics only)


def _is_laptop(_t) -> bool:
    if _t["id"] in _DIAGNOSTIC_IDS:
        return False
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

# Assign a grade (FREE / FOUNDATION / MAXIMUM), derive the required
# subscription tier from it, and attach a verification verdict to every tweak.
# The grade is `classification.grade_optimization`: the reviewed tier-review
# sheet (database/reviewed_tiers.py) is the source of truth, with the
# implementation-derived heuristic as the fallback for anything unreviewed.
# The `requiredTier` the store exposes is the *plan* that unlocks the tweak,
# derived from the *grade* by one fixed mapping (FREE->foundation,
# FOUNDATION->performance, MAXIMUM->maximum). `tier` stays as the internal
# alias of `requiredTier` so existing classifier code and tests keep working;
# both are always written together from the same value and never diverge.
tiers = importlib.import_module("database.tiers")
classification = importlib.import_module("database.classification")
audit_data = importlib.import_module("database.audit_data")
for _t in TWEAKS:
    _facts = tiers.extract_implementation(_t)
    _t["classification"], _t["class_reason"] = \
        classification.grade_optimization(_facts, _t)
    _t["requiredTier"] = classification.tier_for(_t["classification"])
    _t["tier"] = _t["requiredTier"]
    _t["tier_reason"] = _t["class_reason"]
    _t["verified"], _t["verify_reason"] = tiers.assess_verification(_facts, _t)
    _t["disposition"] = tiers.audit_tweak(_t)["disposition"]
    _rec = audit_data.DECISIONS.get(_t["id"], {})
    _t["decision"] = _rec.get("decision", "KEEP")
    _t["decision_reason"] = _rec.get("reason", "")
    _t["canonical"] = _rec.get("canonical") or None
del _t, _facts
