"""Regression tests for the staff audit ping and the join-failure fallback.

These cover the bug where a successful "Connected" login left the staff
channel empty, because only /register-event posted the audit line.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _load_main(db_path):
    import importlib
    import os
    previous = os.environ.get("LICENSE_DB_PATH")
    os.environ["LICENSE_DB_PATH"] = str(db_path)
    try:
        for mod in ("main", "db"):
            sys.modules.pop(mod, None)
        main = importlib.import_module("main")
        return main
    finally:
        if previous is None:
            os.environ.pop("LICENSE_DB_PATH", None)
        else:
            os.environ["LICENSE_DB_PATH"] = previous


class TestRegistrationMessage:
    def test_includes_every_audit_field(self):
        m = _load_main("/tmp/unused.db")
        msg = m._discord_registration_message(
            event_type="ACCOUNT_CREATED", username="rex2yd.",
            discord_id="1545177212255346784", account_id="MO-89A3A7",
            region="EU", tier="foundation", status="active",
            server_membership="PENDING")
        for needle in ("ACCOUNT_CREATED", "rex2yd.", "1545177212255346784",
                       "MO-89A3A7", "EU", "FOUNDATION", "active",
                       "Server Membership: PENDING"):
            assert needle in msg, f"missing {needle!r} in audit line"

    def test_blanks_fall_back_to_n_a(self):
        m = _load_main("/tmp/unused.db")
        msg = m._discord_registration_message(
            event_type="LINKED", username="", discord_id="1",
            account_id="", region="", tier="", status="",
            server_membership="")
        assert "N/A" in msg and "UNKNOWN" in msg

    def test_tier_is_uppercased(self):
        m = _load_main("/tmp/unused.db")
        msg = m._discord_registration_message(
            event_type="X", username="u", discord_id="1", account_id="A",
            tier="performance", status="active", server_membership="CONFIRMED")
        assert "PERFORMANCE" in msg


class TestNotifyStaff:
    def test_posts_to_configured_channel(self):
        m = _load_main("/tmp/unused.db")
        seen = {}

        def fake_send(channel_id, content):
            seen["channel"] = channel_id
            seen["content"] = content
            return True

        m.discord_bot_send_message = fake_send
        m.DISCORD_REGISTRATION_CHANNEL_ID = "1556361665719697489"
        m.DISCORD_BOT_TOKEN = "bot-token"

        ok = m._discord_notify_staff(
            event_type="ACCOUNT_CREATED", username="rex2yd.",
            discord_id="1545177212255346784", account_id="MO-89A3A7",
            tier="foundation", status="active", server_membership="CONFIRMED")
        assert ok is True
        assert seen["channel"] == "1556361665719697489"
        assert "rex2yd." in seen["content"]

    def test_skips_and_warns_when_unconfigured(self):
        m = _load_main("/tmp/unused.db")
        called = []
        m.discord_bot_send_message = lambda c, t: called.append(1) or True
        m.DISCORD_REGISTRATION_CHANNEL_ID = ""
        m.DISCORD_BOT_TOKEN = "bot-token"

        assert m._discord_notify_staff(
            event_type="X", username="u", discord_id="1",
            account_id="A") is False
        assert called == [], "must not call Discord with no channel id"

    def test_never_raises_when_channel_missing(self):
        m = _load_main("/tmp/unused.db")
        m.DISCORD_REGISTRATION_CHANNEL_ID = ""
        m.DISCORD_BOT_TOKEN = ""
        # A staff-ping failure must not abort a successful login.
        assert m._discord_notify_staff(
            event_type="X", username="u", discord_id="1",
            account_id="A") is False


class TestJoinFallbackPage:
    def test_invite_link_rendered_when_link_given(self):
        m = _load_main("/tmp/unused.db")
        page = m._discord_page("Connected", "Could not add you",
                               link_url="https://discord.com/oauth2/authorize?client_id=1",
                               link_label="Join the server")
        html = page.body.decode("utf-8")
        assert "https://discord.com/oauth2/authorize?client_id=1" in html
        assert "Join the server" in html
        assert 'href="https://discord.com/oauth2/authorize?client_id=1"' in html

    def test_no_link_keeps_auto_redirect(self):
        m = _load_main("/tmp/unused.db")
        html = m._discord_page("Connected", "All good").body.decode("utf-8")
        assert "location.href='/'" in html
        assert "<a href" not in html

    def test_body_is_escaped(self):
        m = _load_main("/tmp/unused.db")
        html = m._discord_page("Hi", "<script>x()</script>").body.decode("utf-8")
        assert "<script>x()</script>" not in html
        assert "&lt;script&gt;" in html

    def test_link_url_is_escaped(self):
        m = _load_main("/tmp/unused.db")
        html = m._discord_page("Hi", "b", link_url='a"onmouseover=x',
                               link_label="go").body.decode("utf-8")
        assert 'onmouseover="x' not in html
        assert "&quot;" in html