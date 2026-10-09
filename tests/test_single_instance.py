"""Regression tests for the version-aware single-instance guard and the stale
autostart repair (the "update did nothing until I close and reopen" bug)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import autostart  # noqa: E402
from engine import single_instance as si  # noqa: E402


@pytest.mark.parametrize("raw,expected", [
    ("2.5.9", (2, 5, 9)),
    ("v2.5.10", (2, 5, 10)),
    ("v2.5.9-rc1", (2, 5, 9)),
    ("3", (3,)),
    ("", ()),
    (None, ()),
    ("garbage", ()),
])
def test_parse_version(raw, expected):
    assert si.parse_version(raw) == expected


def test_parse_version_orders_releases_correctly():
    assert si.parse_version("2.5.10") > si.parse_version("2.5.9")
    assert si.parse_version("v2.6.0") > si.parse_version("2.5.99")


@pytest.mark.parametrize("title,expected", [
    ("Maximum Tweaks v2.5.9", "2.5.9"),
    ("Maximum Tweaks v2.5.10", "2.5.10"),
    ("Maximum Tweaks - Updater", None),
    ("Something else", None),
    ("", None),
    (None, None),
])
def test_title_version(title, expected):
    assert si.title_version("Maximum Tweaks", title) == expected


@pytest.mark.parametrize("running,ours,expected", [
    ([], "2.5.9", ("start", None)),
    (["2.5.9"], "2.5.9", ("focus", "2.5.9")),
    (["2.5.10"], "2.5.9", ("focus", "2.5.10")),
    (["2.5.4"], "2.5.9", ("takeover", "2.5.4")),
    (["2.5.4", "2.5.8"], "2.5.9", ("takeover", "2.5.8")),
    (["2.5.4", "2.5.9"], "2.5.9", ("focus", "2.5.9")),
    (["2.5.4", "2.6.0"], "2.5.9", ("focus", "2.6.0")),
])
def test_decide(running, ours, expected):
    assert si.decide(running, ours) == expected


# ---- enforce_single_instance (ctypes faked) --------------------------------

class _Func:
    """Callable that also accepts .argtypes/.restype like a ctypes function."""

    def __init__(self, fn):
        self._fn = fn
        self.argtypes = None
        self.restype = None

    def __call__(self, *a, **k):
        return self._fn(*a, **k)


class _FakeKernel32:
    def __init__(self, already=True, release_after=None):
        self._creates = 0
        self._already = already
        self._release_after = release_after
        self._last = 183 if already else 0
        self.closed = 0
        self.CreateMutexW = _Func(self._create)

    def _create(self, *a):
        self._creates += 1
        if self._release_after is None:
            self._last = 183 if self._already else 0
        elif self._creates > self._release_after:
            self._last = 0
        else:
            self._last = 183
        return 12345

    def GetLastError(self):
        return self._last

    def CloseHandle(self, _h):
        self.closed += 1


class _FakeWindll:
    def __init__(self, kernel32):
        self.kernel32 = kernel32
        self.user32 = object()


def _fake_windll(monkeypatch, kernel32):
    import ctypes
    monkeypatch.setattr(ctypes, "windll", _FakeWindll(kernel32), raising=False)


def test_enforce_starts_when_no_other_instance(monkeypatch):
    k = _FakeKernel32(already=False)
    _fake_windll(monkeypatch, k)
    assert si.enforce_single_instance("Maximum Tweaks", "2.5.9") is True


def test_enforce_focuses_same_version_and_exits(monkeypatch):
    k = _FakeKernel32(already=True)
    _fake_windll(monkeypatch, k)
    focused, terminated = [], []
    monkeypatch.setattr(si, "_enum_app_windows",
                        lambda app: [(111, 4242, "2.5.9")])
    monkeypatch.setattr(si, "_focus", lambda hwnd: focused.append(hwnd))
    monkeypatch.setattr(si, "_terminate", lambda pid: terminated.append(pid))
    assert si.enforce_single_instance("Maximum Tweaks", "2.5.9") is False
    assert focused == [111]
    assert terminated == []


def test_enforce_takes_over_older_instance(monkeypatch):
    k = _FakeKernel32(already=True, release_after=1)
    _fake_windll(monkeypatch, k)
    focused, terminated = [], []
    monkeypatch.setattr(si, "_enum_app_windows",
                        lambda app: [(1, 900, "2.5.4")])
    monkeypatch.setattr(si, "_focus", lambda hwnd: focused.append(hwnd))
    monkeypatch.setattr(si, "_terminate", lambda pid: terminated.append(pid))
    monkeypatch.setattr("time.sleep", lambda *a: None)
    assert si.enforce_single_instance("Maximum Tweaks", "2.5.9") is True
    assert terminated == [900]
    assert focused == []


def test_enforce_never_terminates_itself(monkeypatch):
    import os
    k = _FakeKernel32(already=True, release_after=1)
    _fake_windll(monkeypatch, k)
    terminated = []
    monkeypatch.setattr(si, "_enum_app_windows",
                        lambda app: [(1, os.getpid(), "2.5.4")])
    monkeypatch.setattr(si, "_terminate", lambda pid: terminated.append(pid))
    monkeypatch.setattr("time.sleep", lambda *a: None)
    assert si.enforce_single_instance("Maximum Tweaks", "2.5.9") is True
    assert terminated == []


def test_enforce_proceeds_when_mutex_held_but_no_window(monkeypatch):
    k = _FakeKernel32(already=True)
    _fake_windll(monkeypatch, k)
    monkeypatch.setattr(si, "_enum_app_windows", lambda app: [])
    monkeypatch.setattr("time.sleep", lambda *a: None)
    assert si.enforce_single_instance("Maximum Tweaks", "2.5.9") is True


# ---- stale autostart repair ------------------------------------------------

class _FakeReg:
    def __init__(self, data):
        self.data = data
        self.writes = []
        self.deletes = []

    def read_value(self, hive, path, name):
        if self.data is None:
            return (False, None, None)
        return (True, "REG_SZ", self.data)

    def write_value(self, hive, path, name, value, vtype):
        self.writes.append((hive, path, name, value, vtype))
        return (True, "wrote")

    def delete_value(self, hive, path, name):
        self.deletes.append((hive, path, name))
        return (True, "deleted")


def _install(monkeypatch, fake, exe):
    monkeypatch.setattr(autostart, "reg_util", fake)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))


def test_autostart_repointed_to_current_exe(monkeypatch, tmp_path):
    old = tmp_path / "Desktop" / autostart.EXE_NAME
    old.parent.mkdir()
    old.write_bytes(b"MZ")
    current = tmp_path / "Program Files" / autostart.EXE_NAME
    current.parent.mkdir()
    current.write_bytes(b"MZ")
    fake = _FakeReg(f'"{old}" --minimized')
    _install(monkeypatch, fake, current)

    assert autostart.repair_stale_autostart() is True
    assert fake.deletes == []
    assert fake.writes == [("HKCU", autostart.RUN_KEY, autostart.RUN_NAME,
                            f'"{current}" --minimized', "STRING")]


def test_autostart_entry_removed_when_target_gone(monkeypatch, tmp_path):
    gone = tmp_path / "Desktop" / autostart.EXE_NAME
    current = tmp_path / "installed" / autostart.EXE_NAME
    current.parent.mkdir()
    current.write_bytes(b"MZ")
    fake = _FakeReg(f'"{gone}"')
    _install(monkeypatch, fake, current)

    assert autostart.repair_stale_autostart() is True
    assert fake.writes == []
    assert fake.deletes == [("HKCU", autostart.RUN_KEY, autostart.RUN_NAME)]


def test_autostart_untouched_when_already_current(monkeypatch, tmp_path):
    current = tmp_path / "installed" / autostart.EXE_NAME
    current.parent.mkdir()
    current.write_bytes(b"MZ")
    fake = _FakeReg(f'"{current}" --minimized')
    _install(monkeypatch, fake, current)

    assert autostart.repair_stale_autostart() is False
    assert fake.writes == [] and fake.deletes == []


def test_autostart_ignores_unrelated_entry(monkeypatch, tmp_path):
    current = tmp_path / "installed" / autostart.EXE_NAME
    current.parent.mkdir()
    current.write_bytes(b"MZ")
    fake = _FakeReg('"C:\\Other\\Thing.exe" --foo')
    _install(monkeypatch, fake, current)

    assert autostart.repair_stale_autostart() is False
    assert fake.writes == [] and fake.deletes == []


def test_autostart_noop_when_no_entry(monkeypatch, tmp_path):
    current = tmp_path / "installed" / autostart.EXE_NAME
    fake = _FakeReg(None)
    _install(monkeypatch, fake, current)

    assert autostart.repair_stale_autostart() is False
    assert fake.writes == [] and fake.deletes == []


def test_autostart_skipped_when_not_frozen(monkeypatch, tmp_path):
    fake = _FakeReg('"C:\\Desktop\\MaximumTweaks.exe"')
    monkeypatch.setattr(autostart, "reg_util", fake)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    assert autostart.repair_stale_autostart() is False
    assert fake.writes == [] and fake.deletes == []


def test_nsi_repairs_stale_autostart():
    nsi = (ROOT / "MaximumTweaks-Setup.nsi").read_text(encoding="utf-8")
    assert ('ReadRegStr $R2 HKCU "Software\\Microsoft\\Windows\\'
            'CurrentVersion\\Run"' in nsi)
    assert "autostart_done" in nsi
