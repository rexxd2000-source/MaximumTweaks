"""Diagnose why Fortnite detection is failing."""
import psutil
import os
import time

print("=" * 60)
print("FORTNITE DETECTION DIAGNOSTIC")
print("=" * 60)

# 1. Find all Epic/Fortnite-related processes
print("\n--- ALL EPIC/FORTNITE PROCESSES ---")
epic_procs = []
for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "ppid", "create_time"]):
    try:
        info = proc.info
        name = info.get("name", "")
        exe = info.get("exe", "")
        name_lower = name.lower()
        exe_lower = (exe or "").lower()

        if any(kw in name_lower for kw in ["fortnite", "epic", "easyanticheat"]):
            epic_procs.append(info)
            print(f"  PID: {info['pid']}")
            print(f"  Name: {name}")
            print(f"  Exe: {exe}")
            print(f"  PPID: {info.get('ppid', '?')}")
            cmdline = info.get("cmdline", [])
            if cmdline:
                print(f"  Cmdline: {' '.join(cmdline[:3])}")
            print()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

if not epic_procs:
    print("  NO Epic/Fortnite processes found!")
    print("  This means detection is correct - Fortnite may not be running.")
    print("  Checking ALL processes for any game-like names...")
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            info = proc.info
            name = (info.get("name", "") or "").lower()
            if any(kw in name for kw in ["game", "fort", "epic", "valve", "steam", "riot", "blizzard", "activision"]):
                print(f"    PID: {info['pid']} Name: {info.get('name', '')}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

# 2. Check what the current detector sees
print("\n--- DETECTOR TEST ---")
from engine.intel.games import detect_running_games, get_primary_game, GAME_DEFINITIONS

for game_type, game_def in GAME_DEFINITIONS.items():
    print(f"\nGame: {game_type.value}")
    print(f"  Process names: {game_def.process_names}")
    print(f"  Launcher processes: {game_def.launcher_processes}")
    found = False
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            info = proc.info
            name = info.get("name", "")
            exe = info.get("exe", "")
            for gn in game_def.process_names + game_def.launcher_processes:
                if name.lower() == gn.lower():
                    found = True
                    print(f"  MATCH: PID={info['pid']} name={name} exe={exe}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if not found:
        print(f"  NO MATCH")

# 3. Check network connections for Epic processes
print("\n--- NETWORK CONNECTIONS FOR EPIC PROCESSES ---")
epic_pids = {p["pid"] for p in epic_procs}
for conn in psutil.net_connections(kind="all"):
    if conn.pid in epic_pids:
        local = f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "?"
        remote = f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "?"
        print(f"  PID={conn.pid} {conn.type.name} {conn.status} {local} -> {remote}")

# 4. Check connections for ANY process that might be Fortnite
print("\n--- ALL ESTABLISHED CONNECTIONS ---")
for conn in psutil.net_connections(kind="inet"):
    if conn.status == "ESTABLISHED" and conn.pid:
        try:
            proc = psutil.Process(conn.pid)
            name = proc.name()
            local = f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "?"
            remote = f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "?"
            print(f"  PID={conn.pid} ({name}) {conn.type.name} {local} -> {remote}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

# 5. Full detection test
print("\n--- FULL DETECTION TEST ---")
games = detect_running_games()
print(f"Games detected: {len(games)}")
for g in games:
    print(f"  {g.game.value} PID={g.pid} name={g.process_name} active={g.is_active}")

primary = get_primary_game(games)
if primary:
    print(f"\nPrimary game: {primary.game.value}")
else:
    print("\nNo primary game found!")
