"""Desktop Discord sign-in worker (``ui/license.py``).

Three defects made a successful Discord login look broken:

* the session stored the literal placeholder ``"FOUNDATION-DISCORD"`` as its
  licence, so the minute-by-minute heartbeat posted it to
  ``/api/license/checkin``, the server answered ``invalid_license``, and the
  client cleared the session and relocked the app about a minute later;
* the poll window was 30 seconds, far too short for choosing an account and
  completing 2FA; and
* the worker only understood ``ok`` / ``denied`` / ``expired``, so the
  specific failure reasons the server returns were discarded and the user saw
  a bare "timed out".

The worker is exercised by extracting its ``run`` method with ``ast`` and
executing it against stubs, so PyQt is not needed to run the suite.
"""
import ast
import json
import textwrap
import types

import pytest


SRC_PATH = ("ui", "license.py")
CLASS_NAME = "LicenseDiscordWorker"


def _worker_source():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # tests/ -> auth_backend/ -> repo root
    root = os.path.dirname(root)
    path = os.path.join(root, *SRC_PATH)
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == CLASS_NAME)
    fn = next(n for n in cls.body
              if isinstance(n, ast.FunctionDef) and n.name == "run")
    fn.decorator_list = []
    return textwrap.dedent(ast.get_source_segment(src, fn))


class _Harness:
    """Runs the worker's real ``run`` body against stubbed HTTP + clock."""

    def __init__(self, monkeypatch, *, poll_seq, start=None):
        self._clock = {"t": 0.0}
        self._poll_seq = poll_seq
        self._start = {"ok": True, "url": "https://discord.com/oauth2/authorize",
                       "state": "state123"} if start is None else start
        self._polls = 0
        self.sessions = {}
        self.emitted = []
        self.opened = []
        #: Poll indexes that raise instead of answering (network blips).
        self.fail_on = set()
        self.fail_start = False
        self._install(monkeypatch)

    def _install(self, monkeypatch):
        clock = self._clock
        fake_time = types.ModuleType("time")
        fake_time.monotonic = lambda: clock["t"]
        fake_time.sleep = lambda s: clock.__setitem__("t", clock["t"] + s)
        monkeypatch.setitem(__import__("sys").modules, "time", fake_time)

        sessions = self.sessions
        license_mgr = types.ModuleType("engine.license")
        license_mgr.set_session = lambda s: sessions.update(s)
        engine = types.ModuleType("engine")
        engine.license = license_mgr
        for name, mod in (("engine", engine),
                          ("engine.license", license_mgr)):
            monkeypatch.setitem(__import__("sys").modules, name, mod)

        import urllib.request as real_request
        polls = {"n": 0}
        self._polls = polls

        class _Resp:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        fail_on = self.fail_on

        def _urlopen(req, timeout=None):
            url = getattr(req, "full_url", req)
            if "/auth/discord/poll/" in url:
                i = polls["n"]
                polls["n"] += 1
                if i in fail_on:
                    raise OSError("simulated network blip")
                return _Resp(self._poll_seq[min(i, len(self._poll_seq) - 1)])
            if "/auth/discord/start" in url:
                if self.fail_start:
                    raise OSError("simulated start failure")
                return _Resp(self._start)
            raise AssertionError("unexpected request: %s" % url)

        fake_request = types.ModuleType("urllib.request")
        fake_request.Request = real_request.Request
        fake_request.urlopen = _urlopen
        fake_request.parse = types.SimpleNamespace(
            quote=__import__("urllib.parse", fromlist=["quote"]).quote)
        monkeypatch.setitem(__import__("sys").modules, "urllib.request",
                            fake_request)
        # The worker does `import urllib.request`; make that resolve too.
        monkeypatch.setitem(__import__("sys").modules, "urllib",
                            types.SimpleNamespace(request=fake_request,
                                                  parse=fake_request.parse))

        import webbrowser
        monkeypatch.setattr(webbrowser, "open", self.opened.append)
        monkeypatch.setenv("AUTH_API_URL", "https://maximumtweaks.onrender.com")

    def run(self):
        # Reuse the real body verbatim; only the QThread base is faked so the
        # suite runs without PyQt installed.
        src = "class _W:\n" + textwrap.indent(_worker_source(), "    ")
        ns = {}
        exec(src, {}, ns)
        worker = ns["_W"]()

        sink = self.emitted

        class Done:
            def connect(self, fn):
                self._fn = fn

            def emit(self, *a):
                sink.append(a)

        worker.done = Done()
        worker.run()
        assert sink, "worker never emitted a result"
        return sink[0]


OK_POLL = {"ok": True, "status": "ok",
           "discord_id": "1545177212255346784",
           "username": "rex2yd.", "account_id": "MO-1D887C"}


class TestSessionEntitlement:
    """The heartbeat posts ``session["license"]`` to /api/license/checkin, so
    it has to be an entitlement the server can resolve."""

    def test_uses_resolvable_discord_entitlement(self, monkeypatch):
        h = _Harness(monkeypatch, poll_seq=[OK_POLL])
        status, _msg, _sess = h.run()
        assert status == "ok"
        assert h.sessions["license"] == "DISCORD:1545177212255346784"
        assert "FOUNDATION-DISCORD" not in h.sessions["license"]

    def test_carries_identity_and_tier(self, monkeypatch):
        h = _Harness(monkeypatch, poll_seq=[OK_POLL])
        h.run()
        assert h.sessions["discord_id"] == "1545177212255346784"
        assert h.sessions["account_id"] == "MO-1D887C"
        assert h.sessions["tier"] == "foundation"
        assert h.sessions["owner"] == "rex2yd."

    def test_opens_the_authorize_url(self, monkeypatch):
        h = _Harness(monkeypatch, poll_seq=[OK_POLL])
        h.run()
        assert h.opened and "discord.com" in h.opened[0]


class TestFailureReasons:
    def test_server_error_reason_shown(self, monkeypatch):
        h = _Harness(monkeypatch, poll_seq=[
            {"ok": True, "status": "error",
             "reason": "The server's Discord app credentials are incorrect."}])
        status, msg, _ = h.run()
        assert status == "error"
        assert "credentials are incorrect" in msg

    def test_denied_explains_itself(self, monkeypatch):
        h = _Harness(monkeypatch,
                     poll_seq=[{"ok": True, "status": "denied"}])
        status, msg, _ = h.run()
        assert status == "error"
        assert "cancel" in msg.lower() or "expired" in msg.lower()

    def test_expired_explains_itself(self, monkeypatch):
        h = _Harness(monkeypatch,
                     poll_seq=[{"ok": True, "status": "expired"}])
        status, msg, _ = h.run()
        assert status == "error"
        assert "expired" in msg.lower() or "cancel" in msg.lower()

    def test_unavailable_start_endpoint(self, monkeypatch):
        h = _Harness(monkeypatch, poll_seq=[OK_POLL],
                     start={"ok": False, "url": "", "state": ""})
        status, msg, _ = h.run()
        assert status == "error"
        assert msg

    def test_waiting_is_not_treated_as_failure(self, monkeypatch):
        h = _Harness(monkeypatch, poll_seq=[
            {"ok": True, "status": "waiting"}] * 3 + [OK_POLL])
        status, _msg, _ = h.run()
        assert status == "ok"


class TestPollWindow:
    def test_waits_long_enough_for_a_human(self, monkeypatch):
        """Choosing an account and passing 2FA can take minutes."""
        h = _Harness(monkeypatch,
                     poll_seq=[{"ok": True, "status": "waiting"}] * 200
                     + [OK_POLL])
        status, _msg, _ = h.run()
        assert status == "ok"
        assert h._polls["n"] >= 120, (
            "the old loop gave up after 60 polls and reported a misleading "
            "'timed out'")

    def test_eventual_timeout_is_reported(self, monkeypatch):
        h = _Harness(monkeypatch,
                     poll_seq=[{"ok": True, "status": "waiting"}])
        status, msg, _ = h.run()
        assert status == "error"
        assert "timed out" in msg.lower()
    def test_eventual_timeout_is_reported(self, monkeypatch):
        h = _Harness(monkeypatch,
                     poll_seq=[{"ok": True, "status": "waiting"}])
        status, msg, _ = h.run()
        assert status == "error"
        assert "timed out" in msg.lower()

    def test_transient_network_blip_does_not_abort(self, monkeypatch):
        """A single failed poll must not look like a rejected sign-in.

        Render cold-starts and the user's network drops; both raise here and
        the worker should keep waiting instead of reporting a failure.
        """
        seq = [{"ok": True, "status": "waiting"}] * 5
        h = _Harness(monkeypatch, poll_seq=seq)
        h.fail_on = {2, 4}
        h.run()
        assert h._polls["n"] > 5, "worker gave up at the first network error"

    def test_start_endpoint_network_error_is_surfaced(self, monkeypatch):
        h = _Harness(monkeypatch, poll_seq=[OK_POLL])
        h.fail_start = True
        status, msg, _ = h.run()
        assert status == "error"
        assert msg