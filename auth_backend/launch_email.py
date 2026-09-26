from __future__ import annotations

"""Launch-announcement email for the Ultra Mode waitlist.

Every piece of the eventual launch email is customizable, in ascending
priority:

  1. hard-coded defaults below,
  2. environment overrides (WAITLIST_SUBJECT / WAITLIST_HEADING /
     WAITLIST_MESSAGE / WAITLIST_CTA / WAITLIST_CTA_URL, set server-side),
  3. per-send overrides: the admin send-launch endpoint accepts the same
     fields in its JSON body, which win over both of the above.

Every recipient email carries a one-click unsubscribe link
(``GET /api/waitlist/unsubscribe?token=...``) so launch mail can be stopped
without contacting support. Emails are never sent without one.
"""

import html
import logging
import os

from mailers import MailerError

logger = logging.getLogger("maxtweaks.license.waitlist")

# Brand colours reused on the dashboard site.
LAVENDER = "#9c86f5"
DARK_BG = "#120f1c"
INK = "#1b1826"

DEFAULTS = {
    # Subject line of the launch email.
    "subject": "You're invited — Ultra Mode is ready",
    # Big heading inside the email.
    "heading": "Ultra Mode is ready.",
    # Body paragraph.
    "message": (
        "Thanks for joining the waitlist. Ultra Mode — the single-click "
        "tuning preset that pushes clocks and fan curves to their tested "
        "ceiling — is now available in Maximum Tweaks."),
    # CTA button label and where it points.
    "cta_button": "Get Ultra Mode",
    "cta_url": "https://maximumtweaks.onrender.com",
    # Sender shown in the mail client.
    "from_address": "Maximum Optimizations <maxoptimizations@gmail.com>",
    # Base URL used to build the per-recipient unsubscribe link.
    "base_url": "https://maximumtweaks.onrender.com",
}

_ENV_KEYS = {
    "subject": "WAITLIST_SUBJECT",
    "heading": "WAITLIST_HEADING",
    "message": "WAITLIST_MESSAGE",
    "cta_button": "WAITLIST_CTA",
    "cta_url": "WAITLIST_CTA_URL",
    "from_address": "WAITLIST_FROM",
    "base_url": "WAITLIST_BASE_URL",
}

# Fields the admin send-launch endpoint may override per-send.
OVERRIDABLE = ("subject", "heading", "message", "cta_button", "cta_url")


def content(overrides: dict | None = None) -> dict:
    """Merge defaults -> env -> per-send overrides into one content dict."""
    merged = dict(DEFAULTS)
    for key, env_name in _ENV_KEYS.items():
        value = os.environ.get(env_name)
        if value is not None and str(value).strip():
            merged[key] = value.strip()
    if overrides:
        for key in OVERRIDABLE:
            value = overrides.get(key)
            if isinstance(value, str) and value.strip():
                merged[key] = value.strip()
    return merged


def unsubscribe_url(token: str, base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if not base:
        base = DEFAULTS["base_url"]
    return f"{base}/api/waitlist/unsubscribe?token={token}"


def render(overrides: dict | None = None, unsub_url: str = "") -> dict:
    """Return {"subject", "text", "html"} for a launch email.

    ``unsub_url`` carries the per-recipient unsubscribe link and is always
    included — a launch email without one is a bug.
    """
    c = content(overrides)
    text = (
        f"{c['heading']}\n\n"
        f"{c['message']}\n\n"
        f"{c['cta_button']}: {c['cta_url']}\n"
        f"\n------------------------------------------------------------------\n"
        f"Unsubscribe from launch updates: {unsub_url}"
    )
    if not unsub_url:
        unsub_url = "https://maximumtweaks.onrender.com"
    html = _html(c, unsub_url)
    return {"subject": c["subject"], "action_url": c["cta_url"],
            "text": text, "html": html}


def _html(c: dict, unsub_url: str) -> str:
    heading = html.escape(c["heading"])
    message = html.escape(c["message"])
    cta_label = html.escape(c["cta_button"])
    cta_url = html.escape(c["cta_url"])
    unsub = html.escape(unsub_url)
    return f"""\
<!DOCTYPE html>
<html lang="en">
<body style="margin:0;padding:0;background:{DARK_BG};font-family:-apple-system,
  'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
    style="background:{DARK_BG};">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
          style="max-width:520px;width:100%;background:#ffffff;border-radius:16px;
          overflow:hidden;">
          <tr>
            <td style="height:6px;background:{LAVENDER};"></td>
          </tr>
          <tr>
            <td style="padding:36px 32px 12px;">
              <h1 style="margin:0 0 10px;font-size:22px;line-height:1.25;
                color:{INK};font-weight:800;">{heading}</h1>
              <p style="margin:0 0 22px;font-size:15px;line-height:1.6;
                color:#3c3950;">{message}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 28px;">
              <table role="presentation" cellspacing="0" cellpadding="0">
                <tr>
                  <td style="border-radius:10px;background:{LAVENDER};">
                    <a href="{cta_url}" style="display:inline-block;padding:12px 22px;
                      font-size:14px;font-weight:700;color:#0d0a1a;text-decoration:none;">
                      {cta_label}&nbsp;&rarr;</a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 34px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td style="border-top:1px solid #ece6ff;padding:18px 0 0;
                    font-size:11.5px;line-height:1.6;color:#8a86a3;">
                    Maximum Optimizations &middot; Powered by Maximum Tweaks<br>
                    You are receiving this because you joined the
                    <strong>Ultra Mode waitlist</strong>.<br>
                    <a href="{unsub}" style="color:#8a86a3;text-decoration:underline;">
                      Unsubscribe from launch updates</a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_launch(db, mailer, overrides: dict | None = None) -> dict:
    """Email every subscribed waitlist address and stamp them notified.

    ``db`` is a LicenseDB, ``mailer`` an EmailProvider. Returns per-send
    stats; a failing recipient is reported and left un-notified (so it is
    retried next time). The mailer decides subject/text/html from
    ``overrides`` (per-send) + env + defaults.
    """
    c = content(overrides)
    rows = db.waitlist_list(subscribed_only=True)
    base_url = c.get("base_url", DEFAULTS["base_url"])
    sent_ids: list[int] = []
    failed: list[dict] = []
    for rec in rows:
        unsub = unsubscribe_url(rec["unsub_token"], base_url)
        body = render(overrides, unsub)
        try:
            mailer.send(rec["email"], body["subject"], body["text"], body["html"])
            sent_ids.append(rec["id"])
        except MailerError as exc:
            logger.error("waitlist launch failed for %s: %s", rec["email"], exc)
            failed.append({"email": rec["email"], "error": str(exc)})
    notified = db.waitlist_mark_notified(sent_ids)
    logger.info(
        "waitlist launch finished: %d/%d sent, %d failed (stamped %d)",
        len(sent_ids), len(rows), len(failed), notified)
    return {
        "total": len(rows),
        "sent": len(sent_ids),
        "failed": len(failed),
        "notified": notified,
        "failures": failed[:50],
    }