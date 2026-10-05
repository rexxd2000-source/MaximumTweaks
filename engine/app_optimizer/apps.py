"""Per-app deep debloat plans for the App Optimizers screen.

Each app plan is a dict:

    {
      "key": "discord",
      "name": "Discord",
      "desc": "...",
      "icon": "discord",             # key used by the HTML to pick an svg
      "color": "#5865F2",
      "processes": ["Discord.exe"],  # real RAM measurement by process name
      "impact": 3,                   # 1..4 filled impact bars
      "features": ["...", "..."],    # chips under the app card
      "ops": [
         {"id": "locale", "title": "Strip locale bundles",
          "desc": "...", "default": True, "optional": False,
          "category": "disk", "run": fn},
         {... "optional": True ...}   # only runs when user needs it
      ],
      "options": {"telemetry": {"label": "Block telemetry hosts",
                                "default": False}},
    }

``activate`` runs every default op plus any optional ``option_ids`` the user
checks, records each op's snapshot records into the ledger, and returns
(human_errors, changed_count).  ``reset`` inverts the ledger in reverse.

Detection is a one-shot scan returning install state + measured RAM; the
bridge page reads it via ``detect_payload``.
"""
from __future__ import annotations

import functools
import glob
import json
import os
import time
from pathlib import Path

from engine import reg_util
from engine.app_optimizer import core
from engine.app_optimizer import deep
from maxlog import logger

# Process names each app is *measured* by, and the subset we are willing to
# change scheduling on. They differ on purpose: msedgewebview2.exe is shared
# with every WebView2 host on the box (Widgets, Office, third-party apps), so
# dropping its priority would slow down programs the user never optimized.
ENGAGED_PROCESSES: dict[str, list[str]] = {
    "discord": ["Discord.exe"],
    "edge": ["msedge.exe"],
    "chrome": ["chrome.exe"],
    "spotify": ["Spotify.exe"],
    "brave": ["brave.exe"],
}

# How each app is re-scheduled after every launch. Consumed by the triage
# watcher (deep.triage_pass) and mirrored onto the plan for the UI.
SCHED_SPECS: dict[str, dict] = {
    "discord": {"priority": "below", "cores": 4, "ecoqos": True,
                "kill_types": ["gpu-process", "crashpad-handler"]},
    "edge": {"priority": "below", "cores": 4, "ecoqos": True},
    "chrome": {"priority": "below", "cores": 4, "ecoqos": True},
    "spotify": {"priority": "below", "cores": 2, "ecoqos": True},
    "brave": {"priority": "below", "cores": 4, "ecoqos": True},
}


def expand_path(raw: str) -> str:
    return os.path.expandvars(raw)


# ---------------------------------------------------------------- helpers

def _latest_version_dir(base: str, prefix: str = "app-") -> str | None:
    """Highest <base>/<prefix><n> folder, or None."""
    if not base or not os.path.isdir(base):
        return None
    dirs = [d for d in glob.glob(os.path.join(base, prefix + "*"))
            if os.path.isdir(d)]
    return max(dirs) if dirs else None


def _chrome_version_dir(base: str) -> str | None:
    """Highest <base>/<version> folder containing a Locales dir."""
    if not base or not os.path.isdir(base):
        return None
    dirs = [d for d in glob.glob(os.path.join(base, "*"))
            if os.path.isdir(os.path.join(d, "Locales"))]
    return max(dirs) if dirs else None


def strip_locales(locales_dir: str | None, keep: str = "en-US") -> tuple[list, bool, str]:
    """Move every ``.pak`` bundle except the kept locale into the backup store."""
    records = []
    if not locales_dir or not os.path.isdir(locales_dir):
        return records, False, "locale folder not found"
    moved = 0
    for name in sorted(os.listdir(locales_dir)):
        full = os.path.join(locales_dir, name)
        if not os.path.isfile(full) or not name.lower().endswith(".pak"):
            continue
        if name.lower().startswith(keep.lower()):
            continue
        rec, ok = core.move_away(full, "locale pak")
        if ok:
            records.append(rec)
            moved += 1
        else:
            logger.warn(f"app_optimizer: could not move {full}: {rec.get('error')}")
    if moved:
        return records, True, f"{moved} locale bundle(s) moved to backup"
    return records, False, "only en-US present — nothing to strip"


def _policy_snapshot_apply(policy_path: str,
                           values: dict[str, tuple[int, str]]) -> tuple[list, bool, str]:
    r"""Snapshot + write registry policy values under HKCU\Software\Policies\..."""
    records, ok, written, same = [], True, 0, []
    hive, path = "HKCU", policy_path
    for name, (val, vtype) in values.items():
        # Read before touching: a value already at the intended value produces
        # no snapshot and no ledger entry. Recording those made a plan look
        # "changed" (and marked the app engaged) on a machine where the policy
        # was already correct, and gave reset a no-op entry to unwind.
        existed, rtype, data = reg_util.read_value(hive, path, name)
        if existed and reg_util.value_equals(data, rtype, val, vtype):
            same.append(name)
            continue
        records.append(core.reg_snapshot(hive, path, name))
        wok, msg = reg_util.write_value(hive, path, name, val, vtype)
        if wok:
            written += 1
        else:
            ok = False
            logger.warn(f"app_optimizer: policy {name} not written: {msg}")
    if not records:
        note = f"policies already correct ({', '.join(same)})" if same \
            else "policies already correct"
        return [], True, note
    note = f"{written} policy value(s) written"
    if same:
        note += f" · {len(same)} already correct"
    if not ok:
        note += " · some values failed"
    return records, ok, note


def _disable_tasks_matching(pattern: str) -> tuple[list, int]:
    """Disable every scheduled task whose name matches ``pattern``."""
    records, n = [], 0
    txt = core._ps(
        "((Get-ScheduledTask -ErrorAction SilentlyContinue) | "
        f"Where-Object {{ $_.TaskName -like '{pattern}' }}).TaskName")
    for line in (txt or "").splitlines():
        name = line.strip().split(",")[0].strip()
        if not name:
            continue
        rec, ok = core.disable_task(name)
        if rec.get("error"):
            core.logger.warn(f"app_optimizer: {rec['error']}")
        if not rec.get("missing") and rec.get("changed"):
            # Only record tasks we actually changed, so reset re-enables
            # exactly what we disabled and nothing the user had off already.
            records.append(rec)
            n += 1
    return records, n


# ================================================================ Discord

# Telemetry-only endpoints. Never list discord.com / *.discordapp.com / voice
# or CDN hosts here: those serve the app itself, and blocking them makes
# Discord fail to connect or load content.
DISCORD_TELEMETRY_HOSTS = [
    "sentry.io",                       # crash/error reporting
    "analytics.discord.com",           # usage analytics
    "science.discordapp.com",          # /api/science experiments endpoint
    "rum.browser-intake-datadoghq.com",  # real-user monitoring
]



def _discord_ctx() -> dict:
    base = expand_path(r"%LOCALAPPDATA%\Discord")
    ver = _latest_version_dir(base)
    exe = os.path.join(ver, "Discord.exe") if ver else None
    return {
        "base": base,
        "ver": ver,
        "exe": exe,
        "launcher": os.path.join(base, "Update.exe"),
        "locales": os.path.join(ver, "locales") if ver else None,
        "settings": expand_path(r"%APPDATA%\Discord\settings.json"),
        "modules": os.path.join(ver, "modules") if ver else None,
        "run_path": r"Software\Microsoft\Windows\CurrentVersion\Run",
        # Start from the launcher so a version bump does not orphan the process
        # tree, and pass Discord.exe explicitly the way Discord's own shortcuts
        # do. Any flags we append land after the exe name, which is what makes
        # Update.exe forward them to the real client process.
        "launch_args": (f'--processStart "{exe}" --process-start-StartDiscord'
                        if exe else ""),
    }


# Chromium/Electron flags that cut background GPU and media work without
# touching a single file in the signed package. They are appended to the user
# level launch command (Run value + .lnk), so an app update that replaces the
# install tree cannot invalidate them.
DISCORD_LAUNCH_FLAGS = [
    "--disable-gpu",
    "--disable-gpu-compositing",
    "--disable-features=HardwareMediaKeyHandling",
]


def op_discord_locale(ctx: dict) -> tuple[list, bool, str]:
    return strip_locales(ctx.get("locales"))


# Keys written into Discord's settings.json, kept as one dict so the writer and
# the post-restart verifier (verify_settings) cannot drift apart.
DISCORD_PREF_KEYS = {
    "enableHardwareAcceleration": False,  # no GPU process work
    "SKIP_HOST_UPDATE": True,             # no "check for updates" ping
}


def op_discord_settings(ctx: dict) -> tuple[list, bool, str]:
    path = ctx.get("settings")
    if not path or not os.path.isfile(path):
        return [], False, "settings.json not found"
    rec, ok = core.snapshot_text(path)
    if not ok:
        return [], False, rec.get("error", "settings.json unreadable")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [], False, f"settings.json invalid json: {exc}"
    if not isinstance(data, dict):
        return [], False, "settings.json is not an object"
    for k, v in DISCORD_PREF_KEYS.items():
        data[k] = v
    try:
        Path(path).write_text(json.dumps(data, indent=2),
                              encoding="utf-8", newline="\n")
    except Exception as exc:  # noqa: BLE001
        return [], False, f"settings.json write failed: {exc}"
    return [rec], True, "HW accel + host update check off"


def op_discord_launch_args(ctx: dict) -> tuple[list, bool, str]:
    """Append Discord's GPU flags to its shortcuts.

    Delivered through the .lnk only. The HKCU\\Run value is deliberately left
    alone: the updater op removes Discord's autostart in the same pass, so
    writing flags there was pointless (immediately deleted) and actively harmful
    — the updater's snapshot then captured the *flagged* value, so reset would
    have restored the flags instead of the user's original command.
    """
    links = deep.find_shortcuts(["Discord"])
    recs, ok, note = deep.patch_shortcut_flags(links, DISCORD_LAUNCH_FLAGS)
    if not recs:
        return [], True, note
    return recs, ok, note


def op_discord_schedule(ctx: dict) -> tuple[list, bool, str]:
    """Drop the live processes to Below Normal, confine them, and enable
    Efficiency Mode.

    This is a live Win32 adjustment, so nothing is written to the app. The ledger
    records the *intent* plus each process's real pre-change priority and
    affinity mask, so reset restores what the process actually had instead of
    assuming normal/all-cores.
    """
    sched = SCHED_SPECS["discord"]
    procs = ENGAGED_PROCESSES["discord"]
    # Snapshot before touching anything: this is the only way to undo exactly.
    before = deep.snapshot_scheduling(procs) if procs else []
    parts = []
    n, _note = deep.set_priority(procs, sched["priority"])
    parts.append(f"{n} proc below-normal")
    if sched.get("cores"):
        n, _note = deep.set_affinity(procs, sched["cores"])
        parts.append(f"{n} proc on {sched['cores']} cores")
    if sched.get("ecoqos"):
        n, _note = deep.set_efficiency_mode(procs, True)
        parts.append(f"efficiency mode x{n}")
    if sched.get("kill_types"):
        n, kinds = deep.kill_children(procs, sched["kill_types"])
        if n:
            parts.append(f"stopped {n} {','.join(kinds)}")
    return ([{"kind": "sched", "app": "discord", "processes": procs,
              "spec": sched, "before": before}] if procs else []), True, " · ".join(parts) or "app not running"


def op_discord_helpers(ctx: dict) -> tuple[list, bool, str]:
    """Stop the GPU and crash-reporting child processes.

    Discord runs as one image name with several ``--type=`` children; the GPU
    process and the crashpad handler are the two that keep doing work with the
    window idle. They are not separate executables, so they are addressed by
    their launch type rather than by name. Discord respawns them on demand,
    which is why the triage watcher repeats this.
    """
    sched = SCHED_SPECS["discord"]
    n, kinds = deep.kill_children(ENGAGED_PROCESSES["discord"],
                                  sched.get("kill_types") or [])
    if not n:
        return [], True, "no GPU/crashpad helper running"
    return ([{"kind": "sched", "app": "discord",
              "processes": ENGAGED_PROCESSES["discord"], "spec": sched}],
            True, f"stopped {n} {', '.join(kinds)} process(es)")


def op_discord_updater(ctx: dict) -> tuple[list, bool, str]:
    """Kill/disable the background updater + its autostart Run value.

    The registry snapshot is only recorded when the value actually existed.
    Recording it unconditionally made this op report "changed" (and mark the app
    engaged) even on a machine with no Discord autostart entry at all.
    """
    records = []
    stopped = core.terminate_processes(["Update.exe"])
    snap = core.reg_snapshot("HKCU", ctx["run_path"], "Discord")
    if snap.get("existed"):
        # Check the delete. A silent failure here used to record the removal and
        # report success, so reset would restore an entry that was never taken
        # away and the page would claim the app was optimized.
        ok, msg = reg_util.delete_value("HKCU", ctx["run_path"], "Discord")
        if not ok:
            return records, False, f"autostart entry could not be removed: {msg}"
        records.append(snap)
    task_recs, n = _disable_tasks_matching("Discord*")
    records.extend(task_recs)
    note = "updater off" + (f" · killed {len(stopped)}" if stopped else "")
    if n:
        note += f" · disabled {n} task(s)"
    if not records:
        return [], True, note + " (nothing to change)"
    return records, True, note


def _rename_module(modules: str, prefix: str, label: str) -> tuple[list, bool, str]:
    """Move a `modules\\<prefix>*` directory to backup so Discord's module
    loader cannot find it. Fully reversible via the returned record."""
    if not modules or not os.path.isdir(modules):
        return [], False, "modules folder not found"
    for name in sorted(os.listdir(modules)):
        if name.lower().startswith(prefix.lower()):
            r, ok = core.move_away(os.path.join(modules, name), label)
            if ok:
                return [r], True, f"{label} renamed to backup"
            if r.get("missing"):
                return [], True, f"{label} already removed"
            return [], False, f"{label} locked: {r.get('error')}"
    return [], False, f"no {prefix}* module found"


def op_discord_overlay(ctx: dict) -> tuple[list, bool, str]:
    """Rename the GPU overlay module out of the way (overlay only, not core)."""
    return _rename_module(ctx.get("modules"), "discord_overlay2", "overlay module")


def op_discord_spellcheck(ctx: dict) -> tuple[list, bool, str]:
    """Remove the discord_spellcheck module (the real mechanism — there is no
    DISABLE_SPELLCHECK setting key in settings.json)."""
    return _rename_module(ctx.get("modules"), "discord_spellcheck", "spellcheck module")


def op_discord_hosts(ctx: dict) -> tuple[list, bool, str]:
    rec, ok = core.hosts_block(DISCORD_TELEMETRY_HOSTS, "discord")
    return ([rec] if ok else []), ok, ("telemetry hosts blocked"
                                       if ok else rec.get("error", "hosts block failed"))


# ==================================================== Chromium (Edge/Chrome)

_EDGE_TASKS = ("MicrosoftEdgeUpdateTask*",)
_CHROME_TASKS = ("GoogleUpdateTaskMachine*",)

# The updater *services*, discovered by pattern because the exact names differ
# per version and SKU: Edge ships edgeupdate/edgeupdatem, Chrome ships
# version-stamped GoogleUpdaterService<version>, Brave ships literally
# "brave"/"bravem". Only services actually present are touched.
_SERVICE_PATTERNS = {
    "edge": (r"^edgeupdate", r"^MicrosoftEdgeUpdate"),
    "chrome": (r"^GoogleUpdater(Service|InternalService)",),
    "brave": (r"^brave$", r"^bravem$"),
}
# Elevation services are deliberately excluded: they are what lets the browser
# write to Program Files, and they only run on demand. Disabling them buys
# nothing and can block legitimate self-updates.


def _chromium_ctx(kind: str) -> dict:
    if kind == "edge":
        roots = (expand_path(r"%ProgramFiles(x86)%\Microsoft\Edge\Application"),
                 r"C:\Program Files (x86)\Microsoft\Edge\Application",
                 expand_path(r"%ProgramFiles(x86)%\Microsoft\EdgeCore"),
                 r"C:\Program Files (x86)\Microsoft\EdgeCore",
                 r"C:\Program Files\Microsoft\Edge\Application",
                 expand_path(r"%LOCALAPPDATA%\Microsoft\Edge\Application"))
        policies = r"Software\Policies\Microsoft\Edge"
        tasks = _EDGE_TASKS
        exe_name = "msedge.exe"
        helper = ["MicrosoftEdgeUpdate.exe"]
    else:
        roots = (expand_path(r"%ProgramFiles%\Google\Chrome\Application"),
                 expand_path(r"%ProgramFiles(x86)%\Google\Chrome\Application"))
        policies = r"Software\Policies\Google\Chrome"
        tasks = _CHROME_TASKS
        exe_name = "chrome.exe"
        helper = ["GoogleUpdate.exe", "GoogleUpdateCore.exe"]
    base = next((r for r in roots if os.path.isdir(r)), None)
    ver = _chrome_version_dir(base) if base else None
    return {
        "kind": kind,
        "base": base,
        "ver": ver,
        # The real browser binary lives in the version folder; the Application
        # root only has it for some installs. Prefer whichever exists.
        "exe": next((p for p in (os.path.join(ver, exe_name) if ver else None,
                                 os.path.join(base, exe_name) if base else None)
                     if p and os.path.isfile(p)), None),
        "exe_name": exe_name,
        "locales": os.path.join(ver, "Locales") if ver else None,
        "policies": policies,
        "tasks": tasks,
        "helper": helper,
        "run_path": r"Software\Microsoft\Windows\CurrentVersion\Run",
        "launch_args": "",
    }


def op_chromium_locale(ctx: dict) -> tuple[list, bool, str]:
    return strip_locales(ctx.get("locales"))


def op_chromium_policy(ctx: dict) -> tuple[list, bool, str]:
    values = {
        "BackgroundModeEnabled": (0, "DWORD"),
        "ComponentUpdatesEnabled": (0, "DWORD"),
        "MetricsReportingEnabled": (0, "DWORD"),
        "UrlKeyedAnonymizedDataCollectionEnabled": (0, "DWORD"),
    }
    if ctx["kind"] == "edge":
        values["StartupBoostEnabled"] = (0, "DWORD")
    else:
        # Chrome's background sync keeps a signed-in profile replicating in the
        # background; the policy level stops it without touching the account.
        values["SyncDisabled"] = (1, "DWORD")
        values["BrowserSignin"] = (0, "DWORD")
    return _policy_snapshot_apply(ctx["policies"], values)


def op_chromium_prefetch(ctx: dict) -> tuple[list, bool, str]:
    """Turn off speculative connections and prefetching at the policy level.

    Two corrections to the previous version:

    * Value 2 is "alternate" — it disables prefetch but leaves preconnect on, so
      it only half did what it claimed. 0 is the fully-off state.
    * This is a *policy*, so it belongs under ``Software\\Policies`` in HKCU. The
      old comment claimed HKCU policy would be "silently ignored" and forced
      HKLM; that is backwards — user policy takes precedence over machine
      policy, and HKCU additionally needs no elevation, so the setting now
      actually applies for a normal (non-admin) run.
    """
    key = ctx["policies"]
    if reg_util.value_equals("HKCU", key, "NetworkPredictionOptions", 0):
        return [], True, "prefetch + preconnect already off"
    snap = core.reg_snapshot("HKCU", key, "NetworkPredictionOptions")
    ok, msg = reg_util.write_value("HKCU", key, "NetworkPredictionOptions",
                                   0, "DWORD")
    if not ok:
        return [], False, f"prefetch policy not set: {msg}"
    return [snap], True, "prefetch + preconnect off"


def op_chromium_autostart(ctx: dict) -> tuple[list, bool, str]:
    """Remove the browser's own HKCU\\Run autostart entry.

    Snapshot-based, so an entry that is not there is a clean no-op and one that
    is there is restored verbatim on reset. The MicrosoftEdge/Chrome/Google
    Chrome entries are matched by name so an unrelated Run value is never hit.
    """
    name = {"edge": "MicrosoftEdge", "chrome": "Google Chrome"}.get(ctx["kind"], "")
    if not name:
        return [], False, "unknown browser"
    snap = core.reg_snapshot("HKCU", ctx["run_path"], name)
    if not snap.get("existed"):
        return [], True, f"no {name} autostart entry"
    ok, msg = reg_util.delete_value("HKCU", ctx["run_path"], name)
    if not ok:
        return [], False, f"autostart entry {name} could not be removed: {msg}"
    return [snap], True, f"autostart entry {name} removed"


def op_chromium_services(ctx: dict) -> tuple[list, bool, str]:
    """Stop and disable the browser's updater *services*.

    This is the part that actually removes the recurring background work: the
    scheduled task only fires on a schedule, whereas the service can be woken by
    any component. Each service's real start type is snapshotted first so reset
    puts back exactly what was configured.

    Failure is reported rather than swallowed. This used to return ok=True
    unconditionally, so a denied ``sc.exe config`` was dropped on the floor and
    the page showed the app as optimized while the service was still running.
    """
    records, notes, failed = [], [], []
    found = deep.existing_services(*_SERVICE_PATTERNS[ctx["kind"]])
    if not found:
        return [], True, "no updater service installed"
    for svc in found:
        rec, ok = deep.disable_service(svc)
        if not ok:
            failed.append(rec.get("error") or f"{svc} could not be disabled")
        if rec.get("changed"):
            records.append(rec)
            notes.append(f"{svc} disabled")
        elif rec.get("already"):
            notes.append(f"{svc} already off")
    if failed:
        # Partial success still records what did change, but the caller must
        # surface this rather than pretend the app is fully optimized.
        return records, False, " · ".join(failed + notes)
    if not records:
        return [], True, " · ".join(notes) or "updater services already off"
    return records, True, " · ".join(notes)


def op_chromium_updater(ctx: dict) -> tuple[list, bool, str]:
    records, n = [], 0
    stopped = core.terminate_processes(ctx["helper"])
    for pat in ctx["tasks"]:
        recs, k = _disable_tasks_matching(pat)
        records.extend(recs)
        n += k
    note = "updater process/task off"
    if stopped:
        note += f" · killed {len(stopped)}"
    if n:
        note += f" · disabled {n} task(s)"
    return records, True, note


def op_chromium_deep(ctx: dict) -> tuple[list, bool, str]:
    """Second wave of browser policies: the recurring idle work.

    Every value here is a documented, per-user policy under
    HKCU\\Software\\Policies\\<vendor>, snapshotted so reset puts it back
    exactly. Nothing touches the signed install tree or a user's profile, and
    SafeBrowsing, extensions and crash upload are deliberately left alone -- the
    aim is to stop the browser working when it is idle, not to change what the
    user can browse.

    Keys already handled by op_chromium_policy / op_*_prefetch are not repeated
    here, so each policy value is written by exactly one op. The prediction
    policy in particular is the *_prefetch op's job: Chrome and Edge spell it
    NetworkPredictionOptions, Brave spells it NetworkPredictionEnabled, and
    having two ops fight over one value would make the ledger lie.
    """
    kind = ctx["kind"]
    if kind == "edge":
        values: dict[str, tuple[int, str]] = {
            # No welcome/tips content fetches on first run.
            "ShowStartupExperience": (0, "DWORD"),
            "DnsPrefetchEnabled": (0, "DWORD"),
            "PrefetchToPrerenderEnabled": (0, "DWORD"),
            "ShowOfferedUpdateNotification": (0, "DWORD"),
        }
    elif kind == "chrome":
        values = {
            "DnsPrefetchEnabled": (0, "DWORD"),
            "PrefetchToPrerenderEnabled": (0, "DWORD"),
            "ShowOfferedUpdateNotification": (0, "DWORD"),
        }
    else:  # brave
        values = {
            "DnsPrefetchEnabled": (0, "DWORD"),
            "PrefetchToPrerenderEnabled": (0, "DWORD"),
            "ShowOfferedUpdateNotification": (0, "DWORD"),
            # Brave's own surfaces: the suggestion strip, rewards and ads.
            "BraveSuggestEnable": (0, "DWORD"),
        }
    return _policy_snapshot_apply(ctx["policies"], values)


CHROMIUM_LAUNCH_FLAGS = [
    # Skip the GPU process / compositing work for a browser whose window is
    # usually idle. This is a launch-argument change on the user's own
    # shortcuts -- reversible via the .lnk snapshot, and it does not touch the
    # signed application directory, so an update cannot wipe it.
    "--disable-gpu-compositing",
    "--disable-background-networking",
    "--disable-breakpad",
]


def op_chromium_launch_args(ctx: dict) -> tuple[list, bool, str]:
    """Add GPU/background flags to the browser's shortcuts.

    Shortcuts only. The HKCU\\Run value belongs to op_chromium_autostart, which
    deletes it; writing flags there too would mean the two ops disagreed and
    reset restored a command the user never had.
    """
    names = {"edge": ["Microsoft Edge", "Edge"],
             "chrome": ["Google Chrome", "Chrome"],
             "brave": ["Brave"]}.get(ctx["kind"], [])
    links = deep.find_shortcuts(names)
    if not links:
        return [], True, "no shortcuts found"
    recs, ok, note = deep.patch_shortcut_flags(links, CHROMIUM_LAUNCH_FLAGS)
    return recs, ok, note


def op_spotify_tasks(ctx: dict) -> tuple[list, bool, str]:
    """Disable Spotify's scheduled task.

    Independent of the HKCU\\Run entry removed by op_spotify_autostart: Spotify
    registers a logon-triggered task as well, so removing only the Run value
    still let the client come back on its own. Tasks we did not actually change
    are not recorded, so reset re-enables exactly what was on.
    """
    records, n = _disable_tasks_matching("Spotify*")
    note = f"{n} Spotify task(s) disabled" if n else "no Spotify task to disable"
    return records, True, note


def op_app_firewall(ctx: dict, key: str) -> tuple[list, bool, str]:
    """Block inbound connections for this app's executables (needs admin).

    Genuinely effective and low risk: none of these clients accept inbound
    connections, so the only thing an inbound allow rule achieves is a wider
    attack surface. Outbound is untouched, so updates, sync and streaming keep
    working. Reset deletes only the ``[MT]``-prefixed rules it created.
    """
    programs = [p for p in (ctx.get("exe"), ctx.get("launcher")) if p]
    rec, ok = core.firewall_block_inbound(key, programs)
    if not ok:
        return [], False, "inbound block failed: " + \
            "; ".join(rec.get("errors") or ["unknown"])
    if rec.get("skipped"):
        return [], True, rec["skipped"]
    return [rec], True, f"inbound blocked for {len(rec['rules'])} executable(s)"


def op_app_startup_approval(ctx: dict, key: str) -> tuple[list, bool, str]:
    """Grey out this app's startup entries the way Task Manager does.

    A durable backstop for the autostart op that runs right after it: the Run
    value is deleted, but an app update or a repair can recreate it, and then it
    would start again silently. Marking the StartupApproved state means it comes
    back disabled. Skipped when no Run value exists, since there is nothing to
    approve. Snapshotted, so the user's real choice is restored.
    """
    names = _STARTUP_RUN_NAMES.get(key, [])
    if not names:
        return [], True, "no startup entry known"
    run_path = ctx.get("run_path") or \
        r"Software\Microsoft\Windows\CurrentVersion\Run"
    present = []
    for name in names:
        existed, _rtype, _data = reg_util.read_value("HKCU", run_path, name)
        if existed:
            present.append(name)
    if not present:
        return [], True, "no Run entry to mark disabled"
    records, ok, note = core.startup_approved_disable(key, present)
    return records, ok, note


_STARTUP_RUN_NAMES = {
    "discord": ["Discord"],
    "spotify": ["Spotify"],
    "chrome": ["Google Chrome"],
    "edge": ["MicrosoftEdge"],
    "brave": ["Brave"],
}


def op_chromium_schedule(ctx: dict) -> tuple[list, bool, str]:
    """Below-normal priority + core confinement + Efficiency Mode, live."""
    key = ctx["kind"]
    sched = SCHED_SPECS[key]
    procs = ENGAGED_PROCESSES[key]
    # Snapshot before touching anything, so reset restores the real state.
    before = deep.snapshot_scheduling(procs) if procs else []
    parts = []
    n, _note = deep.set_priority(procs, sched["priority"])
    parts.append(f"{n} proc below-normal")
    if sched.get("cores"):
        n, _note = deep.set_affinity(procs, sched["cores"])
        parts.append(f"{n} proc on {sched['cores']} cores")
    if sched.get("ecoqos"):
        n, _note = deep.set_efficiency_mode(procs, True)
        parts.append(f"efficiency mode x{n}")
    return ([{"kind": "sched", "app": key, "processes": procs, "spec": sched,
              "before": before}]
            if procs else []), True, " · ".join(parts) or "browser not running"


def op_chromium_widevine(ctx: dict) -> tuple[list, bool, str]:
    """Move the Widevine DRM component (netflix playback etc.) to backup."""
    if not ctx.get("ver"):
        return [], False, "not installed"
    wv = os.path.join(ctx["ver"], "WidevineCdm")
    if not os.path.isdir(wv):
        return [], False, "no Widevine component"
    rec, ok = core.move_away(wv, "widevine")
    return ([rec] if ok else []), ok, ("Widevine moved to backup"
                                       if ok else rec.get("error", "Widevine locked"))


# ================================================================ Spotify

SPOTIFY_AD_HOSTS = [
    # Ad-serving and measurement only. Do NOT add spclient.wg.spotify.com
    # (required for the desktop client), the audio-ak CDN (playback), or
    # scdn.co / q4cdn asset hosts — blocking any of those breaks the app.
    "ads.spotify.com",
    "ads-fa.spotify.com",
    "analytics.spotify.com",
    "adeventtracker.spotify.com",
    "adserver.adtechus.com",
    "partnerad.l.doubleclick.net",
    "ads.flurry.com",
    "crashdump.spotify.com",
    "core.insightexpressai.com",
]


def _spotify_ctx() -> dict:
    base = expand_path(r"%APPDATA%\Spotify")
    local = expand_path(r"%LOCALAPPDATA%\Spotify")
    return {
        "base": base,
        "exe": os.path.join(base, "Spotify.exe"),
        "prefs": os.path.join(base, "prefs"),
        "update_dir": os.path.join(local, "Update"),
        "run_path": r"Software\Microsoft\Windows\CurrentVersion\Run",
        "launch_args": "",
    }


SPOTIFY_LAUNCH_FLAGS = ["--disable-gpu", "--disable-gpu-compositing"]


# Keys read back from the real %APPDATA%\Spotify\prefs on this machine.
# The old code wrote "hardware acceleration" / "enable-app-cache" — keys
# Spotify does not parse — so the setting was silently ignored. The real
# hardware-acceleration key is "ui.hardware_acceleration" (dot-separated).
#   ui.hardware_acceleration : confirmed present in the installed prefs
#   es.send-on-startup       : confirmed present (was "true" — a beacon on
#                              every launch); set false
#   system.show-tray         : long-standing public prefs key, absent here so
#                              still at default; kills the tray overlay work
SPOTIFY_PREF_KEYS = {
    "ui.hardware_acceleration": "false",   # no GPU compositing work
    "es.send-on-startup": "false",         # no experiment/analytics beacon
    "system.show-tray": "false",           # no tray icon work per change
}


def op_spotify_prefs(ctx: dict) -> tuple[list, bool, str]:
    path = ctx.get("prefs")
    if not path:
        return [], False, "no prefs path"
    rec, ok = core.snapshot_text(path)
    if not ok:
        return [], False, rec.get("error", "prefs unreadable")
    try:
        prefs = Path(path).read_text(encoding="utf-8", errors="replace") \
            if os.path.isfile(path) else ""
    except Exception as exc:  # noqa: BLE001
        return [], False, f"prefs read failed: {exc}"
    # Drop any existing form of each key (hyphenated, dotted or spaced) so we
    # never end up with two spellings of the same preference.
    wanted = list(SPOTIFY_PREF_KEYS)
    def _is_target(line: str) -> bool:
        name = line.split("=", 1)[0].strip().lower()
        base = name.replace("-", "").replace(" ", "").replace(".", "")
        return any(base == k.replace("-", "").replace(".", "").lower()
                   for k in wanted)
    lines = [l for l in prefs.splitlines() if l.strip() and not _is_target(l)]
    lines.extend(f"{k}={v}" for k, v in SPOTIFY_PREF_KEYS.items())
    try:
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return [], False, f"prefs write failed: {exc}"
    return [rec], True, f"{len(SPOTIFY_PREF_KEYS)} prefs set " \
                        "(ui.hardware_acceleration, es.send-on-startup, ...)"


def op_spotify_launch_args(ctx: dict) -> tuple[list, bool, str]:
    links = deep.find_shortcuts(["Spotify"])
    recs, ok, note = deep.patch_shortcut_flags(links, SPOTIFY_LAUNCH_FLAGS)
    return recs, ok, note


def op_spotify_schedule(ctx: dict) -> tuple[list, bool, str]:
    sched = SCHED_SPECS["spotify"]
    procs = ENGAGED_PROCESSES["spotify"]
    # Snapshot before touching anything, so reset restores the real state.
    before = deep.snapshot_scheduling(procs) if procs else []
    parts = []
    n, _note = deep.set_priority(procs, sched["priority"])
    parts.append(f"{n} proc below-normal")
    if sched.get("cores"):
        n, _note = deep.set_affinity(procs, sched["cores"])
        parts.append(f"{n} proc on {sched['cores']} cores")
    if sched.get("ecoqos"):
        n, _note = deep.set_efficiency_mode(procs, True)
        parts.append(f"efficiency mode x{n}")
    return ([{"kind": "sched", "app": "spotify", "processes": procs,
              "spec": sched, "before": before}] if procs else []), True, " · ".join(parts) or "not running"


def op_spotify_updater(ctx: dict) -> tuple[list, bool, str]:
    """Rename the Update folder + block the migrator relaunch."""
    records = []
    stopped = core.terminate_processes(["SpotifyMigrator.exe", "SpotifyFullSetup.exe"])
    rec, ok = core.move_away(ctx["update_dir"], "spotify update")
    if rec.get("missing"):
        # Nothing to strip (this build has no Update\ folder) — a clean
        # no-op, not a failure.
        return records, True, "no updater folder present — nothing to disable"
    if ok:
        records.append(rec)
    elif rec.get("error"):
        return records, False, f"Update folder locked: {rec['error']}"
    note = "Update\\ moved to backup" if ok else ""
    if stopped:
        note += " · killed relauncher"
    if not note:
        return records, True, "updater handled"
    return records, True, note


def op_spotify_autostart(ctx: dict) -> tuple[list, bool, str]:
    snap = core.reg_snapshot("HKCU", ctx["run_path"], "Spotify")
    if snap.get("existed"):
        ok, msg = reg_util.delete_value("HKCU", ctx["run_path"], "Spotify")
        if not ok:
            return [], False, f"autostart entry could not be removed: {msg}"
        return [snap], True, "autostart removed"
    # No entry to remove: returning no records keeps this from counting as a
    # change and from marking Spotify "engaged" on a machine with no autostart.
    return [], True, "no autostart entry"


def op_spotify_hosts(ctx: dict) -> tuple[list, bool, str]:
    rec, ok = core.hosts_block(SPOTIFY_AD_HOSTS, "spotify")
    return ([rec] if ok else []), ok, ("ad/telemetry hosts blocked"
                                       if ok else rec.get("error", "hosts block failed"))


# ================================================================= Brave

_BRAVE_TASKS = ("BraveSoftwareUpdateTask*",)


def _brave_ctx() -> dict:
    roots = (expand_path(r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application"),
             expand_path(r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application"))
    base = next((r for r in roots if os.path.isdir(r)), None)
    ver = _chrome_version_dir(base) if base else None
    return {
        "base": base,
        "ver": ver,
        "kind": "brave",
        "exe": next((p for p in (os.path.join(ver, "brave.exe") if ver else None,
                                 os.path.join(base, "brave.exe") if base else None)
                     if p and os.path.isfile(p)), None),
        "locales": os.path.join(ver, "Locales") if ver else None,
        "policies": r"Software\Policies\BraveSoftware\Brave",
        "tasks": _BRAVE_TASKS,
        "helper": ["BraveSoftwareUpdate.exe"],
        "run_path": r"Software\Microsoft\Windows\CurrentVersion\Run",
        "launch_args": "",
    }


def op_brave_locale(ctx: dict) -> tuple[list, bool, str]:
    return strip_locales(ctx.get("locales"))


def op_brave_ads(ctx: dict) -> tuple[list, bool, str]:
    values = {
        "BraveRewardsDisabled": (1, "DWORD"),
        "BraveAdsDisabled": (1, "DWORD"),
        "BackgroundModeEnabled": (0, "DWORD"),
        "ComponentUpdatesEnabled": (0, "DWORD"),
    }
    return _policy_snapshot_apply(ctx["policies"], values)


def op_brave_prefetch(ctx: dict) -> tuple[list, bool, str]:
    """Brave's prefetch policy, written per-user so no elevation is needed.

    Same correction as the Chromium op: it is a policy under Software\\Policies,
    and HKCU user policy is the one that actually wins.
    """
    key = ctx["policies"]
    if reg_util.value_equals("HKCU", key, "NetworkPredictionEnabled", 0):
        return [], True, "prefetch + preconnect already off"
    snap = core.reg_snapshot("HKCU", key, "NetworkPredictionEnabled")
    ok, msg = reg_util.write_value("HKCU", key, "NetworkPredictionEnabled",
                                   0, "DWORD")
    if not ok:
        return [], False, f"prefetch policy not set: {msg}"
    return [snap], True, "prefetch + preconnect off"


def op_brave_services(ctx: dict) -> tuple[list, bool, str]:
    """Disable Brave's updater services, reporting failure instead of hiding it."""
    records, notes, failed = [], [], []
    found = deep.existing_services(*_SERVICE_PATTERNS["brave"])
    if not found:
        return [], True, "no Brave updater service installed"
    for svc in found:
        rec, ok = deep.disable_service(svc)
        if not ok:
            failed.append(rec.get("error") or f"{svc} could not be disabled")
        if rec.get("changed"):
            records.append(rec)
            notes.append(f"{svc} disabled")
        elif rec.get("already"):
            notes.append(f"{svc} already off")
    if failed:
        return records, False, " · ".join(failed + notes)
    if not records:
        return [], True, " · ".join(notes) or "updater services already off"
    return records, True, " · ".join(notes)


def op_brave_tasks(ctx: dict) -> tuple[list, bool, str]:
    records, n = [], 0
    stopped = core.terminate_processes(ctx["helper"])
    for pat in _BRAVE_TASKS:
        recs, k = _disable_tasks_matching(pat)
        records.extend(recs)
        n += k
    note = "background updater off"
    if stopped:
        note += f" · killed {len(stopped)}"
    if n:
        note += f" · disabled {n} task(s)"
    return records, True, note


def op_brave_schedule(ctx: dict) -> tuple[list, bool, str]:
    return op_chromium_schedule(ctx)


# ================================================================ plans

def _ctx_for(key: str) -> dict:
    if key == "discord":
        return _discord_ctx()
    if key in ("edge", "chrome"):
        return _chromium_ctx(key)
    if key == "spotify":
        return _spotify_ctx()
    if key == "brave":
        return _brave_ctx()
    return {}


def _plan(key: str, name: str, desc: str, icon: str, color: str,
          processes: list[str], impact: int, features: list[str], ops: list) -> dict:
    return {
        "key": key, "name": name, "desc": desc, "icon": icon, "color": color,
        "processes": processes, "impact": impact, "features": features,
        "ops": ops,
        "sched": SCHED_SPECS.get(key, {}),
        "options": {
            o["id"]: {"label": o.get("option_label", o["title"]),
                      "default": False}
            for o in ops if o.get("optional")
        },
    }


_ORDERS = ("discord", "edge", "chrome", "spotify", "brave")

APP_PLANS: dict[str, dict] = {}


def _plans() -> dict[str, dict]:
    if not APP_PLANS:
        APP_PLANS.update(build_plans())
    return APP_PLANS


def build_plans() -> dict[str, dict]:
    """Assemble the five app plans (static op metadata + run functions)."""
    return {
        "discord": _plan(
            "discord", "Discord", "Trim background overhead from Discord "
            "without touching a file in its signed package: GPU flags via the "
            "launch command, live process scheduling, and the updater stood down.",
            "discord", "#5865F2", ["Discord.exe"], 3,
            ["GPU flags via launch", "Below-normal + efficiency mode",
             "Idle GPU/crashpad stopped", "Updater stood down",
             "Strip locales"],
            [
                {"id": "launch", "title": "Add GPU launch flags",
                 "desc": "Appends --disable-gpu and friends to Discord's "
                         "shortcuts. Autostart is removed separately, so the "
                         "flags live only where Discord is actually launched "
                         "from by hand.",
                 "default": True, "category": "ram", "run": op_discord_launch_args},
                {"id": "settings", "title": "Disable HW accel + updates",
                 "desc": "settings.json: hardware acceleration off and "
                         "SKIP_HOST_UPDATE set.",
                 "default": True, "category": "ram", "run": op_discord_settings},
                {"id": "schedule", "title": "Below-normal + efficiency mode",
                 "desc": "Live Win32 change on the running processes: priority "
                         "class, core confinement and EcoQoS. Re-applied after "
                         "every launch by the triage watcher.",
                 "default": True, "category": "cpu", "run": op_discord_schedule},
                {"id": "helpers", "title": "Stop idle GPU + crashpad helpers",
                 "desc": "Terminates the --type=gpu-process and "
                         "--type=crashpad-handler children Discord keeps alive "
                         "with the window idle. They respawn on demand.",
                 "default": True, "category": "cpu", "run": op_discord_helpers},
                {"id": "startup_approval", "title": "Keep autostart disabled",
                 "desc": "Records the StartupApproved state first, so the Run "
                         "value Discord recreates after an update comes back "
                         "disabled rather than starting silently. Runs before "
                         "the Run value is deleted.",
                 "default": True, "category": "cpu",
                 "run": functools.partial(op_app_startup_approval, key="discord")},
                {"id": "updater", "title": "Stand down the updater",
                 "desc": "Disables the autostart Run key + any Discord update "
                         "scheduled tasks; terminates Update.exe if running.",
                 "default": True, "category": "cpu", "run": op_discord_updater},
                {"id": "firewall", "title": "Block inbound connections",
                 "desc": "Named Windows Firewall inbound-block rules for "
                         "Discord.exe and Update.exe. Discord needs no inbound "
                         "port; voice is outbound. Needs admin.",
                 "default": False, "optional": True, "option_label":
                     "Also block inbound connections (needs admin)",
                 "category": "privacy",
                 "run": functools.partial(op_app_firewall, key="discord")},
                {"id": "locale", "title": "Strip locale bundles",
                 "desc": "Moves every non-en-US locale .pak to backup so the "
                         "client stops loading 40+ language packs. Reversible, "
                         "but Discord's updater may restore them.",
                 "default": True, "category": "disk", "run": op_discord_locale},
                {"id": "spellcheck", "title": "Remove spellcheck module",
                 "desc": "Moves modules\\discord_spellcheck-* out of the way. "
                         "Off by default: it edits the app's own payload, which "
                         "its updater restores.",
                 "default": False, "optional": True, "option_label":
                     "Also remove the spellcheck module (edits app files)",
                 "category": "ram", "run": op_discord_spellcheck},
                {"id": "overlay", "title": "Remove overlay renderer",
                 "desc": "Moves the GPU overlay2 module out of the way. Off by "
                         "default for the same reason: it edits app files.",
                 "default": False, "optional": True, "option_label":
                     "Also remove the in-game overlay module (edits app files)",
                 "category": "ram", "run": op_discord_overlay},
                {"id": "hosts", "title": "Block telemetry hosts",
                 "desc": "hosts-file block of Discord analytics/science "
                         "endpoints (needs admin).",
                 "default": False, "optional": True, "option_label":
                     "Block telemetry hosts", "category": "privacy",
                 "run": op_discord_hosts},
            ]),
        "edge": _plan(
            "edge", "Microsoft Edge", "Disable the updater services, startup "
            "boost, background mode and prefetch, then run the browser itself "
            "below normal priority.",
            "edge", "#4FB6ED", ["msedge.exe", "msedgewebview2.exe"], 3,
            ["Updater services disabled", "Startup boost off",
             "Prefetch off", "Below-normal priority"],
            [
                {"id": "services", "title": "Disable updater services",
                 "desc": "Stops edgeupdate/edgeupdatem and flips them to "
                         "disabled, snapshotting each real start type first. "
                         "This is what removes the recurring background work.",
                 "default": True, "category": "cpu", "run": op_chromium_services},
                {"id": "policy", "title": "Background + boost + telemetry off",
                 "desc": "Edge policy: BackgroundModeEnabled, StartupBoostEnabled, "
                         "component updates and telemetry reporting disabled.",
                 "default": True, "category": "ram", "run": op_chromium_policy},
                {"id": "prefetch", "title": "Disable prefetch / preconnect",
                 "desc": "NetworkPredictionOptions=0 under the per-user policy "
                         "key, so it applies without elevation.",
                 "default": True, "category": "ram", "run": op_chromium_prefetch},
                {"id": "deep", "title": "Cut idle browser work",
                 "desc": "Per-user policies for DNS prefetch, link prerender and "
                         "the update nag, plus the welcome-tips fetches. No "
                         "change to SafeBrowsing or extensions.",
                 "default": True, "category": "ram", "run": op_chromium_deep},
                {"id": "lnk", "title": "GPU + background flags on shortcuts",
                 "desc": "Appends --disable-gpu-compositing and background "
                         "networking flags to this browser's shortcuts.",
                 "default": True, "category": "ram", "run": op_chromium_launch_args},
                {"id": "startup_approval", "title": "Keep autostart disabled",
                 "desc": "Records the StartupApproved state first, so an Edge "
                         "update that recreates the Run value comes back "
                         "disabled.",
                 "default": True, "category": "cpu",
                 "run": functools.partial(op_app_startup_approval, key="edge")},
                {"id": "autostart", "title": "Remove autostart entry",
                 "desc": "Deletes the MicrosoftEdge HKCU Run value (restored "
                         "verbatim on reset).",
                 "default": True, "category": "cpu", "run": op_chromium_autostart},
                {"id": "firewall", "title": "Block inbound connections",
                 "desc": "Adds a named Windows Firewall inbound-block rule for "
                         "msedge.exe. Outbound is untouched, so the browser "
                         "still works. Needs admin.",
                 "default": False, "optional": True, "option_label":
                     "Also block inbound connections (needs admin)",
                 "category": "privacy",
                 "run": functools.partial(op_app_firewall, key="edge")},
                {"id": "updater", "title": "Stop updater task + process",
                 "desc": "Disables EdgeUpdateTaskMachine* tasks and stops the "
                         "MicrosoftEdgeUpdate helper.",
                 "default": True, "category": "cpu", "run": op_chromium_updater},
                {"id": "schedule", "title": "Below-normal + efficiency mode",
                 "desc": "Live priority/affinity/EcoQoS on msedge.exe only. "
                         "msedgewebview2.exe is deliberately excluded: it is "
                         "shared with every other WebView2 app on the machine.",
                 "default": True, "category": "cpu", "run": op_chromium_schedule},
                {"id": "locale", "title": "Strip locale bundles",
                 "desc": "Keep only en-US.pak; everything else to backup.",
                 "default": True, "category": "disk", "run": op_chromium_locale},
                {"id": "widevine", "title": "Move Widevine DRM",
                 "desc": "DRM playback (Netflix/Spotify web) needs Widevine; "
                         "moving it blocks DRM media until restored.",
                 "default": False, "optional": True,
                 "option_label": "Also move Widevine (breaks DRM media)",
                 "category": "ram", "run": op_chromium_widevine},
            ]),
        "chrome": _plan(
            "chrome", "Google Chrome", "Disable the GoogleUpdater services, "
            "background sync and prefetch, trim locale packs, and keep the "
            "browser out of the foreground scheduler's way.",
            "chrome", "#3C7AF0", ["chrome.exe"], 4,
            ["Updater services disabled", "Background sync off",
             "Prefetch off", "Below-normal priority"],
            [
                {"id": "services", "title": "Disable updater services",
                 "desc": "Stops GoogleUpdaterService*/InternalService* and "
                         "flips them to disabled, snapshotting start types.",
                 "default": True, "category": "cpu", "run": op_chromium_services},
                {"id": "policy", "title": "Background + sync + telemetry off",
                 "desc": "Chrome policy: background mode, component updates, "
                         "URL-keyed telemetry, background sync and browser "
                         "sign-in disabled.",
                 "default": True, "category": "ram", "run": op_chromium_policy},
                {"id": "prefetch", "title": "Disable prefetch / preconnect",
                 "desc": "NetworkPredictionOptions=0 under the per-user policy "
                         "key, so it applies without elevation.",
                 "default": True, "category": "ram", "run": op_chromium_prefetch},
                {"id": "deep", "title": "Cut idle browser work",
                 "desc": "Per-user policies for DNS prefetch, link prerender and "
                         "the update nag.",
                 "default": True, "category": "ram", "run": op_chromium_deep},
                {"id": "lnk", "title": "GPU + background flags on shortcuts",
                 "desc": "Appends --disable-gpu-compositing and background "
                         "networking flags to this browser's shortcuts.",
                 "default": True, "category": "ram", "run": op_chromium_launch_args},
                {"id": "startup_approval", "title": "Keep autostart disabled",
                 "desc": "Records the StartupApproved state first, so a Run "
                         "value Chrome recreates on update comes back disabled.",
                 "default": True, "category": "cpu",
                 "run": functools.partial(op_app_startup_approval, key="chrome")},
                {"id": "autostart", "title": "Remove autostart entry",
                 "desc": "Deletes the Google Chrome HKCU Run value (restored on "
                         "reset).",
                 "default": True, "category": "cpu", "run": op_chromium_autostart},
                {"id": "firewall", "title": "Block inbound connections",
                 "desc": "Named Windows Firewall inbound-block rule for "
                         "chrome.exe. Outbound untouched. Needs admin.",
                 "default": False, "optional": True, "option_label":
                     "Also block inbound connections (needs admin)",
                 "category": "privacy",
                 "run": functools.partial(op_app_firewall, key="chrome")},
                {"id": "updater", "title": "Stop updater task + process",
                 "desc": "Disables GoogleUpdateTaskMachine* tasks and stops the "
                         "GoogleUpdate helpers.",
                 "default": True, "category": "cpu", "run": op_chromium_updater},
                {"id": "schedule", "title": "Below-normal + efficiency mode",
                 "desc": "Live priority/affinity/EcoQoS on the running browser.",
                 "default": True, "category": "cpu", "run": op_chromium_schedule},
                {"id": "locale", "title": "Strip locale bundles",
                 "desc": "Keep only en-US.pak; the other 200+ packs go to backup.",
                 "default": True, "category": "disk", "run": op_chromium_locale},
                {"id": "widevine", "title": "Move Widevine DRM",
                 "desc": "DRM playback needs Widevine; moving it blocks DRM "
                         "media until restored.",
                 "default": False, "optional": True,
                 "option_label": "Also move Widevine (breaks DRM media)",
                 "category": "ram", "run": op_chromium_widevine},
            ]),
        "spotify": _plan(
            "spotify", "Spotify", "Block ad/telemetry hosts, drop hardware "
            "accelerated rendering, stand down the updater and keep the client "
            "off the foreground cores.",
            "spotify", "#1ED760", ["Spotify.exe"], 2,
            ["HW accel off", "Ad hosts blocked", "No autostart",
             "Below-normal priority"],
            [
                {"id": "prefs", "title": "Disable hardware acceleration",
                 "desc": "prefs: ui.hardware_acceleration=false, "
                         "es.send-on-startup=false, system.show-tray=false.",
                 "default": True, "category": "ram", "run": op_spotify_prefs},
                {"id": "launch", "title": "Add GPU launch flags",
                 "desc": "Appends --disable-gpu to the Spotify shortcuts.",
                 "default": True, "category": "ram", "run": op_spotify_launch_args},
                {"id": "schedule", "title": "Below-normal + efficiency mode",
                 "desc": "Live priority/affinity/EcoQoS on Spotify.exe.",
                 "default": True, "category": "cpu", "run": op_spotify_schedule},
                {"id": "startup_approval", "title": "Keep autostart disabled",
                 "desc": "Records the StartupApproved state first, so a Run "
                         "value Spotify recreates on update comes back "
                         "disabled.",
                 "default": True, "category": "cpu",
                 "run": functools.partial(op_app_startup_approval, key="spotify")},
                {"id": "autostart", "title": "Remove autostart",
                 "desc": "Deletes the HKCU Run\\Spotify value; Spotify quits "
                         "with the machine (reversible).",
                 "default": True, "category": "cpu", "run": op_spotify_autostart},
                {"id": "tasks", "title": "Remove autostart scheduled task",
                 "desc": "Disables the logon task Spotify registers alongside the "
                         "Run value, so removing one does not leave the other.",
                 "default": True, "category": "cpu", "run": op_spotify_tasks},
                {"id": "firewall", "title": "Block inbound connections",
                 "desc": "Named Windows Firewall inbound-block rule for "
                         "Spotify.exe. Playback is outbound. Needs admin.",
                 "default": False, "optional": True, "option_label":
                     "Also block inbound connections (needs admin)",
                 "category": "privacy",
                 "run": functools.partial(op_app_firewall, key="spotify")},
                {"id": "updater", "title": "Disable auto-updater",
                 "desc": "Moves the Update\\ folder to backup and terminates "
                         "SpotifyMigrator/FullSetup relaunchers.",
                 "default": True, "category": "cpu", "run": op_spotify_updater},
                {"id": "hosts", "title": "Block ad & telemetry hosts",
                 "desc": "hosts-file block of Spotify ad/analytic endpoints "
                         "(needs admin).",
                 "default": True, "category": "privacy", "run": op_spotify_hosts},
            ]),
        "brave": _plan(
            "brave", "Brave", "Disable the brave/bravem updater services, its "
            "Rewards and background policies, and prefetching.",
            "brave", "#FB542B", ["brave.exe"], 3,
            ["Updater services disabled", "Rewards & Ads off",
             "Prefetch off", "Below-normal priority"],
            [
                {"id": "services", "title": "Disable updater services",
                 "desc": "Stops the brave and bravem services and flips them to "
                         "disabled, snapshotting start types. The Elevation "
                         "services are left alone on purpose.",
                 "default": True, "category": "cpu", "run": op_brave_services},
                {"id": "ads", "title": "Rewards + Ads + background off",
                 "desc": "Brave policy: BraveRewardsDisabled, BraveAdsDisabled, "
                         "BackgroundModeEnabled and component updates off.",
                 "default": True, "category": "ram", "run": op_brave_ads},
                {"id": "prefetch", "title": "Disable prefetch / preconnect",
                 "desc": "NetworkPredictionEnabled=0 under the per-user policy "
                         "key, so it applies without elevation.",
                 "default": True, "category": "ram", "run": op_brave_prefetch},
                {"id": "deep", "title": "Cut idle browser work",
                 "desc": "Brave policy: DNS prefetch, link prerender, the update "
                         "nag and the suggestion strip off.",
                 "default": True, "category": "ram", "run": op_chromium_deep},
                {"id": "lnk", "title": "GPU + background flags on shortcuts",
                 "desc": "Appends --disable-gpu-compositing and background "
                         "networking flags to Brave's shortcuts.",
                 "default": True, "category": "ram", "run": op_chromium_launch_args},
                 {"id": "startup_approval", "title": "Keep autostart disabled",
                  "desc": "Records the StartupApproved state first, so a Run "
                         "value Brave recreates on update comes back "
                         "disabled.",
                  "default": True, "category": "cpu",
                  "run": functools.partial(op_app_startup_approval, key="brave")},
                 {"id": "tasks", "title": "Stop updater task + process",
                  "desc": "Disables BraveSoftwareUpdateTaskMachine* tasks and "
                          "stops the BraveSoftwareUpdate helper.",
                  "default": True, "category": "cpu", "run": op_brave_tasks},
                {"id": "firewall", "title": "Block inbound connections",
                 "desc": "Named Windows Firewall inbound-block rule for "
                         "brave.exe. Brave Rewards needs no inbound port. "
                         "Needs admin.",
                 "default": False, "optional": True, "option_label":
                     "Also block inbound connections (needs admin)",
                 "category": "privacy",
                 "run": functools.partial(op_app_firewall, key="brave")},
                {"id": "schedule", "title": "Below-normal + efficiency mode",
                 "desc": "Live priority/affinity/EcoQoS on brave.exe.",
                 "default": True, "category": "cpu", "run": op_brave_schedule},
                {"id": "locale", "title": "Strip locale bundles",
                 "desc": "Keep only en-US.pak in Brave's program folder.",
                 "default": True, "category": "disk", "run": op_brave_locale},
            ]),
    }


def _disk_saved_bytes(ledger: dict) -> int:
    """Real bytes moved out of the app's install dir, summed from the
    ledger's move records.  0 when nothing has been stripped yet."""
    total = 0
    for entry in ledger.get("ops", []):
        for rec in entry.get("records", []):
            if rec.get("kind") == "move" and rec.get("bytes"):
                total += int(rec["bytes"])
    return total


def _measure_procs(key: str) -> list[str]:
    """Process names used for this app's RAM accounting.

    ENGAGED_PROCESSES, not the plan's wider ``processes`` list. Edge's list
    includes msedgewebview2.exe, which is shared with every other WebView2 host
    on the box (Widgets, Office, third-party apps). Counting it inflated Edge's
    "before" and "now" figures with memory this tool never touched, and the
    reclaimed number is derived from those two.
    """
    return ENGAGED_PROCESSES.get(key) or _plans()[key]["processes"]


def detect() -> dict[str, dict]:
    """Live install scan: per-app state (installed, version, RAM now, plan)."""
    plans = _plans()
    ledger = {k: core.load_ledger(k) for k in plans}
    out = {}
    for key, plan in plans.items():
        ctx = _ctx_for(key)
        installed = _installed(ctx, key)
        ram = core.process_mem_mb(_measure_procs(key)) if installed else 0.0
        engaged = bool(ledger[key].get("ops"))
        # Real, measured numbers only. `ram_before` is the working set this
        # app's processes actually used at the moment optimization was applied
        # (persisted in the ledger); `ram_now` is what it uses right now. We
        # never estimate or invent a saving.
        base = ledger[key].get("ram_before_mb")
        reclaimed = round(max(0.0, base - ram), 1) if (engaged and base) else 0.0
        out[key] = {
            "key": key,
            "name": plan["name"],
            "desc": plan["desc"],
            "icon": plan["icon"],
            "color": plan["color"],
            "impact": plan["impact"],
            "features": plan["features"],
            "installed": installed,
            "version": _version(ctx, key),
            "ram_mb": ram,
            "ram_before_mb": base,
            "ram_reclaimed_mb": reclaimed,
            "disk_saved_mb": round(_disk_saved_bytes(ledger[key]) / (1024 ** 2), 1),
            "engaged": engaged,
            "ops_text": [op["note"] for op in ledger[key].get("ops", [])],
            "ops": _op_meta(key),
            "options": _options_state(key, ctx),
        }
    return out


def _op_meta(key: str) -> list[dict]:
    """Op descriptors for the UI, each tagged with whether it is already applied.

    ``applied`` is read from the ledger so an optional box comes back ticked
    after a previous run. Without it the card always rendered optional boxes
    unticked, and a second Apply silently re-ran those ops.
    """
    applied = {e.get("op") for e in core.load_ledger(key).get("ops", [])}
    return [{"id": o["id"], "title": o["title"], "desc": o.get("desc", ""),
             "optional": bool(o.get("optional")),
             "applied": o["id"] in applied}
            for o in _plans()[key]["ops"]]


def _options_state(key: str, ctx: dict) -> dict:
    """Optional-op state for callers that want the map form.

    Option ids are the op ids (see build_plans), so the ledger decides state.
    This used to hardcode ``on: False`` for every option.
    """
    plan = _plans()[key]
    applied = {e.get("op") for e in core.load_ledger(key).get("ops", [])}
    return {oid: {"label": meta["label"], "on": oid in applied,
                  "default": bool(meta.get("default"))}
            for oid, meta in plan["options"].items()}


def _installed(ctx: dict, key: str) -> bool:
    if key == "discord":
        return bool(ctx.get("ver"))
    if key in ("edge", "chrome", "brave"):
        return bool(ctx.get("ver"))
    if key == "spotify":
        return os.path.isfile(ctx.get("exe", ""))
    return False


def _file_version(path: str) -> str:
    """Best-effort real version from a PE file's version resource.

    Prefers the pre-formatted "FileVersion" string, and falls back to
    decoding the raw FileVersionMS/FileVersionLS quads (many apps, e.g.
    Spotify, only carry the numeric fields).
    """
    try:
        import win32api
        info = win32api.GetFileVersionInfo(path, "\\")
    except Exception:  # noqa: BLE001
        return ""
    text = str(info.get("FileVersion", "")).strip()
    if text:
        return text
    ms, ls = info.get("FileVersionMS"), info.get("FileVersionLS")
    if isinstance(ms, int) and isinstance(ls, int):
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    return ""


def _version(ctx: dict, key: str) -> str:
    """A real version identifier, or "" when the app has no versioned
    install dir / file metadata. Never invents a placeholder string."""
    ver = ctx.get("ver")
    if ver:
        # Chromium app dirs are literally named after the version
        # ("153.0.8010.53"); Discord's are "app-1.0.9259".
        name = os.path.basename(ver.rstrip("\\/"))
        if name.lower().startswith("app-"):
            name = name[4:]
        exe = os.path.join(ver, "msedge.exe" if key == "edge"
                           else "chrome.exe" if key == "chrome"
                           else "brave.exe" if key == "brave"
                           else "Discord.exe")
        fv = _file_version(exe) if os.path.isfile(exe) else ""
        return fv or name
    if key == "spotify":
        fv = _file_version(ctx.get("exe", ""))
        return fv or "installed"
    return ""


def activate(key: str, option_ids: list[str] | None = None,
             restart: bool = True, notify=None) -> tuple[list[str], int]:
    """Run a plan's default ops plus the user's optional boxes.

    Returns (human_errors, changed_count).  The ledger is updated per-op so
    reset() can reverse exactly what happened, in reverse order.

    ``restart`` closes and relaunches *this* app once the ops are in, so the
    launch flags and process scheduling take effect immediately instead of
    waiting for the user to restart it by hand. ``notify(key, message)`` is
    called around that step so the UI can show a live "Restarting X..." state
    on the one card being touched rather than looking frozen.

    Ordering matters and used to be wrong. Discord and Spotify both hold their
    settings in memory and rewrite the file on exit, so writing settings.json /
    prefs *before* closing the app meant the app's own shutdown clobbered the
    edit and the change was lost while still being reported as applied. Ops
    that touch the app's own settings file therefore run in a second phase,
    after the app is closed.
    """
    plan = _plans()[key]
    ctx = _ctx_for(key)
    if not _installed(ctx, key):
        return [f"{plan['name']} is not installed"], 0
    want = set(option_ids or [])
    errors, changed = [], 0
    ledger = core.load_ledger(key)
    already = {(e.get("op")) for e in ledger.get("ops", [])}
    # Capture the real pre-optimization working set the first time we touch an
    # app, so the UI can show a measured before/after instead of a guess.
    if not ledger.get("ram_before_mb"):
        before = core.process_mem_mb(_measure_procs(key))
        if before:
            ledger["ram_before_mb"] = before
            core.save_ledger(key, ledger)

    def _selected(op):
        return (op.get("default") or op["id"] in want) and op["id"] not in already

    def _do(op):
        nonlocal changed
        try:
            records, ok, note = op["run"](ctx)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{op['title']}: {exc}")
            logger.error(f"app_optimizer {key}.{op['id']}: {exc}")
            return
        # Record whatever the op reports, even when it failed. An op that
        # disabled two of three services and was denied on the third still
        # changed the machine; dropping its records on the floor left those two
        # changes with no way to be reverted.
        if records:
            core._record(key, {"op": op["id"], "records": records,
                               "note": note, "at": time.strftime("%H:%M:%S")})
            changed += 1
        # ok=True with no records means "already clean / nothing present",
        # which is a no-op, not a failure. Only real failures surface -- and
        # they surface for optional ops too, since the user ticked that box.
        if not ok:
            errors.append(f"{op['title']}: {note}")

    pending = [op for op in plan["ops"] if _selected(op)]
    # Phase 1: registry / services / tasks / shortcuts / hosts. Safe to run
    # while the app is live.
    for op in pending:
        if op["id"] not in _FILE_PHASE_OPS:
            _do(op)

    # Phase 2: the app's own settings file(s), written with the app closed.
    file_ops = [op for op in pending if op["id"] in _FILE_PHASE_OPS]
    if file_ops and deep.process_running(ENGAGED_PROCESSES.get(key) or []):
        if notify:
            try:
                notify(key, f"Closing {plan['name']}…")
            except Exception:  # noqa: BLE001
                pass
        closed, msg = close_engaged(key)
        if closed:
            logger.info(f"app_optimizer {key}: {msg} (before writing settings)")
        else:
            # The app holds its settings in memory and rewrites the file on
            # exit, so writing now would be clobbered a second later. Refuse
            # instead of reporting a change that cannot survive.
            logger.error(f"app_optimizer {key}: {msg}")
            errors.append(
                f"Could not close {plan['name']} to write its settings — "
                f"close it and run this again ({msg})")
            file_ops = []
    for op in file_ops:
        _do(op)

    if changed:
        _ok, note = refresh_watcher()
        logger.info(f"app_optimizer {key}: {note}")
    if restart and changed:
        if notify:
            try:
                notify(key, f"Restarting {plan['name']}…")
            except Exception:  # noqa: BLE001
                pass
        ok, note = restart_engaged(key)
        if ok:
            logger.info(f"app_optimizer {key}: {note}")
            # Re-read the file the app just wrote. Reporting "applied" without
            # checking would repeat the exact failure this pass is fixing: the
            # app starts, overwrites the setting, and nobody notices.
            problems = verify_settings(key)
            for problem in problems:
                errors.append(problem)
                logger.warn(f"app_optimizer {key}: {problem}")
        else:
            # Not fatal: the optimization is applied and takes effect on the
            # user's next launch. Say so rather than reporting a failure.
            errors.append(f"{plan['name']} will pick up the changes on next launch")
    return errors, changed


def reset(key: str, restart: bool = True) -> tuple[list[str], int]:
    """Walk the ledger back in reverse, restoring every recorded snapshot.

    Records that fail to restore are *kept* in the ledger so the user can fix
    the underlying cause (e.g. unlock a file, re-run elevated) and retry.
    Clearing the ledger unconditionally would permanently lose the only copy
    of the backup information, turning a recoverable error into permanent
    data loss.
    """
    ledger = core.load_ledger(key)
    ops = ledger.get("ops", [])
    errors, restored = [], 0
    failed_ops = []
    for entry in reversed(ops):
        bad = []
        for rec in reversed(entry.get("records", [])):
            try:
                ok, msg = _restore_record(rec)
                if ok:
                    restored += 1
                else:
                    bad.append(rec)
                    errors.append(msg)
            except Exception as exc:  # noqa: BLE001
                bad.append(rec)
                errors.append(str(exc))
        if bad:
            failed_ops.append({**entry, "records": bad})
    if failed_ops:
        kept = {"ops": list(reversed(failed_ops)),
                "engaged_at": ledger.get("engaged_at")}
        if ledger.get("ram_before_mb") is not None:
            kept["ram_before_mb"] = ledger["ram_before_mb"]
        core.save_ledger(key, kept)
    else:
        core.save_ledger(key, {"ops": [], "engaged_at": None})
    # The watcher is re-derived from the ledgers, so resetting the last app
    # unregisters it and resetting one of several just drops that one.
    _ok, note = refresh_watcher()
    logger.info(f"app_optimizer {key}: {note}")
    if restart:
        ok, msg = restart_engaged(key)
        if ok:
            logger.info(f"app_optimizer {key}: {msg}")
    return errors, restored


def _restore_record(rec: dict) -> tuple[bool, str]:
    kind = rec.get("kind")
    if kind == "text":
        return core.restore_text(rec)
    if kind == "move":
        return core.restore_move(rec)
    if kind == "reg":
        return core.restore_reg(rec)
    if kind == "hosts":
        return core.restore_hosts(rec)
    if kind == "firewall":
        return core.restore_firewall(rec)
    if kind == "task":
        return core.restore_task(rec)
    if kind == "service":
        return deep.restore_service(rec)
    if kind == "link":
        return deep.restore_link(rec)
    if kind == "sched":
        return _restore_sched(rec)
    if kind == "watcher":
        return deep.restore_watcher(rec)
    return False, f"unknown record kind {kind}"


def _restore_sched(rec: dict) -> tuple[bool, str]:
    """Undo a live scheduling change, exactly.

    Nothing was written to the app, so the only thing to undo is the live
    effect. The record carries each process's real pre-change priority class and
    affinity mask, so those are restored per-process.

    When a record predates the per-process snapshot (an older ledger), fall back
    to the previous behaviour but say so, rather than silently pretending the
    assumption was a real restore. Processes that have since exited are left
    alone: their replacements were started by Windows on default scheduling.
    """
    procs = rec.get("processes") or []
    before = rec.get("before") or []

    if before:
        n, note = deep.restore_scheduling(before)
        return True, note

    if not procs:
        return True, "nothing was running to reschedule"
    if not deep.process_running(procs):
        return True, "app not running - nothing live to reschedule"
    # Legacy record: no per-process snapshot, so this is a best-effort reset to
    # Windows defaults and must be labelled as such.
    notes = ["no per-process snapshot in this record - reset to Windows defaults"]
    n, _note = deep.set_priority(procs, "normal")
    notes.append(f"{n} proc back to normal")
    n, _note = deep.set_affinity(procs, 64)
    if n:
        notes.append(f"{n} proc full CPU")
    n, _note = deep.set_efficiency_mode(procs, False)
    if n:
        notes.append("efficiency mode off")
    return True, " · ".join(notes)


# ------------------------------------------------------------- restart

def _launch_for(key: str) -> tuple[list[str], str, str, str]:
    """(process_names, main_image, exe, args) used to restart just this app."""
    ctx = _ctx_for(key)
    procs = ENGAGED_PROCESSES.get(key) or []
    main = procs[0] if procs else ""
    exe = ctx.get("launcher") or ctx.get("exe") or ""
    args = ctx.get("launch_args") or ""
    return procs, main, exe, args


def restart_engaged(key: str) -> tuple[bool, str]:
    """Close and relaunch one app so its applied changes take effect now.

    Deliberately scoped to the single app that was toggled: restarting one card
    must never disturb another card's processes.
    """
    procs, main, exe, args = _launch_for(key)
    if not main or not exe or not os.path.isfile(exe):
        return False, f"{key} has no launchable executable"
    return deep.restart_app(procs, main, exe, args)


def close_engaged(key: str) -> tuple[bool, str]:
    """Close one app without relaunching it.

    Used by activate() so an app's own settings file is written while the
    process that would overwrite it on exit is already gone. Same scoping rule
    as restart_engaged: only this app is touched.
    """
    procs, main, _exe, _args = _launch_for(key)
    if not main:
        return True, "app not running"
    if not deep.process_running(procs):
        return True, "app already stopped"
    if not deep.close_app(procs, main):
        return False, f"{key} did not close; settings not written"
    return True, f"closed {key} before writing its settings"


# Ops that write the target app's OWN settings file. These must run with the
# app closed: Discord and Spotify keep settings in memory and rewrite the file
# on exit, so writing before the close gets silently reverted. Matched on op
# id, which is unique within a plan.
_FILE_PHASE_OPS = frozenset({"settings", "prefs"})


def verify_settings(key: str) -> list[str]:
    """Re-read an app's settings file and report keys that are not as intended.

    Runs after the relaunch, so it catches the failure mode this whole pass
    exists to prevent: the app starting up, rejecting or overwriting what was
    written, and the change being reported as applied anyway. Returns a list of
    human-readable problems; empty means the file looks right.
    """
    ctx = _ctx_for(key)
    problems: list[str] = []
    if key == "spotify":
        path = ctx.get("prefs")
        if not path or not os.path.isfile(path):
            return [f"spotify prefs missing at {path}"]
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return [f"spotify prefs unreadable: {exc}"]
        found = {}
        for line in text.splitlines():
            if "=" in line:
                name, _, value = line.partition("=")
                found[name.strip().lower()] = value.strip().lower()
        for want_key, want_val in SPOTIFY_PREF_KEYS.items():
            got = found.get(want_key.lower())
            if got is None:
                problems.append(f"spotify: {want_key} missing from prefs")
            elif got != want_val:
                problems.append(f"spotify: {want_key}={got} (wanted {want_val})")
    elif key == "discord":
        path = ctx.get("settings")
        if not path or not os.path.isfile(path):
            return [f"discord settings.json missing at {path}"]
        try:
            data = json.loads(
                Path(path).read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            return [f"discord settings.json unreadable: {exc}"]
        if not isinstance(data, dict):
            return ["discord settings.json is not an object"]
        for want_key, want_val in DISCORD_PREF_KEYS.items():
            if data.get(want_key) != want_val:
                problems.append(
                    f"discord: {want_key}={data.get(want_key)!r} (wanted {want_val!r})")
    for p in problems:
        logger.warn(f"app_optimizer {key}: {p}")
    return problems


# ------------------------------------------------------------- watcher

def engaged_keys() -> list[str]:
    """Apps with a non-empty ledger, i.e. currently optimized."""
    out = []
    for key in _ORDERS:
        ledger = core.load_ledger(key)
        if ledger.get("ops"):
            out.append(key)
    return out


def refresh_watcher() -> tuple[bool, str]:
    """Keep the triage watcher's app list in step with the current ledgers.

    The watcher exists only while at least one app is engaged, and it is told
    exactly which apps those are, so resetting the last app removes it.
    """
    keys = engaged_keys()
    if not keys:
        if deep.watcher_installed():
            return deep.remove_watcher()
        return True, "no apps engaged - no watcher needed"
    rec, ok = deep.install_watcher({k: SCHED_SPECS.get(k, {}) for k in keys})
    return ok, (f"triage watcher active for {', '.join(keys)}" if ok
                else rec.get("error", "watcher registration failed"))


def triage(engaged: list[str] | None = None) -> dict:
    """One triage pass: re-apply the live levers for the engaged apps.

    Invoked by the scheduled watcher after every logon and on a short timer, so
    a relaunched app picks its priority back up instead of silently reverting to
    normal.
    """
    keys = engaged or engaged_keys()
    plans = {}
    for key in keys:
        spec = dict(SCHED_SPECS.get(key, {}))
        spec["processes"] = ENGAGED_PROCESSES.get(key) or []
        if spec["processes"]:
            plans[key] = spec
    return deep.triage_pass(plans)


def optimize_all(cancel=None, progress=None, restart: bool = True) -> dict:
    """Sequential 'Optimize All': every installed app, returns per-app results.

    ``progress(index, total, key, name)`` is invoked before each app so the UI
    can show a determinate progress bar. ``cancel()`` is polled between apps.
    """
    results = {}
    targets = [k for k in _ORDERS if _installed(_ctx_for(k), k)]
    total = len(targets) or 1
    for i, key in enumerate(targets):
        if cancel and cancel():
            results[key] = {"status": "cancelled", "errors": [], "changed": 0}
            continue
        if progress:
            try:
                progress(i, total, key, _plans()[key]["name"])
            except Exception:  # noqa: BLE001
                pass
        errors, changed = activate(key, restart=restart)
        results[key] = {"status": "done", "errors": errors, "changed": changed}
    if progress:
        try:
            progress(total, total, None, None)
        except Exception:  # noqa: BLE001
            pass
    return results
