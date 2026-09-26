from __future__ import annotations

"""Modular email delivery for the Ultra Mode waitlist.

The point of this module is that the provider is swappable: nothing else may
ever talk to SMTP or a mail API directly. The factory reads
``WAITLIST_MAILER``:

  * ``log`` (default) — every send is written to the log but nothing leaves
    the server. Use this while the launch mailer is being set up, or to
    review copy before delivery goes live.
  * ``smtp`` — TLS SMTP via the env vars below (a Gmail "app password" works
    for maxoptimizations@gmail.com).
  * ``resend`` — Resend's HTTP API (best deliverability for launch blasts).
    Set ``WAITLIST_RESEND_API_KEY``; the from-address must be on a domain
    you have verified in Resend — see ``WAITLIST_FROM_EMAIL``.

The send-from address is ``WAITLIST_FROM_EMAIL`` (default
``maxoptimizations@gmail.com``). Credentials/addresses are read from the
environment at send time — never embedded, never committed, never bundled
into the desktop app.
"""

import json
import logging
import os
import smtplib
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("maxtweaks.license.mailer")


class MailerError(Exception):
    """Raised when a provider fails to deliver a message."""


class EmailProvider:
    """Small interface every provider implements."""

    name = "base"

    def send(self, to_email: str, subject: str, body_text: str,
             body_html: str | None = None) -> dict:
        """Deliver one email. Returns {"ok": True} or raises MailerError."""
        raise NotImplementedError


class LogProvider(EmailProvider):
    """Writes every would-be email to the log without sending anything."""

    name = "log"

    def __init__(self, from_address: str) -> None:
        self._from = from_address

    def send(self, to_email: str, subject: str, body_text: str,
             body_html: str | None = None) -> dict:
        logger.info(
            "mailer[log] would-send from=%s to=%s subject=%r",
            self._from, to_email, subject)
        logger.info("mailer[log] body:\n%s", body_text)
        return {"ok": True, "provider": self.name}


class SmtpProvider(EmailProvider):
    """TLS SMTP delivery (works with Gmail app passwords)."""

    name = "smtp"

    def __init__(self, host: str, port: int, username: str, password: str,
                 from_address: str, use_tls: bool = True) -> None:
        self._host = host
        self._port = port
        self._user = username
        self._password = password
        self._from = from_address
        self._tls = use_tls

    def send(self, to_email: str, subject: str, body_text: str,
             body_html: str | None = None) -> dict:
        msg = MIMEMultipart("alternative")
        msg["From"] = self._from
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        if body_html:
            msg.attach(MIMEText(body_html, "html", "utf-8"))
        try:
            with smtplib.SMTP(self._host, self._port, timeout=30) as server:
                server.ehlo()
                if self._tls:
                    server.starttls()
                    server.ehlo()
                server.login(self._user, self._password)
                server.sendmail(self._from, [to_email], msg.as_string())
        except (smtplib.SMTPException, OSError) as exc:
            raise MailerError(f"smtp delivery failed: {exc}") from exc
        return {"ok": True, "provider": self.name}


class ResendProvider(EmailProvider):
    """Resend (https://resend.com) via its HTTP API. Bulk-grade deliverability
    without running our own SMTP. The API key lives in the environment
    (WAITLIST_RESEND_API_KEY, format ``re_...``) and is never logged."""

    name = "resend"
    API_ENDPOINT = "https://api.resend.com/emails"
    _HTTP_TIMEOUT = 30.0

    def __init__(self, api_key: str, from_address: str) -> None:
        self._key = api_key
        self._from = from_address

    def send(self, to_email: str, subject: str, body_text: str,
             body_html: str | None = None) -> dict:
        payload = {
            "from": self._from,
            "to": [to_email],
            "subject": subject,
            "text": body_text,
        }
        if body_html:
            payload["html"] = body_html
        request = urllib.request.Request(
            self.API_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
            method="POST")
        try:
            with urllib.request.urlopen(request,
                                        timeout=self._HTTP_TIMEOUT) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise MailerError(
                f"resend rejected the email ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise MailerError(f"resend network error: {exc}") from exc
        return {"ok": True, "provider": self.name}


def _build_mailer() -> EmailProvider:
    kind = (os.environ.get("WAITLIST_MAILER", "log") or "log").strip().lower()
    from_address = os.environ.get(
        "WAITLIST_FROM_EMAIL", "maxoptimizations@gmail.com").strip()
    if kind == "smtp":
        host = os.environ.get("WAITLIST_SMTP_HOST", "").strip()
        port = int(os.environ.get("WAITLIST_SMTP_PORT", "587") or "587")
        user = os.environ.get("WAITLIST_SMTP_USER", "").strip()
        password = os.environ.get("WAITLIST_SMTP_PASSWORD", "")
        if not (host and user and password):
            logger.warning(
                "WAITLIST_MAILER=smtp but SMTP env not set; falling back"
                " to the log mailer")
            kind = "log"
        else:
            return SmtpProvider(host, port, user, password, from_address)
    if kind == "resend":
        api_key = os.environ.get("WAITLIST_RESEND_API_KEY", "").strip()
        if not api_key:
            logger.warning(
                "WAITLIST_MAILER=resend but WAITLIST_RESEND_API_KEY not"
                " set; falling back to the log mailer")
            kind = "log"
        else:
            return ResendProvider(api_key, from_address)
    return LogProvider(from_address)


_MAILER: EmailProvider | None = None


def get_mailer() -> EmailProvider:
    """Return the configured provider, building it once per process."""
    global _MAILER
    if _MAILER is None:
        _MAILER = _build_mailer()
    return _MAILER


def reset_mailer() -> None:
    """Forget the cached provider (used by tests)."""
    global _MAILER
    _MAILER = None