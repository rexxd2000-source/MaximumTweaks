"""Unit tests for the pluggable waitlist mailer (mailers.py).

Fast and DB-free: these exercise the factory and the Resend provider by
monkeypatching urllib — nothing is ever sent and no secrets are required.
"""
from __future__ import annotations

import json
import urllib.error

import pytest

from mailers import LogProvider, MailerError, ResendProvider, get_mailer, reset_mailer

URLOPEN = "urllib.request.urlopen"


@pytest.fixture(autouse=True)
def _fresh_mailer():
    reset_mailer()
    yield
    reset_mailer()


def test_factory_defaults_to_log():
    assert isinstance(get_mailer(), LogProvider)


def test_factory_resend_without_key_falls_back_to_log(monkeypatch):
    monkeypatch.setenv("WAITLIST_MAILER", "resend")
    monkeypatch.delenv("WAITLIST_RESEND_API_KEY", raising=False)
    assert isinstance(get_mailer(), LogProvider)


def test_factory_resend_with_key(monkeypatch):
    monkeypatch.setenv("WAITLIST_MAILER", "resend")
    monkeypatch.setenv("WAITLIST_RESEND_API_KEY", "re_test")
    assert isinstance(get_mailer(), ResendProvider)


def test_resend_send_success(monkeypatch):
    captured = {}

    class FakeResp:
        def read(self):
            return b'{"id":"abc"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["auth"] = request.get_header("Authorization")
        captured["ua"] = any(k.lower() == "user-agent" for k in request.headers)
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr(URLOPEN, fake_urlopen)
    provider = ResendProvider("re_test", "Maximum Optimizations <n@x.za>")
    result = provider.send("user@example.com", "Subject", "text body",
                           "<b>html</b>")
    assert result == {"ok": True, "provider": "resend"}
    assert captured["auth"] == "Bearer re_test"
    assert captured["ua"]  # Resend rejects requests without User-Agent (403/1010)
    assert captured["body"]["to"] == ["user@example.com"]
    assert captured["body"]["subject"] == "Subject"
    assert captured["body"]["text"] == "text body"
    assert captured["body"]["html"] == "<b>html</b>"
    assert captured["body"]["from"] == "Maximum Optimizations <n@x.za>"


def test_resend_send_raises_on_http_error(monkeypatch):
    import io

    payload = io.BytesIO(b'{"message":"from not verified"}')

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            "https://api.resend.com/emails", 403, "Forbidden", {}, payload)

    monkeypatch.setattr(URLOPEN, fake_urlopen)
    provider = ResendProvider("re_test", "Bad <bad@nope.com>")
    with pytest.raises(MailerError) as exc:
        provider.send("user@example.com", "Subject", "body")
    assert "resend rejected" in str(exc.value)
    assert "403" in str(exc.value)


def test_resend_send_raises_on_network_error(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(URLOPEN, fake_urlopen)
    provider = ResendProvider("re_test", "x <x@n.za>")
    with pytest.raises(MailerError) as exc:
        provider.send("user@example.com", "Subject", "body")
    assert "network error" in str(exc.value)


def test_resend_send_inlines_logo(monkeypatch):
    captured = {}

    class FakeResp:
        def read(self):
            return b'{"id":"abc"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr(URLOPEN, fake_urlopen)
    import os
    logo = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "assets", "logo.png")
    provider = ResendProvider("re_test", "x <x@n.za>", logo_path=logo)
    result = provider.send("user@example.com", "Subject", "body",
                           "<!--LOGO--><h1>Hi</h1>")
    assert result == {"ok": True, "provider": "resend"}
    assert captured["body"]["html"] == (
        '<img src="cid:logo" alt="Maximum Optimizations" '
        'style="display:block;height:44px;width:auto;'
        'margin:0 0 18px;"><h1>Hi</h1>')
    att = captured["body"]["attachments"][0]
    assert att["disposition"] == "inline"
    assert att["content_id"] == "logo"
    assert att["filename"] == "logo.png"
    assert att["content"]


def test_resend_send_without_logo_clears_marker(monkeypatch):
    captured = {}

    class FakeResp:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr(URLOPEN, fake_urlopen)
    provider = ResendProvider("re_test", "x <x@n.za>", logo_path="")
    provider.send("user@example.com", "Subject", "body",
                  "<!--LOGO--><h1>Hi</h1>")
    assert captured["body"]["html"] == "<h1>Hi</h1>"
    assert "attachments" not in captured["body"]