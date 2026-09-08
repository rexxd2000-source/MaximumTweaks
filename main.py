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
    from PySide6.QtWidgets import QApplication

    from config.app_config import APP_VERSION
    from engine import license as license_mgr
    from ui import license as license_ui
    from ui.splash import CinematicSplash
    from ui.styles import build_qss

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(build_qss())

    # Global exception handler: prevent silent crashes by logging unhandled
    # exceptions on the main thread instead of letting Qt terminate the process.
    def _excepthook(exc_type, exc_value, exc_tb):
        import traceback
        from rexlog import logger
        logger.error(f"Unhandled exception: {exc_type.__name__}: {exc_value}\n"
                     + "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    sys.excepthook = _excepthook

    screen = app.primaryScreen().availableGeometry()
    splash = CinematicSplash()
    splash.resize(900, 720)
    splash.move(screen.center().x() - 450, screen.center().y() - 360)
    splash.show()
    splash.start()

    # Refresh the persisted license token in the background so a valid license
    # stays fresh without forcing the gate to appear on every launch.
    license_ui.validate_startup()

    holder: dict = {"window": None}

    # Inline update check as a loading step (no popup): the splash parks its
    # progress until the check resolves, and if a newer build exists the user
    # decides on the splash itself before the main app launches.
    _update: dict = {}

    def _release_into_app():
        _update.clear()
        splash.update_ok()

    def _start_update_check():
        from ui.updater_dialog import FetchWorker
        splash.update_checking()
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
        if error:
            splash.update_error(error)
            return
        if info is None:
            _release_into_app()
            return
        _update["info"] = info
        splash.update_available(APP_VERSION, info["version"],
                                info.get("notes") or "")

    def _start_update_download():
        from ui.updater_dialog import DownloadWorker
        info = _update.get("info")
        if not info:
            return
        worker = DownloadWorker(info["url"], splash)
        worker.progress.connect(splash.update_progress)
        worker.done.connect(_on_update_downloaded)
        _update["dl"] = worker  # keep a strong ref until finished
        worker.start()

    def _on_update_downloaded(new_exe, error):
        if error or new_exe is None:
            splash.update_error(error or "Download failed.")
            return
        from engine import updater
        splash.set_installing()
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
    _start_update_check()

    def build_window():
        if holder["window"] is None:
            from ui.main_window import MainWindow
            holder["window"] = MainWindow()
        return holder["window"]

    def reveal_window():
        win = build_window()
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


def main(argv=None):
    parser = argparse.ArgumentParser(prog="rex", description=__doc__)
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

    args = parser.parse_args(argv)
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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
