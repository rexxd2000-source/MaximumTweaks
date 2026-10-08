"""NSIS-installed copies must update by re-running the setup, not by
swapping the exe (Program Files is not writable from an unelevated app)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import updater  # noqa: E402

SETUP = "MaximumTweaks-Setup-9.9.9.exe"
EXE = "MaximumTweaks.exe"
MANIFEST = {
    "version": "9.9.9",
    "notes": "notes",
    "url": f"https://cdn.example/{EXE}",
    "sha256": "ab" * 32,
    "checksum_url": f"https://cdn.example/{EXE}.sha256",
    "installer_url": f"https://cdn.example/{SETUP}",
    "installer_checksum_url": f"https://cdn.example/{SETUP}.sha256",
    "installer_sha256": "cd" * 32,
}


def _patch_manifest(monkeypatch, data, installed):
    monkeypatch.setattr(updater, "UPDATE_MANIFEST_URL",
                        "https://example.test/update.json")
    monkeypatch.setattr(updater, "_get_json", lambda *a, **k: dict(data))
    monkeypatch.setattr(updater, "is_nsis_installed", lambda *a, **k: installed)


def _patch_github(monkeypatch, release, installed):
    monkeypatch.setattr(updater, "UPDATE_MANIFEST_URL", "")
    monkeypatch.setattr(updater, "GITHUB_TOKEN", "")
    monkeypatch.setattr(updater, "_get_json", lambda *a, **k: dict(release))
    monkeypatch.setattr(updater, "is_nsis_installed", lambda *a, **k: installed)


def _patch_manifest_down_github(monkeypatch, release, installed):
    """Manifest server returns 502; _fetch_update must fall back to GitHub."""
    monkeypatch.setattr(updater, "UPDATE_MANIFEST_URL",
                        "https://example.test/update.json")
    monkeypatch.setattr(updater, "GITHUB_TOKEN", "")

    def _fake_get_json(url, *a, **k):
        if "api.github.com" in url:
            return dict(release)
        raise updater._HttpError(
            "The update server refused the request (HTTP 502).", 502)

    monkeypatch.setattr(updater, "_get_json", _fake_get_json)
    monkeypatch.setattr(updater, "is_nsis_installed", lambda *a, **k: installed)


def test_manifest_down_falls_back_to_github_setup(monkeypatch):
    _patch_manifest_down_github(monkeypatch, _github_release(), installed=True)
    res = updater._fetch_update()
    assert res["url"] == f"https://gh.example/{SETUP}"
    assert res["checksum_url"] == f"https://gh.example/{SETUP}.sha256"
    assert res["kind"] == "setup"
    assert res["filename"] == SETUP


def test_manifest_down_falls_back_to_github_exe(monkeypatch):
    _patch_manifest_down_github(monkeypatch, _github_release(), installed=False)
    res = updater._fetch_update()
    assert res["url"] == f"https://gh.example/{EXE}"
    assert res["checksum_url"] == f"https://gh.example/{EXE}.sha256"
    assert res["kind"] == "exe"
    assert res["filename"] == EXE


def test_manifest_down_falls_back_to_github_up_to_date(monkeypatch):
    release = _github_release()
    release["tag_name"] = "v2.5.3"
    monkeypatch.setattr(updater, "APP_VERSION", "2.5.3")
    _patch_manifest_down_github(monkeypatch, release, installed=True)
    assert updater._fetch_update() is None


def test_manifest_and_github_down_raises(monkeypatch):
    monkeypatch.setattr(updater, "UPDATE_MANIFEST_URL",
                        "https://example.test/update.json")
    monkeypatch.setattr(updater, "GITHUB_TOKEN", "")

    def _down(url, *a, **k):
        raise updater._HttpError(
            "The update server refused the request (HTTP 502).", 502)

    monkeypatch.setattr(updater, "_get_json", _down)
    with pytest.raises(updater.UpdaterError, match="HTTP 502"):
        updater.fetch_update()


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self, *a, **k):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_get_json_tolerates_utf8_bom_manifest(monkeypatch):
    """A BOM'd manifest (release.ps1 used to write one) must still parse —
    plain utf-8 decoding raised and failed the check."""
    payload = json.dumps({"version": "9.9.9", "url": "https://cdn/x.exe"})
    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        lambda *a, **k: _FakeResp(payload.encode("utf-8-sig")))
    data = updater._get_json_once("https://example.test/update.json")
    assert data["version"] == "9.9.9"


def test_is_nsis_installed_by_exe_location(monkeypatch, tmp_path):
    install_dir = tmp_path / "Maximum Tweaks"
    installed_exe = install_dir / EXE
    installed_exe.parent.mkdir(parents=True)
    installed_exe.write_bytes(b"MZ")
    elsewhere = tmp_path / "Desktop" / EXE

    monkeypatch.setattr(updater, "_install_dir_candidates",
                        lambda: [install_dir])
    assert updater.is_nsis_installed(installed_exe) is True
    assert updater.is_nsis_installed(elsewhere) is False

    monkeypatch.setattr(updater, "_install_dir_candidates", lambda: [])
    assert updater.is_nsis_installed(installed_exe) is False


def test_manifest_uses_setup_for_installed_copy(monkeypatch):
    _patch_manifest(monkeypatch, MANIFEST, installed=True)
    res = updater._fetch_update()
    assert res["url"] == MANIFEST["installer_url"]
    assert res["kind"] == "setup"
    assert res["filename"] == SETUP
    assert res["checksum_url"] == MANIFEST["installer_checksum_url"]
    assert res["sha256"] == "cd" * 32


def test_manifest_keeps_exe_for_portable_copy(monkeypatch):
    _patch_manifest(monkeypatch, MANIFEST, installed=False)
    res = updater._fetch_update()
    assert res["url"] == MANIFEST["url"]
    assert res["kind"] == "exe"
    assert res["filename"] == EXE
    assert res["sha256"] == "ab" * 32


def test_manifest_exe_fallback_when_installer_fields_missing(monkeypatch):
    data = {k: v for k, v in MANIFEST.items()
            if not k.startswith("installer")}
    _patch_manifest(monkeypatch, data, installed=True)
    res = updater._fetch_update()
    assert res["url"] == MANIFEST["url"]
    assert res["kind"] == "exe"
    assert res["filename"] == EXE


def test_manifest_forces_setup_filename_on_odd_installer_url(monkeypatch):
    data = dict(MANIFEST, installer_url="https://cdn.example/latest/")
    _patch_manifest(monkeypatch, data, installed=True)
    res = updater._fetch_update()
    assert res["url"] == "https://cdn.example/latest/"
    assert res["filename"] == SETUP


def _github_release():
    return {
        "tag_name": "v9.9.9",
        "body": "notes",
        "assets": [
            {"name": SETUP, "id": 3,
             "browser_download_url": f"https://gh.example/{SETUP}"},
            {"name": EXE, "id": 1,
             "browser_download_url": f"https://gh.example/{EXE}"},
            {"name": SETUP + ".sha256", "id": 4,
             "browser_download_url": f"https://gh.example/{SETUP}.sha256"},
            {"name": EXE + ".sha256", "id": 2,
             "browser_download_url": f"https://gh.example/{EXE}.sha256"},
        ],
    }


def test_github_assets_pick_setup_and_its_checksum(monkeypatch):
    _patch_github(monkeypatch, _github_release(), installed=True)
    res = updater._fetch_update()
    assert res["url"] == f"https://gh.example/{SETUP}"
    assert res["checksum_url"] == f"https://gh.example/{SETUP}.sha256"
    assert res["kind"] == "setup"
    assert res["filename"] == SETUP


def test_github_assets_pick_exe_and_its_checksum(monkeypatch):
    _patch_github(monkeypatch, _github_release(), installed=False)
    res = updater._fetch_update()
    assert res["url"] == f"https://gh.example/{EXE}"
    assert res["checksum_url"] == f"https://gh.example/{EXE}.sha256"
    assert res["kind"] == "exe"
    assert res["filename"] == EXE


def test_github_falls_back_to_exe_when_release_has_no_setup(monkeypatch):
    release = _github_release()
    release["assets"] = [a for a in release["assets"]
                         if not a["name"].startswith(SETUP)]
    _patch_github(monkeypatch, release, installed=True)
    res = updater._fetch_update()
    assert res["url"] == f"https://gh.example/{EXE}"
    assert res["kind"] == "exe"


def test_fetch_skipped_when_not_newer(monkeypatch):
    data = dict(MANIFEST, version=updater.APP_VERSION)
    _patch_manifest(monkeypatch, data, installed=True)
    assert updater._fetch_update() is None


@pytest.mark.parametrize("name,expected", [
    (SETUP, True),
    ("maximumtweaks-setup-2.6.0.exe", True),
    (EXE, False),
    ("MaximumTweaks-Setup-9.9.9.txt", False),
    (f"prefix{SETUP}", False),
    ("", False),
])
def test_is_setup_artifact_name(name, expected):
    assert updater._is_setup_artifact_name(name) is expected


@pytest.mark.parametrize("name,expected", [
    (SETUP, SETUP),
    ("../../evil.exe", "evil.exe"),
    ("", updater.UPDATE_EXE_NAME),
    (None, updater.UPDATE_EXE_NAME),
    (f"..\\..\\{SETUP}", SETUP),
])
def test_safe_name(name, expected):
    assert updater._safe_name(name) == expected


def test_install_requires_frozen_build(tmp_path):
    with pytest.raises(updater.UpdaterError, match="packaged .exe"):
        updater.install_and_restart(tmp_path / EXE)


def test_install_dispatches_setup(monkeypatch, tmp_path):
    setup = tmp_path / SETUP
    setup.write_bytes(b"MZ" + b"\0" * (6 * 1024 * 1024))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    seen = []

    def _recorder(path):
        seen.append(path)
        return path

    monkeypatch.setattr(updater, "_install_via_setup", _recorder)
    out = updater.install_and_restart(setup)
    assert seen == [setup]
    assert out == setup
    assert not (tmp_path / "data" / "updates").exists()


def test_install_dispatches_stub_for_exe(monkeypatch, tmp_path):
    downloaded = tmp_path / "downloaded" / EXE
    downloaded.parent.mkdir()
    downloaded.write_bytes(b"MZ" + b"\0" * (6 * 1024 * 1024))
    target = tmp_path / "installed" / EXE
    target.parent.mkdir()
    target.write_bytes(b"MZ" + b"\0" * (6 * 1024 * 1024))

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "exe_path", lambda: target)
    monkeypatch.setattr(updater.subprocess, "Popen",
                        lambda *a, **k: a)
    import engine.state as state
    monkeypatch.setattr(state, "_load", lambda: {})
    monkeypatch.setattr(state, "_save", lambda data: None)

    stub = updater.install_and_restart(downloaded)
    assert stub == (target.parent / "data" / "updates" / "apply_update.bat")
    assert stub.exists()
    assert (target.parent / "data" / "updates"
            / "MaximumTweaks.update.exe").exists()
    assert not downloaded.exists()


def test_setup_install_flushes_state_before_launch(monkeypatch, tmp_path):
    import engine.state as state
    events = []
    monkeypatch.setattr(state, "_load",
                        lambda: (events.append("load") or {}))
    monkeypatch.setattr(state, "_save",
                        lambda data: events.append("save"))
    monkeypatch.setattr(updater, "_shell_execute_setup",
                        lambda p: events.append(f"launch:{p.name}"))
    out = updater._install_via_setup(tmp_path / SETUP)
    assert events == ["load", "save", f"launch:{SETUP}"]
    assert out == tmp_path / SETUP


def test_data_dir_falls_back_to_localappdata(monkeypatch, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setattr(updater, "ROOT", blocker / "root")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    d = updater.data_dir()
    assert d == (tmp_path / "local" / "MaximumTweaks" / "updates").resolve()
    assert d.is_dir()


def test_setup_launch_shows_the_visible_update_wizard(tmp_path):
    """The updater must launch the setup with /UPDATE and a shown window, so
    the user watches the file-copy progress like a normal installation instead
    of getting a silent background swap."""
    info = updater._build_shell_info(tmp_path / SETUP)
    assert info.lpParameters == "/UPDATE"
    assert info.nShow == 5  # SW_SHOWNORMAL - a visible wizard, not SW_HIDE


def test_nsi_relaunches_app_on_every_install_path():
    """Regression for "press Restart and the app never opens": after an
    install the setup must launch the app in all three modes - /S (legacy
    2.5.4 updaters), /UPDATE (current updater), and a manual double-click
    (Finish page with a checked Launch box)."""
    nsi = (ROOT / "MaximumTweaks-Setup.nsi").read_text(encoding="utf-8")
    # manual wizard: Finish page offers a checked Launch box
    assert 'MUI_FINISHPAGE_RUN "$INSTDIR\\${EXENAME}"' in nsi
    # /UPDATE skips welcome + directory so the copy progress shows first
    assert '${GetOptions} $R0 "/UPDATE" $R1' in nsi
    assert "Function SkipIfUpdateMode" in nsi
    # silent + update mode both relaunch and quit; manual mode falls through
    # to the Finish page
    assert "IfSilent silent_run 0" in nsi
    assert 'StrCmp $UpdateMode "1" silent_run interactive_done' in nsi
