"""§15 logging: every apply/revert result line identifies tweak id, name,
action, result and error state, with a timestamped formatter behind it.

Regression: the unknown-id path and the dry-run path used to bypass the log
file entirely (only the UI activity stream saw them), and the BLOCKED line
omitted the tweak name.
"""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from engine import applier
from maxlog import _make_logger, register_ui_sink


@pytest.fixture
def log_lines(monkeypatch):
    msgs: list[str] = []
    register_ui_sink(msgs.append)
    monkeypatch.setattr(applier, "activity",
                        SimpleNamespace(emit=lambda *a, **k: None))
    yield msgs
    register_ui_sink(None)


def _stub(monkeypatch, *, allowed=True):
    monkeypatch.setattr(applier, "BY_ID", {
        "t-1": {"id": "t-1", "name": "Test Tweak",
                "actions": ["reg"], "tags": []},
    })
    monkeypatch.setattr(
        applier, "preflight",
        lambda *a, **k: {"allowed": allowed,
                         "code": None if allowed else "blocked",
                         "reason": "" if allowed else "unsafe"})
    monkeypatch.setattr(
        applier, "apply_tweak",
        lambda tid, mode, dry_run=False: (True, [("reg", True, "ok")]))
    monkeypatch.setattr(applier.state_checker, "invalidate_cache", lambda: None)
    monkeypatch.setattr(applier.state_checker, "check_tweak", lambda tw: None)
    monkeypatch.setattr(applier, "_collect_backups", lambda tid: {})
    monkeypatch.setattr(applier, "state_mgr", SimpleNamespace(
        state_batch=lambda: nullcontext(),
        mark_applied=lambda tid: None,
        unmark_applied=lambda tid: None,
        unmark_disabled=lambda tid: None,
        mark_disabled=lambda tid: None,
        recompute_restart_required=lambda: None,
    ))


def _line_with(msgs, needle):
    hits = [m for m in msgs if needle in m]
    assert hits, f"no log line containing {needle!r} in {msgs}"
    return hits[-1]


def test_apply_result_logs_id_name_action_result(monkeypatch, log_lines):
    _stub(monkeypatch)
    applier.run(["t-1"], mode="apply")
    line = _line_with(log_lines, "apply t-1")
    assert "Test Tweak" in line          # name
    assert "ok=True" in line             # result
    assert "status=" in line
    assert "verified=" in line


def test_revert_result_logs_id_name_action_result(monkeypatch, log_lines):
    _stub(monkeypatch)
    applier.run(["t-1"], mode="revert")
    line = _line_with(log_lines, "revert t-1")
    assert "Test Tweak" in line
    assert "ok=True" in line
    assert "status=reverted" in line


def test_unknown_id_is_logged_as_error(monkeypatch, log_lines):
    _stub(monkeypatch)
    applier.run(["ghost-99"], mode="apply")
    line = _line_with(log_lines, "ghost-99")
    assert "[ERROR]" in line
    assert "unknown tweak id" in line


def test_dry_run_is_logged(monkeypatch, log_lines):
    _stub(monkeypatch)
    applier.run(["t-1"], mode="apply", dry_run=True)
    line = _line_with(log_lines, "dry-run")
    assert "apply t-1" in line
    assert "Test Tweak" in line
    assert "status=dry_run" in line


def test_blocked_line_includes_name(monkeypatch, log_lines):
    _stub(monkeypatch, allowed=False)
    applier.run(["t-1"], mode="apply")
    line = _line_with(log_lines, "BLOCKED")
    assert "t-1" in line
    assert "Test Tweak" in line


def test_file_handler_formatter_has_timestamp():
    fmts = [h.formatter._fmt for h in _make_logger().handlers
            if getattr(h, "formatter", None)]
    assert any("%(asctime)s" in f for f in fmts)
