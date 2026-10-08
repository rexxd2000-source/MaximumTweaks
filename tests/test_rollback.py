"""P0-2b/2c: mid-apply rollback restores snapshots; skip-restores fail loudly.

The old ``_rollback_actions`` deleted the values it had just written (``reg``
-> ``_reg_delete``, ``svc`` -> force ``manual``) or printed "will be reverted"
without doing anything, and several ``_restore_*`` helpers returned success
while skipping the restore entirely - so a skipped restore cleared the
backups and Revert could never finish the job.  These tests pin the fixed
behavior:

* rollback restores every captured snapshot and reports honestly what it
  cannot restore,
* a restore whose original state is unknown returns False (so ``ok_all``
  stays False and backups are kept),
* ``regdel``/``regdelall``/``inidel`` targets are snapshotted before they are
  removed so rollback/revert can write them back.
"""

from database import executor
from engine import state as state_mgr


# ── P0-2c: a restore that cannot restore must fail, not "skip" ──────

def test_svc_restore_unknown_original_fails():
    ok, detail = executor._restore_svc_backup(
        {"name": "FooSvc", "start_type": None, "is_running": False})
    assert ok is False
    assert "NOT restored" in detail


def test_svc_restore_sc_qc_tokens_roundtrip(monkeypatch):
    """Snapshots store ``sc qc`` tokens (AUTO_START/DEMAND_START/...); the
    restore must map every one back to a real start type.  AUTO_START used to
    fall through to ``_svc``'s ``demand`` default, silently downgrading an
    automatic service to Manual on revert (seen live: SysMain)."""
    calls: list[tuple[str, str]] = []

    def _fake_svc(name, mode):
        calls.append((name, mode))
        return True, "ok"

    def _fake_run(name, action):
        calls.append((name, action))
        return True, "ok"

    monkeypatch.setattr(executor, "_svc", _fake_svc)
    monkeypatch.setattr(executor, "_svc_run", _fake_run)

    cases = {
        "AUTO_START": "auto",
        "DEMAND_START": "manual",
        "DISABLED": "disabled",
        "BOOT_START": "boot",
        "SYSTEM_START": "system",
        "DELAYED_AUTO_START": "delayed",
    }
    for start_type, friendly in cases.items():
        calls.clear()
        ok, _detail = executor._restore_svc_backup(
            {"name": "FooSvc", "start_type": start_type, "is_running": False})
        assert ok is True, start_type
        assert calls == [("FooSvc", friendly)], start_type


def test_svc_restore_auto_start_restarts_if_running(monkeypatch):
    calls: list[tuple[str, str]] = []

    def _fake_svc(name, mode):
        calls.append(("svc", mode))
        return True, "ok"

    def _fake_run(name, action):
        calls.append(("run", action))
        return True, "ok"

    monkeypatch.setattr(executor, "_svc", _fake_svc)
    monkeypatch.setattr(executor, "_svc_run", _fake_run)

    ok, _detail = executor._restore_svc_backup(
        {"name": "SysMain", "start_type": "AUTO_START", "is_running": True})
    assert ok is True
    assert calls == [("svc", "auto"), ("run", "svcstart")]


def test_sched_restore_unknown_original_fails():
    ok, detail = executor._restore_sched_backup(
        {"task": "SomeTask", "was_enabled": None})
    assert ok is False
    assert "NOT restored" in detail


def test_cmd_restore_unknown_scheme_fails():
    ok, detail = executor._restore_cmd_backup(
        {"kind": "powercfg_setactive", "prev_active": None, "prev_name": None})
    assert ok is False
    assert "NOT restored" in detail


def test_cmd_restore_unknown_prev_value_fails(monkeypatch):
    def _explode(*a, **k):  # a skip must never reach a live system command
        raise AssertionError("restore ran despite unknown original")

    monkeypatch.setattr(executor, "_run", _explode)
    for kind in ("powercfg_value", "powercfg_change",
                 "powercfg_hibernate", "netsh"):
        ok, detail = executor._restore_cmd_backup(
            {"kind": kind, "prev_value": None, "name": "n"})
        assert ok is False, kind
        assert "NOT restored" in detail, kind


def test_cmd_restore_unknown_kind_fails():
    ok, detail = executor._restore_cmd_backup({"kind": "mystery"})
    assert ok is False
    assert "NOT restored" in detail


# ── P0-2b: rollback restores snapshots for every category ──────────

def _stub_restores(monkeypatch):
    """Record every restore call instead of touching the live system."""
    calls = []

    def _make(cat):
        def fn(entry, dry_run=False):
            calls.append((cat, entry))
            return True, "ok"
        return fn

    for cat in ("backup", "file_backup", "ini_backup", "power_backup",
                "svc_backup", "cmd_backup", "powerscheme_backup",
                "sched_backup"):
        monkeypatch.setattr(executor, f"_restore_{cat}", _make(cat))
    return calls


def _stub_backups(monkeypatch, *, reg=None, file=None, ini=None, power=None,
                  svc=None, cmd=None, powerscheme=None, sched=None):
    defaults = {"reg": {}, "file": {}, "ini": {}, "power": {},
                "svc": {}, "cmd": {}, "powerscheme": {}, "sched": {}}
    defaults.update({k: v for k, v in {
        "reg": reg, "file": file, "ini": ini, "power": power,
        "svc": svc, "cmd": cmd, "powerscheme": powerscheme,
        "sched": sched}.items() if v is not None})
    for cat, value in defaults.items():
        monkeypatch.setattr(state_mgr, f"get_{cat}_backups",
                            lambda tid, v=value: v)


def test_rollback_restores_every_captured_snapshot(monkeypatch):
    calls = _stub_restores(monkeypatch)
    _stub_backups(
        monkeypatch,
        reg={"R": {"hive": "HKLM", "path": "p", "name": "n"}},
        file={"F": {"path": "x"}},
        ini={"I": {"section": "s", "key": "k"}},
        power={"P": {"setting": "boost_policy"}},
        svc={"S": {"name": "FooSvc"}},
        cmd={"c": {"kind": "bcdedit"}},
        powerscheme={"active_scheme": "guid"},
        sched={"T": {"task": "T"}})

    results = executor._rollback_actions("t1", [])

    restore_labels = [label for label, _, _ in results
                      if str(label).startswith("restore_")]
    assert len(restore_labels) == 8, results
    assert all(ok for _, ok, _ in results), results
    assert {cat for cat, _ in calls} == {
        "backup", "file_backup", "ini_backup", "power_backup",
        "svc_backup", "cmd_backup", "powerscheme_backup", "sched_backup"}


def test_rollback_restore_exception_is_reported_not_raised(monkeypatch):
    _stub_backups(monkeypatch, reg={"R": {"hive": "HKLM", "path": "p",
                                          "name": "n"}})

    def _boom(entry, dry_run=False):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(executor, "_restore_backup", _boom)

    results = executor._rollback_actions("t1", [])
    assert len(results) == 1
    label, ok, detail = results[0]
    assert label == "restore_reg"
    assert ok is False
    assert "kaboom" in detail


# ── P0-2b: honest reporting for actions no snapshot covers ─────────

def test_rollback_reports_uncovered_actions_honestly(monkeypatch):
    _stub_backups(monkeypatch)

    results = executor._rollback_actions("t1", [
        ("guidance", "read the docs"),
        ("mkdir", r"C:\Temp\newdir"),
        ("restart",),
        ("appx", "remove", "Microsoft.Solitaire"),
        ("cmd", "some unparseable command"),
        ("reg", "HKLM", r"SOFTWARE\X", "v", "1", "DWORD"),
        ("regdel", "HKLM", r"SOFTWARE\X", "gone"),
        ("process", ("kill",)),
    ])

    by_kind = {label[0]: (ok, detail) for label, ok, detail in results}
    assert by_kind["guidance"][0] is True
    assert by_kind["mkdir"][0] is True
    assert by_kind["restart"][0] is True
    assert by_kind["appx"][0] is False
    assert "cannot be rolled back" in by_kind["appx"][1]
    assert by_kind["cmd"][0] is False
    assert "NOT restored" in by_kind["cmd"][1]
    # Snapshot absent means the value already sat at its original state
    # (the snapshot step is what would have recorded any real change).
    assert by_kind["reg"][0] is True
    assert by_kind["regdel"][0] is True
    assert by_kind["process"][0] is False


def test_rollback_silent_for_actions_restored_from_snapshot(monkeypatch):
    hive, path, name = "HKLM", r"SOFTWARE\X", "v"
    _stub_backups(monkeypatch, reg={
        executor._target_key(hive, path, name):
            {"hive": hive, "path": path, "name": name, "existed": True}})
    _stub_restores(monkeypatch)

    results = executor._rollback_actions(
        "t1", [("reg", hive, path, name, "1", "DWORD")])

    # One restore line, no duplicate "uncovered" line for the same action.
    assert [label for label, _, _ in results] == ["restore_reg"]


def test_rollback_sc_without_snapshot_is_a_failure(monkeypatch):
    _stub_backups(monkeypatch)
    results = executor._rollback_actions("t1", [("svc", "FooSvc")])
    assert results[0][1] is False
    assert "NOT restored" in results[0][2]


# ── Snapshot coverage for delete actions (regdel/regdelall/inidel) ─

def _patch_snapshot_env(monkeypatch, saved):
    monkeypatch.setattr(state_mgr, "get_reg_backups", lambda tid: {})
    monkeypatch.setattr(state_mgr, "save_reg_backups",
                        lambda tid, entries: saved.update(entries))
    monkeypatch.setattr(state_mgr, "get_ini_backups", lambda tid: {})
    monkeypatch.setattr(state_mgr, "save_ini_backups",
                        lambda tid, entries: saved.update(entries))


def test_regdel_target_is_snapshotted_before_delete(monkeypatch):
    saved = {}
    _patch_snapshot_env(monkeypatch, saved)
    monkeypatch.setattr(executor, "_reg_read_value",
                        lambda hive, path, name: (True, "REG_DWORD", "1"))

    executor._snapshot_reg_targets("t1", [("regdel", "HKLM", r"SOFTWARE\X", "v")])

    key = executor._target_key("HKLM", r"SOFTWARE\X", "v")
    assert saved[key]["existed"] is True
    assert saved[key]["data"] == "1"


def test_regdel_absent_value_is_not_snapshotted(monkeypatch):
    saved = {}
    _patch_snapshot_env(monkeypatch, saved)
    monkeypatch.setattr(executor, "_reg_read_value",
                        lambda hive, path, name: (False, None, None))

    executor._snapshot_reg_targets("t1", [("regdel", "HKLM", r"SOFTWARE\X", "v")])

    assert saved == {}


def test_inidel_target_is_snapshotted_before_delete(monkeypatch):
    saved = {}
    _patch_snapshot_env(monkeypatch, saved)
    monkeypatch.setattr(executor, "_ini_read_value",
                        lambda path, section, key: (True, "1"))

    executor._snapshot_ini_targets(
        "t1", [("inidel", r"C:\game\cfg.ini", "Sec", "Key")])

    assert len(saved) == 1
    entry = next(iter(saved.values()))
    assert entry["existed"] is True
    assert entry["value"] == "1"


def test_inidel_absent_key_is_not_snapshotted(monkeypatch):
    saved = {}
    _patch_snapshot_env(monkeypatch, saved)
    monkeypatch.setattr(executor, "_ini_read_value",
                        lambda path, section, key: (False, None))

    executor._snapshot_ini_targets(
        "t1", [("inidel", r"C:\game\cfg.ini", "Sec", "Key")])

    assert saved == {}
