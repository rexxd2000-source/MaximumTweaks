"""Discord-backed heartbeat check-ins.

A Discord-signed-in client persists ``DISCORD:<discord_id>`` as its entitlement.
The minute-by-minute heartbeat posts that to ``/api/license/checkin``, which
must resolve it against ``discord_accounts`` instead of rejecting it as an
unknown licence key -- that rejection is what used to clear the session and
relock the app about a minute after a good sign-in.
"""
from __future__ import annotations

import os

os.environ["LICENSE_SECRET"] = "test-secret-not-for-production"
os.environ["ADMIN_TOKEN"] = "test-admin-token"

from fastapi.testclient import TestClient  # noqa: E402

import pytest  # noqa: E402

from db import LicenseDB  # noqa: E402
from keys import generate_key  # noqa: E402

import main as backend  # noqa: E402

client = TestClient(backend.app)
db = LicenseDB()

DEVICE = "d" * 64
DISCORD_ID = "1545177212255346784"


@pytest.fixture(autouse=True)
def _clean_db():
    with db._lock:
        conn = db._connect()
        try:
            db._exec(conn, "DELETE FROM licenses")
            db._exec(conn, "DELETE FROM key_activity")
            db._exec(conn, "DELETE FROM key_blocked")
            db._exec(conn, "DELETE FROM discord_accounts")
            db._exec(conn, "DELETE FROM discord_registrations")
            conn.commit()
        finally:
            conn.close()
    yield


def _checkin(key, device=DEVICE):
    return client.post("/api/license/checkin",
                       json={"key": key, "device_id": device,
                             "pc_name": "TEST-PC"})


def _account(**over):
    fields = dict(discord_id=DISCORD_ID, discord_username="rex2yd.",
                  tier="foundation")
    fields.update(over)
    return db.create_discord_account(**fields)


def _set_status(status):
    with db._lock:
        conn = db._connect()
        try:
            db._exec(conn,
                     "UPDATE discord_accounts SET status = ? WHERE discord_id = ?",
                     (status, DISCORD_ID))
            conn.commit()
        finally:
            conn.close()


class TestDiscordCheckinAllowed:
    def test_active_account_is_allowed(self):
        _account()
        r = _checkin(f"DISCORD:{DISCORD_ID}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["source"] == "discord"
        assert body["discord_id"] == DISCORD_ID

    def test_entitlement_round_trips_in_license_key(self):
        """The client persists ``license.key`` and re-posts it every minute,
        so the response has to hand the same string back."""
        _account()
        body = _checkin(f"DISCORD:{DISCORD_ID}").json()
        assert body["license"]["key"] == f"DISCORD:{DISCORD_ID}"

    def test_tier_is_foundation_and_not_expiring(self):
        _account()
        lic = _checkin(f"DISCORD:{DISCORD_ID}").json()["license"]
        assert lic["tier"] == "foundation"
        # A Discord account has no expiry date; a stray one would make the
        # client relock itself once the timestamp passed.
        assert lic["expires_at"] is None

    def test_carries_account_id(self):
        acc = _account()
        body = _checkin(f"DISCORD:{DISCORD_ID}").json()
        assert body["account_id"] == acc["account_id"]

    def test_prefix_is_case_insensitive(self):
        _account()
        assert _checkin(f"discord:{DISCORD_ID}").status_code == 200


class TestDiscordCheckinRefused:
    def test_unknown_account_is_refused(self):
        _account()
        r = _checkin("DISCORD:999999999999999999")
        assert r.status_code == 403
        assert "no longer registered" in r.json()["message"]

    def test_no_account_row_does_not_fall_through_to_licences(self):
        r = _checkin(f"DISCORD:{DISCORD_ID}")
        assert r.status_code == 403
        assert r.json()["error"] == "invalid_license"

    @pytest.mark.parametrize("status", ["banned", "suspended", "revoked"])
    def test_suspended_account_is_refused(self, status):
        _account()
        _set_status(status)
        r = _checkin(f"DISCORD:{DISCORD_ID}")
        assert r.status_code == 403
        assert r.json()["error"] == f"license_{status}"

    def test_malformed_entitlement_is_refused(self):
        r = _checkin("DISCORD:not-a-number")
        assert r.status_code in (400, 403)
        assert "Malformed" in r.json()["message"]

    def test_requires_device_fingerprint(self):
        _account()
        r = _checkin(f"DISCORD:{DISCORD_ID}", device="short")
        assert r.status_code in (400, 403)
        assert r.json()["error"] == "invalid_device"


class TestRealLicencePathUntouched:
    def test_generated_key_still_checks_in(self):
        key = generate_key()
        with db._lock:
            conn = db._connect()
            try:
                db._exec(
                    conn,
                    "INSERT INTO licenses (license_key, plan, tier, status,"
                    " customer, created_at) VALUES (?,?,?,?,?,datetime('now'))",
                    (key, "lifetime", "maximum", "active", "Alice"))
                conn.commit()
            finally:
                conn.close()
        r = _checkin(key)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["license"]["key"] == key
        assert body["license"]["tier"] == "maximum"
        # No `source` marker: this is a genuine licence, not a Discord shim.
        assert "source" not in body

    def test_garbage_key_still_rejected(self):
        r = _checkin("definitely-not-a-key")
        assert r.status_code in (400, 403)
        assert r.json()["error"] == "invalid_license"