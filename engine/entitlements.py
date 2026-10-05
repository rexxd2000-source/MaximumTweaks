"""Subscription entitlement: what tier this PC is allowed to use, and why.

The entitlement is **server-issued**. The license backend signs a session that
carries a ``tier`` field, and that tier is the only input to every gate here.
The client never derives a tier from local state, from a file it can edit, or
from anything the user can type.

What this can and cannot promise
--------------------------------
The backend is the authority, and a tier genuinely has to be bought. But the
tweak engine and the tweak database both ship inside the EXE and execute
locally, so the *check* that runs here can be patched by someone who unpacks
the binary or runs the modules from source. That is a property of shipping an
optimizer locally, not a bug in this module, and it is stated plainly rather
than papered over. What this module does guarantee:

* fail-closed everywhere - missing, malformed, unknown or stale entitlement
  data resolves to Foundation, never to a higher tier;
* one chokepoint - :func:`gate` is called from ``engine.safety.preflight``, so
  every apply path (UI toggle, Apply All, presets, optimizer, CLI) is covered
  without each caller having to remember;
* unverified tweaks are never force-applied.
"""
from __future__ import annotations

from config.plans import (
    FOUNDATION, MAXIMUM, PERFORMANCE, PLAN_LABEL, allows, normalize_tier,
    required_tier_label, tier_rank, upgrade_path,
)

__all__ = [
    "GATE_OK", "GATE_TIER", "GATE_UNVERIFIED",
    "current_tier", "tier_label", "is_entitled", "gate", "describe",
    "entitlement_summary",
]

# Gate outcome codes.
GATE_OK = None
GATE_TIER = "tier_required"
GATE_UNVERIFIED = "unverified"


def _session() -> dict:
    """The persisted license session, or an empty dict."""
    try:
        from engine import license as license_mgr
        return license_mgr.session() or {}
    except Exception:
        # A broken/absent license module must never unlock anything.
        return {}


def current_tier() -> str:
    """The tier this PC is entitled to right now.

    Fails closed at every step:

    * no session (never activated, or cleared on deactivate) -> Foundation;
    * an explicitly recorded refusal (revoked / expired / suspended / device
      mismatch) -> Foundation, because a refused key grants nothing;
    * a session with no ``tier`` field -> Foundation. This is what makes legacy
      keys safe: an old key issued before tiers existed keeps working, but only
      for the free tier, instead of silently inheriting full access;
    * an unrecognised tier string -> Foundation (:func:`normalize_tier` maps
      junk to the lowest tier rather than raising).
    """
    sess = _session()
    if not sess:
        return FOUNDATION

    refusal = sess.get("refusal") or {}
    if refusal.get("code"):
        return FOUNDATION

    status = str(sess.get("status") or "").lower()
    if status in ("revoked", "expired", "suspended", "banned", "inactive"):
        return FOUNDATION

    raw = sess.get("tier")
    if raw is None or str(raw).strip() == "":
        return FOUNDATION

    return normalize_tier(raw)


def tier_label(tier: str | None = None) -> str:
    return PLAN_LABEL[tier or current_tier()]


def is_entitled(required: str, held: str | None = None) -> bool:
    """Whether the entitled tier covers ``required``."""
    return allows(held or current_tier(), required)


def gate(tweak: dict, held: str | None = None) -> dict:
    """Decide whether ``tweak`` may be applied under the current entitlement.

    Returns ``{"allowed", "code", "reason", "requires_confirmation"}``.

    Two independent gates:

    ``GATE_TIER``
        Hard block. A subscriber below the required tier cannot apply it at
        all, on any path. ``force`` deliberately cannot override this - forcing
        a paywalled optimization is exactly what must be impossible.

    ``GATE_UNVERIFIED``
        Soft gate. This audit could not prove the implementation safe. The
        tweak is *allowed* but flagged ``requires_confirmation`` and excluded
        from every automated batch, so it can only ever be applied by a person
        who has read the reason. It is never force-applied, and never labelled a
        verified optimization anywhere in the UI.

    Reverts are never gated: undoing a change must always be possible, even for
    a tweak whose tier has since been downgraded or whose entitlement lapsed.
    """
    held = held or current_tier()
    result = {"allowed": True, "code": GATE_OK, "reason": "",
              "requires_confirmation": False, "tier": held}

    tid = tweak.get("id", "?")

    required = normalize_tier(tweak.get("tier") or FOUNDATION)

    if not allows(held, required):
        missing = upgrade_path(held, required) or required
        result["allowed"] = False
        result["code"] = GATE_TIER
        result["reason"] = (
            f"{required_tier_label(required)}. "
            f"This optimization is part of the {PLAN_LABEL[missing]} plan "
            f"(${_price_for(missing)}/month)."
        )
        return result

    if tweak.get("verified") is False:
        reason = str(tweak.get("verify_reason") or "").strip()
        result["requires_confirmation"] = True
        result["code"] = GATE_UNVERIFIED
        result["reason"] = (
            "Not verified by the safety audit"
            + (f": {reason}" if reason else ".")
        )
    return result


def _price_for(tier: str) -> str:
    from config.plans import monthly_price
    return f"{monthly_price(tier):.2f}"


def describe() -> str:
    """One-line human summary of the current entitlement, for the UI."""
    held = current_tier()
    return f"{PLAN_LABEL[held]} ({required_tier_label(held).replace('Requires ', '')})"


def entitlement_summary(tweaks: list[dict], held: str | None = None) -> dict:
    """Per-tier feature counts for the locked/unlocked UI.

    ``locked`` is the number of tweaks a subscriber on ``held`` cannot apply,
    split by the tier they would need.
    """
    held = held or current_tier()
    counts = {FOUNDATION: 0, PERFORMANCE: 0, MAXIMUM: 0}
    locked = {FOUNDATION: 0, PERFORMANCE: 0, MAXIMUM: 0}
    unverified_locked = 0
    for t in tweaks:
        required = normalize_tier(t.get("tier") or FOUNDATION)
        counts[required] = counts.get(required, 0) + 1
        if not allows(held, required):
            locked[required] = locked.get(required, 0) + 1
            if t.get("verified") is False:
                unverified_locked += 1
    return {
        "held": held,
        "held_label": PLAN_LABEL[held],
        "held_rank": tier_rank(held),
        "counts": counts,
        "locked": locked,
        "locked_total": sum(locked.values()),
        "unverified_locked": unverified_locked,
        "accessible": sum(v for k, v in counts.items() if allows(held, k)),
    }
