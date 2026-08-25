import sys
sys.path.insert(0, r"C:\Users\Admin\Documents\Default Project\RexTweaks")
from engine.intel.games import detect_running_games, get_primary_game

games = detect_running_games()
print(f"Total games found: {len(games)}")
for g in games:
    print(f"  {g.display_name} | PID={g.pid} | name={g.process_name} | active={g.is_active} | conf={g.confidence.value} | net={g.has_network} | endpoints={g.remote_endpoints} | path={g.process_path[:60]}")

primary = get_primary_game(games)
if primary:
    print(f"\nPrimary: {primary.display_name} PID={primary.pid}")
    print(f"  Network: {primary.has_network} ({primary.remote_endpoints} endpoints)")
else:
    print("\nNo primary game found!")
