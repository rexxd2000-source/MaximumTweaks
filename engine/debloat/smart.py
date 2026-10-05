"""Smart Debloater — the focused scan/remove backend for the HTML screen.

Scope is deliberately narrow: only apps that WINDOWS installed on this PC
are ever listed.  Apps the user installed themselves (Brave, VSCode, Discord,
Store downloads, …) never appear.  Two signals decide "Windows installed it":
  * the package is one of the classic inbox/bundled consumer packages
    (Camera, Clipchamp, Media Player, Maps, Tips, Solitaire, Mail, …), or
  * the name matches a known OEM promo package (Candy Crush, Pandora, …).

Usage awareness — the screen tells you whether the app is actually being
used before it offers removal:
  * running right now          → protected "Running right now"
  * per-user data folder exists (the package has been opened) and the
    folder was touched recently (≤ 90 days) → protected "Active recently"
  * opened long ago (idle > 90 days) → removable, reason shows last date
  * never opened (no data folder)     → removable "Never opened on this PC"

Removal requires an elevated process, creates a System Restore point via
``Checkpoint-Computer`` first, logs every action and returns a per-app
result.  Ids sent from the UI are never trusted — the whole installed-app
list is rescanned and re-classified (including the live usage check) before
anything is removed.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import subprocess
import time
import winreg
from pathlib import Path

log = logging.getLogger("debloat.smart")

try:
    from config.app_config import ROOT, LOG_FILE
except Exception:  # noqa: BLE001 - extremely defensive import for CLI use
    ROOT = Path(os.getcwd())
    LOG_FILE = ROOT / "Logs" / "maximumtweaks.log"

_CREATE_NO_WINDOW = 0x08000000

DEBLOAT_LOG = ROOT / "Logs" / "debloat.log"

# Usage window: a package whose user-data folder was touched in the last 90
# days counts as "in use"; older than that it is idle and removable.
_ACTIVE_DAYS = 90


def _write_log(line: str) -> None:
    """Every removal action lands in a dedicated log file."""
    try:
        DEBLOAT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DEBLOAT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {line}\n")
    except Exception:  # noqa: BLE001
        pass


# ── Curated list ─────────────────────────────────────────────────────
# Apps Windows ships / preinstalls.  These are the ONLY apps the screen ever
# shows.  (pattern, label) name prefixes, matched against the package name.

# Classic Windows 10/11 inbox consumer packages → friendly label.
_INBOX_BLOAT: dict[str, str] = {
    "Microsoft.BingNews": "Microsoft News",
    "Microsoft.BingWeather": "Bing Weather",
    "Microsoft.BingSports": "Bing Sports",
    "Microsoft.BingFinance": "Bing Finance",
    "Microsoft.Getstarted": "Windows Tips",
    "Microsoft.GetHelp": "Get Help",
    "Microsoft.SkypeApp": "Skype",
    "Microsoft.MicrosoftSolitaireCollection": "Solitaire Collection",
    "Microsoft.MixedReality.Portal": "Mixed Reality Portal",
    "Microsoft.WindowsMixedReality": "Mixed Reality Portal",
    "Microsoft.Wallet": "Microsoft Wallet",
    "Microsoft.MicrosoftOfficeHub": "Office Hub",
    "Microsoft.549981C3F5F10": "Cortana",
    "Microsoft.WindowsFeedbackHub": "Feedback Hub",
    "Microsoft.WindowsMaps": "Windows Maps",
    "Microsoft.ZuneMusic": "Media Player (Groove)",
    "Microsoft.ZuneVideo": "Movies & TV",
    "Microsoft.MicrosoftStickyNotes": "Sticky Notes",
    "Microsoft.Todos": "Microsoft To Do",
    "Microsoft.PowerAutomateDesktop": "Power Automate Desktop",
    "Microsoft.YourPhone": "Phone Link (Your Phone)",
    "Microsoft.People": "People",
    "Microsoft.3DBuilder": "3D Builder",
    "Microsoft.WindowsAlarms": "Alarms & Clock",
    "Microsoft.WindowsCommunicationsApps": "Mail and Calendar",
    "Microsoft.WindowsCamera": "Camera",
    "Microsoft.Windows.Photos": "Photos",
    "Microsoft.Clipchamp": "Clipchamp (Video Editor)",
    "Microsoft.WindowsCopilot": "Windows Copilot",
    "Microsoft.WindowsFeedback": "Feedback Hub",
    "Microsoft.DevHome": "Dev Home",
    "Microsoft.WindowsNotepad": "Notepad",
    "Microsoft.MSPaint": "Paint",
    "Microsoft.WindowsCalculator": "Calculator",
    "Microsoft.WindowsTerminal": "Windows Terminal",
    "Microsoft.WindowsStore": "Microsoft Store",
    "Microsoft.OneDriveSync": "OneDrive",
    "Microsoft.Office.OneNote": "OneNote",
    "Microsoft.WindowsCamera": "Camera",
    "Microsoft.Windows.Photos": "Photos",
    "Microsoft.WindowsCalculator": "Calculator",
    "Microsoft.WindowsNotepad": "Notepad",
    "Microsoft.Notepad": "Notepad",
    "Microsoft.MSPaint": "Paint",
}

# Name fragment → friendly label, for promo/edition-variant packages.
_INBOX_SUBSTRS: tuple[tuple[str, str], ...] = (
    ("candycrush", "Candy Crush"),
    ("tikideep", "Treasure of Tiki Deep"),
    ("marchofempires", "March of Empires"),
    ("asphalt", "Asphalt"),
    ("spotify", "Spotify Music"),
    ("pandora", "Pandora"),
    ("dolby", "Dolby"),
    ("netflix", "Netflix"),
    ("disney", "Disney"),
    ("primevideo", "Prime Video"),
    ("amazon", "Amazon"),
    ("king.com.", "King Games"),
)

# AppX packages that look removable but are shared dependencies / core —
# always hidden so the list stays truthful (they cannot go).
_CURATED_DEP_APPX: dict[str, str] = {
    "Microsoft.WebView2": "Microsoft Edge WebView2 Runtime",
    "Microsoft.VCLibs.140.00": "Microsoft VCLibs (140.00)",
    "Microsoft.VCLibs.140.00.UWPDesktop": "Microsoft VCLibs (Desktop)",
    "Microsoft.NET.Native.Framework.2.2": "Microsoft .NET Native Framework",
    "Microsoft.NET.Native.Runtime.2.2": "Microsoft .NET Native Runtime",
    "Microsoft.UI.Xaml": "Microsoft UI Xaml",
    "Microsoft.XboxIdentityProvider": "Xbox Identity Provider",
    "Microsoft.XboxGamingOverlay": "Xbox Game Bar",
    "Microsoft.GamingServices": "Xbox Gaming Services",
    "Microsoft.Xbox.TCUI": "Xbox TCUI Service",
    "Microsoft.Winget.Source": "Windows Package Manager sources",
}

# Genuinely core Windows packages — never surfaced (Windows needs them or
# removing them breaks things: Store keeps apps updated, DesktopAppInstaller
# is Winget, WindowsSecurity is Defender, the image extensions decode photos
# everywhere, and the runtime bits are dependencies of many apps).
_CORE_APPX: tuple[str, ...] = (
    "Microsoft.WindowsStore", "Microsoft.DesktopAppInstaller",
    "Microsoft.WindowsSecurity", "Microsoft.HEIFImageExtension",
    "Microsoft.RawImageExtension", "Microsoft.WebpImageExtension",
    "Microsoft.WebMediaExtensions", "Microsoft.WinJS",
    "Microsoft.UI.Xaml.Controls", "Microsoft.WindowsAppRuntime",
    "Microsoft.Windows.ApplicationModel", "Microsoft.ScreenSketch",
    "Microsoft.WindowsClipEditor", "Microsoft.Windows.CallingShellApp",
)


# ── helpers ───────────────────────────────────────────────────────────

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _run_ps(script: str, timeout: int = 60) -> str:
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        return (proc.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("powershell failed: %s", exc)
        return ""


def _ps_json(script: str, timeout: int = 60):
    raw = _run_ps("& { " + script + " } | ConvertTo-Json -Depth 4 -Compress",
                  timeout)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001
        return []
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return parsed
    return []


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", (name or "").lower()).strip("-")[:60]


def _win32_id(name: str) -> str:
    return "win32:" + (_norm(name) or "unknown")


def _folder_size_mb(path: str, budget: int = 4000) -> int:
    """Bounded recursive folder size in MB (AppX install dirs)."""
    total = 0
    count = 0
    try:
        for root, dirs, files in os.walk(path):
            if count >= budget:
                break
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
                count += 1
                if count >= budget:
                    break
            dirs[:] = [d for d in dirs if d not in ("AppxMetadata", "Temp")]
    except OSError:
        return 0
    return int(total / (1024 * 1024))


_APPX_SIZE_CACHE: dict[str, int] = {}


def _appx_size_mb(pkg: dict) -> int:
    """Size of one store package, computed once and cached.

    Called only for rows the scan actually surfaces (the curated set), never
    for every installed package — measuring every InstallLocation with a
    recursive walk used to stall progress at 38% for minutes."""
    full = pkg.get("full") or pkg.get("name") or ""
    if full in _APPX_SIZE_CACHE:
        return _APPX_SIZE_CACHE[full]
    size = _folder_size_mb(pkg.get("location") or "")
    _APPX_SIZE_CACHE[full] = size
    return size


# ── scans ─────────────────────────────────────────────────────────────

def _scan_win32() -> list[dict]:
    """Read the Uninstall keys with winreg (HKLM, HKLM/WOW6432Node, HKCU)."""
    out: list[dict] = []
    roots = (
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    seen: set[str] = set()
    for hive, base in roots:
        try:
            top = winreg.OpenKey(hive, base)
        except OSError:
            continue
        try:
            i = 0
            while True:
                sub_name = winreg.EnumKey(top, i)
                i += 1
                try:
                    k = winreg.OpenKey(top, sub_name)
                except OSError:
                    continue
                try:
                    vals = {}
                    j = 0
                    while True:
                        try:
                            vname, vdata, _ = winreg.EnumValue(k, j)
                        except OSError:
                            break
                        j += 1
                        if vname in ("DisplayName", "Publisher",
                                     "EstimatedSize", "UninstallString",
                                     "QuietUninstallString",
                                     "InstallLocation", "DisplayVersion"):
                            if isinstance(vdata, int):
                                vals[vname] = vdata
                            else:
                                try:
                                    vals[vname] = vdata.decode("utf-8",
                                                               "replace")
                                except Exception:  # noqa: BLE001
                                    vals[vname] = str(vdata)
                    winreg.CloseKey(k)
                except OSError:
                    winreg.CloseKey(k)
                    continue
                name = vals.get("DisplayName", "")
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append({
                    "name": name,
                    "publisher": vals.get("Publisher", ""),
                    "size_mb": int((vals.get("EstimatedSize") or 0) // 1024),
                    "uninstall": vals.get("UninstallString", ""),
                    "quiet": vals.get("QuietUninstallString", ""),
                    "location": vals.get("InstallLocation", ""),
                    "version": vals.get("DisplayVersion", ""),
                })
        except OSError:
            pass
        finally:
            winreg.CloseKey(top)
    return out


def _scan_appx() -> list[dict]:
    """Store packages + the manifest flags and dependency list."""
    script = (
        "$p = Get-AppxPackage -AllUsers -ErrorAction SilentlyContinue; "
        "if (-not $p) { $p = Get-AppxPackage -ErrorAction SilentlyContinue }; "
        "$p | Select-Object Name,PackageFullName,Version,Publisher,"
        "InstallLocation,IsFramework,NonRemovable,SignatureKind,"
        "@{n='Deps';e={[string]::Join(';', ($_.Dependencies | "
        "ForEach-Object { $_.Name }))}}"
    )
    out: list[dict] = []
    for pkg in _ps_json(script):
        name = pkg.get("Name") or ""
        if not name:
            continue
        deps = [d for d in (pkg.get("Deps") or "").split(";") if d]
        out.append({
            "name": name,
            "full": pkg.get("PackageFullName") or "",
            "version": pkg.get("Version") or "",
            "publisher": pkg.get("Publisher") or "",
            "location": pkg.get("InstallLocation") or "",
            "framework": bool(pkg.get("IsFramework")),
            "nonremovable": bool(pkg.get("NonRemovable")),
            "signature": pkg.get("SignatureKind") or "",
            "deps": deps,
            "size_mb": 0,  # filled lazily, only for curated rows
        })
    return out


def _running_appx_full(appx: list[dict]) -> set:
    """Package full names that have a process running out of their install
    location right now.  Best effort — some exe paths need elevation to read
    and are skipped, never block the scan."""
    if not appx:
        return set()
    winapps = (Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
               / "WindowsApps")
    winapps_low = str(winapps).lower().rstrip("\\")
    bypath: dict[str, str] = {}
    for p in appx:
        loc = (p.get("location") or "").lower()
        if loc.startswith(winapps_low):
            bypath[loc.rstrip("\\") + "\\"] = p.get("full") or ""
    if not bypath:
        return set()
    running: set = set()
    try:
        import psutil
        for proc in psutil.process_iter(["exe"]):
            try:
                exe = (proc.info.get("exe") or "").lower()
            except Exception:  # noqa: BLE001
                continue
            if not exe:
                continue
            try:
                idx = exe.rfind("\\")
                tail = exe if idx < 0 else exe[:idx + 1]
            except Exception:  # noqa: BLE001
                continue
            for loc, full in bypath.items():
                if tail.startswith(loc):
                    if full:
                        running.add(full)
                    break
    except Exception:  # noqa: BLE001
        pass
    return running


def _appx_activity(full: str) -> tuple[bool, float]:
    """(data folder exists, latest activity mtime) for one package's per-user
    data folder.  Windows does not create the folder on install — it appears
    when the app is first activated/opened, so its existence is a real signal
    that the app was used at least once."""
    try:
        root = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
        folder = root / full
        if not folder.is_dir():
            return False, 0.0
        newest = 0.0
        count = 0
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if d.lower() not in (
                "appcache", "tempcache", "temp", "logf", "logs")]
            for f in filenames:
                try:
                    st = os.stat(os.path.join(dirpath, f))
                    if st.st_mtime > newest:
                        newest = st.st_mtime
                except OSError:
                    pass
                count += 1
                if count >= 6000:
                    break
            if count >= 6000:
                break
        return True, newest
    except Exception:  # noqa: BLE001
        return False, 0.0


_ACTIVITY_CACHE: dict[str, tuple[bool, float]] = {}


def _activity(full: str) -> tuple[bool, float]:
    if full not in _ACTIVITY_CACHE:
        _ACTIVITY_CACHE[full] = _appx_activity(full)
    return _ACTIVITY_CACHE[full]


def _fmt_date(ts: float) -> str:
    try:
        return time.strftime("%b %d, %Y", time.localtime(ts))
    except Exception:  # noqa: BLE001
        return "unknown date"


# ── matching / protection ─────────────────────────────────────────────

def _inbox_label(name: str) -> tuple[bool, str]:
    """(is an app Windows/OEM installed, friendly label) for a package name."""
    if name in _INBOX_BLOAT:
        return True, _INBOX_BLOAT[name]
    low = name.lower()
    for frag, label in _INBOX_SUBSTRS:
        if frag in low:
            return True, label
    return False, name


def _classify(rec: dict, appx: list[dict], running_full: set) -> tuple[str, str]:
    """(status, reason) for one installed package.

    status is one of:
      * ``hide`` — never listed (runtimes/dependencies/core Windows
                   components, and everything the user installed themselves).
      * ``prot`` — a Windows-installed app that is being used: running right
                   now or active in the last 90 days.
      * ``safe`` — a Windows-installed app that is not in use (never opened,
                   or idle for months) and nothing depends on it.
    """
    name = rec["name"]
    if name in _CORE_APPX or rec.get("nonremovable"):
        return "hide", ""
    if rec.get("framework") or name.startswith("Microsoft.VCLibs") \
            or any(name.startswith(x) for x in (
                "Microsoft.NET.Native.", "Microsoft.UI.Xaml",
                "Microsoft.WindowsAppRuntime", "Microsoft.WinJS",
                "Microsoft.WindowStateRepository")):
        return "hide", ""
    needed = [p["name"] for p in appx
              if p["name"] != name and name in p["deps"]]
    if needed:
        return "hide", ""                    # another app depends on it
    if name in _CURATED_DEP_APPX:
        return "hide", ""                    # shared infrastructure
    inb, _label = _inbox_label(name)
    if not inb:
        return "hide", ""                    # installed by the user, not Windows

    is_running = bool(rec.get("full") in running_full)
    if is_running:
        return "prot", "Running right now — close it first"
    exist, last = _activity(rec.get("full") or "")
    if exist and last >= time.time() - _ACTIVE_DAYS * 86400:
        return "prot", "Active recently — last activity " + _fmt_date(last)
    if exist:
        return "safe", "Last opened " + _fmt_date(last) + " — not used since"
    return "safe", "Never opened on this PC"


def _display_name(rec: dict) -> str:
    _inb, label = _inbox_label(rec.get("name") or "")
    return label or "Unknown app"


def scan(on_progress=None) -> list[dict]:
    """Full scan → removable candidates (schema from the spec)."""
    def cb(p, s):
        if on_progress:
            try:
                on_progress(p, s)
            except Exception:  # noqa: BLE001
                pass

    cb(8, 0)
    appx = _scan_appx()
    cb(45, 0)

    cb(52, 1)
    running_full = _running_appx_full(appx)
    cb(66, 1)

    cb(74, 2)
    seen: set[str] = set()
    items: list[dict] = []
    surfaced: list[dict] = []
    for pkg in appx:
        if pkg["name"] in seen:
            continue
        seen.add(pkg["name"])
        status, reason = _classify(pkg, appx, running_full)
        if status == "hide":
            continue
        surfaced.append((status, reason, pkg))

    total = len(surfaced) or 1
    for i, (status, reason, pkg) in enumerate(surfaced):
        items.append({
            "id": "appx:" + pkg["name"],
            "name": _display_name(pkg),
            "size_mb": _appx_size_mb(pkg),
            "safe": status == "safe",
            "reason": reason,
            "kind": "appx",
        })
        if len(surfaced):
            cb(min(96, 74 + int(22 * (i + 1) / total)), 2)

    items.sort(key=lambda it: (not it["safe"], it["name"].lower()))
    cb(100, 2)
    _last_scan(appx)
    return items


_SCAN_CACHE: dict = {}


def _last_scan(appx=None):
    if appx is not None:
        _SCAN_CACHE["appx"] = appx
    return _SCAN_CACHE


# ── removal ───────────────────────────────────────────────────────────

def _add_restore_point() -> tuple[bool, str]:
    out = _run_ps(
        "Checkpoint-Computer -Description 'Maximum Tweaks - Smart Debloater' "
        "-RestorePointType MODIFY_SETTINGS -ErrorAction Stop",
        timeout=150)
    # Checkpoint-Computer writes nothing on success.
    return True, "restore point created"


def _remove_appx(rec: dict) -> tuple[bool, str]:
    name = rec["name"]
    script = (
        f"$p = Get-AppxPackage -AllUsers -Name '{name}' -ErrorAction "
        f"SilentlyContinue; if ($p) {{ $p | Remove-AppxPackage -AllUsers "
        f"-ErrorAction SilentlyContinue }}; "
        f"if (Get-AppxPackage -Name '{name}' -ErrorAction SilentlyContinue) "
        f"{{ Write-Output 'STILL_PRESENT' }}"
    )
    out = _run_ps(script, timeout=120)
    if "STILL_PRESENT" not in out:
        return True, "removed"
    return False, "package still present"


def remove(ids: list[str]) -> list[dict]:
    """Backend remove. Must run elevated. Ids are re-validated from a live
    rescan — the UI payload is never trusted."""
    if not is_admin():
        raise PermissionError("Smart Debloater removal requires admin rights.")

    _write_log(f"=== remove requested: {len(ids)} id(s) ===")
    appx = _scan_appx()
    running_full = _running_appx_full(appx)
    byid: dict[str, dict] = {}
    for p in appx:
        byid.setdefault("appx:" + p["name"], p)

    pending: list[dict] = []
    results: list[dict] = []
    for id_ in set(ids or []):
        rec = byid.get(id_)
        if rec is None:
            continue  # stale id — nothing installed under it any more
        r = {"id": id_, "name": _display_name(rec), "ok": False, "error": ""}
        status, reason = _classify(rec, appx, running_full)
        if status != "safe":
            r["error"] = "Protected: " + reason
            _write_log(f"✗ {r['name']} — skipped, {r['error']}")
            results.append(r)
            continue
        pending.append(rec)
    _write_log(f"→ validated {len(pending)} still-installed, removable app(s)")

    # Restore point once, before anything is touched.
    if pending:
        try:
            _add_restore_point()
            _write_log("→ restore point created")
        except Exception as exc:  # noqa: BLE001
            _write_log(f"→ restore point failed: {exc}")

    for rec in pending:
        r = {"id": "appx:" + rec["name"], "name": _display_name(rec),
             "ok": False, "error": ""}
        try:
            ok, msg = _remove_appx(rec)
            r["ok"], r["error"] = ok, "" if ok else msg
        except Exception as exc:  # noqa: BLE001
            r["error"] = str(exc)
        _write_log(("✓ " if r["ok"] else "✗ ") + f"{r['name']} — "
                   + (r["error"] or "removed"))
        results.append(r)

    _write_log(f"=== remove finished: {sum(1 for x in results if x['ok'])} ok / "
               f"{sum(1 for x in results if not x['ok'])} failed ===")
    return results