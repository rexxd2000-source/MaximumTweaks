"""Mass audit cleanup: remove aggressive, duplicate, placebo, broken tweaks."""
import re, sys, os

TWEAKS_DIR = r"C:\Users\Admin\Documents\Default Project\RexTweaks\database\tweaks"

# ═══════════════════════════════════════════════════════════════════
# Tweaks to REMOVE (by file), identified by the comprehensive audit
# ═══════════════════════════════════════════════════════════════════

REMOVE_BY_FILE = {
    "cpu.py": [
        "cpu-005",   # Aggressive boost mode → thermal throttling
        "cpu-015",   # Decrease threshold 100 → aggressive downclocking
        "cpu-018",   # Action/revert swapped (enables HAGS when it says disable)
        "cpu-021",   # Rocket increase → thermal throttling
        "cpu-022",   # Rocket decrease → prevents downclocking → heat
        "cpu-024",   # EPP=0 → e-cores at max → steals thermal headroom
    ],
    "laptop.py": [
        "lap-051",   # Min 100% CPU on AC → constant max power/heat
    ],
    "power.py": [
        "power-007",  # Duplicate of cpu-002
        "power-015",  # Duplicate of power-006
    ],
    "performance.py": [
        "perf-022",  # Duplicate of cpu-005 (aggressive boost)
        "perf-031",  # Contradicts perf-025 (Enable vs Disable HPET)
    ],
    "nvidia.py": [
        "nv-004",   # Forces highest GPU perf level, blocks dynamic clock
        "nv-008",   # Triple-registry forced max GPU perf
        "nv-017",   # Duplicate of nv-005
    ],
    "gpu.py": [
        "gpu-004",  # Redundant with gpu-057
        "gpu-017",  # Disabling TDR = hard lock on hung GPU
        "gpu-023",  # Disabling DWM breaks Win10/11 rendering
        "gpu-026",  # Undocumented DWM AnimationAttribute
        "gpu-031",  # Undocumented DWM thumbnail size; no gaming impact
        "gpu-033",  # Undocumented; purely cosmetic
        "gpu-034",  # Undocumented; purely cosmetic
        "gpu-036",  # Undocumented Avalon key
        "gpu-037",  # Undocumented Avalon key; wastes fill rate
        "gpu-038",  # Undocumented Avalon key; may break rendering
        "gpu-039",  # Same as gpu-038
        "gpu-041",  # Undocumented Direct3D key
        "gpu-049",  # Utility, not a perf tweak
        "gpu-053",  # Can cause black screen
        "gpu-055",  # Disabling preemption = display stalls/mouse lag
        "gpu-056",  # Undocumented; no measurable effect
        "gpu-057",  # Redundant with gpu-004
        "gpu-061",  # Security risk: allows unsigned kernel drivers
    ],
    "intel.py": [
        "int-015",  # Sets min to 5% — blocks normal frequency scaling
    ],
    "network.py": [
        "net-011",  # Conflicts with net-005 (timestamps on vs off)
        "net-018",  # Sets autotuning to normal = default; no-op
        "net-019",  # Conflicts with net-003 (RSS enable vs disable)
    ],
    "ethernet.py": [
        "eth-002",  # Duplicate of aim-001/net-017
        "eth-003",  # Duplicate of aim-001/net-017
        "eth-007",  # Spikes CPU from per-packet interrupts
        "eth-014",  # Disabling LSO IPv6 increases CPU overhead
    ],
    "storage.py": [
        "stor-003",  # Duplicate of stor-016
        "stor-012",  # Triplicate write caching
        "stor-015",  # Duplicate of stor-001
        "stor-017",  # Undocumented; unsafe with BitLocker
        "stor-018",  # Duplicate of stor-012
        "stor-019",  # Prevents NVMe power states; wastes power/heat
    ],
    "ram.py": [
        "ram-006",  # Conflicts with ram-058
        "ram-025",  # Conflicts with ram-024; manual sizing risky
        "ram-026",  # Assumes D: exists; fails on single-drive
        "ram-027",  # Arbitrary fixed size; causes OOM
        "ram-034",  # Disabling BITS breaks Windows Update
        "ram-039",  # PcaSvc detects/fixes game crashes
        "ram-041",  # XP-era key; ignored by modern Windows
        "ram-045",  # Breaks pen/touch/Windows Ink
        "ram-046",  # Breaks notification apps and game invites
        "ram-053",  # Debloat task, not RAM optimization
        "ram-057",  # Conflicts with sys-003; favors file cache over games
        "ram-059",  # Duplicate of sys-001
    ],
    "aim.py": [
        "aim-001",  # Triplicate with net-017 and eth-003
    ],
    "system.py": [
        "sys-001",  # Duplicate of ram-059
        "sys-003",  # Conflicts with adv-002
        "sys-005",  # Prevents diagnosing BSODs
        "sys-018",  # Major security risk
        "sys-020",  # Duplicate of sys-012
        "sys-024",  # Conflicts with adv-006
    ],
    "advanced.py": [
        "adv-001",  # Duplicate of sys-018
        "adv-002",  # Conflicts with sys-003
        "adv-005",  # Triplicate write caching
        "adv-012",  # Duplicate of ram-040
        "adv-013",  # Removes heap corruption protection
        "adv-016",  # Triplicate write caching
    ],
    "windows.py": [
        "win-003",  # Conflicts with Game Mode enable
        "win-020",  # Duplicate of db-008
        "win-024",  # Actually controls recent docs, not animations
    ],
    "display.py": [
        "disp-001",  # Conflicts with win-004 (FSE)
        "disp-003",  # Makes text blurry; terrible UX
        "disp-013",  # Duplicate of disp-010; undocumented key
        "disp-015",  # Undocumented wildcard path
    ],
    "usb.py": [
        "usb-002",  # Blocks ALL USB drives; extreme
        "usb-009",  # Duplicate of usb-001
        "usb-011",  # Duplicate of audio-010
        "usb-013",  # Triplicate of usb-001
        "usb-015",  # Undocumented; masks real USB errors
    ],
    "mouse.py": [
        "mouse-011",  # Duplicate of mouse-022
        "mouse-033", "mouse-034", "mouse-035", "mouse-036",
        "mouse-037", "mouse-038", "mouse-039", "mouse-040",
        "mouse-041", "mouse-042", "mouse-043", "mouse-044",
        "mouse-045", "mouse-046",  # All cosmetic cursor themes
        "mouse-054",  # Undocumented; advanced risk
    ],
    "debloat.py": [
        "db-007",  # Duplicate of tel-008
        "db-008",  # Duplicate of win-020
        "db-009",  # Duplicate of win-017
        "db-010",  # Duplicate of win-009
        "db-011",  # Duplicate of win-014
        "db-013",  # Duplicate of win-018
    ],
    "telemetry.py": [
        "tel-006",  # Duplicate of win-013
        "tel-007",  # Duplicate of win-014/db-011
        "tel-008",  # Duplicate of db-007
        "tel-014",  # Duplicate of net-013
        "tel-015",  # Exact duplicate of tel-001
        "tel-018",  # Duplicate of tel-010
    ],
    "services.py": [
        "svc-003",  # Duplicate of ram-030
        "svc-004",  # 4th copy of WerSvc disable
        "svc-008",  # Duplicate of gpu-043/gpu-044
        "svc-009",  # Duplicate of net-013/tel-014
        "svc-015",  # Breaks NTP sync; TLS/AD failures
        "svc-017",  # Duplicate of svc-006
        "svc-018",  # Duplicate of svc-007
    ],
    "startup.py": [
        "start-015",  # 4th copy of WerSvc disable
    ],
    "scheduling.py": [
        # sched-015 conflicts with perf-048 but both disable interrupt steering
        # Keep sched-015 as it's the cleaner version
    ],
}


def remove_tweaks_from_file(filepath, ids_to_remove):
    """Remove tweak blocks matching IDs from a Python file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    removed = []
    for tid in ids_to_remove:
        # Match the T() call block for this tweak ID
        # Pattern: from the T("tid", line to the closing ),\n
        # We need to find T("tid" and remove the entire block
        
        # Find the start: T("tid-001",
        pattern_start = f'    T("{tid}",'
        idx = content.find(pattern_start)
        if idx == -1:
            # Try with spaces
            pattern_start = f'T("{tid}",'
            idx = content.find(pattern_start)
        if idx == -1:
            # Try without trailing comma (for last entry)
            pattern_start = f'    T("{tid}"'
            idx = content.find(pattern_start)
        
        if idx == -1:
            # Try matching in any whitespace context
            pattern_start = f'T("{tid}"'
            idx = content.find(pattern_start)
        
        if idx == -1:
            print(f"  WARNING: {tid} not found in {os.path.basename(filepath)}")
            continue
        
        # Find the end: match balanced parentheses
        # Start from the T( opening
        paren_depth = 0
        found_first_paren = False
        end_idx = idx
        in_string = False
        string_char = None
        escape_next = False
        
        i = idx
        while i < len(content):
            ch = content[i]
            
            if escape_next:
                escape_next = False
                i += 1
                continue
            
            if ch == '\\':
                escape_next = True
                i += 1
                continue
            
            if in_string:
                if ch == string_char:
                    in_string = False
                i += 1
                continue
            
            if ch in ('"', "'"):
                # Check for triple quotes
                if content[i:i+3] in ('"""', "'''"):
                    in_string = True
                    string_char = ch
                    i += 3
                    continue
                in_string = True
                string_char = ch
                i += 1
                continue
            
            if ch == '(':
                paren_depth += 1
                found_first_paren = True
            elif ch == ')':
                paren_depth -= 1
                if found_first_paren and paren_depth == 0:
                    end_idx = i + 1
                    break
            i += 1
        
        # Find the trailing comma/newline after the closing paren
        rest = content[end_idx:end_idx+5]
        if rest.startswith(','):
            end_idx += 1
        elif rest.startswith(')\n'):
            pass  # already at end
        
        # Also grab leading whitespace/newlines
        start = idx
        while start > 0 and content[start-1] in (' ', '\t'):
            start -= 1
        if start > 0 and content[start-1] == '\n':
            start -= 1
        if start > 0 and content[start-1] == '\n':
            start -= 1
        
        removed.append(tid)
        content = content[:start] + "\n" + content[end_idx:]
    
    # Clean up excessive blank lines (3+ → 2)
    while '\n\n\n' in content:
        content = content.replace('\n\n\n', '\n\n')
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return removed


# Run the cleanup
total_removed = 0
for filename, ids in REMOVE_BY_FILE.items():
    if not ids:
        continue
    filepath = os.path.join(TWEAKS_DIR, filename)
    if not os.path.exists(filepath):
        print(f"SKIP: {filename} not found")
        continue
    
    removed = remove_tweaks_from_file(filepath, ids)
    total_removed += len(removed)
    print(f"{filename}: removed {len(removed)}/{len(ids)} tweaks: {', '.join(removed)}")

print(f"\nTotal removed: {total_removed}")
