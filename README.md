# Rex Tweaks

Detect -> Analyze -> Recommend -> Optimize -> Measure -> Revert

Rex Tweaks is a Windows system optimizer with a **603-tweak database** across
45 categories (CPU, GPU, RAM, network, power, services, privacy, storage,
audio, input, BIOS, game-specific and more). It detects your hardware, marks
only **compatible** tweaks as ready, and applies/reverts them with one click.

## Features

- **Expandable sidebar navigation** — "Tweaks" expands in the sidebar into
  CPU, GPU, RAM, Mouse, Keyboard, Aim/Input, Network, Storage, Windows,
  Performance, Fortnite and Games. Click any one and its tweak cards appear
  in the main panel instantly. Plus Game Profiles, Tools and Settings.
- **Modern tweak cards** — every tweak is a proper card with an icon, name,
  short description, Category/Impact/Affects labels, a status pill and an
  Apply/Disable toggle. Cards fade green (**● APPLIED**) when applied and
  red (**● DISABLED**) when reverted, with smooth glow transitions.
- **Performance control-center dashboard** — a live **PC Performance Overview**
  with CPU / GPU / RAM / System cards (real-time usage via psutil + NVIDIA SMI,
  VRAM, temps, uptime), hero status chips, quick actions, gaming-optimization
  status and a premium **COMING SOON** Discord card.
- **Game Profiles** — one-click per-game performance profiles for 12 titles
  (Fortnite, Valorant, CS2, COD, Apex, Overwatch 2, Minecraft, Rocket League,
  LoL, Rust, Tarkov, Warzone) with an animated **"LAUNCHING <GAME> PROFILE…"**
  screen that steps through each stage and finishes on **"✓ PROFILE READY"**,
  active-profile tracking and easy deactivation.
- **Dedicated Fortnite section** organized into Performance, Input/Latency, FPS,
  Graphics, Network, Launch Options and Config subsections, with a one-click
  Fortnite profile launch.
- **Tools page** — hardware detection, one-click optimize bundles, live logs
  and the System Tools category in one place, plus a **Settings** page for
  admin mode, applied-state reset, active-profile and restart-flag control.
- **Hardware-aware compatibility**: every tweak is gated on your actual CPU,
  GPU, RAM, storage, network and Windows build, so nothing incompatible is
  suggested.
- **One-click bundles**:
  - **Balanced** (safe, 15 tweaks) — everyday performance.
  - **Competitive** (29) — minimum input latency for esports.
  - **Maximum** (48) — advanced debloating and latency tuning (security/stability trade-offs).
- **Full revert support** — every tweak ships paired `actions` / `revert` steps;
  an applied-state tracker makes anything you applied one click away from being
  undone.
- **Preview before apply** — see the exact registry keys, services and commands
  a tweak touches before running it.
- **Terminal mode** for scripting (`--cli`).
- Built-in logging (live-viewable in the app) at `Logs/rextweaks.log`.

## Requirements

- Windows 10 1903+ or Windows 11
- Python 3.10+ (dev only — end users get the `.exe`)

## Run from source

```powershell
pip install -r requirements.txt
python main.py              # GUI
python main.py --cli list   # terminal mode
```

## CLI

```
python main.py list | stats | show <id> | category <name> | search <query>
python main.py apply <id> [--dry-run] | revert <id> [--dry-run] | report <id>
```

## Build the .exe

```powershell
pip install pyinstaller
python -m PyInstaller RexTweaks.spec --noconfirm
# output: dist\RexTweaks.exe
```

Run the resulting exe as **Administrator** to apply admin-requiring tweaks
(186 of them need elevation).

## Live updates

New builds are **pushed to users without a reinstall**:

1. Users run the app; at startup and from **Settings → Update → Check for
   Updates** it asks the server if a newer version exists.
2. When a release is newer than the installed build, the user presses
   **Restart & Update** — the app downloads the new exe in the background and
   swaps itself on relaunch.

### Publish an update

```powershell
# one command: bumps version, builds dist\RexTweaks.exe, tags, creates the
# GitHub Release and uploads the exe
.\.\release.ps1 -Version 1.1.0
```

Requirements for publishing:

- `GITHUB_REPO` set in `config/app_config.py` (e.g. `"you/RexTweaks"`).
- A GitHub Personal Access Token in `$env:GITHUB_TOKEN` (scope: `repo`).
- GitHub CLI (`gh`) is **not** required — the script uses `curl`.

The app's update check resolves the **latest release tag** of `GITHUB_REPO`
and downloads the asset named `RexTweaks.exe`. For a custom server instead of
GitHub, set `UPDATE_MANIFEST_URL` to a JSON document:

```json
{ "version": "1.2.0", "url": "https://your-cdn.com/RexTweaks.exe", "notes": "what's new" }
```

Leave `GITHUB_REPO` and `UPDATE_MANIFEST_URL` empty to disable update checks.
The "Open GitHub" sidebar button is controlled by `GITHUB_URL`.

## Project layout

```
config/     app configuration, theme, paths
database/   tweak database (603 tweaks) + action executor
engine/     recommender, bundles, applier, applied-state tracking
hardware/   hardware detection (WMI + psutil)
ui/         PySide6 pages: dashboard, detect, tweaks, optimize, logs
Logs/       rotating rextweaks.log
data/       state.json — tracks which tweaks you applied
```

## Safety notes

- Always create a System Restore Point before applying "Maximum" bundles
  (the bundle does this automatically when you keep the checkbox on).
- Advanced tweaks (Spectre/Meltdown mitigations, memory compression, C-States,
  VBS) can reduce security or stability — they are marked and require an
  explicit opt-in.
- "Guidance" tweaks only print recommendations (they never change the system).
- Reboot after applying for the full effect; all tweaks are revertible.
