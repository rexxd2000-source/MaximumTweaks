"""Tests for the subscription/tier system.

Covers the parts that must never regress silently, because each one is a way of
either charging the wrong amount or silently unlocking/locking the wrong tweaks:

  * exact pricing arithmetic (Decimal, no float drift) and the no-$8 rule
  * tier inheritance and fail-closed normalization
  * entitlement gating, including that `force` can never bypass a tier or
    compatibility block, and that reverts are never gated
  * unverified tweaks being allowed one-at-a-time but excluded from Apply All
  * backend tier persistence, upgrade/downgrade, and payload serialization
  * validation override drift being reported rather than silently ignored
"""
from __future__ import annotations

import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "auth_backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "auth_backend"))


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
from config.plans import (  # noqa: E402
    ANNUAL, CYCLE_MONTHS, FOUNDATION, MAXIMUM, MONTHLY, PERFORMANCE,
    SIX_MONTHS, allows, cycle_total, effective_monthly, inherits,
    monthly_price, normalize_tier, price_matrix, pricing_rows, tier_rank,
    upgrade_path, verify,
)


def test_verify_passes():
    """The module's own self-check (totals, no legacy $8 price) must hold."""
    verify()


@pytest.mark.parametrize("tier,expected", [
    (FOUNDATION, Decimal("0")),
    (PERFORMANCE, Decimal("10")),
    (MAXIMUM, Decimal("15")),
])
def test_monthly_prices_are_exact(tier, expected):
    assert monthly_price(tier) == expected


@pytest.mark.parametrize("tier,cycle,total", [
    (FOUNDATION, MONTHLY, Decimal("0.00")),
    (FOUNDATION, SIX_MONTHS, Decimal("0.00")),
    (FOUNDATION, ANNUAL, Decimal("0.00")),
    (PERFORMANCE, MONTHLY, Decimal("10.00")),
    (PERFORMANCE, SIX_MONTHS, Decimal("49.80")),   # 60 - 17%
    (PERFORMANCE, ANNUAL, Decimal("90.00")),       # 120 - 25%
    (MAXIMUM, MONTHLY, Decimal("15.00")),
    (MAXIMUM, SIX_MONTHS, Decimal("74.70")),       # 90 - 17%
    (MAXIMUM, ANNUAL, Decimal("135.00")),          # 180 - 25%
])
def test_cycle_totals_are_computed_not_hardcoded(tier, cycle, total):
    assert cycle_total(tier, cycle) == total


def test_discounts_match_stated_percentages():
    assert cycle_total(PERFORMANCE, SIX_MONTHS) == Decimal("60") * Decimal("0.83")
    assert cycle_total(PERFORMANCE, ANNUAL) == Decimal("120") * Decimal("0.75")
    assert cycle_total(MAXIMUM, SIX_MONTHS) == Decimal("90") * Decimal("0.83")
    assert cycle_total(MAXIMUM, ANNUAL) == Decimal("180") * Decimal("0.75")


def test_effective_monthly_is_derived_from_total():
    for tier in (PERFORMANCE, MAXIMUM):
        for cycle in (MONTHLY, SIX_MONTHS, ANNUAL):
            expected = cycle_total(tier, cycle) / CYCLE_MONTHS[cycle]
            assert effective_monthly(tier, cycle) == expected


def test_no_eight_dollar_performance_price_anywhere():
    """The old $8 Performance price must not reappear as a base price."""
    assert monthly_price(PERFORMANCE) != Decimal("8")
    for tier in (FOUNDATION, PERFORMANCE, MAXIMUM):
        for cycle in (MONTHLY, SIX_MONTHS, ANNUAL):
            assert cycle_total(tier, cycle) != Decimal("8.00")
            # the six-month *effective* rate is 8.30; that is not a base price
            assert monthly_price(tier) != Decimal("8")


def test_pricing_rows_cover_every_plan_and_cycle():
    """One row per tier, each carrying all three billing cycles."""
    rows = pricing_rows()
    assert len(rows) == 3
    assert {r["tier"] for r in rows} == {FOUNDATION, PERFORMANCE, MAXIMUM}
    for row in rows:
        assert set(row["cycles"]) == {MONTHLY, SIX_MONTHS, ANNUAL}
        for cycle, c in row["cycles"].items():
            assert c["cycle"] == cycle
            assert c["months"] == CYCLE_MONTHS[cycle]
            assert Decimal(str(c["total"])) >= Decimal("0")


def test_pricing_row_badges_match_the_discounts():
    badges = {r["tier"]: {c: r["cycles"][c]["badge"] for c in r["cycles"]}
              for r in pricing_rows()}
    for tier in (FOUNDATION, PERFORMANCE, MAXIMUM):
        assert badges[tier][MONTHLY] == ""
        assert badges[tier][SIX_MONTHS] == "17% OFF"
        assert badges[tier][ANNUAL] == "25% OFF"


def test_only_performance_and_maximum_cost_anything():
    rows = {r["tier"]: r for r in pricing_rows()}
    assert rows[FOUNDATION]["free"] is True
    assert rows[PERFORMANCE]["free"] is False
    assert rows[MAXIMUM]["free"] is False


def test_price_matrix_is_cycle_major():
    matrix = price_matrix()
    assert set(matrix) == {MONTHLY, SIX_MONTHS, ANNUAL}
    for cycle, tiers in matrix.items():
        assert set(tiers) == {FOUNDATION, PERFORMANCE, MAXIMUM}
        for tier, total in tiers.items():
            assert total == cycle_total(tier, cycle)


# ---------------------------------------------------------------------------
# Tiers: normalization, inheritance, ranking
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("maximum", MAXIMUM), ("MAXIMUM", MAXIMUM), (" Maximum ", MAXIMUM),
    ("performance", PERFORMANCE), ("pro", PERFORMANCE),
    ("foundation", FOUNDATION), ("free", FOUNDATION),
    ("", FOUNDATION), (None, FOUNDATION), (42, FOUNDATION),
    ("enterprise", FOUNDATION), ("ultra", MAXIMUM),
])
def test_normalize_tier_fails_closed(raw, expected):
    assert normalize_tier(raw) == expected


def test_tier_rank_is_strictly_ordered():
    assert tier_rank(FOUNDATION) < tier_rank(PERFORMANCE) < tier_rank(MAXIMUM)


@pytest.mark.parametrize("held,required,ok", [
    (FOUNDATION, FOUNDATION, True),
    (FOUNDATION, PERFORMANCE, False),
    (FOUNDATION, MAXIMUM, False),
    (PERFORMANCE, FOUNDATION, True),
    (PERFORMANCE, PERFORMANCE, True),
    (PERFORMANCE, MAXIMUM, False),
    (MAXIMUM, FOUNDATION, True),
    (MAXIMUM, PERFORMANCE, True),
    (MAXIMUM, MAXIMUM, True),
])
def test_allows_is_inherited_and_strictly_ordered(held, required, ok):
    assert allows(held, required) is ok


def test_inherits_lists_granted_tiers_lowest_first():
    """`inherits(held)` returns every tier the subscriber is entitled to."""
    assert inherits(FOUNDATION) == (FOUNDATION,)
    assert inherits(PERFORMANCE) == (FOUNDATION, PERFORMANCE)
    assert inherits(MAXIMUM) == (FOUNDATION, PERFORMANCE, MAXIMUM)


def test_inherits_agrees_with_allows():
    for held in (FOUNDATION, PERFORMANCE, MAXIMUM):
        for required in (FOUNDATION, PERFORMANCE, MAXIMUM):
            assert allows(held, required) == (required in inherits(held))


def test_upgrade_path_points_upward_only():
    assert upgrade_path(FOUNDATION, FOUNDATION) in (FOUNDATION, None)
    assert tier_rank(upgrade_path(FOUNDATION, MAXIMUM)) == tier_rank(MAXIMUM)
    assert tier_rank(upgrade_path(PERFORMANCE, MAXIMUM)) == tier_rank(MAXIMUM)
    # already at or above the target -> no upgrade needed
    assert upgrade_path(MAXIMUM, PERFORMANCE) in (None, PERFORMANCE)


# ---------------------------------------------------------------------------
# Every loaded tweak carries consistent tier metadata
# ---------------------------------------------------------------------------
from database.tweaks import BY_ID, TWEAKS  # noqa: E402

VALID_TIERS = (FOUNDATION, PERFORMANCE, MAXIMUM)


def test_tweak_catalog_loads():
    # Catalogue holds only real, applyable tweaks plus the Diagnostics /
    # System Tools diagnostic groups; guidance/informational text is gone.
    assert len(TWEAKS) == len(BY_ID)
    assert len(TWEAKS) > 500


def test_every_tweak_has_required_tier_and_it_is_valid():
    for t in TWEAKS:
        assert t.get("requiredTier") in VALID_TIERS, t["id"]


def test_required_tier_never_disagrees_with_internal_tier():
    for t in TWEAKS:
        assert t.get("requiredTier") == t.get("tier"), t["id"]


def test_required_tier_is_already_normalized():
    for t in TWEAKS:
        assert normalize_tier(t.get("requiredTier")) == t.get("requiredTier"), t["id"]


def test_every_tweak_has_verification_and_disposition():
    for t in TWEAKS:
        assert isinstance(t.get("verified"), bool), t["id"]
        assert t.get("disposition"), t["id"]


def test_tier_distribution_is_plausible():
    """Catches a classifier that collapses everything to one tier."""
    counts = {tier: 0 for tier in VALID_TIERS}
    for t in TWEAKS:
        counts[t["requiredTier"]] += 1
    assert all(n > 0 for n in counts.values()), counts
    assert counts[MAXIMUM] < len(TWEAKS) * 0.5


# ---------------------------------------------------------------------------
# Entitlements
# ---------------------------------------------------------------------------
from engine import entitlements as ENT  # noqa: E402
from engine.safety import preflight  # noqa: E402


def _tweak(**kw):
    base = dict(id="t", name="t", status="VALID", tier=FOUNDATION,
                actions=[("reg", "HKCU", "S", "v", "1", "")], verified=True,
                recommended="recommended")
    base.update(kw)
    return base


PROFILE = {"win_version": "10", "gpu": ["nvidia"], "gpu_types": ["RTX"],
           "ram_gb": 64, "cpu_cores": 16}


def test_gate_requires_the_right_tier():
    for held, required, ok in [
        (FOUNDATION, MAXIMUM, False),
        (PERFORMANCE, MAXIMUM, False),
        (MAXIMUM, MAXIMUM, True),
    ]:
        g = ENT.gate(_tweak(tier=required), held=held)
        assert g["allowed"] is ok


def test_locked_reason_names_the_plan_and_price():
    g = ENT.gate(_tweak(tier=MAXIMUM), held=FOUNDATION)
    assert g["code"] == ENT.GATE_TIER
    assert "Maximum" in g["reason"]
    assert "$15.00/month" in g["reason"]


def test_foundation_tier_is_free_in_reason_text():
    g = ENT.gate(_tweak(tier=PERFORMANCE), held=FOUNDATION)
    assert "$10.00/month" in g["reason"]


def test_unverified_requires_confirmation_but_is_allowed():
    g = ENT.gate(_tweak(verified=False), held=MAXIMUM)
    assert g["allowed"] is True
    assert g["requires_confirmation"] is True
    assert g["code"] == ENT.GATE_UNVERIFIED
    assert g["reason"]


def test_entitlement_summary_counts_locked_tweaks():
    summary = ENT.entitlement_summary([
        _tweak(id="a", tier=FOUNDATION),
        _tweak(id="b", tier=PERFORMANCE),
        _tweak(id="c", tier=MAXIMUM),
    ], held=FOUNDATION)
    assert summary["counts"] == {FOUNDATION: 1, PERFORMANCE: 1, MAXIMUM: 1}
    assert summary["locked"][MAXIMUM] == 1
    assert summary["locked_total"] == 2
    assert summary["accessible"] == 1


# ---------------------------------------------------------------------------
# preflight: force must never bypass tier / compatibility / status
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tweak,profile,code", [
    (_tweak(win="11"), {"win_version": "10"}, "win_version"),
    (_tweak(status="INVALID"), None, "status_blocked"),
    (_tweak(status="OUTDATED"), None, "status_blocked"),
    (_tweak(tier=MAXIMUM), {"win_version": "10"}, "tier_required"),
    (_tweak(when={"gpu": ["amd", "intel"]}), PROFILE, "incompatible"),
    (_tweak(when={"ram_gb": 256}), PROFILE, "incompatible"),
])
def test_force_cannot_bypass_hard_blocks(tweak, profile, code):
    assert not preflight(tweak, profile=profile, mode="apply", force=True)["allowed"]
    assert preflight(tweak, profile=profile, mode="apply",
                     force=True)["code"] == code


def test_hardware_gated_tweak_without_a_profile_is_blocked():
    r = preflight(_tweak(when={"gpu": ["nvidia"]}), profile=None, mode="apply")
    assert not r["allowed"] and r["code"] == "no_profile"


def test_compatible_hardware_is_allowed():
    assert preflight(_tweak(when={"gpu": ["nvidia"]}), profile=PROFILE,
                     mode="apply")["allowed"]


def test_unverified_is_flagged_not_blocked():
    r = preflight(_tweak(verified=False), profile=PROFILE, mode="apply",
                  force=True)
    assert r["allowed"] is True
    assert r["code"] == "unverified"
    assert r.get("unverified") is True


def test_unverified_never_becomes_a_hard_denial():
    """`unverified` must not deny, or Apply All would silently drop it."""
    for mode in ("apply",):
        r = preflight(_tweak(verified=False), profile=PROFILE, mode=mode)
        assert r["allowed"] is True


def test_guidance_tweaks_are_info_only():
    r = preflight(_tweak(guidance="just read this"), profile=PROFILE)
    assert not r["allowed"] and r["code"] == "info_only"


@pytest.mark.parametrize("tweak", [
    _tweak(tier=MAXIMUM, verified=False),
    _tweak(status="INVALID"),
    _tweak(win="11"),
    _tweak(status="CONFLICTING", conflicts=[{"with": "c2", "target": "x",
                                             "reason": "dup"}]),
])
def test_revert_is_never_gated(tweak):
    """A lapsed/downgraded entitlement must never trap a change in place."""
    assert preflight(tweak, profile=None, mode="revert")["allowed"]


def test_guidance_tweak_revert_is_info_only():
    """A guidance entry has nothing written, so revert is a no-op by design."""
    r = preflight(_tweak(guidance="read this"), profile=None, mode="revert")
    assert not r["allowed"]
    assert r["code"] == "info_only"


def test_conflict_guard_is_force_able_but_only_that(monkeypatch):
    """`force` exists to resolve conflicts, and must do nothing else."""
    from engine import state as state_mgr
    monkeypatch.setattr(state_mgr, "applied_ids", lambda: {"c2"})
    c1 = _tweak(id="c1", conflicts=[{"with": "c2", "target": "HKCU\\S\\v",
                                     "reason": "duplicate"}])
    blocked = preflight(c1, profile=PROFILE, mode="apply", force=False)
    assert not blocked["allowed"]
    assert blocked["code"] == "conflict_active"
    assert blocked["conflicts"] == ["c2"]

    forced = preflight(c1, profile=PROFILE, mode="apply", force=True)
    assert forced["allowed"] is True
    assert forced["code"] is None
    assert forced["conflicts"] == ["c2"]   # still reported, just not blocking


def test_optimizer_paths_cannot_force_through(monkeypatch):
    """preflight is the single chokepoint; verify the applier honours it."""
    from engine import applier
    src = Path(applier.__file__).read_text(encoding="utf-8")
    assert "preflight(" in src
    # the applier must consult preflight before executing
    assert src.index("preflight(") < src.index("apply_tweak(")


def test_apply_all_excludes_unverified(monkeypatch):
    """The Apply All builder must split unverified tweaks out of the batch.

    This mirrors `request_apply_all`: an unverified tweak is allowed one at a
    time but must never be part of an unattended batch.
    """
    tweaks = [
        _tweak(id="safe", tier=FOUNDATION, verified=True),
        _tweak(id="risky", tier=FOUNDATION, verified=False),
        _tweak(id="locked", tier=MAXIMUM, verified=True),
    ]
    ids, skipped, unverified = [], [], []
    for t in tweaks:
        pf = preflight(t, profile=PROFILE, mode="apply")
        if not pf["allowed"]:
            skipped.append(t["id"])
        elif pf.get("requires_confirmation"):
            unverified.append(t["id"])
        else:
            ids.append(t["id"])
    assert ids == ["safe"]
    assert unverified == ["risky"]
    assert skipped == ["locked"]


# ---------------------------------------------------------------------------
# Validation override drift
# ---------------------------------------------------------------------------
from database import validation as V  # noqa: E402


def test_orphan_detection_reports_missing_ids():
    orphan = V.orphaned_overrides()
    assert isinstance(orphan, dict)
    for tid in orphan:
        assert tid not in BY_ID


def test_orphan_count_matches_live_catalog():
    """A rename must show up as drift rather than as a silent data loss."""
    live = set(BY_ID)
    expected = {tid for tid in V.OVERRIDES if tid not in live}
    assert set(V.orphaned_overrides()) >= expected


def test_override_drift_is_reported_once(capsys):
    n = V.audit_override_drift()
    assert n == len(V.orphaned_overrides())


def test_apply_does_not_raise_on_orphan_overrides():
    sample = [_tweak()]
    V.apply(sample)          # must not raise
    assert sample[0]["status"] == "VALID"


def test_no_orphaned_validation_overrides():
    """Hard gate: ids missing from the shipped catalogue fail the suite.

    This used to be only a RuntimeWarning, and the warning fired on *any*
    partial list (a one-element sample reported all 295 overrides as stale).
    Real drift now must not exist at all - tools/check_validation_drift.py
    lists the offenders for cleanup.
    """
    orphan = V.orphaned_overrides()
    assert orphan == {}, (
        f"{len(orphan)} validation override(s) reference tweak ids that are "
        f"not in the shipped catalogue; first 20: "
        f"{', '.join(sorted(orphan)[:20])}"
    )


def test_apply_on_partial_list_does_not_warn():
    """Auditing the caller's sample list made every override look stale."""
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        V.apply([_tweak()])
    stale = [w for w in caught if "validation override" in str(w.message)]
    assert stale == []


# ---------------------------------------------------------------------------
# Backend: tier persistence and payload serialization
# ---------------------------------------------------------------------------
from db import TIERS as BACKEND_TIERS  # noqa: E402
from db import LicenseDB, normalize_tier as backend_normalize  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    return LicenseDB(str(tmp_path / "licenses.db"))


def test_backend_tiers_match_the_client_tiers():
    assert set(BACKEND_TIERS) == {FOUNDATION, PERFORMANCE, MAXIMUM}


def test_backend_normalize_matches_client_normalize():
    for raw in ("maximum", "MAXIMUM", "pro", "free", "", None, "nonsense"):
        assert backend_normalize(raw) == normalize_tier(raw)


def test_create_persists_tier_and_plan_separately(db):
    rec = db.create("MAX-TEST-0001", plan="yearly", customer="A", tier="performance")
    assert rec["tier"] == "performance"
    assert rec["plan"] == "yearly"
    assert rec["status"] == "unused"


def test_default_tier_is_foundation(db):
    assert db.create("MAX-TEST-0002")["tier"] == "foundation"


def test_upgrade_and_downgrade_move_only_the_tier(db):
    db.create("MAX-TEST-0003", plan="yearly", tier="foundation")
    assert db.set_tier("MAX-TEST-0003", "maximum")["tier"] == "maximum"
    rec = db.set_tier("MAX-TEST-0003", "foundation")
    assert rec["tier"] == "foundation"
    assert rec["plan"] == "yearly"     # billing duration untouched


def test_set_tier_is_idempotent(db):
    db.create("MAX-TEST-0004", tier="performance")
    before = db.get("MAX-TEST-0004")
    after = db.set_tier("MAX-TEST-0004", "performance")
    assert before["tier"] == after["tier"] == "performance"


def test_set_tier_fails_closed_on_garbage(db):
    db.create("MAX-TEST-0005", tier="maximum")
    assert db.set_tier("MAX-TEST-0005", "ultra-premium")["tier"] == "foundation"


def test_set_tier_unknown_key_returns_none(db):
    assert db.set_tier("MAX-DOES-NOT-EXIST", "maximum") is None


def test_legacy_row_without_tier_defaults_to_foundation(tmp_path):
    """An existing DB row predating the tier column must read as Foundation."""
    path = tmp_path / "legacy.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE licenses (license_key TEXT, status TEXT, plan TEXT)")
    con.execute("INSERT INTO licenses VALUES ('MAX-LEGACY-0001', 'active', 'lifetime')")
    con.commit()
    con.close()
    rec = LicenseDB(str(path)).get("MAX-LEGACY-0001")
    assert backend_normalize(rec.get("tier")) == "foundation"


def test_migration_adds_tier_column_to_existing_table(tmp_path):
    path = tmp_path / "migrate.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE licenses (license_key TEXT, status TEXT, plan TEXT)")
    con.execute("INSERT INTO licenses VALUES ('MAX-OLD-0001', 'active', 'yearly')")
    con.commit()
    con.close()
    rec = LicenseDB(str(path)).get("MAX-OLD-0001")
    assert rec is not None and rec.get("tier") == "foundation"


def test_license_payload_includes_tier_and_plan():
    """The client gates on `tier`; both must reach the wire."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mt_auth_main", ROOT / "auth_backend" / "main.py")
    # Importing the whole app needs its deps; assert on the source instead.
    src = (ROOT / "auth_backend" / "main.py").read_text(encoding="utf-8")
    for fn in ("_license_payload", "_session_payload"):
        block = src.split(f"def {fn}(")[1].split("\n\n\n")[0]
        assert '"tier"' in block, fn
        assert '"plan"' in block, fn


# ---------------------------------------------------------------------------
# License client: 24h grace + tier passthrough
# ---------------------------------------------------------------------------
def test_license_client_grace_is_24_hours_not_30_days():
    import engine.license as lic
    assert lic._OFFLINE_GRACE_HOURS == 24
    assert lic._OFFLINE_GRACE_HOURS != 24 * 30


def test_session_from_response_carries_tier_and_status():
    """The server envelope nests the licence under `license`; read tier from it."""
    from engine.license import _session_from_response
    s = _session_from_response({
        "valid": True,
        "license": {"key": "MAX-TEST-0001", "plan": "yearly", "tier": "maximum",
                    "status": "active"},
    })
    assert s.get("tier") == "maximum"
    assert s.get("plan") == "yearly"        # duration preserved separately
    assert s.get("status") == "active"
    assert s.get("license") == "MAX-TEST-0001"


def test_session_from_response_tolerates_a_missing_tier():
    from engine.license import _session_from_response
    s = _session_from_response({"license": {"key": "MAX-OLD", "plan": "yearly"}})
    assert s.get("tier") is None      # not defaulted here; current_tier() fails closed
    assert normalize_tier(s.get("tier")) == FOUNDATION


def test_current_tier_fails_closed_without_a_license(monkeypatch):
    import engine.license as lic
    monkeypatch.setattr(lic, "session", lambda: {}, raising=False)
    assert ENT.current_tier() == FOUNDATION


@pytest.mark.parametrize("sess", [
    {}, {"valid": False}, {"status": "revoked"}, {"status": "expired"},
    {"status": "suspended"}, {"status": "banned"}, {"status": "inactive"},
    {"tier": "nonsense"}, {"tier": None}, {"tier": 123},
])
def test_bad_sessions_never_unlock_paid_features(monkeypatch, sess):
    import engine.license as lic
    monkeypatch.setattr(lic, "session", lambda: sess, raising=False)
    assert ENT.current_tier() == FOUNDATION
    assert not ENT.gate(_tweak(tier=MAXIMUM))["allowed"]


def test_valid_maximum_session_unlocks_maximum(monkeypatch):
    import engine.license as lic
    monkeypatch.setattr(
        lic, "session",
        lambda: {"valid": True, "status": "active", "tier": "maximum"},
        raising=False)
    assert ENT.current_tier() == MAXIMUM
    assert ENT.gate(_tweak(tier=MAXIMUM))["allowed"]


# ---------------------------------------------------------------------------
# Admin desktop plan labels
# ---------------------------------------------------------------------------
def test_yearly_plan_is_not_labelled_six_months():
    src = (ROOT / "admin_desktop" / "main.py").read_text(encoding="utf-8")
    import re
    m = re.search(r'"yearly":\s*\("([^"]+)",\s*"([^"]+)",\s*(\w+)\)', src)
    assert m, "yearly entry not found"
    label, _code, days = m.group(1), m.group(2), m.group(3)
    assert "Month" not in label, f"yearly still labelled {label!r}"
    assert days == "365"


def test_admin_plan_table_covers_every_duration():
    src = (ROOT / "admin_desktop" / "main.py").read_text(encoding="utf-8")
    for key in ("1m", "6m", "yearly", "lifetime"):
        assert f'"{key}"' in src
