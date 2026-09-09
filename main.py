"""Maximum Tweaks — GUI app with a CLI fallback.

Usage:
  python main.py                 # launch the GUI
  python main.py --cli <cmd>     # terminal mode (see commands below)

CLI commands:
  list | stats
  show <id> | category <name> | search <query>
  apply <id> [--dry-run] | revert <id> [--dry-run] | report <id>
"""
from __future__ import annotations

import argparse
import os
import sys

from database import BY_ID, CATEGORIES, TWEAKS

RISK_ORDER = {"safe": 0, "low": 1, "moderate": 2, "advanced": 3}
IMPACT_ORDER = {"very low": 0, "low": 1, "moderate": 2, "high": 3, "extreme": 4}
REC_ORDER = {"recommended": 0, "optional": 1, "experimental": 2, "advanced": 3, "guide": 4, "not_recommended": 5}


def run_gui():
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    # Standard Windows DPI hardening: opt the process into per-monitor-v2 DPI
    # awareness up-front so Qt never composites through legacy bitmap scaling
    # (the main cause of soft/blurry text in desktop Qt apps). Harmless at 100%
    # scaling, correct at any fractional desktop scale.
    import ctypes as _dpi_ct
    try:
        _PDM2 = _dpi_ct.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        _dpi_ct.windll.user32.SetProcessDpiAwarenessContext(_PDM2)
    except Exception:  # noqa: BLE001
        pass

    # Single instance: a second launch would double every scanner/auditor and
    # flood the machine with child command processes. Exit quietly instead.
    import ctypes as _ct
    _h = _ct.windll.kernel32.CreateMutexW(None, False,
                                          "Local\\MaximumTweaks.SingleInstance")
    if _ct.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        try:
            hwnd = _ct.windll.user32.FindWindowW(None, "Maximum Tweaks v2.2.0")
            if hwnd:
                _ct.windll.user32.ShowWindow(hwnd, 9)   # SW_RESTORE
                _ct.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        return

    from config.app_config import APP_VERSION
    from engine import license as license_mgr
    from ui import license as license_ui
    from ui.splash import CinematicSplash
    from ui.styles import build_qss
    from ui.fonts import register_fonts

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    register_fonts()
    app.setStyleSheet(build_qss())

    # Runtime window/app icon: the taskbar/alt-tab/title icon should match the
    # packaging icon rather than PySide's default.
    try:
        from config.app_config import DIRS as _DIRS
        _ico = _DIRS["assets"] / "app.ico"
        if _ico.is_file():
            app.setWindowIcon(QIcon(str(_ico)))
    except Exception:  # noqa: BLE001
        pass

    # Belt & braces: force CREATE_NO_WINDOW onto every child process the app
    # spawns, so no code path — current or future — can flash a console.
    # Also audit every unique command once, so mystery popups can be traced.
    import subprocess as _sp
    _CNW = 0x08000000
    _seen_cmds: set = set()

    def _sp_desc(a):
        try:
            first = a[0] if a and isinstance(a[0], (list, tuple, str)) else a
            if isinstance(first, (list, tuple)):
                first = " ".join(str(x) for x in first[:6])
            return str(first)[:160]
        except Exception:
            return "?"

    for _fn in ("run", "Popen", "call", "check_call", "check_output"):
        _orig = getattr(_sp, _fn)

        def _make(fn=_orig):
            def wrapper(*a, **k):
            # noqa: E306 - nested factory keeps late binding correct
                if k.get("creationflags") is None:
                    k["creationflags"] = _CNW
                elif not (int(k["creationflags"]) & _CNW):
                    k["creationflags"] = int(k["creationflags"]) | _CNW
                try:
                    from maxlog import logger as _lg
                    key = _sp_desc(a)
                    if key not in _seen_cmds:
                        _seen_cmds.add(key)
                        _lg.info(f"spawn: {key}"
                                 + ("  [shell=True]" if k.get("shell")
                                    else ""))
                except Exception:
                    pass
                return fn(*a, **k)
            return wrapper
        setattr(_sp, _fn, _make())

    # Global exception handler: prevent silent crashes by logging unhandled
    # exceptions on the main thread instead of letting Qt terminate the process.
    def _excepthook(exc_type, exc_value, exc_tb):
        import traceback
        from maxlog import logger
        logger.error(f"Unhandled exception: {exc_type.__name__}: {exc_value}\n"
                     + "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    sys.excepthook = _excepthook

    screen = app.primaryScreen().availableGeometry()

    # Boot/autostart: --minimized (set by the HKCU Run entry) used to skip
    # the splash and land straight in the taskbar. We still show the splash
    # every time (so the loading screen is always visible), but flag the
    # autostart case so the window parks minimized in the taskbar afterwards
    # instead of maximizing into the foreground.
    autostart = any(a.lower() in ("--minimized", "--autostart", "/min")
                    for a in sys.argv[1:])

    splash = CinematicSplash()
    # Fullscreen boot (CSS .screen is 100vh): cover the whole primary monitor.
    # Pin the window onto the primary screen's geometry BEFORE showFullScreen,
    # otherwise Qt resolves the fullscreen target from the window's default
    # position, which lands on the wrong monitor in multi-monitor setups.
    _prim = app.primaryScreen().geometry()
    splash.setGeometry(_prim)
    splash.move(_prim.topLeft())
    splash.showFullScreen()
    splash.start()

    # Refresh the persisted license token in the background so a valid license
    # stays fresh without forcing the gate to appear on every launch.
    license_ui.validate_startup()

    holder: dict = {"window": None}

    # Update check as a background boot step (no popup at launch): the splash
    # plays its normal loading sequence first and the check view only appears
    # mid-way through; if a newer build exists the user decides on the splash
    # before the main app launches.
    _update: dict = {}

    def _release_into_app():
        _update.clear()
        splash.update_ok()

    def _start_update_check():
        from ui.updater_dialog import FetchWorker
        splash.arm_update_check()
        worker = FetchWorker(splash)
        worker.done.connect(_on_update_checked)
        _update["worker"] = worker  # keep a strong ref until finished
        worker.start()

    def _on_update_checked(payload):
        info = payload.get("info")
        error = payload.get("error")
        if holder.get("window") is not None:
            splash.update_ok()
            return
        # The splash parks this until its mid-boot milestone unless the check
        # view is already on screen.
        if info is not None:
            _update["info"] = info
        splash.update_check_result(info, error)

    def _start_update_download():
        from ui.updater_dialog import DownloadWorker
        info = _update.get("info")
        if not info:
            return
        worker = DownloadWorker(info["url"], splash)
        worker.bytes.connect(splash.on_download_bytes)
        worker.bytes_total.connect(splash.set_download_bytes)
        worker.progress.connect(splash.update_progress)
        worker.done.connect(_on_update_downloaded)
        _update["dl"] = worker  # keep a strong ref until finished
        worker.start()

    def _on_update_downloaded(new_exe, error):
        if error or new_exe is None:
            splash.update_error(error or "Download failed.")
            return
        _update["new_exe"] = new_exe
        splash.update_downloaded()

    def _apply_update():
        new_exe = _update.get("new_exe")
        if not new_exe:
            return
        from engine import updater
        try:
            updater.install_and_restart(new_exe)
        except updater.UpdaterError as exc:
            splash.update_error(str(exc))
            return
        # The old build terminates here; the stub swaps in the new exe and
        # relaunches it. The restarted app runs the same check, finds no newer
        # version, and proceeds straight into the main window — no loop.
        import time as _time
        _time.sleep(1)
        os._exit(0)

    splash.install_clicked.connect(_start_update_download)
    splash.skip_clicked.connect(_release_into_app)
    splash.retry_clicked.connect(_start_update_check)
    splash.restart_clicked.connect(_apply_update)
    _start_update_check()

    def build_window():
        if holder["window"] is None:
            from ui.main_window import MainWindow
            holder["window"] = MainWindow()
        return holder["window"]

    def reveal_window():
        win = build_window()
        # Same multi-monitor pin: place on the primary screen before showing.
        win.setGeometry(app.primaryScreen().availableGeometry())
        if autostart:
            # Boot/autostart: splash has already played, so park the app in
            # the taskbar instead of stealing foreground focus.
            win.showMinimized()
        else:
            win.showMaximized()
        return win

    def on_finished():
        # Fade the splash first, then hand off on the next event-loop pass.
        # Revealing synchronously here freezes the loading screen whenever the
        # main window takes a moment to build — the boot screen must always
        # clear itself within the ~7s sequence.
        splash.fade_out(700)

        def handoff():
            if license_mgr.is_authorized():
                reveal_window()
                return
            from ui.gate import GateWindow
            gate = GateWindow()
            gate.setGeometry(screen)
            gate.show()

            def unlock(_session):
                win = reveal_window()
                gate.fade_out(600)
            gate.unlocked.connect(unlock)

        QTimer.singleShot(0, handoff)

    splash.finished.connect(on_finished)
    sys.exit(app.exec())

def _risk_star(t):
    return "*" * (RISK_ORDER[t["risk"]] + 1)


def _impact(t):
    return IMPACT_ORDER[t["impact"]]


def cmd_list():
    header = f"{'Category':<22}{'Module':<16}{'Tweaks':>7}"
    print(header)
    print("-" * len(header))
    for cat, module in sorted(CATEGORIES.items(), key=lambda kv: kv[0]):
        count = sum(1 for t in TWEAKS if t["category"] == cat)
        print(f"{cat:<22}{module:<16}{count:>7}")
    print("-" * len(header))
    print(f"Total: {len(TWEAKS)} tweaks in {len(CATEGORIES)} categories")


def cmd_show(tweak_id):
    t = BY_ID.get(tweak_id)
    if not t:
        print(f"Unknown tweak id: {tweak_id}")
        sys.exit(1)
    print(f"[{t['id']}] {t['name']}  ({t['category']})")
    print(f"  Description : {t['desc']}")
    print(f"  Why         : {t['why']}")
    print(f"  Changes     : {t['changes']}")
    print(f"  Risk        : {t['risk']}  Impact: {t['impact']}  Rec: {t['recommended']}")
    print(f"  Windows     : {t['win']}   Admin: {'yes' if t['admin'] else 'no'}")
    print(f"  Tags        : {', '.join(t['tags']) or '-'}")
    print("  Applies:")
    for a in t["actions"]:
        print(f"    - {a}")
    if t["revert"]:
        print("  Reverts:")
        for a in t["revert"]:
            print(f"    - {a}")


def cmd_category(name):
    matches = [t for t in TWEAKS if t["category"].lower() == name.lower()]
    if not matches:
        print(f"No category named {name!r}. Try one of:")
        for cat in sorted(CATEGORIES):
            print(f"  - {cat}")
        sys.exit(1)
    print(f"{name}: {len(matches)} tweaks")
    for t in sorted(matches, key=lambda t: t["id"]):
        print(f"  {t['id']:<12} {_risk_star(t):<10} {t['name']}")


def cmd_search(query):
    q = query.lower()
    hits = []
    for t in TWEAKS:
        hay = " ".join([t["id"], t["name"], t["desc"], t["category"], " ".join(t["tags"])]).lower()
        if q in hay:
            hits.append(t)
    hits.sort(key=lambda t: (t["category"], t["id"]))
    if not hits:
        print(f"No tweaks match {query!r}")
        return
    print(f"{len(hits)} match(es) for {query!r}:")
    for t in hits:
        print(f"  {t['id']:<12} [{t['category']:<18}] {t['name']}")


def cmd_apply(tweak_id, mode, dry_run):
    from engine import applier
    t = BY_ID.get(tweak_id)
    if not t:
        print(f"Unknown tweak id: {tweak_id}")
        sys.exit(1)
    label = "dry-run apply" if (dry_run and mode == "apply") else "dry-run revert" if dry_run else mode
    print(f"{label.title()} -> [{t['id']}] {t['name']}")

    # The engine refuses to run hardware-gated tweaks without a detected
    # profile, so detect the system for a real apply. Failures degrade to a
    # minimal Windows-version-only profile (still safe: vendor-gated tweaks
    # are then refused rather than blindly applied).
    profile = None
    if mode == "apply" and not dry_run:
        try:
            from hardware import detect
            profile = detect()
        except Exception as exc:  # noqa: BLE001
            print(f"  note: hardware detection unavailable ({exc}) — "
                  "hardware-gated tweaks will be blocked")
            profile = None

    result = applier.run([tweak_id], mode, profile=profile, dry_run=dry_run)
    r = result["results"][tweak_id]
    status = r.get("status")
    for action, aok, detail in r.get("actions") or []:
        print(f"  [{'ok  ' if aok else 'FAIL'}] {action[0]:<11} {detail}")
    if status == "blocked":
        print(f"Blocked: {r.get('detail')}")
        sys.exit(3)
    if not r.get("ok"):
        print(f"Failed: {r.get('detail')}")
        sys.exit(2)
    if status == "dry_run":
        print(f"Dry-run: {len(r.get('actions') or [])} action(s) would run.")
        return
    verified = r.get("verified")
    if verified is None:
        print(f"Applied \u2014 could not be verified against the live system.")
    elif verified is True:
        print("Applied and verified against the live system.")
    else:
        print("Executed but the live system does not match — NOT recorded as applied.")
        sys.exit(2)


def cmd_report(tweak_id):
    t = BY_ID.get(tweak_id)
    if not t:
        print(f"Unknown tweak id: {tweak_id}")
        sys.exit(1)
    print(f"[{t['id']}] {t['name']}")
    print(f"  Admin required: {'yes' if t['admin'] else 'no'}   Confirm: {'yes' if t['confirm'] else 'no'}")
    print(f"  Applies {len(t['actions'])} action(s):")
    for a in t["actions"]:
        print(f"    - {a}")
    print(f"  Revert ({len(t['revert'])} action(s)):")
    for a in t["revert"]:
        print(f"    - {a}")


def cmd_stats():
    risky = sorted((t for t in TWEAKS if t["risk"] in ("moderate", "advanced")),
                   key=lambda t: t["category"])
    print(f"Registry: {len(TWEAKS)} tweaks, {len(CATEGORIES)} categories, {len(BY_ID)} unique ids")
    print(f"Admin-required tweaks: {sum(1 for t in TWEAKS if t['admin'])}")
    print(f"Moderate/advanced risk tweaks: {len(risky)}")
    for t in risky:
        print(f"  {t['id']:<12} [{t['risk']:<9}] {t['name']}")
    print(f"Action kinds in use:")
    kinds = {}
    for t in TWEAKS:
        for a in t["actions"]:
            kinds[a[0]] = kinds.get(a[0], 0) + 1
    for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<12} {n}")


def cmd_detect(seconds: float, use_qt: bool) -> int:
    """Diagnostic probe for live game-server detection (mimics the GUI path)."""
    import sys as _sys

    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if use_qt:
        from PySide6.QtCore import QCoreApplication, QTimer, QThread, Signal

        class _ProbeWorker(QThread):
            done = Signal(object)
            _game = "Fortnite"
            _sec = seconds

            def run(self):
                from engine.netmonitor.targeting import resolve_game_server
                self.done.emit(
                    resolve_game_server(self._game, duration=max(1.0, self._sec)))

        app = QCoreApplication([])
        worker = _ProbeWorker()
        outcome = {}

        def _on_done(res):
            outcome["res"] = res
            app.quit()

        worker.done.connect(_on_done)
        worker.start()
        QTimer.singleShot(int(seconds + 30) * 1000, app.quit)
        app.exec()
        res = outcome.get("res")
    else:
        from engine.netmonitor.targeting import resolve_game_server
        res = resolve_game_server("Fortnite", duration=max(1.0, seconds))

    if res is None:
        print("PROBE: no result (timed out)")
        return 2
    print(f"PROBE found={res.found} confidence={res.confidence} "
          f"ip={res.ip or '-'} candidates={res.candidate_count}")
    print(f"PROBE reason={res.reason}")
    return 0


def cmd_trace(target: str, max_hops: int) -> int:
    """One bounded scapy traceroute probe (mirrors the monitor's scan path)."""
    import sys as _sys
    import time as _time

    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from engine.netmonitor.traceroute import run_traceroute

    t0 = _time.time()
    route = run_traceroute(target, max_hops=max_hops, timeout=2.0)
    print(f"PROBE traced {route.destination} -> {route.destination_ip} "
          f"hops={len(route.hops)} total={route.total_latency:.1f}ms "
          f"dt={_time.time() - t0:.1f}s")
    for h in route.hops:
        print(f"  hop {h.number}: {h.ip or '-'}  {h.latency:.1f}ms  {h.status.value}")
    return 0


def cmd_monitor(seconds: float) -> int:
    """Detect + start_monitoring + short run (mirrors the auto-trace after detect)."""
    import sys as _sys
    import time as _time

    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from engine.netmonitor.targeting import resolve_game_server, TargetMatch
    from engine.netmonitor.engine import NetworkMonitorEngine
    from engine.netmonitor.types import ProbeMethod

    tgt = resolve_game_server("Fortnite", duration=2.0)
    print(f"PROBE detect found={tgt.found} ip={tgt.ip or '-'} "
          f"ports={tgt.remote_ports} clients={tgt.client_ports}")
    if not (tgt.found and tgt.ip):
        print("PROBE no target — nothing to monitor")
        return 0

    tm = TargetMatch(
        found=True, game="Fortnite", ip=tgt.ip,
        remote_ports=tgt.remote_ports, client_ports=tgt.client_ports,
        confidence="signature", reason="probe", protocol=ProbeMethod.UDP,
    )
    eng = NetworkMonitorEngine()
    eng.on_event(lambda e: print(f"  event:[{e.level}] {e.message}"))
    t0 = _time.time()
    eng.start_monitoring(tgt.ip, target=tm)
    print(f"PROBE monitoring started (dt={_time.time() - t0:.2f}s)")
    _time.sleep(max(2.0, seconds))
    eng.stop()
    r = eng.get_route()
    print(f"PROBE stopped. route hops={len(r.hops) if r else 0} "
          f"total={r.total_latency if r else 0:.1f}ms")
    return 0


def cmd_verify(target: str) -> int:
    """Side-by-side fidelity check: our traceroute vs native `tracert`."""
    import re as _re
    import subprocess as _sp
    import sys as _sys
    import time as _time

    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from engine.netmonitor.traceroute import run_traceroute

    print(f"VERIFY target={target}")
    print("  running our traceroute ...")
    t0 = _time.time()
    route = run_traceroute(target, max_hops=30, timeout=2.0)
    print(f"  ours: {len(route.hops)} hops in {_time.time() - t0:.1f}s")

    ours = {}
    for h in route.hops:
        ours[h.number] = (h.ip or "", round(h.latency, 1))

    print("  running native tracert -d -h 30 ...")
    try:
        proc = _sp.run(
            ["tracert", "-d", "-h", "30", target],
            capture_output=True, text=True, timeout=120,
            creationflags=0x08000000,
        )
        native = {}
        for line in proc.stdout.splitlines():
            m = _re.match(r"\s*(\d+)\s+(\d+)\s+ms\s+(\d+)\s+ms\s+([\d.]+|Request timed out)", line)
            if m:
                num = int(m.group(1))
                ip = m.group(4)
                native[num] = ip if ip != "Request timed out" else ""
            else:
                m2 = _re.match(r"\s*(\d+)\s+<1\s+ms\s+<1\s+ms\s+([\d.]+)", line)
                if m2:
                    native[int(m2.group(1))] = m2.group(2)
    except Exception as exc:
        print(f"  tracert failed: {exc}")
        native = {}

    all_nums = sorted(set(ours) | set(native))
    print(f"\n{'hop':>4} {'ours ip':<16}{'ours ms':>9}   {'tracert ip':<16}{'match':>7}")
    print("-" * 58)
    matched = 0
    ours_only = []
    native_only = []
    for n in all_nums:
        o_ip, o_ms = ours.get(n, ("-", 0.0))
        n_ip = native.get(n, "-")
        if o_ip == "-":
            label = "-"
        else:
            label = "YES" if n_ip == o_ip else "no"
        if n_ip != "-" and o_ip == n_ip:
            matched += 1
        elif o_ip != "-" and n_ip == "-":
            ours_only.append(n)
        elif n_ip != "-" and o_ip == "-":
            native_only.append(n)
        o_disp = o_ip if o_ip else "-"
        print(f"{n:>4} {o_disp:<16}{o_ms:>8.1f}   {n_ip:<16}{label:>7}")

    print(f"\nAGREEMENT: {matched} hop(s) identical",
          f"| ours-only: {ours_only or '-'}",
          f"| tracert-only: {native_only or '-'}")
    if ours_only:
        print("  NOTE: hops visible to us but not tracert — these are partial/"
              "rate-limited responders our windowed sweep still picks up.")
    if native_only:
        print("  NOTE: hops visible to tracert but not us — strong rate-limiting;"
              "the TTL was probed but the responder only answers ICMP echo.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="maximum-tweaks", description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="preview actions without executing")
    parser.add_argument("--cli", action="store_true", help="run in terminal mode instead of GUI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="list all categories")
    sub.add_parser("stats", help="database statistics")
    p_show = sub.add_parser("show", help="show one tweak in detail")
    p_show.add_argument("id")
    p_cat = sub.add_parser("category", help="list tweaks in a category")
    p_cat.add_argument("name")
    p_search = sub.add_parser("search", help="search tweaks")
    p_search.add_argument("query")
    p_apply = sub.add_parser("apply", help="apply a tweak")
    p_apply.add_argument("id")
    p_revert = sub.add_parser("revert", help="revert a tweak")
    p_revert.add_argument("id")
    p_rep = sub.add_parser("report", help="preview a tweak's actions")
    p_rep.add_argument("id")
    p_det = sub.add_parser("detect", help="probe live game-server detection (diagnostic)")
    p_det.add_argument("--seconds", type=float, default=5.0)
    p_det.add_argument("--qt", action="store_true")
    p_tr = sub.add_parser("trace", help="run one bounded scapy traceroute probe (diagnostic)")
    p_tr.add_argument("target")
    p_tr.add_argument("--hops", type=int, default=6)
    p_vf = sub.add_parser("verify", help="side-by-side fidelity check vs native tracert (diagnostic)")
    p_vf.add_argument("target")
    p_mon = sub.add_parser("monitor", help="run detect + full monitoring (diagnostic)")
    p_mon.add_argument("--seconds", type=float, default=12.0)

    # Unknown top-level flags (e.g. --minimized/--autostart set by the HKCU Run
    # entry) must never fail the launch — they're consumed inside run_gui().
    # parse_known_args lets unrecognized args pass through and we still head to
    # the GUI (the CLI code path is chosen below when --cli + a command is given).
    args, _unknown = parser.parse_known_args(argv)
    if not args.cli and not args.command:
        run_gui()
        return
    if args.command == "list":
        cmd_list()
    elif args.command == "stats":
        cmd_stats()
    elif args.command == "show":
        cmd_show(args.id)
    elif args.command == "category":
        cmd_category(args.name)
    elif args.command == "search":
        cmd_search(args.query)
    elif args.command == "apply":
        cmd_apply(args.id, "apply", args.dry_run)
    elif args.command == "revert":
        cmd_apply(args.id, "revert", args.dry_run)
    elif args.command == "report":
        cmd_report(args.id)
    elif args.command == "detect":
        raise SystemExit(cmd_detect(args.seconds, args.qt))
    elif args.command == "trace":
        raise SystemExit(cmd_trace(args.target, args.hops))
    elif args.command == "verify":
        raise SystemExit(cmd_verify(args.target))
    elif args.command == "monitor":
        raise SystemExit(cmd_monitor(args.seconds))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
