"""Tests for the Ultra Mode waitlist API.

Same throwaway-DB discipline as test_license.py: env is set before ``main``
is imported, and the tests only touch the waitlist table. The mailer is the
default log provider (WAITLIST_MAILER=log) so nothing ever leaves the test
process.
"""
from __future__ import annotations

import os
import tempfile

_tmpdir = tempfile.mkdtemp(prefix="mt-waitlist-")
os.environ["LICENSE_DB_PATH"] = os.path.join(_tmpdir, "test.db")
os.environ["LICENSE_SECRET"] = "test-secret-not-for-production"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["WAITLIST_MAILER"] = "log"

try:
    from dotenv import load_dotenv
    load_dotenv()  # pickup TEST_DATABASE_URL from auth_backend/.env if set
except Exception:  # noqa: BLE001
    pass

if os.environ.get("TEST_DATABASE_URL", "").strip():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"].strip()

from fastapi.testclient import TestClient  # noqa: E402

import pytest  # noqa: E402

from db import LicenseDB  # noqa: E402

import main as backend  # noqa: E402

import launch_email  # noqa: E402

client = TestClient(backend.app)
db = LicenseDB()

ADMIN_HEADERS = {"Authorization": "Bearer test-admin-token"}


@pytest.fixture(autouse=True)
def _clean_waitlist():
    with db._lock:
        conn = db._connect()
        try:
            db._exec(conn, "DELETE FROM waitlist")
            conn.commit()
        finally:
            conn.close()
    yield


def _join(email, source="ultra_mode"):
    return client.post("/api/waitlist/join",
                       json={"email": email, "source": source})


# ---------------------------------------------------------------------------
# Public join endpoint
# ---------------------------------------------------------------------------


def test_join_adds_lowercased_email():
    r = _join(" Some.User@Example.COM ")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["added"] is True
    assert db.waitlist_get("some.user@example.com") is not None


def test_join_rejects_invalid_email():
    for bad in ["", "nope", "a@b", "a b@c.com", "a@.com"]:
        r = _join(bad)
        assert r.status_code == 400, bad
        assert r.json()["error"] == "invalid_email"


def test_join_duplicate_is_not_an_error():
    assert _join("dup@example.com").json()["added"] is True
    r = _join("DUP@example.com")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["added"] is False
    assert db.waitlist_count(subscribed_only=False) == 1


def test_join_rate_limited_per_ip():
    limiter = backend._limiter_waitlist_ip
    original = limiter._limit
    limiter._limit = 3
    limiter._buckets.clear()
    try:
        for i in range(3):
            assert _join(f"user{i}@example.com").status_code == 200
        r = _join("over@example.com")
        assert r.status_code == 429
        assert r.json()["error"] == "rate_limited"
    finally:
        limiter._limit = original
        limiter._buckets.clear()


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------


def test_unsubscribe_flips_subscribed_off():
    _join("list@example.com")
    rec = db.waitlist_get("list@example.com")
    r = client.get(f"/api/waitlist/unsubscribe?token={rec['unsub_token']}")
    assert r.status_code == 200
    assert "unsubscribed" in r.text.lower()
    assert db.waitlist_get("list@example.com")["subscribed"] == 0


def test_unsubscribe_unknown_token_shows_status():
    r = client.get("/api/waitlist/unsubscribe?token=bogus")
    assert r.status_code == 200
    assert "no longer valid" in r.text.lower()


# ---------------------------------------------------------------------------
# Admin roster
# ---------------------------------------------------------------------------


def test_admin_waitlist_roster():
    _join("one@example.com")
    _join("two@example.com")
    body = client.get("/admin/waitlist",
                      headers=ADMIN_HEADERS).json()
    assert body["ok"] and body["total"] == 2 and body["subscribed"] == 2
    emails = [e["email"] for e in body["entries"]]
    assert "one@example.com" in emails and "two@example.com" in emails


def test_admin_waitlist_requires_auth():
    assert client.get("/admin/waitlist").status_code == 401


def test_admin_waitlist_include_unsubscribed_uses_flag():
    _join("list@example.com")
    rec = db.waitlist_get("list@example.com")
    _ = rec["unsub_token"]
    db.waitlist_unsubscribe(rec["unsub_token"])
    subbed = client.get("/admin/waitlist",
                        headers=ADMIN_HEADERS).json()
    all_ = client.get("/admin/waitlist?include_unsubscribed=true",
                      headers=ADMIN_HEADERS).json()
    assert subbed["subscribed"] == 0 and all_["total"] == 1


# ---------------------------------------------------------------------------
# Launch email dispatch (log mailer — nothing is sent)
# ---------------------------------------------------------------------------


def test_send_launch_reports_stats_and_stamps_notified():
    for i in range(3):
        _join(f"fan{i}@example.com")
    r = client.post("/admin/waitlist/send-launch",
                    json={"code": "test-admin-token"}, headers=ADMIN_HEADERS)
    assert r.status_code == 200
    stats = r.json()
    assert stats["ok"] and stats["total"] == 3 and stats["sent"] == 3
    assert stats["failed"] == 0 and stats["notified"] == 3
    assert stats["provider"] == "log"
    for rec in db.waitlist_list(subscribed_only=False):
        assert rec["notified_at"]


def test_send_launch_honours_content_overrides():
    _join("custom@example.com")
    r = client.post(
        "/admin/waitlist/send-launch",
        json={
            "code": "test-admin-token",
            "subject": "Custom subject",
            "heading": "Custom heading",
            "message": "Custom body",
            "cta_button": "Custom CTA",
            "cta_url": "https://example.com/ultra",
        },
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200 and r.json()["sent"] == 1


def test_send_launch_requires_reconfirm():
    _join("locked@example.com")
    r = client.post("/admin/waitlist/send-launch",
                    json={"code": "wrong"}, headers=ADMIN_HEADERS)
    assert r.status_code == 401

    r = client.post("/admin/waitlist/send-launch",
                    json={"code": "test-admin-token"})
    assert r.status_code == 401


def test_launch_email_uses_detailed_asset_template():
    body = launch_email.render(
        {"cta_url": "https://example.com/signup"},
        unsub_url="https://maximumtweaks.onrender.com/api/waitlist/"
                  "unsubscribe?token=abc")
    html = body["html"]
    assert "Introducing Ultra Mode" in html
    assert "Faster runs. Cleaner output. Zero extra setup." in html
    assert "{{CTA_URL}}" not in html and "{{UNSUB_URL}}" not in html
    assert 'https://example.com/signup' in html
    assert "unsubscribe?token=abc" in html
    assert "Your Company" not in html
    assert "Product preview" in html