"""Rex Tweaks — GUI app with a CLI fallback.

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
import sys

from database import BY_ID, CATEGORIES, TWEAKS
from database.executor import apply_tweak

RISK_ORDER = {"safe": 0, "low": 1, "moderate": 2, "advanced": 3}
IMPACT_ORDER = {"very low": 0, "low": 1, "moderate": 2, "high": 3, "extreme": 4}
REC_ORDER = {"recommended": 0, "optional": 1, "experimental": 2, "advanced": 3, "not_recommended": 4}


def run_gui():
    from PySide6.QtWidgets import QApplication

    from engine import auth_server, discord_auth
    from ui import discord as discord_ui
    from ui.splash import CinematicSplash
    from ui.styles import build_qss

    # Bring up the auth backend (OAuth/verification server) so the app can
    # log users in without anyone having to run it separately. No-op if it is
    # already reachable (e.g. a shared/hosted backend).
    auth_server.start()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(build_qss())

    screen = app.primaryScreen().availableGeometry()
    splash = CinematicSplash()
    splash.setGeometry(screen)
    splash.show()
    splash.start()

    # Stop the auth backend when the app closes (only if we started it).
    app.aboutToQuit.connect(auth_server.stop)

    # Refresh the persisted Discord token in the background so a verified
    # identity stays valid without popping the browser on every launch.
    discord_ui.validate_startup()

    holder: dict = {"window": None}

    def build_window():
        if holder["window"] is None:
            from ui.main_window import MainWindow
            holder["window"] = MainWindow()
        return holder["window"]

    def reveal_window():
        win = build_window()
        win.move(screen.topLeft())
        win.show()
        win.raise_()
        return win

    def on_finished():
        # Verified? Go straight to the app. Otherwise block behind the gate
        # so a fresh install cannot reach the app until an identity attaches.
        if discord_auth.session():
            reveal_window()
            splash.fade_out(750)
            return
        from ui.gate import GateWindow
        gate = GateWindow()
        gate.setGeometry(screen)
        gate.show()

        def unlock(_profile):
            win = reveal_window()
            gate.fade_out(600)
            # The gate can be bypassed (owner dev build). If no identity was
            # actually attached, park on the disconnect landing until verified.
            if not discord_auth.session():
                win.on_disconnect()
        gate.unlocked.connect(unlock)
        splash.fade_out(750)

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
    t = BY_ID.get(tweak_id)
    if not t:
        print(f"Unknown tweak id: {tweak_id}")
        sys.exit(1)
    label = "dry-run apply" if (dry_run and mode == "apply") else "dry-run revert" if dry_run else mode
    print(f"{label.title()} -> [{t['id']}] {t['name']}")
    if t["admin"] and mode == "apply" and not dry_run:
        print("  note: this tweak requires administrator privileges")
    ok, results = apply_tweak(tweak_id, mode=mode, dry_run=dry_run)
    for action, aok, detail in results:
        status = "ok  " if aok else "FAIL"
        print(f"  [{status}] {action[0]:<11} {detail}")
    if ok:
        print(f"Done: {len(results)} action(s).")
    else:
        print("Some actions failed — see above.")
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
