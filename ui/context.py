"""Shared application state passed to every page."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from database import TWEAKS
from engine import state as state_mgr
from engine.audit import StateAuditor
from engine.recommender import evaluate_many


#: Verified license owner display name, or None while the user is a guest
#: (no active license session).
LICENSE_NAME: str | None = None

#: True when the license was activated for the first time this session.
LICENSE_FIRST_VERIFY: bool = False


class AppContext(QObject):
    profile_changed = Signal()
    state_changed = Signal()
    pfp_changed = Signal()
    license_changed = Signal()
    live_state_changed = Signal(str, object)  # tid, value (True/False/None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile: dict = {}
        self.eval: dict = {}
        self.detecting = False
        # Live system-state map filled by the background auditor:
        #   True = tweak currently active, False = inactive, None = unknown.
        self.live: dict[str, bool | None] = {}
        self.auditing = False
        self.auditor = StateAuditor(self)
        self.auditor.live_changed.connect(self._on_live_result)
        self.auditor.batch_done.connect(self._on_audit_batch_done)

    # ---------------- hardware profile / compatibility ----------------

    def refresh_eval(self):
        if self.profile:
            self.eval = evaluate_many(TWEAKS, self.profile)
        else:
            self.eval = {}
        self.state_changed.emit()

    def set_profile(self, profile: dict):
        self.profile = profile
        self.refresh_eval()
        self.profile_changed.emit()

    def state_of(self, tweak_id: str) -> str:
        """Compatibility state; defaults to ready when no profile yet."""
        if not self.profile:
            return "ready"
        return self.eval.get(tweak_id, {}).get("state", "ready")

    def applied_ids(self) -> set[str]:
        return state_mgr.applied_ids()

    def note_state_change(self):
        self.state_changed.emit()

    # ---------------- live state detection ----------------

    def live_state(self, tweak_id: str) -> bool | None:
        """Detected real system state for a tweak (True/False/None)."""
        return self.live.get(tweak_id)

    def live_active(self, tweak_id: str) -> bool:
        """Is this tweak currently active on the system?

        Uses the live audit when available; falls back to the tweaks this app
        recorded as applied (for informational/guidance tweaks the live audit
        cannot measure).
        """
        value = self.live.get(tweak_id)
        if value is not None:
            return bool(value)
        return tweak_id in state_mgr.applied_ids()

    def live_active_ids(self) -> set[str]:
        return {t["id"] for t in TWEAKS if self.live_active(t["id"])}

    def live_active_count(self) -> int:
        return len(self.live_active_ids())

    def start_full_audit(self):
        """Audit every tweak in the database in the background."""
        self.auditing = True
        self.auditor.request(TWEAKS)

    def request_audit(self, tweaks):
        """Audit a specific set of tweaks (deduplicated against pending)."""
        if not tweaks:
            return
        self.auditing = True
        self.auditor.request(tweaks)

    def force_audit_ids(self, tweak_ids):
        """Re-check specific tweaks even if an older audit still runs."""
        from database import BY_ID
        tweaks = [t for tid in tweak_ids if (t := BY_ID.get(tid))]
        if not tweaks:
            return
        self.auditing = True
        self.auditor.request(tweaks, force=True)

    def invalidate_state(self):
        """Drop cached system reads so the next audit re-queries Windows."""
        from engine import state_checker
        state_checker.invalidate_cache()

    def _on_live_result(self, tid, value):
        self.live[tid] = value
        self.live_state_changed.emit(tid, value)

    def _on_audit_batch_done(self):
        self.auditing = False
