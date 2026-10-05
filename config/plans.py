"""Subscription tiers, pricing and billing cycles - the single source of truth.

Every price in the product is computed here. Nothing else is allowed to
hard-code an amount: the pricing page, the checkout payload, the backend
entitlement record and the license expiry all read from these tables, so a
price can only ever be changed in one place.

Money is :class:`~decimal.Decimal` end to end. Binary floats cannot represent
0.83 exactly, so ``10 * 6 * 0.83`` drifts; ``Decimal`` keeps the displayed
total equal to the amount actually charged.

Tier hierarchy::

    FOUNDATION  (free)
        |
    PERFORMANCE  ($10 / month)
        |
    MAXIMUM     ($15 / month)

Higher tiers inherit every lower tier's features, so a tweak is gated by the
*lowest* tier that grants it and a Maximum subscriber reaches all of them.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

__all__ = [
    "FOUNDATION", "PERFORMANCE", "MAXIMUM", "PLAN_ORDER", "PLAN_RANK",
    "MONTHLY", "SIX_MONTHS", "ANNUAL", "CYCLE_ORDER", "CYCLE_MONTHS",
    "CYCLE_LABEL", "CYCLE_DISCOUNT", "CYCLE_BADGE", "CYCLE_DAYS",
    "CENTS", "monthly_price", "cycle_total", "effective_monthly",
    "pricing_rows", "price_matrix", "normalize_tier", "tier_rank",
    "allows", "inherits", "upgrade_path", "required_tier_label",
    "cycle_days", "verify",
]

# --------------------------------------------------------------------------
# Tiers
# --------------------------------------------------------------------------

FOUNDATION = "foundation"
PERFORMANCE = "performance"
MAXIMUM = "maximum"

#: Lowest tier first. Index in this tuple *is* the privilege rank.
PLAN_ORDER: tuple[str, ...] = (FOUNDATION, PERFORMANCE, MAXIMUM)

PLAN_RANK: dict[str, int] = {tier: i for i, tier in enumerate(PLAN_ORDER)}

PLAN_LABEL: dict[str, str] = {
    FOUNDATION: "Foundation",
    PERFORMANCE: "Performance",
    MAXIMUM: "Maximum",
}

PLAN_BLURB: dict[str, str] = {
    FOUNDATION: "Safe, broadly compatible optimizations for supported Windows gaming PCs.",
    PERFORMANCE: "Everything in Foundation, plus verified advanced optimizations.",
    MAXIMUM: "Everything in Foundation and Performance, plus the most advanced verified optimizations.",
}

# --------------------------------------------------------------------------
# Billing cycles
# --------------------------------------------------------------------------

MONTHLY = "monthly"
SIX_MONTHS = "six_months"
ANNUAL = "annual"

CYCLE_ORDER: tuple[str, ...] = (MONTHLY, SIX_MONTHS, ANNUAL)

#: How many months of access one payment buys.
CYCLE_MONTHS: dict[str, int] = {MONTHLY: 1, SIX_MONTHS: 6, ANNUAL: 12}

CYCLE_LABEL: dict[str, str] = {MONTHLY: "Monthly", SIX_MONTHS: "6 Months", ANNUAL: "Annual"}

#: Fractional discount off the undiscounted total. 17% on 6 months, 25% annual.
CYCLE_DISCOUNT: dict[str, Decimal] = {
    MONTHLY: Decimal("0"),
    SIX_MONTHS: Decimal("0.17"),
    ANNUAL: Decimal("0.25"),
}

#: What the pricing UI prints next to the cycle. Empty means "no discount".
CYCLE_BADGE: dict[str, str] = {
    MONTHLY: "",
    SIX_MONTHS: "17% OFF",
    ANNUAL: "25% OFF",
}

#: Days of access granted, used for licence expiry. Nominal, not exact - the
#: backend stores an explicit ``expires_at`` timestamp.
CYCLE_DAYS: dict[str, int] = {MONTHLY: 30, SIX_MONTHS: 180, ANNUAL: 365}

# --------------------------------------------------------------------------
# Prices
# --------------------------------------------------------------------------

#: USD price for one month of each tier. Foundation is free at every cycle.
MONTHLY_PRICE: dict[str, Decimal] = {
    FOUNDATION: Decimal("0"),
    PERFORMANCE: Decimal("10"),
    MAXIMUM: Decimal("15"),
}

CENTS = Decimal("0.01")
_CENT = Decimal("1.00")


def _money(value: Decimal) -> Decimal:
    """Quantize to whole cents, rounding half away from zero.

    Banker's rounding (``ROUND_HALF_EVEN``) would make 49.805 -> 49.80 while
    a customer expects 49.81, so half-up is used deliberately.
    """
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def monthly_price(tier: str) -> Decimal:
    """List price for one month of ``tier``."""
    return _money(MONTHLY_PRICE[normalize_tier(tier)])


def cycle_total(tier: str, cycle: str) -> Decimal:
    """Total charged today for ``tier`` paid up-front on ``cycle``.

    Derived from the monthly base price and the cycle's discount - never typed
    in directly, so the displayed total and the charged total cannot disagree.
    """
    tier = normalize_tier(tier)
    if cycle not in CYCLE_MONTHS:
        raise ValueError(f"unknown billing cycle: {cycle!r}")
    gross = MONTHLY_PRICE[tier] * CYCLE_MONTHS[cycle]
    return _money(gross * (_CENT - CYCLE_DISCOUNT[cycle]))


def effective_monthly(tier: str, cycle: str) -> Decimal:
    """Per-month cost once the cycle discount is spread over its months."""
    tier = normalize_tier(tier)
    months = CYCLE_MONTHS[cycle]
    if MONTHLY_PRICE[tier] == 0:
        return Decimal("0.00")
    return _money(cycle_total(tier, cycle) / months)


def price_matrix() -> dict[str, dict[str, Decimal]]:
    """``{cycle: {tier: total}}`` - the whole grid, for tests and the API."""
    return {
        cycle: {tier: cycle_total(tier, cycle) for tier in PLAN_ORDER}
        for cycle in CYCLE_ORDER
    }


def pricing_rows() -> list[dict]:
    """Row-per-plan pricing payload for the pricing UI.

    One row per tier, each carrying every cycle's total, so the billing
    selector can switch instantly without a round-trip and without any second
    place where a number could be mistyped.
    """
    rows = []
    for tier in PLAN_ORDER:
        rows.append({
            "tier": tier,
            "label": PLAN_LABEL[tier],
            "blurb": PLAN_BLURB[tier],
            "monthly": monthly_price(tier),
            "free": MONTHLY_PRICE[tier] == 0,
            "cycles": {
                cycle: {
                    "cycle": cycle,
                    "label": CYCLE_LABEL[cycle],
                    "badge": CYCLE_BADGE[cycle],
                    "months": CYCLE_MONTHS[cycle],
                    "total": cycle_total(tier, cycle),
                    "per_month": effective_monthly(tier, cycle),
                    "savings": _money(
                        MONTHLY_PRICE[tier] * CYCLE_MONTHS[cycle]
                        - cycle_total(tier, cycle)
                    ),
                    "days": CYCLE_DAYS[cycle],
                }
                for cycle in CYCLE_ORDER
            },
        })
    return rows


# --------------------------------------------------------------------------
# Tier logic
# --------------------------------------------------------------------------

def normalize_tier(value: object) -> str:
    """Coerce loose input to a valid tier id.

    Unknown values collapse to ``foundation`` rather than raising, so a corrupt
    or hand-edited entitlement record can never accidentally grant more than
    the free tier. Fail closed, always.
    """
    if not isinstance(value, str):
        return FOUNDATION
    key = value.strip().lower()
    if key in PLAN_RANK:
        return key
    aliases = {
        "free": FOUNDATION, "basic": FOUNDATION, "starter": FOUNDATION,
        "pro": PERFORMANCE, "performance_monthly": PERFORMANCE,
        "premium": MAXIMUM, "ultra": MAXIMUM, "max": MAXIMUM,
    }
    return aliases.get(key, FOUNDATION)


def tier_rank(tier: object) -> int:
    """Privilege rank; higher is more. Unknown input ranks as Foundation."""
    return PLAN_RANK[normalize_tier(tier)]


def allows(held: object, required: object) -> bool:
    """True when a subscriber on ``held`` may use a ``required``-tier feature."""
    return tier_rank(held) >= tier_rank(required)


def inherits(held: object) -> tuple[str, ...]:
    """Every tier granted by ``held``, lowest first."""
    return PLAN_ORDER[: tier_rank(held) + 1]


def upgrade_path(held: object, required: object) -> str | None:
    """The tier that should be sold when ``held`` is too low for ``required``.

    ``None`` when the subscriber already qualifies. This is what the UI prints
    as "Requires Maximum".
    """
    if allows(held, required):
        return None
    return normalize_tier(required)


def required_tier_label(required: object) -> str:
    """Human label for a gate, e.g. ``"Requires Performance"``."""
    return f"Requires {PLAN_LABEL[normalize_tier(required)]}"


def cycle_days(cycle: str) -> int:
    """Days of access a payment on ``cycle`` grants."""
    if cycle not in CYCLE_DAYS:
        raise ValueError(f"unknown billing cycle: {cycle!r}")
    return CYCLE_DAYS[cycle]


# --------------------------------------------------------------------------
# Self-verification
# --------------------------------------------------------------------------

#: Totals that must hold. Asserted by ``verify()`` so a careless edit to the
#: discount tables cannot silently ship a wrong price.
EXPECTED_TOTALS: dict[str, dict[str, str]] = {
    #          6 months (17% off)   annual (25% off)
    "foundation":   {"six_months": "0.00", "annual": "0.00"},
    "performance":  {"six_months": "49.80", "annual": "90.00"},
    "maximum":      {"six_months": "74.70", "annual": "135.00"},
}

EXPECTED_EFFECTIVE_MONTHLY: dict[str, dict[str, str]] = {
    "performance": {"six_months": "8.30", "annual": "7.50"},
    "maximum":     {"six_months": "12.45", "annual": "11.25"},
}


def verify() -> None:
    """Raise if any price, rank or inheritance rule is wrong.

    Cheap enough to call from the test suite, from the pricing page's build, and
    from the backend's startup.
    """
    # Base monthly prices.
    assert monthly_price(FOUNDATION) == Decimal("0.00"), "Foundation must be free"
    assert monthly_price(PERFORMANCE) == Decimal("10.00"), "Performance must be $10/mo"
    assert monthly_price(MAXIMUM) == Decimal("15.00"), "Maximum must be $15/mo"

    # Computed totals match the values shown to customers.
    for tier, by_cycle in EXPECTED_TOTALS.items():
        for cycle, want in by_cycle.items():
            got = cycle_total(tier, cycle)
            assert got == Decimal(want), (
                f"{tier}/{cycle}: computed {got}, expected {want}"
            )

    # Monthly is always the undiscounted base.
    for tier in PLAN_ORDER:
        assert cycle_total(tier, MONTHLY) == monthly_price(tier), tier

    # A longer cycle is never more expensive than paying month-to-month.
    for tier in PLAN_ORDER:
        rolling = monthly_price(tier) * CYCLE_MONTHS[SIX_MONTHS]
        assert cycle_total(tier, SIX_MONTHS) <= rolling, f"{tier} 6-month not discounted"
        rolling = monthly_price(tier) * CYCLE_MONTHS[ANNUAL]
        assert cycle_total(tier, ANNUAL) <= rolling, f"{tier} annual not discounted"

    # Discount labels agree with the discount actually applied.
    assert CYCLE_BADGE[SIX_MONTHS] == "17% OFF"
    assert CYCLE_BADGE[ANNUAL] == "25% OFF"
    assert CYCLE_DISCOUNT[SIX_MONTHS] == Decimal("0.17")
    assert CYCLE_DISCOUNT[ANNUAL] == Decimal("0.25")

    # Effective monthly figures.
    for tier, by_cycle in EXPECTED_EFFECTIVE_MONTHLY.items():
        for cycle, want in by_cycle.items():
            got = effective_monthly(tier, cycle)
            assert got == Decimal(want), (
                f"{tier}/{cycle} per-month: computed {got}, expected {want}"
            )

    # The retired $8 Performance price must not exist anywhere.
    for tier in PLAN_ORDER:
        for cycle in CYCLE_ORDER:
            total = cycle_total(tier, cycle)
            per_month = effective_monthly(tier, cycle)
            assert total != Decimal("8.00"), f"{tier}/{cycle} reintroduced $8"
            assert per_month != Decimal("8.00"), f"{tier}/{cycle} reintroduced $8"

    # Hierarchy.
    assert tier_rank(FOUNDATION) < tier_rank(PERFORMANCE) < tier_rank(MAXIMUM)
    assert allows(MAXIMUM, FOUNDATION) and allows(MAXIMUM, PERFORMANCE) and allows(MAXIMUM, MAXIMUM)
    assert allows(PERFORMANCE, FOUNDATION) and allows(PERFORMANCE, PERFORMANCE)
    assert not allows(PERFORMANCE, MAXIMUM)
    assert allows(FOUNDATION, FOUNDATION)
    assert not allows(FOUNDATION, PERFORMANCE)
    assert inherits(MAXIMUM) == (FOUNDATION, PERFORMANCE, MAXIMUM)
    assert inherits(PERFORMANCE) == (FOUNDATION, PERFORMANCE)
    assert inherits(FOUNDATION) == (FOUNDATION,)

    # Fails closed on junk input.
    for junk in ("", None, "enterprise", "MAXIMUM_PLUS", 123, object()):
        assert normalize_tier(junk) == FOUNDATION, f"{junk!r} did not fail closed"
    assert normalize_tier("MAXIMUM") == MAXIMUM
    assert normalize_tier(" Maximum ") == MAXIMUM

    # Gate labels.
    assert required_tier_label(PERFORMANCE) == "Requires Performance"
    assert required_tier_label(MAXIMUM) == "Requires Maximum"
    assert upgrade_path(FOUNDATION, PERFORMANCE) == PERFORMANCE
    assert upgrade_path(FOUNDATION, MAXIMUM) == MAXIMUM
    assert upgrade_path(PERFORMANCE, MAXIMUM) == MAXIMUM
    assert upgrade_path(MAXIMUM, FOUNDATION) is None

    # The pricing UI payload is complete and self-consistent.
    rows = pricing_rows()
    assert [r["tier"] for r in rows] == list(PLAN_ORDER)
    for row in rows:
        assert row["cycles"][MONTHLY]["total"] == row["monthly"], row["tier"]
        assert set(row["cycles"]) == set(CYCLE_ORDER)
        assert row["cycles"][ANNUAL]["savings"] >= 0, row["tier"]

    # Guard against a stale/duplicated 6-month-or-annual confusion.
    assert CYCLE_MONTHS[SIX_MONTHS] == 6 and CYCLE_DAYS[SIX_MONTHS] == 180
    assert CYCLE_MONTHS[ANNUAL] == 12 and CYCLE_DAYS[ANNUAL] == 365
