"""Lock in the User-Agent fix for bot REST calls.

Discord's edge answers a browser-spoofing User-Agent with 403/40333 on every
guild-scoped endpoint, while /users/@me still returns 200. That pattern was
misdiagnosed as an IP block and cost days. These tests fail if a browser UA
is ever reintroduced on a bot call.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

BROWSER_MARKERS = ("Mozilla/5.0", "Chrome/", "Safari/", "AppleWebKit")


def _load_main():
    import importlib
    import os
    import tempfile
    os.environ.setdefault("LICENSE_DB_PATH",
                          str(Path(tempfile.gettempdir()) / "ua_probe.db"))
    for mod in ("main", "db"):
        sys.modules.pop(mod, None)
    return importlib.import_module("main")


class TestBotUserAgent:
    def test_bot_ua_identifies_as_discordbot(self):
        m = _load_main()
        assert m._DISCORD_BOT_UA.startswith("DiscordBot ("), m._DISCORD_BOT_UA
        assert "maximumtweaks" in m._DISCORD_BOT_UA

    def test_bot_ua_is_not_a_browser(self):
        m = _load_main()
        for marker in BROWSER_MARKERS:
            assert marker not in m._DISCORD_BOT_UA, \
                "browser marker %r must not appear in the bot UA" % marker

    def test_bot_headers_use_the_bot_ua(self):
        m = _load_main()
        m.DISCORD_BOT_TOKEN = "token-for-test"
        headers = m._discord_bot_headers()
        assert headers is not None
        assert headers["User-Agent"] == m._DISCORD_BOT_UA
        for marker in BROWSER_MARKERS:
            assert marker not in headers["User-Agent"]

    def test_bot_headers_none_without_token(self):
        m = _load_main()
        m.DISCORD_BOT_TOKEN = ""
        assert m._discord_bot_headers() is None

    def test_browser_ua_still_available_for_oauth_exchange(self):
        # The OAuth token exchange legitimately uses the browser UA; the two
        # must not be collapsed into one constant.
        m = _load_main()
        assert m._DISCORD_UA != m._DISCORD_BOT_UA
        assert "Mozilla/5.0" in m._DISCORD_UA

    def test_send_message_does_not_send_browser_ua(self):
        m = _load_main()
        seen = {}

        class FakeResp:
            def getcode(self):
                return 200

            def read(self):
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            seen["ua"] = req.get_header("User-agent")
            return FakeResp()

        real = m.urllib.request.urlopen
        m.urllib.request.urlopen = fake_urlopen
        try:
            m.DISCORD_BOT_TOKEN = "token-for-test"
            m.discord_bot_send_message("123", "hello")
        finally:
            m.urllib.request.urlopen = real

        assert seen.get("ua") == m._DISCORD_BOT_UA, seen
        for marker in BROWSER_MARKERS:
            assert marker not in (seen.get("ua") or "")

    def test_add_member_does_not_send_browser_ua(self):
        m = _load_main()
        seen = {}

        class FakeResp:
            def __init__(self, body=b""):
                self.body = body

            def getcode(self):
                return 201

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            seen["ua"] = req.get_header("User-agent")
            # A 201 whose body carries the member object is trusted directly,
            # so add_member skips the membership lookup this test does not stub.
            return FakeResp(b'{"user":{"id":"111"}}')

        real = m.urllib.request.urlopen
        m.urllib.request.urlopen = fake_urlopen
        try:
            m.DISCORD_BOT_TOKEN = "token-for-test"

            assert m.discord_bot_add_member("999", "111", "tok") is True
        finally:
            m.urllib.request.urlopen = real

        assert seen.get("ua") == m._DISCORD_BOT_UA, seen
        for marker in BROWSER_MARKERS:
            assert marker not in (seen.get("ua") or "")