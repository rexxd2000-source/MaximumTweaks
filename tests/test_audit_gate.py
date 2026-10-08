"""The catalogue release gate (tools/audit_tweak_db.py) must pass on the
shipped catalogue and must actually catch each class of regression it
claims to gate: duplicate cards, undocumented conflicts, unrevertable
mutations and unknown executables."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import BY_ID  # noqa: E402
from tools import audit_tweak_db as G  # noqa: E402


def test_gate_passes_on_live_catalogue() -> None:
    assert G.check_schema() == []
    assert G.check_duplicates() == []
    assert G.check_conflicts_documented() == []
    safety_errors, _info = G.check_safety()
    assert safety_errors == []
    assert G.check_drift() == []


def test_duplicate_clone_is_caught(monkeypatch) -> None:
    clone = dict(BY_ID["ram-005"])
    clone["id"] = "fake-dup-001"
    catalogue = dict(BY_ID)
    catalogue["fake-dup-001"] = clone
    monkeypatch.setattr(G, "BY_ID", catalogue)
    errs = G.check_duplicates()
    assert any("fake-dup-001" in e and "ram-005" in e for e in errs), errs


def test_undocumented_conflict_is_caught(monkeypatch) -> None:
    fake_a = dict(BY_ID["ram-005"])
    fake_a["id"] = "fake-a"
    fake_a["actions"] = [("reg", "HKLM", "PATH\\X", "EnableSuperfetch",
                          1, "DWORD")]
    fake_b = dict(BY_ID["ram-004"])
    fake_b["id"] = "fake-b"
    fake_b["actions"] = [("reg", "HKLM", "PATH\\X", "EnableSuperfetch",
                          0, "DWORD")]
    catalogue = dict(BY_ID)
    catalogue["fake-a"] = fake_a
    catalogue["fake-b"] = fake_b
    monkeypatch.setattr(G, "BY_ID", catalogue)
    errs = G.check_conflicts_documented()
    assert any("fake-a" in e and "fake-b" in e for e in errs), errs


def test_unrevertable_card_is_caught(monkeypatch) -> None:
    broken = dict(BY_ID["ram-005"])
    broken["id"] = "fake-broken"
    broken["actions"] = [("svc", "Spooler", "disabled")]
    broken["revert"] = []
    catalogue = dict(BY_ID)
    catalogue["fake-broken"] = broken
    monkeypatch.setattr(G, "BY_ID", catalogue)
    errs, _info = G.check_safety()
    assert any("fake-broken" in e and "revers" in e.lower()
               for e in errs), errs


def test_unknown_executable_is_caught(monkeypatch) -> None:
    weird = dict(BY_ID["ram-005"])
    weird["id"] = "fake-exe"
    weird["actions"] = [("cmd", "totally-unknown-thing.exe /x")]
    weird["revert"] = [("cmd", "totally-unknown-thing.exe /x")]
    catalogue = dict(BY_ID)
    catalogue["fake-exe"] = weird
    monkeypatch.setattr(G, "BY_ID", catalogue)
    errs, _info = G.check_safety()
    assert any("fake-exe" in e and "audited set" in e for e in errs), errs
