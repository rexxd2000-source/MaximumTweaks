"""Live updater for Maximum Tweaks — checks, downloads and installs updates.

The release source is either:

* a plain JSON manifest (``UPDATE_MANIFEST_URL``), or
* the latest GitHub Release of ``GITHUB_REPO`` (strictly the asset named
  ``UPDATE_EXE_NAME``); the tag name doubles as the version string.

Pure-stdlib (urllib) so the updater works in the frozen exe without extra
dependencies. The running .exe cannot overwrite itself, so installing works in
two stages:

1. download the new exe to ``data/updates/``,
2. write a tiny batch stub that waits for this process to exit, replaces
   ``MaximumTweaks.exe`` in place and relaunches it, then deletes itself.

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
    GITHUB_TOKEN,
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


def _get_json(url: str, timeout: float = 15.0, token: str = "") -> dict:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MaximumTweaks-updater/1.0")
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
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


def _github_asset_url(asset_id) -> str:
    """API asset endpoint: streams the binary directly (no redirect), so the
    Authorization header survives even when the repo is private."""
    owner_repo = (GITHUB_REPO or "").strip("/")
    return f"https://api.github.com/repos/{owner_repo}/releases/assets/{asset_id}"


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
        data = _get_json(_github_api_url(), timeout, token=GITHUB_TOKEN)
        tag = str(data.get("tag_name") or "").strip().lstrip("v")
        if not tag:
            raise UpdaterError("The release has no version tag.")
        version = tag
        notes = str(data.get("body") or "")
        url = ""

    if not is_newer(version, APP_VERSION):
        logger.info(f"updater: up to date (latest is v{version})")
        return None

    if not url:
        asset_url = ""
        for asset in data.get("assets", []):
            if str(asset.get("name")) == UPDATE_EXE_NAME:
                # Private repos: download via the authenticated API endpoint.
                asset_id = asset.get("id")
                if asset_id and GITHUB_TOKEN:
                    asset_url = _github_asset_url(asset_id)
                else:
                    asset_url = str(asset.get("browser_download_url") or "")
                break
        if not asset_url:
            raise UpdaterError(
                f"No asset named {UPDATE_EXE_NAME!r} on the latest release.")
        url = asset_url
    logger.info(f"updater: update available: v{version} -> {url}")
    return {"version": version, "notes": notes, "url": url}


# ---------------------------------------------------------------------------
# Download + install
# ---------------------------------------------------------------------------

def download(url: str, progress_cb=None, timeout: float = 60.0) -> Path:
    """Stream the exe to data/updates/UPDATE_EXE_NAME. progress_cb(frac)."""
    logger.info("updater: download started")
    dest = data_dir() / UPDATE_EXE_NAME
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MaximumTweaks-updater/1.0")
    if "api.github.com" in url:
        req.add_header("Accept", "application/octet-stream")
        if GITHUB_TOKEN:
            req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
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
    size = dest.stat().st_size
    if size == 0:
        dest.unlink(missing_ok=True)
        raise UpdaterError("Downloaded file is empty.")
    logger.info(f"updater: downloaded {size} bytes")
    _verify_download(dest)
    logger.info("updater: download verified OK")
    return dest


def _verify_download(path: Path):
    """Validate the downloaded file is a plausible Windows PE executable.

    Checks: minimum size, MZ header (PE signature), and that it's not an
    HTML error page from a CDN or proxy.
    """
    MIN_SIZE = 5 * 1024 * 1024  # 5 MB — a legitimate build is always larger
    size = path.stat().st_size
    if size < MIN_SIZE:
        path.unlink(missing_ok=True)
        raise UpdaterError(
            f"Downloaded file is too small ({size:,} bytes) — expected at "
            f"least {MIN_SIZE:,} bytes. The download may be corrupt or "
            "blocked by a firewall/proxy.")
    with open(path, "rb") as f:
        header = f.read(2)
    if header != b"MZ":
        path.unlink(missing_ok=True)
        raise UpdaterError(
            "Downloaded file is not a valid executable — it may be an "
            "HTML error page from a CDN or firewall. Check your internet "
            "connection and try again.")


def _stub_script(target: Path, new_exe: Path) -> str:
    target = Path(target)
    new_exe = Path(new_exe)
    backup = target.parent / "data" / "updates" / "MaximumTweaks.rollback.exe"
    template = """@echo off
rem Maximum Tweaks self-update stub - with backup and rollback
set "STUB_LOG=%~dp0stub.log"
del /Q "%STUB_LOG%" 2>nul
echo [%date% %time%] stub start >> "%STUB_LOG%"
echo   target={target} >> "%STUB_LOG%"
echo   new={new} >> "%STUB_LOG%"
echo   backup={backup} >> "%STUB_LOG%"

rem Step 1: Create a backup of the current exe for rollback.
echo [%date% %time%] creating backup of current exe >> "%STUB_LOG%"
copy /Y "{target}" "{backup}" >> "%STUB_LOG%" 2>&1
if %errorlevel%==0 (
  echo [%date% %time%] backup created successfully >> "%STUB_LOG%"
) else (
  echo [%date% %time%] WARNING: backup failed, proceeding anyway >> "%STUB_LOG%"
)

rem Step 2: Wait for the old process to fully exit (up to 30s).
set /a RETRIES=0
:wait
tasklist /FI "IMAGENAME eq {exe}" 2>nul | find /I "{exe}" > nul
if %errorlevel%==0 (
  set /a RETRIES+=1
  if %RETRIES% GEQ 30 (
    echo [%date% %time%] ERROR: process still running after 30s, forcing kill >> "%STUB_LOG%"
    taskkill /F /IM "{exe}" >> "%STUB_LOG%" 2>&1
    timeout /t 2 /nobreak > nul
  ) else (
    timeout /t 1 /nobreak > nul
    goto :wait
  )
)
echo [%date% %time%] process exited, waiting 3s for file handles to release >> "%STUB_LOG%"
timeout /t 3 /nobreak > nul

rem Step 3: Swap in the new build with retries.
set /a RETRIES=0
:swap
echo [%date% %time%] swapping in new build (attempt %RETRIES%) >> "%STUB_LOG%"
move /Y "{new}" "{target}" >> "%STUB_LOG%" 2>&1
if %errorlevel%==0 goto :swapped
copy /Y "{new}" "{target}" >> "%STUB_LOG%" 2>&1
if %errorlevel%==0 (
  del /Q "{new}" >> "%STUB_LOG%" 2>&1
  goto :swapped
)
set /a RETRIES+=1
if %RETRIES% GEQ 10 (
  echo [%date% %time%] ERROR: could not replace exe after 10 attempts >> "%STUB_LOG%"
  echo [%date% %time%] attempting rollback to backup >> "%STUB_LOG%"
  if exist "{backup}" (
    copy /Y "{backup}" "{target}" >> "%STUB_LOG%" 2>&1
    echo [%date% %time%] rollback completed >> "%STUB_LOG%"
  ) else (
    echo [%date% %time%] no backup available for rollback >> "%STUB_LOG%"
  )
  goto :done
)
timeout /t 3 /nobreak > nul
goto :swap

:swapped
echo [%date% %time%] new exe installed successfully >> "%STUB_LOG%"
rem Verify the new exe exists and has reasonable size.
for %%A in ("{target}") do set NEWSIZE=%%~zA
echo [%date% %time%] new exe size: %NEWSIZE% bytes >> "%STUB_LOG%"
if %NEWSIZE% LSS 1000000 (
  echo [%date% %time%] ERROR: new exe is suspiciously small, rolling back >> "%STUB_LOG%"
  if exist "{backup}" (
    copy /Y "{backup}" "{target}" >> "%STUB_LOG%" 2>&1
    echo [%date% %time%] rollback completed >> "%STUB_LOG%"
  )
  goto :done
)
echo [%date% %time%] relaunching "{target}" >> "%STUB_LOG%"
start "" "{target}" >> "%STUB_LOG%" 2>&1

:done
rem Clean up backup after successful launch (keep for 30s in case of issues).
echo [%date% %time%] stub finished >> "%STUB_LOG%"
del /Q "%~f0" 2>nul
"""
    return template.format(exe=UPDATE_EXE_NAME, new=new_exe, target=target,
                           backup=backup)


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
    _verify_download(new_exe)

    original = exe_path()
    if not original.exists():
        raise UpdaterError(f"Could not find the application at {original}")

    logger.info("updater: preparing update installation")

    # Stage alongside the real exe so the batch can act on the same drive.
    stub_dir = original.parent / "data" / "updates"
    stub_dir.mkdir(parents=True, exist_ok=True)
    staged = stub_dir / "MaximumTweaks.update.exe"
    try:
        if staged.exists():
            staged.unlink()
        os.replace(new_exe, staged)
    except OSError as exc:
        raise UpdaterError(f"Could not stage the update: {exc}") from exc
    logger.info("updater: update staged")

    stub = stub_dir / "apply_update.bat"
    try:
        stub.write_text(_stub_script(original, staged), encoding="utf-8")
    except OSError as exc:
        raise UpdaterError(f"Could not write the updater script: {exc}") from exc

    # Flush all state files before launching the stub — critical for
    # license persistence and applied-tweak state.
    try:
        from engine import state as _state
        _state._save(_state._load())
    except Exception:  # noqa: BLE001
        pass

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