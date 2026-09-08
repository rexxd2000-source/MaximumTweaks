"""Live updater for Rex Tweaks — checks, downloads and installs updates.

The release source is either:

* a plain JSON manifest (``UPDATE_MANIFEST_URL``), or
* the latest GitHub Release of ``GITHUB_REPO`` (strictly the asset named
  ``UPDATE_EXE_NAME``); the tag name doubles as the version string.

Pure-stdlib (urllib) so the updater works in the frozen exe without extra
dependencies. The running .exe cannot overwrite itself, so installing works in
two stages:

1. download the new exe to ``data/updates/``,
2. write a tiny batch stub that waits for this process to exit, replaces
   ``RexTweaks.exe`` in place and relaunches it, then deletes itself.

All network/disk work happens off the UI thread (see ui/updater_dialog.py).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from config.app_config import (
    APP_VERSION,
    GITHUB_REPO,
    ROOT,
    UPDATE_EXE_NAME,
    UPDATE_MANIFEST_URL,
)
from rexlog import logger


class UpdaterError(Exception):
    """Raised for any network/parse/install failure with a user message."""


def exe_path() -> Path:
    """Absolute path of the running/installable exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    # Dev fallback: the path the packaged build would live at.
    return (ROOT / "dist" / UPDATE_EXE_NAME).resolve()


def data_dir() -> Path:
    """Writable staging directory for downloads."""
    d = (ROOT / "data" / "updates").resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def parse_version(text: str) -> tuple:
    """Normalize 'v1.2.3-beta' -> (1, 2, 3, 'beta'). Non-numeric parts sort last."""
    text = re.sub(r"[^0-9a-zA-Z.]", "", text).lstrip("vV")
    parts = text.split(".")
    nums: list = []
    suf: list = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
        elif p:
            suf.append(p)
    return (tuple(nums), tuple(suf))


def is_newer(remote: str, local: str) -> bool:
    if remote == local:
        return False
    return parse_version(remote) > parse_version(local)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class _HttpError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


def _get_json(url: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "RexTweaks-updater/1.0")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            try:
                return json.loads(resp.read().decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                raise _HttpError(f"invalid JSON from {url}") from exc
    except urllib.error.HTTPError as exc:
        raise _HttpError(f"HTTP {exc.code}", exc.code) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise _HttpError(f"network error: {exc}") from exc


def _github_api_url() -> str:
    owner_repo = (GITHUB_REPO or "").strip("/")
    if not owner_repo or "/" not in owner_repo:
        raise UpdaterError("Update checks not configured — set GITHUB_REPO.")
    return f"https://api.github.com/repos/{owner_repo}/releases/latest"


# ---------------------------------------------------------------------------
# Remote update info
# ---------------------------------------------------------------------------

def fetch_update(timeout: float = 15.0) -> dict | None:
    """Return {version, notes, url} for a remote update, or None if current.

    Raises UpdaterError on network/config problems so the caller can choose to
    surface them; a None return means "you are up to date".
    """
    if UPDATE_MANIFEST_URL:
        data = _get_json(UPDATE_MANIFEST_URL.strip(), timeout)
        version = str(data.get("version") or "").strip()
        url = str(data.get("url") or "").strip()
        notes = str(data.get("notes") or "")
        if not version or not url:
            raise UpdaterError("The update manifest is missing version/url.")
    else:
        data = _get_json(_github_api_url(), timeout)
        tag = str(data.get("tag_name") or "").strip().lstrip("v")
        if not tag:
            raise UpdaterError("The release has no version tag.")
        asset_url = ""
        for asset in data.get("assets", []):
            if str(asset.get("name")) == UPDATE_EXE_NAME:
                asset_url = str(asset.get("browser_download_url") or "")
                break
        if not asset_url:
            raise UpdaterError(
                f"No asset named {UPDATE_EXE_NAME!r} on the latest release.")
        version = tag
        notes = str(data.get("body") or "")
        url = asset_url

    if not is_newer(version, APP_VERSION):
        logger.info(f"updater: up to date (latest is v{version})")
        return None
    logger.info(f"updater: update available: v{version} -> {url}")
    return {"version": version, "notes": notes, "url": url}


# ---------------------------------------------------------------------------
# Download + install
# ---------------------------------------------------------------------------

def download(url: str, progress_cb=None, timeout: float = 60.0) -> Path:
    """Stream the exe to data/updates/UPDATE_EXE_NAME. progress_cb(frac)."""
    dest = data_dir() / UPDATE_EXE_NAME
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "RexTweaks-updater/1.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            chunksize = 1 << 16
            with open(dest, "wb") as fh:
                while True:
                    chunk = resp.read(chunksize)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    if total and progress_cb is not None:
                        progress_cb(min(1.0, got / total))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise UpdaterError(f"Download failed: {exc}") from exc
    if dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise UpdaterError("Downloaded file is empty.")
    logger.info(f"updater: downloaded {dest} ({dest.stat().st_size} bytes)")
    return dest


def _stub_script(target: Path, new_exe: Path) -> str:
    target = Path(target)
    new_exe = Path(new_exe)
    template = """@echo off
rem Rex Tweaks self-update stub
set "STUB_LOG=%~dp0stub.log"
del /Q "%STUB_LOG%" 2>nul
echo [%date% %time%] stub start >> "%STUB_LOG%"
:wait
tasklist /FI "IMAGENAME eq {exe}" | find /I "{exe}" > nul
if %errorlevel%==0 (
  timeout /t 1 /nobreak > nul
  goto :wait
)
echo [%date% %time%] swapping in new build >> "%STUB_LOG%"
move /Y "{new}" "{target}" >> "%STUB_LOG%" 2>&1
if not exist "{target}" copy /Y "{new}" "{target}" >> "%STUB_LOG%" 2>&1
echo [%date% %time%] relaunching "{target}" >> "%STUB_LOG%"
start "" "{target}" >> "%STUB_LOG%" 2>&1
del /Q "%~f0"
"""
    return template.format(exe=UPDATE_EXE_NAME, new=new_exe, target=target)


def install_and_restart(new_exe: Path):
    """Prepare + launch the swap stub, then the caller quits the app.

    On success returns the stub path that has been launched; callers should
    terminate the current process (os._exit / QApplication.quit) right after.
    """
    if not getattr(sys, "frozen", False):
        raise UpdaterError(
            "Updates apply to packaged .exe builds only — running from source, "
            "just restart the app.")
    if not new_exe.exists():
        raise UpdaterError("Downloaded update file is missing.")

    original = exe_path()
    if not original.exists():
        raise UpdaterError(f"Could not find the application at {original}")

    # Stage alongside the real exe so the batch can act on the same drive.
    stub_dir = original.parent / "data" / "updates"
    stub_dir.mkdir(parents=True, exist_ok=True)
    staged = stub_dir / "RexTweaks.update.exe"
    try:
        if staged.exists():
            staged.unlink()
        os.replace(new_exe, staged)
    except OSError as exc:
        raise UpdaterError(f"Could not stage the update: {exc}") from exc

    stub = stub_dir / "apply_update.bat"
    try:
        stub.write_text(_stub_script(original, staged), encoding="ascii")
    except OSError as exc:
        raise UpdaterError(f"Could not write the updater script: {exc}") from exc

    try:
        subprocess.Popen(
            [str(stub)],
            cwd=str(stub.parent),
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except OSError as exc:
        raise UpdaterError(f"Could not launch the updater: {exc}") from exc
    logger.info(f"updater: update stub launched ({stub})")
    return stub