"""Live updater for Maximum Tweaks — checks, downloads and installs updates.

The release source is either:

* a plain JSON manifest (``UPDATE_MANIFEST_URL``), or
* the latest GitHub Release of ``GITHUB_REPO`` (strictly the asset named
  ``UPDATE_EXE_NAME``); the tag name doubles as the version string.

Pure-stdlib (urllib) so the updater works in the frozen exe without extra
dependencies. Two install strategies exist, and the artifact picks one:

* **NSIS install** (registry ``InstallDir`` contains the running exe): the
  downloaded ``MaximumTweaks-Setup-*.exe`` is launched silently (``/S``).
  It self-elevates (``RequestExecutionLevel admin``), so Program Files is
  writable even when this process is unelevated; its ``.onInit`` kills this
  instance before overwriting, and its silent branch relaunches the freshly
  installed exe — no batch waiter needed.
* **Portable** (anything else): the running .exe cannot overwrite itself, so
  a tiny batch stub waits for this process to exit, replaces
  ``MaximumTweaks.exe`` in place and relaunches it, then deletes itself.

All network/disk work happens off the UI thread (see ui/updater_dialog.py).
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
import hashlib
from pathlib import Path

from config.app_config import (
    APP_VERSION,
    GITHUB_REPO,
    GITHUB_TOKEN,
    ROOT,
    UPDATE_EXE_NAME,
    UPDATE_MANIFEST_URL,
)
from maxlog import logger


class UpdaterError(Exception):
    """Raised for any network/parse/install failure with a user message."""


def exe_path() -> Path:
    """Absolute path of the running/installable exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    # Dev fallback: the path the packaged build would live at.
    return (ROOT / "dist" / UPDATE_EXE_NAME).resolve()


def data_dir() -> Path:
    """Writable staging directory for downloads.

    Prefers ``ROOT/data/updates`` (next to the exe). An NSIS install lives
    under Program Files, which unelevated processes cannot write to, so fall
    back to ``%LOCALAPPDATA%`` when the primary location is not writable —
    the setup file only needs to be launchable from anywhere.
    """
    candidates = [(ROOT / "data" / "updates").resolve()]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append((Path(local) / "MaximumTweaks" / "updates").resolve())
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".write_probe"
            probe.write_bytes(b"")
            probe.unlink(missing_ok=True)
            return d
        except OSError:
            continue
    return candidates[0]


# ---------------------------------------------------------------------------
# NSIS install detection
# ---------------------------------------------------------------------------

_INSTALL_REG = r"Software\Maximum Tweaks"
_SETUP_PREFIX = "MaximumTweaks-Setup-"


def _install_dir_candidates() -> list[Path]:
    """``InstallDir`` as written by the NSIS installer.

    The installer writes HKCU and HKLM in the *default* registry view, which
    on 64-bit Windows is the 32-bit view, while Python's default read is the
    64-bit view — so probe both views of both hives.
    """
    try:
        import winreg
    except ImportError:  # pragma: no cover - non-Windows
        return []
    out: list[Path] = []
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(root, _INSTALL_REG, 0,
                                    winreg.KEY_READ | view) as key:
                    val, _ = winreg.QueryValueEx(key, "InstallDir")
            except OSError:
                continue
            if val:
                out.append(Path(str(val)))
    return out


def install_dir() -> Path | None:
    """Registered install folder, or None when the app was never installed."""
    for d in _install_dir_candidates():
        try:
            return d.resolve()
        except OSError:
            continue
    return None


def is_nsis_installed(exe: Path | None = None) -> bool:
    """True when this exe sits inside the registered NSIS install folder.

    Such copies must be updated by re-running the setup (Program Files is not
    writable unelevated); everything else uses the in-place exe swap.
    """
    d = install_dir()
    if d is None:
        return False
    try:
        return (exe or exe_path()).resolve().is_relative_to(d)
    except (OSError, ValueError):
        return False


def _url_basename(url: str) -> str:
    return Path(urllib.parse.urlparse(str(url or "")).path).name


def _is_setup_artifact_name(name: str) -> bool:
    n = Path(str(name or "")).name.lower()
    return n.startswith(_SETUP_PREFIX.lower()) and n.endswith(".exe")


def _is_setup_artifact(path: Path) -> bool:
    return _is_setup_artifact_name(Path(path).name)


def _safe_name(filename: str) -> str:
    """Download destination file name; rejects any path components."""
    name = Path(str(filename or "")).name
    return name if name else UPDATE_EXE_NAME


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def parse_version(text: str) -> tuple:
    """Normalize 'v1.2.3-beta' -> ((1, 2, 3), ('beta',)).

    Numeric runs are split from trailing letters inside each dot-part, so
    '3rc1' contributes 3 to the numbers and 'rc1' to the suffix. Comparing
    the numbers first keeps '2.5.3-rc1' newer than '2.5.2' (it contains newer
    code) while the suffix keeps a prerelease below its own release - see
    is_newer.
    """
    text = re.sub(r"[^0-9a-zA-Z.]", "", text).lstrip("vV")
    parts = text.split(".")
    nums: list = []
    suf: list = []
    for p in parts:
        m = re.match(r"(\d+)(.*)", p)
        if m:
            nums.append(int(m.group(1)))
            if m.group(2):
                suf.append(m.group(2))
        elif p:
            suf.append(p)
    return (tuple(nums), tuple(suf))


def is_newer(remote: str, local: str) -> bool:
    """True when remote is a newer version than local.

    Numbers decide first; with equal numbers a release beats its own
    prerelease ('2.5.3' > '2.5.3-rc1'), and prereleases order among
    themselves ('2.5.3-rc2' > '2.5.3-rc1'). That combination is what keeps a
    prerelease build from ever being offered the previous stable manifest
    (a downgrade), and keeps stable users from being offered an rc.
    """
    if remote == local:
        return False
    r_nums, r_suf = parse_version(remote)
    l_nums, l_suf = parse_version(local)
    if r_nums != l_nums:
        return r_nums > l_nums
    if bool(r_suf) != bool(l_suf):
        return not r_suf  # release beats prerelease at equal numbers
    return r_suf > l_suf


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class _HttpError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


def _get_json(url: str, timeout: float = 15.0, token: str = "",
              attempts: int = 3, backoff: float = 2.0) -> dict:
    """GET + parse a JSON endpoint with bounded retries.

    One retry is enough to absorb the free-tier cold start on Render (the
    instance sleeps after inactivity and the first request takes ~30s to wake
    it). Each attempt gets the full ``timeout``, so a hung socket can't stall
    the boot past timeout * attempts + backoff.
    """
    last_err = None
    for attempt in range(attempts):
        if attempt:
            logger.info(
                f"updater: retrying {url} (attempt {attempt + 1}/{attempts})")
            time.sleep(backoff * attempt)
        try:
            return _get_json_once(url, timeout, token)
        except _HttpError as exc:
            # Hard client errors won't heal from a retry — fail fast.
            if 400 <= getattr(exc, "status", 0) < 500:
                raise
            last_err = exc
            continue
    assert last_err is not None
    raise last_err


def _get_json_once(url: str, timeout: float = 15.0, token: str = "") -> dict:
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
        raise _HttpError(_http_reason(exc.code), exc.code) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise _HttpError(f"network error: {exc}") from exc


def _http_reason(status: int) -> str:
    """Friendly (and honest) label for an HTTP status, so the user is never
    told to check a VPN they do not have."""
    if status == 403:
        return ("The update server is rate-limiting requests right now "
                "(HTTP 403). This happens when too many updates are checked "
                "from one connection. Wait a few minutes and Retry.")
    if status == 429:
        return "Too many update checks in a short time (HTTP 429). Wait a bit and Retry."
    if status == 404:
        return ("No update was found for this app (HTTP 404). "
                "This build may not be published yet.")
    return f"The update server refused the request (HTTP {status})."


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



# ---------------------------------------------------------------------------# Remote update info
# ---------------------------------------------------------------------------

def fetch_update(timeout: float = 15.0) -> dict | None:
    """Return {version, notes, url} for a remote update, or None if current.

    Raises UpdaterError on network/config problems so the caller can choose to
    surface them; a None return means "you are up to date".
    """
    try:
        return _fetch_update(timeout)
    except _HttpError as exc:
        raise UpdaterError(str(exc)) from exc


def _fetch_update(timeout: float = 15.0) -> dict | None:
    checksum_url = ""
    sha256 = ""
    kind = "exe"
    filename = ""
    if UPDATE_MANIFEST_URL:
        data = _get_json(UPDATE_MANIFEST_URL.strip(), timeout)
        version = str(data.get("version") or "").strip()
        url = str(data.get("url") or "").strip()
        notes = str(data.get("notes") or "")
        checksum_url = str(data.get("checksum_url") or "").strip()
        sha256 = _normalize_sha256(str(data.get("sha256") or ""))
        if not version or not url:
            raise UpdaterError("The update manifest is missing version/url.")
        # Installed (NSIS) copies prefer the setup the manifest points at;
        # without installer fields the manifest keeps its old exe behavior.
        installer_url = str(data.get("installer_url") or "").strip()
        if installer_url and is_nsis_installed():
            url = installer_url
            checksum_url = str(
                data.get("installer_checksum_url") or "").strip()
            sha256 = _normalize_sha256(str(data.get("installer_sha256") or ""))
            kind = "setup"
        base = _url_basename(url)
        if kind == "setup":
            filename = (base if _is_setup_artifact_name(base)
                        else f"{_SETUP_PREFIX}{version}.exe")
        else:
            filename = (base if base.lower().endswith(".exe")
                        else UPDATE_EXE_NAME)
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
        assets = data.get("assets", [])
        want_setup = is_nsis_installed()

        def _find(setup: bool):
            for asset in assets:
                name = str(asset.get("name") or "")
                if setup:
                    if _is_setup_artifact_name(name):
                        return asset
                elif name == UPDATE_EXE_NAME:
                    return asset
            return None

        primary = _find(want_setup)
        if primary is None and want_setup:
            # No installer asset in this release - fall back to the exe.
            primary = _find(False)
            want_setup = False
        if primary is None:
            raise UpdaterError(
                f"No asset named {UPDATE_EXE_NAME!r} on the latest release.")
        name = str(primary.get("name") or "")
        kind = "setup" if want_setup else "exe"
        filename = name
        # Private repos: download via the authenticated API endpoint.
        asset_id = primary.get("id")
        if asset_id and GITHUB_TOKEN:
            url = _github_asset_url(asset_id)
        else:
            url = str(primary.get("browser_download_url") or "")
        # GitHub's API reports a server-computed digest on assets.
        digest = _normalize_sha256(str(primary.get("digest") or ""))
        if digest and not sha256:
            sha256 = digest
        # Checksum must be the sibling of the chosen artifact - a release
        # ships both .exe and setup .sha256 files.
        for asset in assets:
            if str(asset.get("name") or "") == name + ".sha256":
                checksum_url = str(asset.get("browser_download_url") or "")
                break
    logger.info(f"updater: update available: v{version} -> {url}")
    res = {"version": version, "notes": notes, "url": url,
           "kind": kind, "filename": filename}
    if checksum_url:
        res["checksum_url"] = checksum_url
    if sha256:
        res["sha256"] = sha256
    return res


# ---------------------------------------------------------------------------
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()


def _normalize_sha256(text: str) -> str:
    """Extract a bare 64-hex digest from 'sha256:<hex>', '<hex>  file', etc."""
    if not text:
        return ""
    m = re.search(r"[0-9a-fA-F]{64}", text)
    return m.group(0).lower() if m else ""


def _compare_sha256(path: Path, expected: str, source: str) -> None:
    """Fail-closed comparison; deletes the artifact on mismatch."""
    actual = _sha256_file(path)
    if actual != expected:
        path.unlink(missing_ok=True)
        raise UpdaterError(
            f"The downloaded update does not match the published {source} "
            "and was deleted. The file may be corrupt or tampered with — "
            "try again, or download the latest build manually.")
    logger.info(f"updater: {source} verified OK")


def _fetch_expected_sha256(url: str, timeout: float) -> str:
    """Download a published .sha256 file and return its digest (fail-closed)."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MaximumTweaks-updater/1.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read(4096).decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise UpdaterError(
            f"Could not download the update checksum: {exc}") from exc
    digest = _normalize_sha256(text)
    if not digest:
        raise UpdaterError("The published update checksum is missing or malformed.")
    return digest


def _verify_checksum(path: Path, checksum_url: str, timeout: float) -> None:
    _compare_sha256(path, _fetch_expected_sha256(checksum_url, timeout),
                    "SHA-256 checksum")


def _verify_sha256(path: Path, expected: str) -> None:
    digest = _normalize_sha256(expected)
    if not digest:
        raise UpdaterError("The published update checksum is malformed.")
    _compare_sha256(path, digest, "SHA-256 checksum")

# Download + install
# ---------------------------------------------------------------------------

def download(url: str, progress_cb=None, timeout: float = 60.0,
             checksum_url: str = "", expected_sha256: str = "",
             filename: str = "") -> Path:
    """Stream the artifact to data/updates/<filename>. progress_cb(got, total)."""
    logger.info("updater: download started")
    dest = data_dir() / _safe_name(filename)
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
                        progress_cb(got, total)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise UpdaterError(f"Download failed: {exc}") from exc
    size = dest.stat().st_size
    if size == 0:
        dest.unlink(missing_ok=True)
        raise UpdaterError("Downloaded file is empty.")
    logger.info(f"updater: downloaded {size} bytes")
    try:
        if expected_sha256:
            _verify_sha256(dest, expected_sha256)
        elif checksum_url:
            _verify_checksum(dest, checksum_url, timeout)
        _verify_download(dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
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


def _flush_state() -> None:
    """Persist applied-tweak/license state before a kill can happen."""
    try:
        from engine import state as _state
        _state._save(_state._load())
    except Exception:  # noqa: BLE001
        pass


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hKeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_ulong),
        ("hIconOrMonitor", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


def _shell_execute_setup(setup: Path) -> None:
    """Launch the downloaded NSIS setup silently (``/S``).

    ``lpVerb=None`` lets the shell honour the setup's own
    ``RequestExecutionLevel admin`` manifest: already-elevated processes run
    it directly, unelevated ones get the standard UAC consent prompt.
    """
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(_ShellExecuteInfo)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpFile = str(setup)
    info.lpParameters = "/S"
    info.lpDirectory = str(setup.parent)
    info.nShow = 0  # SW_HIDE - the silent installer draws nothing itself
    ok = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info))
    err = ctypes.windll.kernel32.GetLastError() if not ok else 0
    if info.hProcess:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
    if not ok:
        if err == 1223:  # ERROR_CANCELLED - the user declined the UAC prompt
            raise UpdaterError(
                "The Windows administrator prompt was declined, so the "
                "update was not installed. The downloaded installer is "
                "kept - run it manually, or accept the prompt and Retry.")
        raise UpdaterError(f"Could not start the installer (Windows error {err}).")


def _install_via_setup(setup: Path) -> Path:
    """Run the downloaded NSIS setup and let it replace + relaunch the app.

    State is flushed first because the installer's ``.onInit`` force-kills
    this process before overwriting the exe; the silent install branch then
    relaunches the new build, so no batch waiter is needed here.
    """
    logger.info("updater: launching NSIS setup for silent install")
    _flush_state()
    _shell_execute_setup(setup)
    logger.info(f"updater: NSIS setup launched ({setup})")
    return setup


def install_and_restart(new_exe: Path):
    """Prepare + launch the update, then the caller quits the app.

    The artifact picks the strategy: ``MaximumTweaks-Setup-*.exe`` runs the
    NSIS installer silently (it self-elevates and relaunches the app), any
    other executable goes through the in-place batch-stub swap.

    On success returns the launched path; callers should terminate the
    current process (os._exit / QApplication.quit) right after.
    """
    if not getattr(sys, "frozen", False):
        raise UpdaterError(
            "Updates apply to packaged .exe builds only — running from source, "
            "just restart the app.")
    if not new_exe.exists():
        raise UpdaterError("Downloaded update file is missing.")
    _verify_download(new_exe)

    if _is_setup_artifact(new_exe):
        return _install_via_setup(new_exe)

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
        script = _stub_script(original, staged).encode("ascii", errors="replace").decode("ascii")
        with open(stub, "w", encoding="ascii", errors="replace") as fh:
            fh.write(script)
    except OSError as exc:
        raise UpdaterError(f"Could not write the updater script: {exc}") from exc

    # Flush all state files before launching the stub — critical for
    # license persistence and applied-tweak state.
    _flush_state()

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