"""Checkout seam: builds a checkout request for any payment provider.

The point of this module is the *seam*, not a payment integration. It turns a
(tier, cycle) selection into a fully-priced, provider-neutral request that a
Stripe/Paddle/whatever adapter can fulfil, and it records that intent locally.

What it deliberately does NOT do:

  * It never contacts a payment provider.
  * It never takes card details. This app is a desktop binary that ships its own
    entitlement data, so handling a card number here would mean shipping PCI
    scope into every copy. Real payment happens on a hosted checkout page owned
    by the provider.
  * It never grants a tier. Entitlement comes from the server verifying a
    webhook, so nothing the client does can mint itself a paid feature.

Until a provider is chosen, :func:`begin_checkout` returns the request it built
and leaves the decision to the caller. That keeps the UI honest: it can show a
price and an intent without pretending a payment happened.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

from config.app_config import ROOT
from config.plans import (
    CYCLE_MONTHS, PLAN_LABEL, cycle_days, cycle_total, monthly_price,
    normalize_tier,
)

__all__ = [
    "CheckoutError", "CheckoutRequest", "begin_checkout", "pending_path",
    "read_pending", "clear_pending",
]

#: Orders are kept next to the app's other state so a crash between "clicked
#: pay" and "webhook arrived" is recoverable. One file, last order wins - the
#: desktop app only ever has one purchase in flight.
_ORDERS_DIR = Path(ROOT) / "state"


class CheckoutError(RuntimeError):
    """Raised when a checkout request cannot be built at all."""


@dataclass(frozen=True)
class CheckoutRequest:
    """A fully-priced, provider-neutral order.

    ``amount_cents`` is authoritative for what the customer is charged. It is
    derived from :func:`config.plans.cycle_total`, so the number the UI shows and
    the number sent to the provider cannot disagree.
    """

    order_id: str
    tier: str
    cycle: str
    months: int
    days: int
    amount: Decimal
    amount_cents: int
    currency: str = "USD"
    product_name: str = ""
    created_at: float = field(default_factory=time.time)
    provider: str | None = None
    checkout_url: str | None = None
    paid: bool = False
    #: Filled in by the webhook verifier, never by the client.
    entitlement_token: str | None = None

    def as_payload(self) -> dict:
        """JSON-safe dict for a provider API or a hosted-checkout redirect."""
        d = asdict(self)
        d["amount"] = str(self.amount)
        return d


def _to_cents(amount: Decimal) -> int:
    """Exact cents conversion. Never float, never ``int(amount * 100)``."""
    return int((amount * 100).quantize(Decimal("1")))


def build_request(tier: str, cycle: str, order_id: str | None = None) -> CheckoutRequest:
    """Price a (tier, cycle) selection. Pure: touches no network and no disk."""
    tier = normalize_tier(tier)
    if cycle not in CYCLE_MONTHS:
        raise CheckoutError(f"unknown billing cycle: {cycle!r}")

    total = cycle_total(tier, cycle)
    return CheckoutRequest(
        order_id=order_id or f"MT-{uuid.uuid4().hex[:16].upper()}",
        tier=tier,
        cycle=cycle,
        months=CYCLE_MONTHS[cycle],
        days=cycle_days(cycle),
        amount=total,
        amount_cents=_to_cents(total),
        product_name=f"{PLAN_LABEL[tier]} \u2014 {cycle.replace('_', ' ')}",
    )


def pending_path() -> Path:
    return _ORDERS_DIR / "pending_order.json"


def read_pending() -> dict | None:
    """The in-flight order, if any. Never raises on a corrupt file."""
    try:
        return json.loads(pending_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clear_pending() -> None:
    try:
        pending_path().unlink()
    except OSError:
        pass


def begin_checkout(tier: str, cycle: str, provider: str | None = None) -> CheckoutRequest:
    """Build the order and record it as pending.

    ``provider`` is the name of an adapter that will fulfil the order. No
    adapter ships yet, so this only stamps the request: the return value is a
    priced intent, and ``paid`` stays False until a server-side webhook sets it.

    Nothing here can raise a tier. Even for a free plan this produces a
    zero-amount order rather than silently activating anything, because
    entitlement is granted server-side only.
    """
    req = build_request(tier, cycle)
    if provider:
        req = CheckoutRequest(**{**asdict(req), "provider": provider})
    _ORDERS_DIR.mkdir(parents=True, exist_ok=True)
    pending_path().write_text(
        json.dumps(req.as_payload(), indent=2), encoding="utf-8")
    return req


def describe_selection(tier: str, cycle: str) -> dict:
    """UI-facing summary of a selection, with no side effects."""
    req = build_request(tier, cycle)
    per_month = monthly_price(tier)
    return {
        "tier": req.tier,
        "label": PLAN_LABEL[req.tier],
        "cycle": req.cycle,
        "cycle_label": req.cycle.replace("_", " ").title(),
        "total": req.amount,
        "amount_cents": req.amount_cents,
        "per_month": per_month,
        "months": req.months,
        "days": req.days,
        "free": req.amount == 0,
    }
