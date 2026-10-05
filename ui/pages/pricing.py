"""Pricing page: the three subscription plans and the locked-feature summary.

Every amount on this page comes from :mod:`config.plans`, so there is exactly
one place a price can be edited. The page reads the current entitlement from
:mod:`engine.entitlements` and renders each plan as either "your plan" or
"locked", with the concrete count of optimizations that stay out of reach.

The counts come from the live tweak catalogue, not a hand-written feature list,
so the page cannot advertise a feature set that disagrees with what the app
actually gates.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from config.app_config import THEME as T
from config.checkout import CheckoutError, begin_checkout, describe_selection
from config.plans import (
    CYCLE_LABEL, CYCLE_ORDER, PLAN_LABEL, PLAN_ORDER, pricing_rows, tier_rank,
)
from database.tweaks import TWEAKS
from engine.entitlements import current_tier, entitlement_summary

_ACCENT = {tier: key for tier, key in zip(
    PLAN_ORDER, ("blue", "purple", "accent"))}


def _label(text: str, size: int = 12, color: str | None = None,
           bold: bool = False, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setFont(QFont("Segoe UI", size,
                      QFont.Weight.DemiBold if bold else QFont.Weight.Normal))
    if color:
        lab.setStyleSheet(f"color:{color};")
    if wrap:
        lab.setWordWrap(True)
    return lab


def _money(value) -> str:
    """Format a Decimal without ever routing it through a float."""
    return f"${value:,.2f}"


class PlanCard(QFrame):
    """One plan: price, per-cycle totals, counts, and CTA state.

    A cycle toggle lives on each card rather than once at the top: the price a
    customer cares about is the cycle total, so the selection has to sit next to
    the number it changes.
    """

    def __init__(self, tier: str, cycle_rows: dict, held: str, counts: dict,
                 locked: dict, parent=None):
        super().__init__(parent)
        self.tier = tier
        self.cycle = CYCLE_ORDER[0]
        self._held = held
        self.is_held = held == tier
        self.is_locked = tier_rank(held) < tier_rank(tier)

        accent = T[_ACCENT[tier]]
        self.setStyleSheet(f"""
            QFrame {{
                background:{T['card']};
                border:{'2' if self.is_held else '1'}px solid
                        {accent if self.is_held else T['border']};
                border-radius:14px;
            }}
        """)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(270)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_label(PLAN_LABEL[tier], 16, accent, bold=True))
        if self.is_held:
            head.addWidget(_label("YOUR PLAN", 9, T["success"], bold=True))
        elif self.is_locked:
            head.addWidget(_label("LOCKED", 9, T["text_dim"], bold=True))
        head.addStretch(1)
        lay.addLayout(head)

        lay.addWidget(_label(cycle_rows["blurb"], 11, T["text_dim"], wrap=True))

        self.price_label = _label("", 30, T["text"], bold=True)
        lay.addWidget(self.price_label)

        self.cycle_row = QHBoxLayout()
        self.cycle_row.setSpacing(6)
        self._cycle_buttons: dict[str, QLabel] = {}
        for cycle in CYCLE_ORDER:
            cap = QLabel(CYCLE_LABEL[cycle])
            cap.setAlignment(Qt.AlignCenter)
            cap.setCursor(Qt.PointingHandCursor)
            cap.setFixedHeight(30)
            cap.mousePressEvent = lambda _e, c=cycle: self._choose_cycle(c)
            self._cycle_buttons[cycle] = cap
            self.cycle_row.addWidget(cap)
        lay.addLayout(self.cycle_row)

        self.terms_label = _label("", 11, T["text_dim"], wrap=True)
        lay.addWidget(self.terms_label)

        # Inherited tiers are spelled out so "Performance" is never ambiguous
        # about whether it includes Foundation.
        lay.addWidget(_label(self._feature_text(counts), 11, T["text_dim"],
                             wrap=True))

        note = locked.get(tier, 0)
        if self.is_held:
            self.cta = _label("Active on this PC", 12, T["success"], bold=True)
        elif self.is_locked:
            self.cta = _label(
                f"Unlocks {note} optimization{'s' if note != 1 else ''}",
                11, T["text_dim"], bold=True)
        else:
            self.cta = _label("Included in your plan", 11, T["text_faint"])
        lay.addWidget(self.cta)
        lay.addStretch(1)

        self._refresh(cycle_rows)

    def _feature_text(self, counts: dict) -> str:
        idx = list(_ACCENT).index(self.tier)
        inherited = [PLAN_LABEL[t] for t in list(_ACCENT)[:idx]]
        starts = counts.get(self.tier, 0)
        parts = [f"{starts} optimization"
                 f"{'s' if starts != 1 else ''} start at this tier"]
        if inherited:
            parts.append("includes all of " + ", ".join(inherited))
        return "\n".join(parts)

    def _choose_cycle(self, cycle: str) -> None:
        self.cycle = cycle
        self._refresh(self._cycle_rows)

    def _refresh(self, cycle_rows: dict) -> None:
        self._cycle_rows = cycle_rows
        c = cycle_rows[self.cycle]
        sel = describe_selection(self.tier, self.cycle)

        if sel["free"]:
            self.price_label.setText("FREE")
            self.terms_label.setText("No card required, no expiry.")
        else:
            self.price_label.setText(f"{_money(sel['per_month'])}/mo")
            badge = f"  \u00b7 {c['badge']}" if c["badge"] else ""
            if sel["cycle"] == "monthly":
                self.terms_label.setText(f"Billed monthly{badge}")
            else:
                self.terms_label.setText(
                    f"{_money(c['total'])} billed once for "
                    f"{sel['cycle_label'].lower()} \u00b7 "
                    f"{_money(c['per_month'])}/mo equivalent{badge}")

        accent = T[_ACCENT[self.tier]]
        for cycle, btn in self._cycle_buttons.items():
            active = cycle == self.cycle
            btn.setStyleSheet(
                f"background:{accent if active else T['card_alt']};"
                f"color:{T['bg'] if active else T['text_dim']};"
                f"border:1px solid {accent if active else T['border']};"
                f"border-radius:8px;"
                f"font-weight:{'600' if active else '400'};")


class PricingPage(QWidget):
    """The three plans, plus what the current subscription unlocks."""

    def __init__(self, ctx=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.held = current_tier()
        self.summary = entitlement_summary(TWEAKS, held=self.held)

        rows = {r["tier"]: r for r in pricing_rows()}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        outer.addWidget(_label("Plans", 22, T["text"], bold=True))
        outer.addWidget(_label(
            f"You are on {PLAN_LABEL[self.held]}. Every higher plan includes "
            f"everything in the plan below it.", 12, T["text_dim"], wrap=True))

        cards = QHBoxLayout()
        cards.setSpacing(14)
        for tier, row in rows.items():
            cards.addWidget(PlanCard(
                tier, {"blurb": row["blurb"], **row["cycles"]},
                self.held, self.summary["counts"], self.summary["locked"]))
        outer.addLayout(cards)

        self.status = _label("", 11, T["text_dim"], wrap=True)
        outer.addWidget(self.status)
        outer.addWidget(_label(self._policy(), 10, T["text_faint"], wrap=True))
        outer.addStretch(1)

    @staticmethod
    def _policy() -> str:
        return (
            "Billing is monthly, 6 months (17% off) or annual (25% off), and "
            "the amount charged is exactly the total shown. A plan change "
            "applies on your next validation. Reverting a tweak always works, "
            "whatever your plan.")

    def begin_checkout(self, tier: str, cycle: str) -> str:
        """Create a priced checkout intent. Nothing is charged here."""
        try:
            req = begin_checkout(tier, cycle)
        except CheckoutError as exc:
            self.status.setText(str(exc))
            return ""
        if req.amount == 0:
            self.status.setText("Foundation is free \u2014 no payment needed.")
            return ""
        self.status.setText(
            f"Order {req.order_id} prepared: {_money(req.amount)} for "
            f"{PLAN_LABEL[req.tier]} ({req.cycle.replace('_', ' ')}). "
            f"No payment provider is connected yet, so nothing has been "
            f"charged and no plan has changed.")
        return req.order_id
