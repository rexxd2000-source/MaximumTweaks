"""Regression tests for the Discord end-user OAuth callback.

These lock in the two bugs that broke the flow in production:

1. The authorize URL is built with the *user* app client id, so the code must be
   exchanged with that same client. Exchanging it with the bot app credentials
   made Discord answer ``unauthorized_client`` / ``invalid_grant``.
2. A repeated sign-in (double-click, page refresh, retried poll) must not raise
   a UNIQUE-constraint error out of ``create_discord_account``.
"""

import io
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)


def _load_main(db_path):
    """Import main.py against a throwaway SQLite DB.

    Restores LICENSE_DB_PATH afterwards: leaving a per-test tmp_path in the
    environment leaks into every later module that constructs a LicenseDB.
    """
    import importlib
    previous = os.environ.get("LICENSE_DB_PATH")
    os.environ["LICENSE_DB_PATH"] = db_path
    try:
        for mod in ("main", "db"):
            sys.modules.pop(mod, None)
        main = importlib.import_module("main")
        dbmod = sys.modules["db"]
    finally:
        if previous is None:
            os.environ.pop("LICENSE_DB_PATH", None)
        else:
            os.environ["LICENSE_DB_PATH"] = previous
    return main, dbmod


class TestDiscordUserOAuth:
    def _fixture(self, tmp_path):
        import main, db
        db.LicenseDB(str(tmp_path / "t.db"))
        # user app credentials present, bot app credentials absent
        main.DISCORD_CLIENT_ID_USER = "user-client-id"
        main.DISCORD_CLIENT_SECRET_USER = "user-secret"
        main.DISCORD_CLIENT_ID = "bot-client-id"
        main.DISCORD_CLIENT_SECRET = "bot-secret"
        main.DISCORD_GUILD_ID = ""
        return main

    def test_start_url_uses_user_client_id(self, tmp_path, monkeypatch):
        main = self._fixture(tmp_path)
        r = main.auth_discord_start(request=type("R", (), {"base_url": "http://x/"})())
        assert r["ok"] is True
        assert "client_id=user-client-id" in r["url"]
        assert "scope=identify+guilds.join" in r["url"]
        assert r["state"]

    def test_start_url_forces_consent_prompt(self, tmp_path, monkeypatch):
        """guilds.join must not be silently downgraded by a prior approval.

        Anyone who authorised the app before it asked for guilds.join
        receives an identify-only token on every later sign-in unless
        consent is re-prompted. That left guilds.join permanently missing
        from the token, so add-member silently no-op'd.
        """
        main = self._fixture(tmp_path)
        r = main.auth_discord_start(request=type("R", (), {"base_url": "http://x/"})())
        assert "prompt=consent" in r["url"]

    def test_callback_rejects_token_without_guilds_join(self, tmp_path):
        """A token whose granted scope lacks guilds.join must be refused, not
        passed onward to a doomed add-member call."""
        import json
        import urllib.error
        import urllib.parse

        main, _ = _load_main(str(tmp_path / "t2.db"))
        main.DISCORD_CLIENT_ID_USER = "user-client-id"
        main.DISCORD_CLIENT_SECRET_USER = "user-secret"
        main.DISCORD_GUILD_ID = "guild-id"
        state = main._discord_user_state_new()

        seen = {}

        def fake_token(req, timeout=None):
            seen["body"] = req.data.decode()
            class R:
                def read(self):
                    return (b'{"access_token":"t","scope":"identify"}')
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    return False
            return R()

        def fake_get_user(access_token):
            return {"id": "992", "username": "noscope"}

        monkeypatch = __import__("pytest").MonkeyPatch()
        monkeypatch.setattr(main.urllib.request, "urlopen", fake_token)
        monkeypatch.setattr(main, "_discord_user", fake_get_user)
        res = main.auth_discord_callback(request=object(), code="c", state=state)
        html = res.body.decode()
        assert "Server access not granted" in html
        assert "Authorized Apps" in html
        entry = main._discord_user_state_get(state)
        assert entry["status"] == "error"
        assert "guilds.join" not in " ".join(entry.get("reason", ""))

    def test_callback_accepts_token_with_guilds_join(self, tmp_path, monkeypatch):
        import json

        main, _ = _load_main(str(tmp_path / "t3.db"))
        main.DISCORD_CLIENT_ID_USER = "user-client-id"
        main.DISCORD_CLIENT_SECRET_USER = "user-secret"
        main.DISCORD_GUILD_ID = ""
        state = main._discord_user_state_new()

        def fake_token(req, timeout=None):
            class R:
                def read(self):
                    return (b'{"access_token":"t","scope":"identify guilds.join"}')
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    return False
            return R()

        monkeypatch.setattr(main.urllib.request, "urlopen", fake_token)
        monkeypatch.setattr(main, "_discord_user",
                            lambda at: {"id": "993", "username": "withscope"})
        assert main.auth_discord_callback(request=object(), code="c", state=state)
        assert main._discord_user_state_get(state)[
            "status"] in ("ok", "completed")

    def test_exchange_uses_user_credentials_not_bot(self, tmp_path, monkeypatch):
        """The code MUST be redeemed with DISCORD_CLIENT_ID_USER."""
        main = self._fixture(tmp_path)
        seen = {}

        class FakeResp:
            def read(self):
                return b'{"access_token":"tok"}'
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            body = req.data.decode()
            seen["body"] = body
            return FakeResp()

        monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)

        out = main._discord_exchange_user("code123", "http://x/cb")
        assert out.get("access_token") == "tok"
        assert "client_id=user-client-id" in seen["body"]
        assert "user-secret" in seen["body"]
        assert "bot-client-id" not in seen["body"]
        assert "bot-secret" not in seen["body"]

    def test_callback_never_uses_bot_exchange(self, tmp_path, monkeypatch):
        """End-to-end guard: the user callback must not call _discord_exchange."""
        main = self._fixture(tmp_path)
        called = []
        monkeypatch.setattr(main, "_discord_exchange",
                            lambda *a, **k: called.append("bot") or {})
        monkeypatch.setattr(main, "_discord_exchange_user",
                            lambda *a, **k: {"access_token": "tok"})
        monkeypatch.setattr(main, "_discord_user",
                            lambda tok: {"id": "42", "username": "tester"})

        state = main._discord_user_state_new()
        main.auth_discord_callback(
            request=type("R", (), {"base_url": "http://x/"})(),
            code="c", state=state)
        assert called == []

        entry = main._discord_user_state_get(state)
        assert entry["status"] == "ok"
        assert entry["discord_id"] == "42"
        assert entry["account_id"]

    def test_new_user_gets_foundation(self, tmp_path, monkeypatch):
        main = self._fixture(tmp_path)
        monkeypatch.setattr(main, "_discord_exchange_user",
                            lambda *a, **k: {"access_token": "tok"})
        monkeypatch.setattr(main, "_discord_user",
                            lambda tok: {"id": "999", "username": "newbie"})

        state = main._discord_user_state_new()
        main.auth_discord_callback(
            request=type("R", (), {"base_url": "http://x/"})(),
            code="c", state=state)
        acc = main._DB.get_discord_account_by_discord_id("999")
        assert acc is not None
        assert acc["current_tier"] == "foundation"
        assert acc["entitlements"] == "foundation"
        assert acc["status"] == "active"

    def test_repeat_login_is_idempotent(self, tmp_path, monkeypatch):
        """Second sign-in for the same user must reuse the account."""
        main = self._fixture(tmp_path)
        monkeypatch.setattr(main, "_discord_exchange_user",
                            lambda *a, **k: {"access_token": "tok"})
        monkeypatch.setattr(main, "_discord_user",
                            lambda tok: {"id": "999", "username": "newbie"})

        first = main._discord_user_state_new()
        main.auth_discord_callback(
            request=type("R", (), {"base_url": "http://x/"})(),
            code="c", state=first)
        first_acc = main._discord_user_state_get(first)["account_id"]

        second = main._discord_user_state_new()
        resp = main.auth_discord_callback(
            request=type("R", (), {"base_url": "http://x/"})(),
            code="c", state=second)
        # must not raise; page should still say Connected
        second_acc = main._discord_user_state_get(second)
        assert second_acc["status"] == "ok"
        assert second_acc["account_id"] == first_acc

    def test_db_failure_does_not_leak_server_error(self, tmp_path, monkeypatch):
        main = self._fixture(tmp_path)
        monkeypatch.setattr(main, "_discord_exchange_user",
                            lambda *a, **k: {"access_token": "tok"})
        monkeypatch.setattr(main, "_discord_user",
                            lambda tok: {"id": "777", "username": "unlucky"})

        def boom(*a, **k):
            raise RuntimeError("database is on fire")
        monkeypatch.setattr(main._DB, "get_discord_account_by_discord_id", boom)

        state = main._discord_user_state_new()
        resp = main.auth_discord_callback(
            request=type("R", (), {"base_url": "http://x/"})(),
            code="c", state=state)
        assert main._discord_user_state_get(state)["status"] == "error"
        assert "on fire" not in str(getattr(resp, "body", b""))


class TestDiscordTierSafety:
    def _db(self, tmp_path):
        import db
        return db.LicenseDB(str(tmp_path / "d.db"))

    def test_paid_tier_not_downgraded_by_foundation_link(self, tmp_path):
        d = self._db(tmp_path)
        d.create_discord_account("1", "paid")
        d.link_discord_to_license("1", "MAX-A-B-C", tier="maximum")
        assert d.get_discord_account_by_discord_id("1")["current_tier"] == "maximum"
        # linking a foundation-tier key must not lower it
        d.link_discord_to_license("1", "MAX-X-Y-Z", tier="foundation")
        assert d.get_discord_account_by_discord_id("1")["current_tier"] == "maximum"

    def test_foundation_account_upgraded_by_paid_key(self, tmp_path):
        d = self._db(tmp_path)
        d.create_discord_account("2", "free")
        d.link_discord_to_license("2", "MAX-Q-R-S", tier="performance")
        assert d.get_discord_account_by_discord_id("2")["current_tier"] == "performance"