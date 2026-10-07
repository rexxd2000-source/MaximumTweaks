"""P1-5: the preset (one-click optimize) path enforces requires_confirmation.

Unverified tweaks (the safety audit could not prove them safe) are allowed
one at a time after the user reads the reason, but they are never applied
unattended - Apply All already branched on ``requires_confirmation`` while
the preset path blindly applied every "ready" tweak.  These tests pin the
preset split: unverified tweaks land in their own bucket and stay out of the
applyable list.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from database import BY_ID  # noqa: E402
from engine import bundles as bundles_mod  # noqa: E402
from engine import entitlements  # noqa: E402
from ui.pages.optimize import BundleCard  # noqa: E402


class _Sig:
    def connect(self, fn):
        pass


class _FakeCtx:
    profile = None
    state_changed = _Sig()

    def state_of(self, tid):
        return "ready"


def _app():
    return QApplication.instance() or QApplication([])


def test_preset_excludes_unverified_tweaks(monkeypatch):
    _app()
    bundle = bundles_mod.resolve_bundle("balanced")
    tid = next(t for t in bundle["tweaks"] if t in BY_ID)
    base = BY_ID[tid]
    # Force the exact shape that makes preflight set requires_confirmation:
    # entitled (free tier) but unverified by the safety audit.
    monkeypatch.setitem(BY_ID, tid, {**base,
                                     "tier": entitlements.FOUNDATION,
                                     "verified": False})

    card = BundleCard(_FakeCtx(), bundle)
    applyable, skipped, unverified = card._states()

    unverified_ids = {t["id"] for t in unverified}
    assert tid in unverified_ids
    assert tid not in {t["id"] for t in applyable}


def test_preset_keeps_verified_tweaks_applyable(monkeypatch):
    _app()
    bundle = bundles_mod.resolve_bundle("balanced")
    tid = next(t for t in bundle["tweaks"] if t in BY_ID)
    base = BY_ID[tid]
    monkeypatch.setitem(BY_ID, tid, {**base,
                                     "tier": entitlements.FOUNDATION,
                                     "verified": True})

    card = BundleCard(_FakeCtx(), bundle)
    applyable, skipped, unverified = card._states()

    assert tid in {t["id"] for t in applyable}
    assert tid not in {t["id"] for t in unverified}
