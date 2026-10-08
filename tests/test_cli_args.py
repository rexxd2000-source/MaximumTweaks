"""``--cli apply/revert <id> --dry-run`` must preview, never mutate.

main() parses with ``parse_known_args``, so an option the subparser does not
define is silently dropped into the unknown list instead of erroring: before
the fix, ``--dry-run`` placed after the subcommand was swallowed and the apply
ran for real against the live system (caught by the §7 frozen-exe smoke).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402


def _capture_apply(monkeypatch):
    calls: list[tuple[str, str, bool]] = []

    def _fake(tweak_id, mode, dry_run):
        calls.append((tweak_id, mode, dry_run))

    monkeypatch.setattr(main, "cmd_apply", _fake)
    return calls


def test_apply_dry_run_after_subcommand(monkeypatch) -> None:
    calls = _capture_apply(monkeypatch)
    main.main(["--cli", "apply", "perf-005", "--dry-run"])
    assert calls == [("perf-005", "apply", True)]


def test_apply_dry_run_before_subcommand(monkeypatch) -> None:
    calls = _capture_apply(monkeypatch)
    main.main(["--cli", "--dry-run", "apply", "perf-005"])
    assert calls == [("perf-005", "apply", True)]


def test_apply_without_dry_run_stays_wet(monkeypatch) -> None:
    calls = _capture_apply(monkeypatch)
    main.main(["--cli", "apply", "perf-005"])
    assert calls == [("perf-005", "apply", False)]


def test_revert_dry_run_after_subcommand(monkeypatch) -> None:
    calls = _capture_apply(monkeypatch)
    main.main(["--cli", "revert", "perf-005", "--dry-run"])
    assert calls == [("perf-005", "revert", True)]


def test_revert_without_dry_run(monkeypatch) -> None:
    calls = _capture_apply(monkeypatch)
    main.main(["--cli", "revert", "perf-005"])
    assert calls == [("perf-005", "revert", False)]
