# Maximum Tweaks

Detect -> Analyze -> Recommend -> Optimize -> Measure -> Revert

Maximum Tweaks is a Windows system optimizer with a **577-tweak database** across
52 categories (CPU, GPU, RAM, network, power, services, privacy, storage,
audio, input, BIOS, game-specific and more). It detects your hardware, marks
only **compatible** tweaks as ready, and applies/reverts them with one click.

## Features

- **Expandable sidebar navigation** — "Tweaks" expands in the sidebar into
  CPU, GPU, RAM, Mouse, Keyboard, Pointer & Input, Network, Storage, Windows,
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
- **Game Profiles** — one-click per-game performance profiles for 21 titles
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
  - **Balanced** (safe, 14 tweaks) — everyday performance.
  - **Competitive** (24) — minimum input latency for esports.
  - **Maximum** (39) — advanced debloating and latency tuning (security/stability trade-offs).
- **Full revert support** — every tweak ships paired `actions` / `revert` steps;
  an applied-state tracker makes anything you applied one click away from being
  undone.
- **Preview before apply** — see the exact registry keys, services and commands
  a tweak touches before running it.
- **Terminal mode** for scripting (`--cli`).
- Built-in logging (live-viewable in the app) at `Logs/maximumtweaks.log`.

## Requirements

- Windows 10 1903+ or Windows 11
- Python 3.14 (dev only — end users get the `.exe`)

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
pip install -r requirements.txt   # pinned: PySide6==6.11.1, psutil==7.2.2, pyinstaller==6.22.0
python -m PyInstaller MaximumTweaks.spec --noconfirm
# output: dist\MaximumTweaks.exe
```

**The release artifact is built by CI, not by hand.** On every version tag,
`.github/workflows/release.yml` runs the exact command above on `windows-latest`
with Python 3.14 and the pinned `requirements.txt`, then logs the byte size and
SHA-256 of every artifact in the workflow summary. A local build is for testing
only — never upload a locally built exe as a release asset, and never widen the
pinned versions without rebuilding and re-testing.

Run the resulting exe as **Administrator** to apply admin-requiring tweaks
(many of them need elevation).

## Live updates

New builds are **pushed to users without a reinstall**:

1. Users run the app; at startup and from **Settings → Update → Check for
   Updates** it asks the server if a newer version exists.
2. When a release is newer than the installed build, the user presses
   **Restart & Update** — the app downloads the new build in the background
   and installs it: **NSIS installs** (registered in the registry) download
   `MaximumTweaks-Setup-<version>.exe`, verify its SHA-256 and run it
   silently (the installer self-elevates, replaces the Program Files copy
   and relaunches the app); **portable copies** swap the exe in place via a
   batch stub.

### Publish an update

```powershell
# bumps APP_VERSION, regenerates auth_backend\web\update.json, commits both,
# pushes main, tags vX.Y.Z and pushes the tag
.\release.ps1 -Version 2.0.1
```

Pushing the tag triggers the **Release workflow**, which is the single
source of truth for published artifacts: it builds the exe with the pinned
toolchain, compiles the NSIS installer, prints byte sizes + SHA-256 for both
artifacts in the job summary, refuses to release if the update manifest is
missing `installer_url`/checksum fields, and creates the GitHub Release
(marked prerelease when the tag contains `-`).

Requirements for publishing:

- `GITHUB_REPO` set in `config/app_config.py` (e.g. `"you/MaximumTweaks"`).
- An authenticated `git push` to origin (your normal GitHub login). No PAT
  and no token are used by the script — the workflow publishes with its
  built-in `GITHUB_TOKEN`.
- The local build is for smoke tests only; never upload it as a release
  asset. The artifact users download is the CI-built one.

> **Private repos**: if `GITHUB_REPO` is private, you must set the
> `GITHUB_TOKEN` environment variable to a GitHub PAT (scope: `repo`) in the
> running process before launching the app; no secrets are ever embedded in the
> exe or read from `config/_secrets.py`.

The app's update check resolves the **latest release tag** of `GITHUB_REPO`
and downloads the asset named `MaximumTweaks.exe`. For a custom server instead of
GitHub, set `UPDATE_MANIFEST_URL` to a JSON document:

```json
{
  "version": "2.0.1",
  "url": "https://your-cdn.com/MaximumTweaks.exe",
  "notes": "what's new",
  "sha256": "<sha256 of url>",
  "installer_url": "https://your-cdn.com/MaximumTweaks-Setup-2.0.1.exe",
  "installer_checksum_url": "https://your-cdn.com/MaximumTweaks-Setup-2.0.1.exe.sha256"
}
```

`installer_url` / `installer_checksum_url` (or `installer_sha256`) are used
only by NSIS-installed copies; when omitted, every copy uses the exe swap.

Leave `GITHUB_REPO` and `UPDATE_MANIFEST_URL` empty to disable update checks.
The "Open GitHub" sidebar button is controlled by `GITHUB_URL`.

## Project layout

```
config/     app configuration, theme, paths
database/   tweak database (577 tweaks) + action executor
engine/     recommender, bundles, applier, applied-state tracking
hardware/   hardware detection (WMI + psutil)
ui/         PySide6 pages: dashboard, detect, tweaks, optimize, logs
Logs/       rotating maximumtweaks.log
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

## Releasing a new version

1. Update `CHANGELOG.md` with release notes (New / Fixed / Updated).
2. Publish with the script — it bumps `APP_VERSION`, regenerates
   `auth_backend\web\update.json`, commits both, tags `vX.Y.Z` and pushes
   the tag:
   ```powershell
   .\release.ps1 -Version X.Y.Z
   ```
3. Pushing the tag triggers the Release workflow, which verifies the tag
   matches `APP_VERSION` exactly, runs both test suites plus the catalogue
   gate, builds the exe and installer, publishes their hashes
   (`SHA256SUMS.txt` + per-file `.sha256`) and creates the GitHub Release.
4. The in-app updater verifies SHA-256 before installing.
