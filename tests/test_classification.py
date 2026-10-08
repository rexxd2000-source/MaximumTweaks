"""Tests for the tweak grade axis (database/classification.py).

The axis is the single source of truth for what a tweak is graded as; the
subscription plan is *derived* from it, never authored. These tests pin the
contract:

  * the axis is exactly FREE < FOUNDATION < MAXIMUM and maps onto the plans
    foundation / performance / maximum in that order
  * grades and plans are disjoint vocabularies that cannot be confused
  * the shipped grade is the reviewed one, for every optimization tweak, and the
    heuristic still agrees with the loader for anything unreviewed
  * the heuristic itself is unchanged, so review and machine opinion stay
    diffable
  * danger is decided by the implementation, not by the module or the name
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.plans import (  # noqa: E402
    FOUNDATION as PLAN_FOUNDATION,
    MAXIMUM as PLAN_MAXIMUM,
    PERFORMANCE as PLAN_PERFORMANCE,
)
from database.classification import (  # noqa: E402
    CLASSIFICATIONS, CLASSIFICATION_TO_TIER, FOUNDATION, FREE, GRADES, MAXIMUM,
    PLANS, PLAN_FOR_GRADE, classify_optimization, grade_optimization,
    normalize_grade, normalize_plan, reviewed_grade, tier_for,
)
from database.reviewed_tiers import REVIEWED_COUNTS, REVIEWED_GRADES  # noqa: E402
from database.tiers import extract_implementation  # noqa: E402
from database.tweaks import BY_ID, TWEAKS  # noqa: E402

NON_OPTIMIZATION = {"Diagnostics", "System Tools"}


def _optimization_tweaks() -> list[dict]:
    out = []
    for t in TWEAKS:
        if t.get("category") in NON_OPTIMIZATION:
            continue
        facts = extract_implementation(t)
        if facts["guidance_only"] or not facts["mutating_count"]:
            continue
        out.append(t)
    return out


# ---------------------------------------------------------------------------
# Axis contract
# ---------------------------------------------------------------------------
def test_axis_is_exactly_three_ordered_grades():
    assert CLASSIFICATIONS == (FREE, FOUNDATION, MAXIMUM)
    assert GRADES is CLASSIFICATIONS


def test_maps_onto_plans_in_order():
    assert CLASSIFICATION_TO_TIER == {
        FREE: PLAN_FOUNDATION,
        FOUNDATION: PLAN_PERFORMANCE,
        MAXIMUM: PLAN_MAXIMUM,
    }
    assert PLAN_FOR_GRADE is CLASSIFICATION_TO_TIER


def test_tier_for_round_trips_every_grade():
    plans = {tier_for(cls) for cls in CLASSIFICATIONS}
    assert plans == {PLAN_FOUNDATION, PLAN_PERFORMANCE, PLAN_MAXIMUM}
    assert len(plans) == len(CLASSIFICATIONS)  # injective: no two grades share a plan
    # Unknown input fails closed to the lowest paid plan, never to a wild tier.
    assert tier_for("UNKNOWN-GRADE") == PLAN_FOUNDATION


def test_grades_and_plans_are_disjoint_vocabularies():
    """The whole reason the axis exists: a grade must never be mistakable for
    a plan, so 'FOUNDATION' the grade is not 'foundation' the plan -- and no
    normalizer may quietly translate one into the other."""
    assert PLANS == (PLAN_FOUNDATION, PLAN_PERFORMANCE, PLAN_MAXIMUM)
    assert not set(GRADES) & set(PLANS)  # disjoint: case included
    # Only 'foundation'/'maximum' are spelled alike in both vocabularies, and
    # only case tells them apart. 'free' (grade) and 'performance' (plan) are
    # different words entirely -- which is exactly why the mapping has to be an
    # explicit table rather than a case change.
    assert {g.lower() for g in GRADES} & set(PLANS) == {"foundation", "maximum"}
    assert "free" not in PLANS and "performance" not in GRADES
    assert PLAN_FOR_GRADE[FREE] == PLAN_FOUNDATION
    assert PLAN_FOR_GRADE[FOUNDATION] == PLAN_PERFORMANCE
    # A grade token resolves as a grade.
    for g in GRADES:
        assert normalize_grade(g) == g
        assert normalize_grade(f"  {g}  ") == g  # whitespace only
    # A plan token is NOT a grade. This is case-sensitive on purpose: the grade
    # ids are the plan ids uppercased, so folding case here would let
    # 'foundation' (a plan) resolve as 'FOUNDATION' (a grade).
    for p in PLANS:
        assert normalize_grade(p) is None, p
        assert normalize_grade(f"  {p} ") is None, p
    assert normalize_grade("performance") is None
    assert normalize_grade("PERFORMANCE") is None
    assert normalize_grade("max") is None
    # ...and the shared word resolves the right way through each normalizer.
    assert normalize_grade("FREE") == FREE
    assert normalize_plan("FREE") == PLAN_FOUNDATION
    assert normalize_plan("FOUNDATION") == PLAN_FOUNDATION  # a plan input
    assert normalize_plan("MAXIMUM") == PLAN_MAXIMUM  # a plan input
    assert normalize_grade("foundation") is None  # not a grade input


def test_normalize_grade_rejects_junk_instead_of_guessing():
    for junk in (None, "", "   ", 42, [], {}, True, object(),
                 "ENTERPRISE", "MAXIMUM_PLUS", "free-ish"):
        assert normalize_grade(junk) is None, junk


# ---------------------------------------------------------------------------
# The reviewed sheet is the source of truth for shipped grades
# ---------------------------------------------------------------------------
def test_review_covers_every_optimization_tweak_exactly_once():
    opt = _optimization_tweaks()
    ids = [t["id"] for t in opt]
    assert len(ids) == 499
    assert len(set(ids)) == 499
    assert set(REVIEWED_GRADES) == set(ids)


def test_review_grades_are_all_valid_and_the_tally_is_honest():
    assert all(g in CLASSIFICATIONS for g in REVIEWED_GRADES.values())
    assert REVIEWED_COUNTS == dict(Counter(REVIEWED_GRADES.values()))
    assert set(REVIEWED_COUNTS) == set(CLASSIFICATIONS)
    assert sum(REVIEWED_COUNTS.values()) == 499


def test_shipped_grade_is_the_reviewed_grade_for_every_optimization_tweak():
    for t in _optimization_tweaks():
        facts = extract_implementation(t)
        grade, reason = grade_optimization(facts, t)
        assert grade == REVIEWED_GRADES[t["id"]], t["id"]
        assert t["classification"] == grade, t["id"]
        assert "reviewed" in reason.lower(), (t["id"], reason)
        # The plan is still derived from the grade, never reviewed separately.
        assert t["requiredTier"] == tier_for(grade) == PLAN_FOR_GRADE[grade], t["id"]


def test_diagnostics_and_tools_are_not_tier_reviewed_and_keep_the_heuristic():
    """The review only covered applyable optimizations; diagnostics and system
    tools must fall back to the heuristic rather than inherit a stale grade."""
    unreviewed = [t for t in TWEAKS if t.get("category") in NON_OPTIMIZATION]
    assert unreviewed
    for t in unreviewed:
        assert reviewed_grade(t["id"]) is None, t["id"]
        facts = extract_implementation(t)
        assert t["classification"] == classify_optimization(facts, t)[0], t["id"]


def test_reviewed_grade_lookup_fails_closed_for_unknown_ids():
    for junk in (None, "", "   ", 42, [], {}, True, object(), "not-a-real-id"):
        assert reviewed_grade(junk) is None, junk


def test_heuristic_differs_from_review_on_a_known_bounded_set():
    """Review is allowed to overrule the heuristic, but the disagreement is
    pinned so a wholesale drift (a broken import, a bad CSV) is loud."""
    disagreements = []
    for t in _optimization_tweaks():
        facts = extract_implementation(t)
        if grade_optimization(facts, t)[0] != classify_optimization(facts, t)[0]:
            disagreements.append(t["id"])
    # 169: the 2026-10-08 duplicate consolidation removed 16 reviewed tweaks
    # (two of them disagreed), dropping the pin from 171.
    assert len(disagreements) == 169
    assert "nv-001" in disagreements and "lap-001" in disagreements


# ---------------------------------------------------------------------------
# Grades are deterministic and grounded in the implementation
# ---------------------------------------------------------------------------
def test_classification_matches_what_the_loader_stamped():
    for t in TWEAKS:
        facts = extract_implementation(t)
        cls, _ = grade_optimization(facts, t)
        assert cls == t.get("classification"), t["id"]
        assert cls in CLASSIFICATIONS, t["id"]


def test_every_tweak_carries_a_grade_and_a_derived_tier():
    for t in TWEAKS:
        assert t.get("classification") in CLASSIFICATIONS, t["id"]
        assert t["requiredTier"] == tier_for(t["classification"]), t["id"]
        # `tier` is the internal alias; the two never diverge.
        assert t["tier"] == t["requiredTier"], t["id"]


def test_the_whole_catalogue_is_properly_distributed():
    grades = {t["id"]: t["classification"] for t in TWEAKS}
    assert set(grades.values()) <= set(CLASSIFICATIONS)
    assert any(v == FREE for v in grades.values())
    assert any(v == FOUNDATION for v in grades.values())
    assert any(v == MAXIMUM for v in grades.values())


# ---------------------------------------------------------------------------
# Danger follows the implementation, not the module or the name
# ---------------------------------------------------------------------------
def test_vendor_tuning_classifies_maximum_regardless_of_module():
    """nvidia-smi driver control is a MAXIMUM change even though the module is
    called "NVIDIA" and carries a benign-sounding name."""
    for tid in ("nv-001", "nv-002"):
        t = BY_ID[tid]
        cls, reason = classify_optimization(extract_implementation(t), t)
        assert cls == MAXIMUM, (tid, reason)


def test_registry_policy_cleanup_is_not_a_cheat_just_because_of_the_module():
    """aim/delay_destroyer tweaks that merely clear a registry policy value are
    FREE/FOUNDATION grades; 'aim' in the module name is not an aimbot signal."""
    for tid in ("aim-002", "dd-001"):
        t = BY_ID[tid]
        facts = extract_implementation(t)
        cls, reason = classify_optimization(facts, t)
        assert cls in (FREE, FOUNDATION), (tid, reason)


def test_critical_service_disable_never_ships_as_free():
    """Cards must not disable critical Windows repair/update services (WaaSMedicSvc,
    wuauserv, usosvc, Windefend)."""
    from database.tweaks import TWEAKS
    critical = {"waasmedicsvc", "wuauserv", "usosvc", "windefend"}
    for t in TWEAKS:
        tid = t["id"]
        for a in t.get("actions") or []:
            if not isinstance(a, (tuple, list)) or len(a) <= 1:
                continue
            kind = str(a[0])
            svc = ""
            if kind in ("svc", "svcstop") and len(a) > 1:
                svc = str(a[1])
            if kind == "sc" and len(a) >= 3:
                svc = str(a[2])
            if svc and svc.lower() in critical:
                cls, _ = grade_optimization(extract_implementation(t), t)
                assert cls != FREE, (tid, svc)


def test_confirmed_risky_always_lands_in_maximum():
    for t in TWEAKS:
        if t.get("confirm"):
            facts = extract_implementation(t)
            cls, reason = classify_optimization(facts, t)
            assert cls == MAXIMUM, (t["id"], reason)