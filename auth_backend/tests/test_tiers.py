"""Tests for subscription tiers end to end.

A tier is the *level* a key unlocks (foundation / performance / maximum); the
billing duration in ``plan`` is a separate fact. These cover:

* choosing the tier at creation time, via /admin/keys and /admin/generate;
* failing closed - an absent or junk tier can only ever issue Foundation;
* tier and duration being genuinely independent;
* changing the tier afterwards via /admin/set-tier (upgrade and downgrade),
  and that the change reaches the customer-facing activate payload;
* the tier being visible to the operator (/admin/keys rows + by_tier counters).

Runs against the same throwaway SQLite DB pattern as test_license.py.
"""
from __future__ import annotations

import os
import tempfile

# LICENSE_DB_PATH is pinned by tests/conftest.py (isolated sqlite temp file)
os.environ["LICENSE_SECRET"] = "test-secret-not-for-production"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["SESSION_TTL_HOURS"] = "2"
os.environ["OFFLINE_GRACE_HOURS"] = "24"

try:
    from dotenv import load_dotenv
    load_dotenv()  # pick up TEST_DATABASE_URL from auth_backend/.env if set
except Exception:  # noqa: BLE001
    pass

if os.environ.get("TEST_DATABASE_URL", "").strip():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"].strip()

from fastapi.testclient import TestClient  # noqa: E402

import pytest  # noqa: E402

from db import TIERS, LicenseDB, normalize_tier  # noqa: E402
from keys import generate_key  # noqa: E402

import main as backend  # noqa: E402

client = TestClient(backend.app)
# Every module shares the one sqlite file pinned by tests/conftest.py,
# so this is the same store the API handlers write to.
db = backend._DB

DEVICE_A = "a" * 64


@pytest.fixture(autouse=True)
def _clean_db():
    with db._lock:
        conn = db._connect()
        try:
            db._exec(conn, "DELETE FROM licenses")
            db._exec(conn, "DELETE FROM key_activity")
            db._exec(conn, "DELETE FROM key_blocked")
            db._exec(conn, "DELETE FROM key_log")
            conn.commit()
        finally:
            conn.close()
    # The activation rate limiters are module-level singletons with a 1h window
    # keyed by client IP, and every TestClient request shares one IP. Left alone
    # they carry a budget across the whole pytest session, so these tests would
    # pass alone but 429 under a full run. Clearing them per test keeps the
    # assertions about the tier, not about the order the suite ran in.
    for limiter in (backend._limiter_key, backend._limiter_ip,
                    backend._limiter_waitlist_ip):
        with limiter._lock:
            limiter._buckets.clear()
    yield


def _admin_headers():
    return {"Authorization": f"Bearer {os.environ['ADMIN_TOKEN']}"}


# ---------------------------------------------------------------------------
# normalize_tier: the fail-closed contract
# ---------------------------------------------------------------------------

def test_normalize_tier_accepts_exact_ids():
    assert normalize_tier("foundation") == "foundation"
    assert normalize_tier("performance") == "performance"
    assert normalize_tier("maximum") == "maximum"


def test_normalize_tier_is_case_and_space_insensitive():
    assert normalize_tier("  MAXIMUM ") == "maximum"
    assert normalize_tier("Performance") == "performance"


def test_normalize_tier_fails_closed_on_junk():
    for junk in ("enterprise", "", "   ", None, 123, [], {}, "maximum_plus"):
        assert normalize_tier(junk) == "foundation", junk


def test_normalize_tier_maps_documented_aliases():
    """The marketing names used on pricing pages resolve to real tiers."""
    for alias, want in (("free", "foundation"), ("basic", "foundation"),
                        ("starter", "foundation"), ("pro", "performance"),
                        ("performance_monthly", "performance"),
                        ("premium", "maximum"), ("ultra", "maximum"),
                        ("max", "maximum")):
        assert normalize_tier(alias) == want, alias


def test_normalize_tier_never_ranks_above_the_paid_ceiling():
    """No input, however mangled, may resolve above ``maximum``."""
    for junk in ("ultra", "premium", "pro", "max", "godmode", "maximum+1"):
        assert normalize_tier(junk) in TIERS
        assert TIERS.index(normalize_tier(junk)) <= TIERS.index("maximum")


# ---------------------------------------------------------------------------
# Tier chosen at creation time
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tier", ["foundation", "performance", "maximum"])
def test_create_key_honours_chosen_tier(tier):
    r = client.post("/admin/keys",
                    json={"customer": "Thabo", "plan": "life", "tier": tier,
                          "max_pcs": 1, "note": ""},
                    headers=_admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tier"] == tier
    assert db.get(body["key"])["tier"] == tier


def test_create_key_defaults_to_foundation_when_tier_omitted():
    r = client.post("/admin/keys", json={"customer": "Defaulted"},
                    headers=_admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tier"] == "foundation"
    assert db.get(body["key"])["tier"] == "foundation"


def test_create_key_with_junk_tier_issues_foundation_not_a_paid_level():
    """A typo must fail closed, never grant more than was asked for."""
    for junk in ("MAXIMUM_PLUS", "enterprise", "", "   ", None):
        r = client.post("/admin/keys",
                        json={"customer": "Typo", "plan": "life", "tier": junk},
                        headers=_admin_headers())
        assert r.status_code == 200, r.text
        key = r.json()["key"]
        assert db.get(key)["tier"] == "foundation", junk


def test_create_key_treats_a_null_tier_as_unspecified():
    """A client that has never heard of tiers can send ``null`` and get free."""
    r = client.post("/admin/keys",
                    json={"customer": "Nullish", "plan": "life", "tier": None},
                    headers=_admin_headers())
    assert r.status_code == 200, r.text
    key = r.json()["key"]
    assert db.get(key)["tier"] == "foundation"


def test_create_key_rejects_a_non_string_tier_outright():
    """A wrong-typed tier is refused by the schema instead of being coerced.

    Either outcome is safe - it can never grant a paid level - but a 422 is the
    honest one: there is no sensible tier for a number or a list.
    """
    for junk in (7, [], {}, True):
        r = client.post("/admin/keys",
                        json={"customer": "Typo", "plan": "life", "tier": junk},
                        headers=_admin_headers())
        assert r.status_code == 422, (junk, r.status_code, r.text)


def test_create_key_accepts_documented_aliases():
    """Marketing names map onto real tiers, and still cap out at ``maximum``."""
    for alias, want in (("free", "foundation"), ("basic", "foundation"),
                        ("pro", "performance"), ("premium", "maximum"),
                        ("ultra", "maximum"), ("max", "maximum")):
        r = client.post("/admin/keys",
                        json={"customer": "Alias", "plan": "life", "tier": alias},
                        headers=_admin_headers())
        key = r.json()["key"]
        got = db.get(key)["tier"]
        assert got == want, alias
        assert TIERS.index(got) <= TIERS.index("maximum"), alias


def test_tier_is_independent_of_duration():
    """Same duration, different tier - the two must not bleed into each other."""
    a = client.post("/admin/keys",
                    json={"customer": "A", "plan": "life", "tier": "foundation"},
                    headers=_admin_headers()).json()
    b = client.post("/admin/keys",
                    json={"customer": "B", "plan": "life", "tier": "maximum"},
                    headers=_admin_headers()).json()
    ra, rb = db.get(a["key"]), db.get(b["key"])
    assert ra["plan"] == rb["plan"]
    assert ra["tier"] == "foundation" and rb["tier"] == "maximum"


def test_generate_stamps_the_chosen_tier_on_every_key():
    r = client.post("/admin/generate",
                    json={"count": 5, "plan": "lifetime", "duration": "lifetime",
                          "tier": "performance", "prefix": "MAX",
                          "customer": "Batch", "note": ""},
                    headers=_admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 5
    assert body["tier"] == "performance"
    assert all(db.get(k)["tier"] == "performance" for k in body["keys"])


def test_generate_defaults_to_foundation():
    r = client.post("/admin/generate",
                    json={"count": 3, "plan": "lifetime", "duration": "lifetime"},
                    headers=_admin_headers())
    body = r.json()
    assert body["tier"] == "foundation"
    assert all(db.get(k)["tier"] == "foundation" for k in body["keys"])


def test_generate_with_junk_tier_issues_foundation():
    r = client.post("/admin/generate",
                    json={"count": 2, "plan": "lifetime", "duration": "lifetime",
                          "tier": "enterprise-plus"},
                    headers=_admin_headers())
    assert r.json()["tier"] == "foundation"
    assert all(db.get(k)["tier"] == "foundation" for k in r.json()["keys"])


def test_create_key_tier_requires_admin_auth():
    r = client.post("/admin/keys",
                    json={"customer": "Sneaky", "plan": "life", "tier": "maximum"})
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Changing the tier afterwards
# ---------------------------------------------------------------------------

def test_set_tier_upgrades_and_downgrades():
    key = generate_key()
    db.create(key, plan="life", customer="Rex", tier="foundation")

    up = client.post("/admin/set-tier", json={"key": key, "tier": "maximum"},
                     headers=_admin_headers())
    assert up.status_code == 200, up.text
    assert up.json()["license"]["tier"] == "maximum"
    assert db.get(key)["tier"] == "maximum"

    down = client.post("/admin/set-tier", json={"key": key, "tier": "performance"},
                       headers=_admin_headers())
    assert down.json()["license"]["tier"] == "performance"
    assert db.get(key)["tier"] == "performance"


def test_set_tier_does_not_disturb_the_duration():
    """Changing level must not silently extend or shorten the licence term."""
    key = generate_key()
    db.create(key, plan="6m", customer="Rex", tier="foundation",
              expires_at="2027-01-01 00:00:00")
    before = db.get(key)

    client.post("/admin/set-tier", json={"key": key, "tier": "maximum"},
                headers=_admin_headers())
    after = db.get(key)

    assert after["plan"] == before["plan"]
    assert after["expires_at"] == before["expires_at"]


def test_set_tier_with_junk_downgrades_to_foundation():
    key = generate_key()
    db.create(key, plan="life", customer="Rex", tier="maximum")
    r = client.post("/admin/set-tier", json={"key": key, "tier": "not-a-tier"},
                    headers=_admin_headers())
    assert r.json()["license"]["tier"] == "foundation"
    assert db.get(key)["tier"] == "foundation"


def test_set_tier_on_unknown_key_is_404():
    r = client.post("/admin/set-tier",
                    json={"key": "NOPE-NOPE-NOPE-NOPE", "tier": "maximum"},
                    headers=_admin_headers())
    assert r.status_code == 404


def test_set_tier_requires_admin_auth():
    key = generate_key()
    db.create(key, plan="life", tier="foundation")
    r = client.post("/admin/set-tier", json={"key": key, "tier": "maximum"})
    assert r.status_code in (401, 403)
    assert db.get(key)["tier"] == "foundation"


def test_set_tier_records_the_direction_in_the_log():
    key = generate_key()
    db.create(key, plan="life", tier="foundation")
    client.post("/admin/set-tier", json={"key": key, "tier": "maximum"},
                headers=_admin_headers())
    events = [row["event"] for row in db.logs(key)]
    assert "upgraded" in events

    client.post("/admin/set-tier", json={"key": key, "tier": "foundation"},
                headers=_admin_headers())
    events = [row["event"] for row in db.logs(key)]
    assert "downgraded" in events


# ---------------------------------------------------------------------------
# The tier reaches the customer, and the panel can see it
# ---------------------------------------------------------------------------

def test_activate_payload_carries_the_key_tier():
    key = client.post("/admin/keys",
                      json={"customer": "Buyer", "plan": "life",
                            "tier": "performance"},
                      headers=_admin_headers()).json()["key"]
    r = client.post("/api/license/activate",
                    json={"key": key, "device_id": DEVICE_A})
    assert r.status_code == 200, r.text
    assert r.json()["license"]["tier"] == "performance"


def test_validate_payload_carries_an_upgraded_tier():
    """The client re-reads the tier on validate, so an upgrade lands on the PC."""
    key = client.post("/admin/keys",
                      json={"customer": "Buyer", "plan": "life",
                            "tier": "foundation"},
                      headers=_admin_headers()).json()["key"]
    act = client.post("/api/license/activate",
                      json={"key": key, "device_id": DEVICE_A}).json()
    assert act["license"]["tier"] == "foundation"

    client.post("/admin/set-tier", json={"key": key, "tier": "maximum"},
                headers=_admin_headers())

    val = client.post("/api/license/validate",
                      json={"token": act["session_token"], "device_id": DEVICE_A})
    assert val.status_code == 200, val.text
    assert val.json()["license"]["tier"] == "maximum"


def test_checkin_reflects_a_downgraded_tier():
    key = client.post("/admin/keys",
                      json={"customer": "Buyer", "plan": "life",
                            "tier": "maximum"},
                      headers=_admin_headers()).json()["key"]
    client.post("/api/license/activate",
                json={"key": key, "device_id": DEVICE_A})
    client.post("/admin/set-tier", json={"key": key, "tier": "foundation"},
                headers=_admin_headers())
    r = client.post("/api/license/checkin",
                    json={"key": key, "device_id": DEVICE_A, "pc_name": "PC"})
    assert r.status_code == 200, r.text
    assert r.json()["license"]["tier"] == "foundation"


def test_admin_keys_rows_expose_a_normalized_tier():
    a = client.post("/admin/keys",
                    json={"customer": "A", "plan": "life", "tier": "maximum"},
                    headers=_admin_headers()).json()["key"]
    # A legacy row written before tiers existed / hand-edited to junk.
    b = generate_key()
    db.create(b, plan="life", customer="Legacy")

    rows = {k["key"]: k for k in
            client.get("/admin/keys", headers=_admin_headers()).json()["keys"]}
    assert rows[a]["tier"] == "maximum"
    assert rows[b]["tier"] == "foundation"


def test_admin_keys_reports_by_tier_with_every_tier_present():
    for tier, n in (("foundation", 2), ("maximum", 1)):
        for i in range(n):
            client.post("/admin/keys",
                        json={"customer": f"{tier}{i}", "plan": "life",
                              "tier": tier},
                        headers=_admin_headers())
    by_tier = client.get("/admin/keys",
                         headers=_admin_headers()).json()["stats"]["by_tier"]
    assert set(by_tier) == set(TIERS)
    assert by_tier["foundation"] == 2
    assert by_tier["maximum"] == 1
    assert by_tier["performance"] == 0  # present, not missing


def test_db_stats_by_tier_always_lists_every_tier():
    assert set(db.stats()["by_tier"]) == set(TIERS)
    assert all(v == 0 for v in db.stats()["by_tier"].values())


def test_db_create_normalizes_the_tier_it_is_given():
    key = generate_key()
    db.create(key, plan="life", tier="nonsense")
    assert db.get(key)["tier"] == "foundation"