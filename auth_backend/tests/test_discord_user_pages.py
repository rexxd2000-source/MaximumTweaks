"""Cover the three end-user sign-in complaints:

1. the result page must not bounce to Max Manager
2. a failure must name the real reason
3. a failed guild add must not read as a completed signup
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _load_main():
    import importlib
    import os
    import tempfile
    # start from an empty file every call: create_discord_account is
    # idempotent, so a leftover row from a previous run silently kept its
    # NULL license_key and made the "already connected" path unreachable.
    db_path = Path(tempfile.gettempdir()) / "userpage_tests.db"
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    os.environ["DATABASE_URL"] = ""
    os.environ["TEST_DATABASE_URL"] = ""
    os.environ["LICENSE_DB_PATH"] = str(db_path)
    for mod in ("main", "db"):
        sys.modules.pop(mod, None)
    return importlib.import_module("main")


def _client(m):
    from fastapi.testclient import TestClient
    return TestClient(m.app)


class TestNoManagerHijack:
    def test_auto_redirect_off_suppresses_the_bounce(self):
        m = _load_main()
        html = m._discord_page("Connected", "done", auto_redirect=False).body.decode()
        assert "location.href='/'" not in html, "must not bounce to the SPA"
        assert "close this window" in html

    def test_auto_redirect_on_keeps_the_bounce_for_admin(self):
        m = _load_main()
        html = m._discord_page("Signed in", "done").body.decode()
        assert "location.href='/'" in html

    def test_link_page_never_redirects_even_if_asked(self):
        m = _load_main()
        html = m._discord_page("Join required", "join",
                               link_url="https://discord.com/x",
                               link_label="Join").body.decode()
        assert "location.href='/'" not in html


class TestFailureReasons:
    def test_invalid_grant_explains_a_used_link(self):
        m = _load_main()
        msg = m._discord_failure_reason(
            {"__error__": 'HTTP 400: {"error": "invalid_grant"}'})
        assert "already been used" in msg and "expired" in msg

    def test_invalid_client_is_flagged_as_a_server_problem(self):
        m = _load_main()
        msg = m._discord_failure_reason(
            {"__error__": 'HTTP 401: {"error": "invalid_client"}'})
        assert "server" in msg.lower() and "contact support" in msg.lower()

    def test_access_denied_reads_as_cancelled(self):
        m = _load_main()
        msg = m._discord_failure_reason(
            {"__error__": 'HTTP 400: {"error": "access_denied"}'})
        assert "cancelled" in msg.lower()

    def test_network_failure_is_not_called_an_auth_problem(self):
        m = _load_main()
        msg = m._discord_failure_reason(
            {"__error__": "<urlopen error timed out>"})
        assert "reach Discord" in msg

    def test_missing_error_falls_back(self):
        m = _load_main()
        assert m._discord_failure_reason({})
        assert m._discord_failure_reason({"access_token": ""})

    def test_never_leaks_the_raw_discord_payload(self):
        m = _load_main()
        raw = 'HTTP 400: {"error": "invalid_grant", "trace": "abc123"}'
        msg = m._discord_failure_reason({"__error__": raw})
        for leak in ("{", "}", "trace", "abc123", "__error__"):
            assert leak not in msg, f"raw payload fragment {leak!r} leaked"

    def test_every_mapped_code_returns_a_non_empty_reason(self):
        m = _load_main()
        for code, _ in m._DISCORD_ERROR_REASONS:
            got = m._discord_failure_reason(
                {"__error__": 'HTTP 400: {"error": "%s"}' % code})
            assert got and len(got) > 15, code


class TestEndUserCallbackPages:
    def _prep(self, m, joined):
        m._discord_exchange_user = lambda c, r: {"access_token": "t"}
        m._discord_user = lambda t: {"id": "9" * 19, "username": "probe"}
        m.discord_bot_add_member = lambda g, u, a: joined
        m._discord_notify_staff = lambda **k: True
        m.DISCORD_GUILD_ID = "1438996702756475063"
        return _client(m)

    def test_confirmed_join_says_they_are_in_the_server(self):
        m = _load_main()
        c = self._prep(m, True)
        state = c.post("/auth/discord/start", json={}).json()["state"]
        html = c.get(f"/auth/discord/callback?code=x&state={state}").text
        assert "added to the Maximum" in html
        assert "location.href='/'" not in html

    def test_failed_join_shows_join_required_and_invite(self):
        m = _load_main()
        c = self._prep(m, False)
        state = c.post("/auth/discord/start", json={}).json()["state"]
        html = c.get(f"/auth/discord/callback?code=x&state={state}").text
        assert "Join required" in html
        assert "NOT in the" in html
        assert "discord.com/oauth2/authorize" in html

    def test_poll_reports_error_with_reason(self):
        m = _load_main()
        c = self._prep(m, True)
        state = c.post("/auth/discord/start", json={}).json()["state"]
        m._discord_exchange_user = lambda c2, r: {
            "__error__": 'HTTP 400: {"error": "invalid_grant"}'}
        c.get(f"/auth/discord/callback?code=x&state={state}")
        poll = c.get(f"/auth/discord/poll/{state}").json()
        assert poll["status"] == "error"
        assert "already been used" in poll["reason"]

    def test_expired_state_page_does_not_redirect(self):
        m = _load_main()
        c = self._prep(m, True)
        html = c.get("/auth/discord/callback?code=x&state=nope").text
        assert "location.href='/'" not in html
        assert "no longer valid" in html

    def test_repeat_login_of_a_linked_account_says_already_connected(self):
        m = _load_main()
        uid = "9" * 19
        # pre-existing account that already carries a license key
        m._DB.create_discord_account(
            discord_id=uid, discord_username="probe", region="",
            license_key="MT-EXISTING-KEY", tier="performance")
        c = self._prep(m, True)
        state = c.post("/auth/discord/start", json={}).json()["state"]
        html = c.get(f"/auth/discord/callback?code=x&state={state}").text
        assert "Already connected" in html
        assert "already signed in" in html