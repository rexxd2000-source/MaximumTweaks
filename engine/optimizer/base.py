"""Category optimizer engine.

A category optimizer is the *dedicated* scan -> evaluate -> recommend flow for
one subsystem (Network, TCP, UDP, DNS, GPU, CPU, RAM, Mouse, ...).  It is kept
separate from the plain tweak cards:

    normal cards:   apply / revert / details / evidence / risk
    optimizer:      detect hardware -> scan category -> check compatibility ->
                    validate -> rank -> recommend -> apply -> verify

The base :class:`Optimizer` provides the shared pipeline; concrete optimizers
only declare which subsystem they probe, which tweaks they own, and any
subsystem-specific evaluation overrides (e.g. services).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from database import TWEAKS
from database.validation import BLOCKED_STATUSES
from engine.recommender import evaluate as rec_evaluate
from hardware import probes

# Recommendation states, in display/rank order.
STATE_ORDER = {
    "compatible": 0,
    "optional": 1,
    "driver_dependent": 2,
    "unknown": 3,
    "guidance": 4,
    "already_active": 5,
    "not_applicable": 6,
    "conflicting": 7,
    "outdated": 8,
    "placebo": 9,
    "invalid": 10,
}

READY_STATES = ("compatible", "optional")
# Only validated-and-compatible tweaks are selectable for auto-apply. A
# driver_dependent tweak may look right on the surface but can silently no-op
# on a driver that exposes no matching panel — never auto-apply it. "unknown"
# (no evidence at all) is likewise not selectable. Both remain visible in the
# report so the user can read why they were held back.
SELECTABLE_STATES = READY_STATES

_EVIDENCE_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNKNOWN": 3}
_IMPACT_RANK = {"extreme": 6, "high": 5, "moderate": 4, "low": 3,
                "very low": 2}

# Group titles shown in the recommendation dialog, in display order.
SECTION_TITLES = [
    ("ready", "READY TO APPLY"),
    ("driver", "DRIVER-DEPENDENT \u2014 VERIFY FIRST"),
    ("unknown", "INSUFFICIENT EVIDENCE"),
    ("guidance", "INFORMATIONAL GUIDANCE"),
    ("active", "ALREADY APPLIED"),
    ("notapp", "NOT APPLICABLE TO THIS SYSTEM"),
    ("blocked", "BLOCKED BY VALIDATION"),
]


def _section(state: str) -> str:
    if state in ("compatible", "optional"):
        return "ready"
    if state == "driver_dependent":
        return "driver"
    if state == "unknown":
        return "unknown"
    if state == "guidance":
        return "guidance"
    if state == "already_active":
        return "active"
    if state == "not_applicable":
        return "notapp"
    return "blocked"


def _is_guidance_only(tweak: dict) -> bool:
    actions = tweak.get("actions") or []
    return not actions or all(a[0] == "guidance" for a in actions)


def _sort_key(rec: "Rec"):
    state = rec.state
    ev = _EVIDENCE_RANK.get(rec.tweak.get("evidence", "UNKNOWN"), 3)
    impact = -_IMPACT_RANK.get(rec.tweak.get("impact", "low"), 0)
    return (STATE_ORDER.get(state, 9), ev, impact, rec.name.lower())


@dataclass
class Rec:
    """One per-tweak recommendation produced by an optimizer."""
    tweak: dict
    state: str
    reason: str = ""
    evidence: str = ""

    @property
    def tid(self) -> str:
        return self.tweak["id"]

    @property
    def name(self) -> str:
        return self.tweak["name"]

    @property
    def selectable(self) -> bool:
        return self.state in SELECTABLE_STATES

    @property
    def default_checked(self) -> bool:
        return self.state in ("compatible", "optional")


@dataclass
class OptimizeReport:
    """Result of running an optimizer: detection facts + ranked recommendations."""
    key: str
    title: str
    subtitle: str
    detection: dict = field(default_factory=dict)
    recs: list = field(default_factory=list)

    @property
    def detection_facts(self) -> list:
        return self.detection.get("facts") or []

    def ready(self) -> list:
        return [r for r in self.recs if r.state in READY_STATES]

    def grouped(self) -> list:
        """Return [(section_key, title, [recs])] in display order."""
        buckets = {k: [] for k, _t in SECTION_TITLES}
        for r in self.recs:
            buckets[_section(r.state)].append(r)
        out = []
        for key, title in SECTION_TITLES:
            items = buckets[key]
            if items:
                out.append((key, title, items))
        return out


def merge_reports(reports: list[OptimizeReport], title: str,
                  subtitle: str) -> OptimizeReport:
    """Combine per-subsystem reports into one category report.

    A category page may run several optimizers (e.g. Network, TCP, UDP, DNS).
    Recommendations are de-duplicated by tweak id — the first occurrence wins
    because a tweak can be owned by more than one optimizer (TCP tweaks are
    scanned by both Network and TCP) — and re-ranked into the shared order.
    """
    seen, recs = set(), []
    facts: list = []
    for rep in reports:
        facts.extend(rep.detection_facts)
        for r in rep.recs:
            if r.tid in seen:
                continue
            seen.add(r.tid)
            recs.append(r)
    recs.sort(key=_sort_key)
    return OptimizeReport(
        key=reports[0].key if reports else "",
        title=title, subtitle=subtitle,
        detection={"facts": facts}, recs=recs)


class Optimizer:
    """Base category optimizer — override key/title/probe/categories/evaluate."""

    key: str = ""
    title: str = ""
    subtitle: str = ""
    probe_name: str = ""
    categories: tuple = ()
    tags: tuple = ()
    explicit_ids: tuple = ()
    group_key: str = ""

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def select_tweaks(self, pool: list | None = None) -> list[dict]:
        source = pool if pool is not None else TWEAKS
        if self.explicit_ids:
            by_id = {t["id"]: t for t in source}
            return [by_id[i] for i in self.explicit_ids if i in by_id]
        cats = set(self.categories)
        tags = set(self.tags)
        out, seen = [], set()
        for t in source:
            if not cats and not tags:
                continue
            if (t["category"] in cats) or (tags & set(t.get("tags") or [])):
                if t["id"] not in seen:
                    seen.add(t["id"])
                    out.append(t)
        return out

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect(self, refresh: bool = False) -> dict:
        if self.probe_name:
            return probes.run_probe(self.probe_name, refresh=refresh)
        return {"label": self.title, "ok": True, "facts": [], "data": {}}

    def _profile(self, det: dict, ctx) -> dict:
        """Merge detected subsystem data into the hardware profile so the
        recommender's ``when`` conditions evaluate against fresh data."""
        profile = dict(ctx.profile or {})
        data = det.get("data") or {}

        gpus = data.get("gpus")
        if gpus:
            profile["gpu"] = list(dict.fromkeys(g["vendor"] for g in gpus))
            profile["gpu_names"] = [g["name"] for g in gpus]
            profile["gpu_types"] = list(dict.fromkeys(
                g.get("type") for g in gpus if g.get("type")))
            profile["gpu_dedicated"] = [g["name"] for g in gpus
                                        if g.get("type") == "dedicated"]
            profile["gpu_integrated"] = [g["name"] for g in gpus
                                         if g.get("type") == "integrated"]
            profile["gpu_vram_gb"] = max((g.get("vram_gb", 0) for g in gpus),
                                         default=0)
        elif data.get("vendors"):
            profile["gpu"] = data["vendors"]

        if data.get("media"):
            profile["net_media"] = data["media"]
            profile["adapter"] = {
                "name": data.get("name") or "-",
                "type": data["media"],
                "speed": data.get("link_speed") or "",
            }

        for key in ("ssd", "nvme", "hdd"):
            if key in data:
                profile[key] = bool(data[key])
        if "laptop" in data:
            profile["laptop"] = bool(data["laptop"])
        if data.get("cpu_vendor"):
            profile["cpu_vendor"] = data["cpu_vendor"]
        if data.get("cores"):
            profile["cpu_cores"] = data["cores"]
        if data.get("total_gb"):
            profile["ram_gb"] = data["total_gb"]
        if data.get("channels"):
            profile["ram_channels"] = data["channels"]
        return profile

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, tweak: dict, det: dict, ctx, profile: dict) -> Rec:
        """Default per-tweak evaluation.  Override in subclasses for
        subsystem-specific checks (services, adapter media, ...)."""
        status = tweak.get("status", "UNKNOWN")
        if status in BLOCKED_STATUSES:
            return Rec(tweak, status.lower(),
                       tweak.get("validation_note") or "Blocked by validation")
        if _is_guidance_only(tweak):
            return Rec(tweak, "guidance",
                       "Guidance card \u2014 describes a manual setting to "
                       "apply in Windows; not an automatic change.")

        from .applicability import check_applicability
        ok, note, dd = check_applicability(tweak, det.get("data") or {}, profile)
        if not ok:
            return Rec(tweak, "not_applicable", note or "Not compatible.")

        ev = rec_evaluate(tweak, profile)
        if ev["state"] == "incompatible":
            reasons = "; ".join(ev["reasons"]) or "Incompatible with this system."
            return Rec(tweak, "not_applicable", reasons)

        if ctx.live_active(tweak["id"]):
            return Rec(tweak, "already_active",
                       "Already configured on this system.")

        # service-action tweaks (e.g. SysMain) still get the service check
        if any(a and a[0] in ("svc", "svcstart", "svcstop", "sc")
               for a in (tweak.get("actions") or [])):
            return self._service_aware(tweak, det, ctx, profile, dd, ev, note)

        if dd:
            return Rec(tweak, "driver_dependent",
                       note or "Depends on driver/panel support.")

        state = "optional" if ev["state"] == "optional" else "compatible"
        reason = (note or ("Compatible with detected hardware."
                           if state == "compatible" else
                           "Compatible \u2014 advanced/optional setting."))
        return Rec(tweak, state, reason,
                   evidence=tweak.get("evidence", "UNKNOWN"))

    def _service_aware(self, tweak: dict, det: dict, ctx, profile: dict,
                       dd: bool, ev: dict, note: str) -> Rec:
        """Safety wrapper for tweaks that reconfigure Windows services:
        never recommend disabling a service that does not exist, and show the
        service's current state in the reason."""
        svc_map = (det.get("data") or {}).get("services") or {}
        names = []
        for a in tweak.get("actions") or []:
            kind = a[0]
            if kind == "sc" and len(a) >= 3:
                names.append(a[2])
            elif kind in ("svc", "svcstart", "svcstop") and len(a) >= 2:
                names.append(a[1])
        if names:
            missing = [n for n in names if n not in svc_map]
            if missing:
                return Rec(tweak, "not_applicable",
                           "Service not installed: " + ", ".join(missing))
            if all(str(svc_map[n].get("start", "")).lower() == "disabled"
                   for n in names):
                return Rec(tweak, "already_active",
                           "Target service(s) already disabled.")
            if dd:
                return Rec(tweak, "driver_dependent", note)
            state = "optional" if ev["state"] == "optional" else "compatible"
            current = ", ".join(
                f"{n} = {svc_map[n].get('state', '?')} / "
                f"{svc_map[n].get('start', '?')}" for n in names)
            return Rec(tweak, state,
                       f"Service check: {current}.",
                       evidence=tweak.get("evidence", "UNKNOWN"))
        return self.evaluate_skip_service(tweak, det, ctx, profile)

    def evaluate_skip_service(self, tweak, det, ctx, profile) -> Rec:
        from .applicability import check_applicability
        if _is_guidance_only(tweak):
            return Rec(tweak, "guidance",
                       "Guidance card \u2014 not an automatic change.")
        ok, note, dd = check_applicability(tweak, det.get("data") or {}, profile)
        if not ok:
            return Rec(tweak, "not_applicable", note or "Not compatible.")
        ev = rec_evaluate(tweak, profile)
        if ev["state"] == "incompatible":
            return Rec(tweak, "not_applicable",
                       "; ".join(ev["reasons"]) or "Incompatible.")
        if ctx.live_active(tweak["id"]):
            return Rec(tweak, "already_active",
                       "Already configured on this system.")
        if dd:
            return Rec(tweak, "driver_dependent", note or "Driver-dependent.")
        state = "optional" if ev["state"] == "optional" else "compatible"
        return Rec(tweak, state, "Compatible with detected hardware.",
                   evidence=tweak.get("evidence", "UNKNOWN"))

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def run(self, ctx, pool: list | None = None, refresh: bool = False) -> OptimizeReport:
        det = self.detect(refresh=refresh)
        profile = self._profile(det, ctx)
        tweaks = self.select_tweaks(pool)
        recs = [self.evaluate(t, det, ctx, profile) for t in tweaks]
        recs = [r for r in recs if r is not None]
        recs.sort(key=_sort_key)
        return OptimizeReport(self.key, self.title, self.subtitle, det, recs)
