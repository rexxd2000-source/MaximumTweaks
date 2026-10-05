"""Bot wiring tests: permissions, invite URL, self-check, error reporting."""
import io, os, sys, json

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)


def _load():
    import importlib
    for m in ("main", "db"):
        sys.modules.pop(m, None)
    return importlib.import_module("main")


class TestBotPermissions:
    def test_permissions_include_send_messages(self):
        m = _load()
        bits = m.DISCORD_BOT_PERMISSIONS
        assert bits & m.DISCORD_PERM_VIEW_CHANNEL, "must be able to see the channel"
        assert bits & m.DISCORD_PERM_SEND_MESSAGES, \
            "View Channel alone cannot post to staff channel"

    def test_invite_url_carries_permissions_and_bot_scope(self, monkeypatch):
        m = _load()
        m.DISCORD_CLIENT_ID_USER = "123456789"
        # monkeypatch, never a bare os.environ write: a plain assignment plus
        # ``del`` left DISCORD_CLIENT_ID unset for every later test in the
        # session (test_discord_login.py asserts on it).
        monkeypatch.setenv("DISCORD_CLIENT_ID", "123456789")
        url = m.discord_bot_invite_url()
        assert "client_id=123456789" in url
        assert "scope=bot" in url
        assert f"permissions={m.DISCORD_BOT_PERMISSIONS}" in url

    def test_old_1024_would_be_insufficient(self):
        """Guard against regressing to View Channel only."""
        m = _load()
        assert m.DISCORD_BOT_PERMISSIONS != 1024
        assert not (1024 & m.DISCORD_PERM_SEND_MESSAGES)


class TestSelfCheck:
    def test_reports_missing_token(self):
        m = _load()
        m.DISCORD_BOT_TOKEN = ""
        m.DISCORD_GUILD_ID = "1"
        m.DISCORD_REGISTRATION_CHANNEL_ID = "2"
        r = m.discord_bot_self_check()
        assert r["token_configured"] is False
        assert r["bot_reachable"] is False
        assert any("DISCORD_BOT_TOKEN" in p for p in r["problems"])

    def test_reports_missing_guild_and_channel(self):
        m = _load()
        m.DISCORD_BOT_TOKEN = "fake"
        m.DISCORD_GUILD_ID = ""
        m.DISCORD_REGISTRATION_CHANNEL_ID = ""
        r = m.discord_bot_self_check()
        joined = " ".join(r["problems"])
        assert "DISCORD_GUILD_ID" in joined
        assert "DISCORD_REGISTRATION_CHANNEL_ID" in joined

    def test_never_leaks_token(self):
        m = _load()
        m.DISCORD_BOT_TOKEN = "SUPER_SECRET_TOKEN_VALUE"
        m.DISCORD_GUILD_ID = ""
        r = m.discord_bot_self_check()
        assert "SUPER_SECRET_TOKEN_VALUE" not in json.dumps(r)


class TestSelfCheckIpBlock:
    """Discord returns 403/40333 and 1010 for some routes depending on egress
    IP. That must NOT be reported as 'bot not in guild' or 'missing
    permissions' - it is a network condition, and it produced a false
    negative during setup."""

    def _blocked(self, monkeypatch, code=403, body=b'{"message":"internal network error","code":40333}'):
        def raiser(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, code, "Forbidden", {},
                                         io.BytesIO(body))
        monkeypatch.setattr(m.urllib.request, "urlopen", raiser)

    def test_membership_uses_guild_list_not_member_route(self, monkeypatch):
        m = _load()
        m.DISCORD_BOT_TOKEN = "t"
        m.DISCORD_GUILD_ID = "G1"
        m.DISCORD_REGISTRATION_CHANNEL_ID = ""

        seen = []

        class R:
            def __init__(self, payload): self.p = payload
            def read(self): return json.dumps(self.p).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(req, timeout=None):
            seen.append(req.full_url)
            if req.full_url.endswith("/users/@me"):
                return R({"id": "B1", "username": "bot"})
            if req.full_url.endswith("/users/@me/guilds"):
                return R([{"id": "G1", "name": "My Server"}])
            raise AssertionError("unexpected call " + req.full_url)
        import urllib.request as ur
        monkeypatch.setattr(ur, "urlopen", urlopen)

        r = m.discord_bot_self_check()
        assert r["in_guild"] is True
        assert r["guild_name"] == "My Server"
        assert not any("NOT in the configured guild" in p for p in r["problems"])
        assert any(u.endswith("/users/@me/guilds") for u in seen), \
            "membership must be resolved from the guild list"

    def test_403_1010_reported_as_network_not_permissions(self, monkeypatch):
        m = _load()
        m.DISCORD_BOT_TOKEN = "t"
        m.DISCORD_GUILD_ID = "G1"
        m.DISCORD_REGISTRATION_CHANNEL_ID = "C1"
        self._blocked(monkeypatch=None) if False else None

        import urllib.request as ur
        # /users/@me and /users/@me/guilds succeed; everything else is blocked
        class R:
            def __init__(self, payload): self.p = payload
            def read(self): return json.dumps(self.p).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(req, timeout=None):
            if req.full_url.endswith("/users/@me"):
                return R({"id": "B1", "username": "bot"})
            if req.full_url.endswith("/users/@me/guilds"):
                return R([{"id": "G1", "name": "My Server"}])
            raise urllib.error.HTTPError(
                req.full_url, 403, "Forbidden", {},
                io.BytesIO(b'{"message":"internal network error","code":40333}'))
        monkeypatch.setattr(ur, "urlopen", urlopen)

        r = m.discord_bot_self_check()
        assert r["in_guild"] is True, "membership proven by guild list"
        assert r["network_restricted"] is True
        joined = " ".join(r["problems"])
        # 403/40333 is an edge refusal, not a permissions fault
        assert "edge" in joined.lower()
        assert "blocked this ip" not in joined.lower()
        assert "missing: " not in joined, \
            "an IP block must not be reported as missing permissions"

    def test_code_1010_also_counts_as_ip_block(self, monkeypatch):
        m = _load()
        m.DISCORD_BOT_TOKEN = "t"
        m.DISCORD_GUILD_ID = "G1"
        assert m._discord_is_ip_block("error code: 1010") is True
        assert m._discord_is_ip_block('{"code":40333}') is True
        assert m._discord_is_ip_block('{"message":"Missing Permissions"}') is False

    def test_genuinely_missing_guild_is_still_reported(self, monkeypatch):
        m = _load()
        m.DISCORD_BOT_TOKEN = "t"
        m.DISCORD_GUILD_ID = "G1"
        m.DISCORD_REGISTRATION_CHANNEL_ID = ""

        class R:
            def __init__(self, payload): self.p = payload
            def read(self): return json.dumps(self.p).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(req, timeout=None):
            if req.full_url.endswith("/users/@me"):
                return R({"id": "B1", "username": "bot"})
            return R([])          # in no guilds
        import urllib.request as ur
        monkeypatch.setattr(ur, "urlopen", urlopen)

        r = m.discord_bot_self_check()
        assert r["in_guild"] is False
        assert any("NOT in the configured guild" in p for p in r["problems"])
        assert r["invite_url"]


class TestBotCallErrorHandling:
    def test_headers_absent_without_token(self):
        m = _load()
        m.DISCORD_BOT_TOKEN = ""
        assert m._discord_bot_headers() is None
        assert m.discord_bot_add_member("1", "2", "tok") is False
        assert m.discord_bot_send_message("1", "hi") is False

    def test_add_member_treats_201_and_204_as_success(self, monkeypatch):
        m = _load()
        m.DISCORD_BOT_TOKEN = "t"

        class R:
            def __init__(self, code, payload=b""):
                self.code, self.payload = code, payload
            def getcode(self): return self.code
            def read(self): return self.payload
            def __enter__(self): return self
            def __exit__(self, *a): return False

        seen = {}
        def ok(req, timeout=None):
            seen["method"] = req.get_method()
            seen["url"] = req.full_url
            seen["body"] = req.data.decode()
            r = R(201)
            r.payload = b'{"user":{"id":"U1"},"joined_at":"now"}'
            return r
        monkeypatch.setattr(m.urllib.request, "urlopen", ok)
        assert m.discord_bot_add_member("G1", "U1", "user_token") is True
        assert seen["method"] == "PUT"
        assert "/guilds/G1/members/U1" in seen["url"]
        # the user's access token must be forwarded for guilds.join
        assert "user_token" in seen["body"]

        # 204 is "already a member" and carries no body, so membership has to
        # be confirmed with a follow-up lookup rather than assumed.
        def already(req, timeout=None):
            r = R(204)
            r.payload = b""
            return r
        monkeypatch.setattr(m.urllib.request, "urlopen", already)
        monkeypatch.setattr(m, "discord_bot_is_member",
                            lambda g, u: True)
        assert m.discord_bot_add_member("G1", "U1", "user_token") is True, \
            "204 plus a confirmed member lookup is success"


class TestMembershipIsVerifiedNotAssumed:
    """A 2xx from add-to-server is not proof the user joined the guild.

    Discord answers 204 with an empty body when the member already existed,
    and a silent no-op is indistinguishable from success at the status level.
    Treating "no exception raised" as joined made the staff card print
    ``Server Membership: CONFIRMED`` for a user who was never added.
    """

    def _bot(self):
        m = _load()
        m.DISCORD_BOT_TOKEN = "t"
        return m

    def test_201_with_member_body_needs_no_lookup(self, monkeypatch):
        m = self._bot()

        class R:
            def __init__(self, code, payload):
                self.code, self.payload = code, payload

            def getcode(self): return self.code

            def read(self): return self.payload

            def __enter__(self): return self

            def __exit__(self, *a): return False

        calls = []
        monkeypatch.setattr(m.urllib.request, "urlopen",
                            lambda req, timeout=None: calls.append(req.get_method())
                            or R(201, b'{"user":{"id":"U1"}}'))
        monkeypatch.setattr(m, "discord_bot_is_member",
                            lambda g, u: pytest.fail("must trust a 201 body"))
        assert m.discord_bot_add_member("G1", "U1", "tok") is True
        assert calls == ["PUT"]

    def test_204_but_user_not_in_guild_is_a_failure(self, monkeypatch):
        m = self._bot()

        class R:
            def __init__(self, code, payload):
                self.code, self.payload = code, payload

            def getcode(self): return self.code

            def read(self): return self.payload

            def __enter__(self): return self

            def __exit__(self, *a): return False

        monkeypatch.setattr(m.urllib.request, "urlopen",
                            lambda req, timeout=None: R(204, b""))
        monkeypatch.setattr(m, "discord_bot_is_member", lambda g, u: False)
        assert m.discord_bot_add_member("G1", "U1", "tok") is False, \
            "204 with Discord saying 404 means the join did not happen"

    def test_unverifiable_membership_is_not_claimed(self, monkeypatch):
        m = self._bot()

        class R:
            def __init__(self, code, payload):
                self.code, self.payload = code, payload

            def getcode(self): return self.code

            def read(self): return self.payload

            def __enter__(self): return self

            def __exit__(self, *a): return False

        monkeypatch.setattr(m.urllib.request, "urlopen",
                            lambda req, timeout=None: R(204, b""))
        monkeypatch.setattr(m, "discord_bot_is_member", lambda g, u: None)
        assert m.discord_bot_add_member("G1", "U1", "tok") is False, \
            "we could not check, so we must not report CONFIRMED"


class TestIsMemberLookup:
    def test_200_means_member(self, monkeypatch):
        m = _load()
        m.DISCORD_BOT_TOKEN = "t"

        class R:
            def getcode(self): return 200

            def __enter__(self): return self

            def __exit__(self, *a): return False

        monkeypatch.setattr(m.urllib.request, "urlopen",
                            lambda req, timeout=None: R())
        assert m.discord_bot_is_member("G1", "U1") is True

    def test_404_means_not_a_member(self, monkeypatch):
        m = _load()
        m.DISCORD_BOT_TOKEN = "t"

        def raise404(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {},
                                         io.BytesIO(b'{"message":"Unknown Member"}'))
        monkeypatch.setattr(m.urllib.request, "urlopen", raise404)
        assert m.discord_bot_is_member("G1", "U1") is False

    def test_other_errors_are_unknown_not_false(self, monkeypatch):
        m = _load()
        m.DISCORD_BOT_TOKEN = "t"

        def raise500(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {},
                                         io.BytesIO(b'{"message":"boom"}'))
        monkeypatch.setattr(m.urllib.request, "urlopen", raise500)
        assert m.discord_bot_is_member("G1", "U1") is None, \
            "a server error must not be reported as 'not in the guild'"

    def test_no_token_is_unknown(self):
        m = _load()
        m.DISCORD_BOT_TOKEN = ""
        assert m.discord_bot_is_member("G1", "U1") is None

    def test_add_member_logs_and_fails_loudly_on_403(self, monkeypatch, caplog):
        m = _load()
        m.DISCORD_BOT_TOKEN = "t"

        def raise403(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {},
                                         io.BytesIO(b'{"message":"Missing Permissions"}'))
        import urllib.error
        monkeypatch.setattr(m.urllib.request, "urlopen", raise403)
        with caplog.at_level("WARNING"):
            ok = m.discord_bot_add_member("G1", "U1", "tok")
        assert ok is False
        assert any("403" in r.message or "add-to-server" in r.message
                   for r in caplog.records), "failure must be logged, not silent"

    def test_send_message_posts_content(self, monkeypatch):
        m = _load()
        m.DISCORD_BOT_TOKEN = "t"
        seen = {}

        class R:
            def getcode(self): return 200
            def read(self): return b'{"id":"1"}'
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def ok(req, timeout=None):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["body"] = json.loads(req.data.decode())
            seen["auth"] = req.headers.get("Authorization")
            return R()
        monkeypatch.setattr(m.urllib.request, "urlopen", ok)
        assert m.discord_bot_send_message("C1", "hello staff") is True
        assert "/channels/C1/messages" in seen["url"]
        assert seen["method"] == "POST"
        assert seen["body"]["content"] == "hello staff"
        assert seen["auth"].startswith("Bot ")

    def test_long_message_is_truncated(self, monkeypatch):
        m = _load()
        m.DISCORD_BOT_TOKEN = "t"
        seen = {}

        class R:
            def getcode(self): return 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def ok(req, timeout=None):
            seen["body"] = json.loads(req.data.decode())
            return R()
        monkeypatch.setattr(m.urllib.request, "urlopen", ok)
        m.discord_bot_send_message("C1", "x" * 5000)
        assert len(seen["body"]["content"]) <= 2000, "Discord rejects >2000 chars"


import urllib.error  # noqa: E402  (used by the 403 test)

class TestClientIdMismatchIsVisible:
    """A stale DISCORD_CLIENT_ID sends admin login to a different Discord
    application, which fails as "invalid redirect_uri" and looks unrelated."""

    def _check(self, m, admin_id, user_id, monkeypatch=None):
        if monkeypatch is not None:
            monkeypatch.setenv("DISCORD_CLIENT_ID", admin_id)
            monkeypatch.delenv("DISCORD_CLIENT_ID", raising=False) \
                if admin_id == "" else None
        m.DISCORD_CLIENT_ID_USER = user_id
        m.DISCORD_BOT_TOKEN = ""
        return m.discord_bot_self_check()

    def test_reports_both_client_ids(self, monkeypatch):
        m = _load()
        out = self._check(m, "111", "222", monkeypatch)
        assert out["admin_login_client_id"] == "111"
        assert out["user_login_client_id"] == "222"

    def test_mismatch_is_flagged_as_a_problem(self, monkeypatch):
        m = _load()
        out = self._check(m, "111", "222", monkeypatch)
        joined = " ".join(out["problems"])
        assert "does not match" in joined
        assert "222" in joined

    def test_matching_ids_are_not_flagged(self, monkeypatch):
        m = _load()
        out = self._check(m, "222", "222", monkeypatch)
        assert not [p for p in out["problems"] if "does not match" in p]

    def test_unset_admin_id_is_not_flagged(self, monkeypatch):
        """DISCORD_CLIENT_ID is optional - the admin flow falls back to the
        request host, so its absence is not a mismatch."""
        m = _load()
        out = self._check(m, "", "222", monkeypatch)
        assert out["admin_login_client_id"] == ""
        assert not [p for p in out["problems"] if "does not match" in p]