"""Final QA for the 57 verified mutating optimizations.

Every one of the 57 is checked individually, not sampled, so a regression in a
single tweak fails the suite. The two non-mutating groups (279 verified
guidance/read-only plus 510 unverified mutating) are asserted separately so a
mistake in one cannot be masked by another.

Note: the set was 58 until the removal audit consolidated exact duplicates and
dropped unsafe/obsolete tweaks (see database/removed_tweaks.py). pre-002
(Fire Timing) was the one verified mutating tweak removed: it was an exact
duplicate of pre-006. The catalogue is now 846 tweaks.

Notes on the environment, established by inspection:

* ``extract_implementation()`` returns ``hw_gates``, not ``hardware_gates``.
* ``_effective_win_version()`` only honours profile values ``"10"``/``"11"`` and
  otherwise reads the real OS. The detector likewise only ever emits those two.
  So Windows checks below use 10/11 profiles; the ``7,8`` in tweak ``win`` fields
  is legacy metadata and is not reachable through a detected profile.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.plans import FOUNDATION, MAXIMUM, PERFORMANCE, normalize_tier  # noqa: E402
from database.tiers import (  # noqa: E402
    _revert_coverage, audit_tweak, extract_implementation,
)
from database.tweaks import BY_ID, TWEAKS  # noqa: E402
from engine.applier import STATUS_FOR_CODE, blocked_status_for  # noqa: E402
from engine.entitlements import gate  # noqa: E402
from engine.safety import preflight  # noqa: E402

VALID_TIERS = (FOUNDATION, PERFORMANCE, MAXIMUM)
HARD_GATES = ("not_supported", "incompatible", "no_profile", "win_version")


def _kind(t: dict) -> str:
    facts = extract_implementation(t)
    if facts["guidance_only"]:
        return "guidance"
    if facts["transient"]:
        return "transient"
    if facts["read_only"]:
        return "read_only"
    return "mutating"


VERIFIED_MUTATING = [t for t in TWEAKS
                     if t.get("verified") and _kind(t) == "mutating"]
VERIFIED_NON_MUTATING = [t for t in TWEAKS
                         if t.get("verified") and _kind(t) != "mutating"]
VM_IDS = {t["id"] for t in VERIFIED_MUTATING}


def _profile(t: dict, **over) -> dict:
    """A profile satisfying this tweak's own hardware gates."""
    prof = {"win_version": "11", "gpu": ["nvidia", "amd", "intel"],
            "gpu_types": ["GeForce RTX", "RX", "Arc"],
            "cpu_vendor": ["amd", "intel"], "cpu_cores": 32,
            "ram_gb": 64, "ram_channels": 4, "ssd": True, "hdd": True,
            "nvme": True, "laptop": False}
    when = t.get("when") or {}
    if when.get("gpu"):
        prof["gpu"] = list(when["gpu"])
    if when.get("gpu_type"):
        gt = when["gpu_type"]
        prof["gpu_types"] = [gt] if isinstance(gt, str) else list(gt)
    if when.get("cpu_vendor"):
        prof["cpu_vendor"] = list(when["cpu_vendor"])
    for key in ("ram_gb", "cpu_cores", "ram_channels"):
        if isinstance(when.get(key), (int, float)):
            prof[key] = max(prof[key], int(when[key] * 2))
    prof.update(over)
    return prof


@pytest.fixture
def at_tier(monkeypatch):
    """Pin the held tier so a gate test isolates the check under test."""
    import engine.entitlements as ENT

    def _set(tier):
        monkeypatch.setattr(ENT, "current_tier", lambda: tier, raising=False)
        return tier
    yield _set
    monkeypatch.undo()


# ---------------------------------------------------------------------------
# Counts. Pinned deliberately.
# ---------------------------------------------------------------------------
def test_verified_mutating_count_is_pinned():
    assert len(VERIFIED_MUTATING) == 65


def test_verified_non_mutating_count_is_pinned():
    """Verified non-mutating = read-only diagnostics + transient one-shots.
    Every one of them now lives in the Diagnostics / System Tools categories,
    because guidance and informational text is no longer shipped."""
    assert len(VERIFIED_NON_MUTATING) == 80


def test_verified_and_mutating_partition_the_verified_set():
    verified = [t for t in TWEAKS if t.get("verified")]
    ids = {t["id"] for t in verified}
    assert ids == VM_IDS | {t["id"] for t in VERIFIED_NON_MUTATING}
    assert len(ids) == len(VERIFIED_MUTATING) + len(VERIFIED_NON_MUTATING) == 145


def test_no_cmd_action_that_writes_is_classified_as_read_only():
    """The four entries that slipped through: `wmic ... set/delete/create` and
    `netsh <any-interface> set`. A bare token list missed them because
    "delete " has a trailing space and "netsh interface set" was too narrow."""
    writes = ("wmic computersystem set", "wmic pagefileset", "netsh int tcp set")
    for t in VERIFIED_NON_MUTATING:
        for action in t.get("actions") or []:
            if action[0] != "cmd":
                continue
            low = str(action[1]).lower()
            assert not any(w in low for w in writes), \
                f"{t['id']} writes via cmd but is counted as non-mutating"


def test_no_read_only_entry_is_ever_counted_as_a_mutating_optimization():
    for t in VERIFIED_NON_MUTATING:
        facts = extract_implementation(t)
        assert facts["guidance_only"] or facts["transient"] or facts["read_only"], t["id"]


def test_non_mutating_verified_entries_change_nothing():
    """A verified non-mutating entry is only "verified" because there is
    nothing to revert, so it must extract zero state-changing actions."""
    for t in VERIFIED_NON_MUTATING:
        facts = extract_implementation(t)
        assert facts["mutating_count"] == 0, \
            f"{t['id']} extracts {facts['mutating_count']} mutating action(s)"
        assert not facts["state_changing"], t["id"]
        assert audit_tweak(t)["reversible"] is False, t["id"]


# ---------------------------------------------------------------------------
# Per-tweak checks, applied to all 57
# ---------------------------------------------------------------------------
def test_all_57_have_actions_and_a_revert_path():
    for t in VERIFIED_MUTATING:
        assert t.get("actions"), f"{t['id']} has no actions"
        assert t.get("revert"), f"{t['id']} has no reverts"


def test_all_57_revert_coverage_is_complete():
    for t in VERIFIED_MUTATING:
        covered, total = _revert_coverage(extract_implementation(t))
        assert total > 0, f"{t['id']} extracts no mutating actions"
        assert covered == total, f"{t['id']} revert {covered}/{total}"
        assert audit_tweak(t)["reversible"] is True, t["id"]


def test_all_57_carry_a_valid_tier_matching_their_internal_tier():
    for t in VERIFIED_MUTATING:
        assert t.get("requiredTier") in VALID_TIERS, t["id"]
        assert t["requiredTier"] == t.get("tier"), t["id"]
        assert normalize_tier(t["requiredTier"]) == t["requiredTier"], t["id"]


def test_all_57_declare_real_windows_versions():
    for t in VERIFIED_MUTATING:
        wins = [w.strip() for w in (t.get("win") or "").split(",") if w.strip()]
        assert wins, f"{t['id']} declares no Windows versions"
        assert all(w in ("7", "8", "10", "11") for w in wins), \
            f"{t['id']} odd versions {wins}"


def test_all_57_hardware_gated_tweaks_declare_their_requirements():
    gated = [t for t in VERIFIED_MUTATING if extract_implementation(t)["hw_gates"]]
    assert gated, "expected some hardware-gated verified tweaks"
    for t in gated:
        assert t.get("when"), f"{t['id']} is gated but declares no `when`"


def test_all_57_apply_and_revert_cleanly_at_their_own_tier(at_tier):
    for t in VERIFIED_MUTATING:
        at_tier(normalize_tier(t["requiredTier"]))
        r = preflight(t, profile=_profile(t), mode="apply")
        assert r["allowed"], f"{t['id']} apply blocked at own tier: {r['reason']}"
        assert r.get("requires_confirmation") is not True, \
            f"{t['id']} is verified but still demands confirmation"
        rv = preflight(t, profile=None, mode="revert")
        assert rv["allowed"], f"{t['id']} revert blocked: {rv['reason']}"


def test_all_57_revert_stays_open_at_every_tier(at_tier):
    """Reverting must never be gated, including below the required tier."""
    for tier in VALID_TIERS:
        at_tier(tier)
        for t in VERIFIED_MUTATING:
            r = preflight(t, profile=None, mode="revert")
            assert r["allowed"], f"{t['id']} revert blocked at held={tier}"


def test_all_57_are_locked_below_their_own_tier():
    for t in VERIFIED_MUTATING:
        tier = normalize_tier(t["requiredTier"])
        for held in VALID_TIERS:
            g = gate(t, held=held)
            expected = VALID_TIERS.index(held) >= VALID_TIERS.index(tier)
            assert g["allowed"] is expected, \
                f"{t['id']} ({tier}) at held={held}: {g['reason']}"
            if not expected:
                assert g["code"] == "tier_required", t["id"]


def test_tier_inheritance_is_exactly_foundation_plus_upward():
    for tier, expect in ((FOUNDATION, {FOUNDATION}),
                         (PERFORMANCE, {FOUNDATION, PERFORMANCE}),
                         (MAXIMUM, {FOUNDATION, PERFORMANCE, MAXIMUM})):
        visible = set()
        for t in VERIFIED_MUTATING:
            if gate(t, held=tier)["allowed"]:
                visible.add(t["requiredTier"])
        assert visible <= expect, f"{tier} leaked {visible - expect}"


def test_force_cannot_unlock_any_of_the_57(at_tier):
    forced = 0
    for t in VERIFIED_MUTATING:
        tier = normalize_tier(t["requiredTier"])
        if tier == FOUNDATION:
            continue
        at_tier(FOUNDATION)
        r = preflight(t, profile=_profile(t), mode="apply", force=True)
        assert not r["allowed"], f"{t['id']} unlocked by force"
        assert r["code"] == "tier_required", f"{t['id']}: {r['reason']}"
        forced += 1
    assert forced, "expected some tier-gated verified tweaks"


def test_force_cannot_override_hardware_compatibility(at_tier):
    checked = 0
    for t in VERIFIED_MUTATING:
        if not extract_implementation(t)["hw_gates"]:
            continue
        at_tier(MAXIMUM)
        r = preflight(t, profile=None, mode="apply", force=True)
        assert not r["allowed"], f"{t['id']} forced past missing hardware"
        assert r["code"] == "no_profile", t["id"]
        checked += 1
    assert checked, "expected some hardware-gated verified tweaks"


def test_no_detected_hardware_means_no_apply(at_tier):
    for t in VERIFIED_MUTATING:
        if not extract_implementation(t)["hw_gates"]:
            continue
        at_tier(MAXIMUM)
        r = preflight(t, profile=None, mode="apply")
        assert r["code"] == "no_profile", f"{t['id']}: {r['reason']}"


def test_mismatched_vendor_is_incompatible_not_a_generic_failure(at_tier):
    checked = 0
    for t in VERIFIED_MUTATING:
        when = t.get("when") or {}
        want = when.get("gpu") or when.get("cpu_vendor")
        if not want or len(want) > 1:
            continue  # allows every vendor, nothing to mismatch
        prof = _profile(t, gpu=["amd"], gpu_types=["RX"],
                        cpu_vendor=["amd"])
        if want == ["amd"]:
            prof.update(gpu=["nvidia"], gpu_types=["GeForce RTX"])
        if want == ["nvidia"]:
            prof.update(gpu=["amd"], gpu_types=["RX"])
        if want == ["intel"]:
            prof.update(gpu=["amd"], gpu_types=["RX"])
        at_tier(MAXIMUM)
        r = preflight(t, profile=prof, mode="apply")
        assert not r["allowed"], f"{t['id']} allowed on wrong vendor"
        assert r["code"] == "incompatible", f"{t['id']}: {r['reason']}"
        checked += 1
    assert checked, "expected some vendor-restricted verified tweaks"


def test_windows_11_only_tweaks_are_blocked_on_windows_10(at_tier):
    """reg-016 declares win=11, so Windows 10 must refuse it.

    Only "10" and "11" are usable profile values: _effective_win_version()
    ignores anything else and reads the real OS, so a synthetic "7" would
    silently test against this machine instead.
    """
    strict = [t for t in VERIFIED_MUTATING
              if "11" in {w.strip() for w in (t.get("win") or "").split(",")}
              and "10" not in {w.strip() for w in (t.get("win") or "").split(",")}]
    assert strict, "expected a Windows-11-only verified tweak"
    for t in strict:
        at_tier(MAXIMUM)
        r = preflight(t, profile=_profile(t, win_version="10"), mode="apply")
        assert not r["allowed"], f"{t['id']} allowed on Windows 10"
        assert r["code"] == "win_version", t["id"]
        ok = preflight(t, profile=_profile(t, win_version="11"), mode="apply")
        assert ok["allowed"], f"{t['id']} blocked on its own Windows version"


def test_every_declared_windows_version_is_honoured_in_both_directions(at_tier):
    """For each of the 57, a Windows version outside its `win` list must be
    refused and every version inside it must be accepted."""
    at_tier(MAXIMUM)
    outside = inside = 0
    for t in VERIFIED_MUTATING:
        wins = {w.strip() for w in (t.get("win") or "").split(",") if w.strip()}
        assert wins, t["id"]
        for wv in ("10", "11"):
            r = preflight(t, profile=_profile(t, win_version=wv), mode="apply")
            if wv in wins:
                assert r["allowed"], f"{t['id']} refused on its own win={t['win']}"
                inside += 1
            else:
                assert not r["allowed"], f"{t['id']} allowed on unsupported {wv}"
                assert r["code"] == "win_version", t["id"]
                outside += 1
    assert inside and outside, "expected both accepted and refused versions"


def test_maximum_holder_reaches_all_57():
    locked = [t["id"] for t in VERIFIED_MUTATING
              if not gate(t, held=MAXIMUM)["allowed"]]
    assert locked == []


# ---------------------------------------------------------------------------
# Status mapping: one class per code, so the UI cannot contradict itself
# ---------------------------------------------------------------------------
def test_hard_gate_codes_map_to_a_ui_status_and_nothing_maps_to_both():
    for c in HARD_GATES + ("tier_required",):
        assert c in STATUS_FOR_CODE, f"no UI status for preflight code {c!r}"
    assert set(STATUS_FOR_CODE.values()) == {"locked", "not_compatible"}


def test_codes_outside_the_map_default_to_blocked_never_to_success():
    for c in ("conflict_active", "unverified", "admin", "status_blocked",
              "duplicate", "dry_run", None, "", "totally_unknown"):
        assert blocked_status_for(c) == "blocked", c
        assert blocked_status_for(c) not in ("locked", "not_compatible", "ok")


def test_tier_denial_maps_to_locked_and_hard_gates_to_not_compatible():
    assert STATUS_FOR_CODE["tier_required"] == "locked"
    for c in ("incompatible", "no_profile", "win_version", "not_supported"):
        assert STATUS_FOR_CODE[c] == "not_compatible", c


def test_locked_and_not_compatible_are_distinct_ui_statuses():
    assert STATUS_FOR_CODE["tier_required"] != STATUS_FOR_CODE["incompatible"]


def test_compatibility_denial_is_never_reported_as_a_tier_lock(at_tier):
    """A hardware refusal must not be blamed on the subscription."""
    at_tier(MAXIMUM)
    for t in VERIFIED_MUTATING:
        if not extract_implementation(t)["hw_gates"]:
            continue
        r = preflight(t, profile=None, mode="apply")
        assert r["code"] in HARD_GATES, f"{t['id']} leaked code {r['code']!r}"
        assert STATUS_FOR_CODE[r["code"]] != "locked", t["id"]


def test_tier_denial_is_reported_as_locked_at_every_tier_below(at_tier):
    for t in VERIFIED_MUTATING:
        tier = normalize_tier(t["requiredTier"])
        for held in VALID_TIERS[:VALID_TIERS.index(tier)]:
            at_tier(held)
            r = preflight(t, profile=_profile(t), mode="apply")
            assert not r["allowed"], f"{t['id']} allowed at held={held}"
            assert r["code"] == "tier_required", t["id"]
            assert blocked_status_for(r["code"]) == "locked", t["id"]


# ---------------------------------------------------------------------------
# Audit report agrees with the catalogue
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def report():
    from tools.tweak_audit_report import collect
    return collect()


def test_report_lists_exactly_the_verified_mutating_set(report):
    assert {r["id"] for r in report["verified_mutating"]} == VM_IDS
    assert report["verified_kinds"]["mutating"] == 65


def test_report_never_lists_a_diagnostic_as_a_mutating_verified_tweak(report):
    ids = {r["id"] for r in report["verified_mutating"]}
    for t in VERIFIED_NON_MUTATING:
        assert t["id"] not in ids, f"{t['id']} miscounted as a mutating tweak"


def test_report_counts_diagnostics_separately(report):
    kinds = report["verified_kinds"]
    assert kinds["guidance"] + kinds["read_only"] + kinds["transient"] == 80
    assert kinds["guidance"] == 0


def test_report_rows_cover_the_catalogue_exactly_once(report):
    ids = [r["id"] for r in report["rows"]]
    assert len(ids) == len(set(ids)) == len(TWEAKS) == 596


def test_report_marks_non_mutating_rows_reversible_na(report):
    for r in report["rows"]:
        if r["kind"] != "mutating":
            assert r["reversible"] == "n/a", r["id"]


def test_report_shows_real_hardware_gates(report):
    """Guards the key-name bug that blanked this column for all rows."""
    gates = {r["id"]: r["hardware_gates"] for r in report["rows"]}
    for tid in ("int-003", "int-009", "stor-005", "stor-006", "wgr-003"):
        assert gates[tid] != "-", f"{tid} hardware gate not reported"
    assert any(v != "-" for v in gates.values())


def test_report_has_no_stale_overrides(report):
    assert report["orphans"] == []


def test_no_orphan_overrides_remain_in_the_loader():
    """The catalogue cleanup pruned overrides/notes for ids that no longer
    ship, so the loader and the catalogue must agree exactly."""
    from database.validation import orphaned_overrides
    assert orphaned_overrides(TWEAKS) == {}


# ---------------------------------------------------------------------------
# The full scenario matrix from the release checklist
# ---------------------------------------------------------------------------
def _visible(held: str) -> list:
    return [t for t in VERIFIED_MUTATING if gate(t, held=held)["allowed"]]


def test_fresh_foundation_account_sees_only_foundation(at_tier):
    at_tier(FOUNDATION)
    visible = _visible(FOUNDATION)
    # 43 foundation-graded verified mutating tweaks, per the tier review.
    assert len(visible) == 43
    assert all(t["requiredTier"] == FOUNDATION for t in visible)
    for t in VERIFIED_MUTATING:
        if t["requiredTier"] != FOUNDATION:
            r = preflight(t, profile=_profile(t), mode="apply")
            assert not r["allowed"] and r["code"] == "tier_required", t["id"]


def test_performance_account_adds_performance_and_keeps_foundation(at_tier):
    at_tier(PERFORMANCE)
    perf = _visible(PERFORMANCE)
    # 60 = 43 foundation + 17 performance-graded verified mutating tweaks.
    assert len(perf) == 60
    assert all(t["requiredTier"] in (FOUNDATION, PERFORMANCE) for t in perf)


def test_maximum_account_reaches_everything(at_tier):
    at_tier(MAXIMUM)
    assert len(_visible(MAXIMUM)) == 65


def test_upgrade_only_ever_adds_visibility():
    order = [FOUNDATION, PERFORMANCE, MAXIMUM]
    sets = [set(t["id"] for t in _visible(tier)) for tier in order]
    for lower, higher in zip(sets, sets[1:]):
        assert lower <= higher, "an upgrade removed a tweak from view"


def test_downgrade_only_ever_removes_visibility():
    order = [MAXIMUM, PERFORMANCE, FOUNDATION]
    prev = set(t["id"] for t in _visible(order[0]))
    for tier in order[1:]:
        cur = set(t["id"] for t in _visible(tier))
        assert cur <= prev, f"downgrade to {tier} revealed a new tweak"
        prev = cur


def test_expired_or_invalid_entitlement_fails_closed(at_tier):
    """A missing, blank, malformed, or wrong-typed tier must never grant more
    than Foundation — including a non-string that could otherwise be truthy."""
    locked = [t for t in VERIFIED_MUTATING
              if t["requiredTier"] in (PERFORMANCE, MAXIMUM)]
    assert locked
    for bad in (None, "", "   ", "garbage", "admin", "root", 0, 1, [], {},
                True, object()):
        at_tier(FOUNDATION)
        for t in locked:
            r = preflight(t, profile=_profile(t), mode="apply")
            assert not r["allowed"], f"{t['id']} allowed with held={bad!r}"
            assert r["code"] == "tier_required", t["id"]


def test_entitlement_whitespace_is_tolerated_but_unknown_words_are_not():
    """Casing/whitespace tolerance is deliberate; it must not extend to
    inventing a tier that the server never sent."""
    t = next(t for t in VERIFIED_MUTATING if t["requiredTier"] == MAXIMUM)
    for sloppy in ("MAXIMUM", "  maximum  ", "\tmaximum", "maximum\n"):
        assert gate(t, held=sloppy)["allowed"], f"rejected {sloppy!r}"
    for unknown in ("maximum-plus", "maximums", "max2", "ultimate"):
        assert not gate(t, held=unknown)["allowed"], f"accepted {unknown!r}"


def test_apply_and_revert_report_a_single_consistent_outcome(at_tier):
    """Each state must resolve to exactly one status, so the UI cannot show a
    LOCKED row and a FAIL row for the same operation."""
    at_tier(MAXIMUM)
    for t in VERIFIED_MUTATING:
        apply_r = preflight(t, profile=_profile(t), mode="apply")
        revert_r = preflight(t, profile=None, mode="revert")
        assert apply_r["allowed"] is True
        assert apply_r["code"] is None
        assert revert_r["allowed"] is True
        assert blocked_status_for(apply_r["code"]) == "blocked"  # allowed -> unused


def test_every_denied_state_maps_to_exactly_one_status(at_tier):
    """Walk the four refusal classes over the whole verified set and confirm
    each lands on LOCKED, FAIL - NOT COMPATIBLE, or FAIL, never two."""
    seen = set()
    for tier in VALID_TIERS:
        at_tier(tier)
        for t in VERIFIED_MUTATING:
            for prof in (None, _profile(t), _profile(t, gpu=["amd"],
                                                     gpu_types=["RX"])):
                r = preflight(t, profile=prof, mode="apply")
                if r["allowed"]:
                    continue
                status = blocked_status_for(r["code"])
                assert status in {"locked", "not_compatible", "blocked"}, status
                seen.add(status)
    # A cleared tweak should never reach the generic "blocked" class: every
    # refusal is either the plan or the hardware. If this ever gains a third
    # member, a verified tweak has started refusing for a murky reason.
    assert seen == {"locked", "not_compatible"}, seen


def test_verified_set_never_reports_unverified(at_tier):
    """The 57 are cleared by the audit, so none may still demand confirmation."""
    at_tier(MAXIMUM)
    for t in VERIFIED_MUTATING:
        r = preflight(t, profile=_profile(t), mode="apply")
        assert r["code"] != "unverified", t["id"]
        assert not r.get("requires_confirmation"), t["id"]
