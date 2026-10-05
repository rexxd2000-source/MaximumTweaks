# MaximumTweaks — Investigation & Utility Scripts

This folder is the tooling for the **500 → 60 → 500 FPS collapse investigation**
(intermittent, severe FPS dropout with recovery, seen after applying Maximum
Optimizations), plus standalone NVIDIA utilities. Everything here is optional —
none of it is required to use the app.

## TL;DR of the investigation outcome

- The undocumented **GPU PowerMizer registry writes** (`fpsb-004` and the
  similar `nv-003` / `wgr-007` family) were removed from every apply path and
  `fpsb-004` is now **guidance only**: it points you at the vendor-supported
  NVIDIA Control Panel profile (Power management mode → *Prefer maximum
  performance*) instead of writing `PerfLevelSrc` / `PowerMizerLevel*` under
  the NVIDIA class key, which is driver-version dependent, a classic cause of
  temporary GPU **clock collapse** on the driver generations that honor them,
  and was hard-coded to a `\0000` display-adapter instance that is not
  reliable across PCs.
- The **timer-resolution cluster** was merged into a single optional
  **diagnostic** (`perf-001`). `power-017`, `fpsb-018` and `cpu:timer_resolution`
  were removed because they all overlapped: the three wrote the same
  `GlobalTimerResolutionRequests=1` flag, and the fourth forced an
  undocumented `GlobalTimerResolution` — yet none of them actually force a
  0.5 ms timer, so the old latency claims oversold what the registry actions
  do. `perf-001` now says exactly that and is marked optional.
- The conflict detector is now **sound**: it reports *every* disagreeing pair
  (many-to-many) instead of only the first writer, and the DB declares
  *semantic* conflicts that different key names/paths hide from the value-based
  detector. Re-run the smoke harness after any DB change to re-check.

What this means practically: the app no longer offers PowerMizer registry
writes, and the timer-resolution area is one honest optional diagnostic
instead of four overlapping claims.

## The workflow (run on the gaming PC)

1. **Baseline (clean)**: reboot to a known state. Apply *nothing*.
2. Run `A-B-Harness.ps1` (calls `Baseline-Capture.ps1` + `Register-Diff.ps1`).
   It captures actual Windows state, tells you to apply **one tweak**, run a
   fixed Fortnite benchmark, then revert and benchmark again, then diffs all
   three snapshots.
3. Feed the benchmark frametime logs into
   `frametime_regression_test.py --baseline base.csv --compare tweak.csv`.
4. For deep tracing, run `ETW-Capture.ps1` and look at the GPU/driver +
   game-thread scheduler rows in WPA during a collapse window.

### Recommended format for a fixed benchmark

- Same map/replay, same route, same settings, ~2–3 minutes.
- Capture frametime CSV (RivaTuner/CapFrameX/PresentMon), not just an FPS
  counter — collapses are invisible in an average.
- Record avg FPS, 1% low, 0.1% low, max frametime per run.
- Test **one tweak at a time**, always returning to the clean baseline between
  tweaks (reboot where HKLM/services/driver settings are involved).

## Scripts

### `A-B-Harness.ps1`
Interactive one-tweak test loop. Options: `-SnapshotDir`, `-TweakId`,
`-BaselineLabel`. Produces `snapshots\baseline/applied/reverted-*` and
`diff-*.txt` files.

### `Baseline-Capture.ps1`
Captures the exact registry values/services/power plan/boot flags/scheduled
tasks the app is able to change. Every capture includes a `restore.ps1` that
re-imports the exact `.reg` backups, service start modes, and the exported
power plan (`active-power-scheme.pow`) — so a baseline is genuinely restorable,
not just inspectable. `-RegistryOnly` skips services/power/tasks.

### `Register-Diff.ps1`
`-Before <snapshot>` `-After <snapshot>` - diffs `reg_values.txt` (added /
removed / changed), and service start/state lines.

### `ETW-Capture.ps1`
WPR wrapper (`-Profiles "CPU GPU Power"`). Start → reproduce the collapse →
stop. Opens a `.etl` for Windows Performance Analyzer. Use it to check whether
a collapse window coincides with a service wake-up, a DPC storm, or a GPU
clock drop.

### `frametime_regression_test.py`
Compares a baseline and a with-tweak frametime CSV with **relative** thresholds
only (nothing hardcoded at 60 FPS): mean-FPS drop ratio, hitch ratio, and
sliding-window collapse detection (`--window`, `--mean-drop`, `--hitch-ratio`).
Exit code 1 = regression detected (usable in CI/harnesses). Use `--baseline`
and `--compare` CSV paths; auto-detects CapFrameX / PresentMon / plain
frametime columns. `--json` writes a machine-readable summary.

## NVIDIA utilities

These are **standalone, optional, and conservative**. The app itself never
touches NVIDIA Control Panel or writes undocumented driver keys.

### `Revert-FPS-Collapse.bat`

Standalone undo for anyone who already applied the collapse-causing tweaks
(themselves or via an older app build): deletes the GPU PowerMizer values
(`PerfLevelSrc`, `PowerMizerLevel*`, `PowerMizerEnable`) and the
timer-resolution overrides (`GlobalTimerResolutionRequests`,
`GlobalTimerResolution`, `TimerResolution`), returning them to
Windows/driver defaults. Backs up the pre-state to
`nvidia-backups\collapse-revert-<timestamp>\` first, verifies each value,
counts removed/errors, and reports which were already absent. Requires
Administrator; a reboot is advised afterwards. Safe to run even when nothing
was ever applied.

### `NVIDIA-Control-Panel-Optimize.bat` / `-Restore.bat`

- Detects the GPU + driver (exits cleanly if no NVIDIA GPU or no `nvidia-smi`).
- Backs up the pre-change `nvidia-smi` state.
- Applies exactly **one documented** change: GPU **persistence mode** (`nvidia-smi
  -pm 1`), verifies it, and the Restore script reverts to the exact previous
  mode (or the system default when no backup exists).
- It deliberately does **not** write the undocumented 3D-profile registry keys.
  NVCP 3D settings (Power Management Mode → Prefer maximum performance, Low
  Latency Mode, Texture Filtering) are applied in the **NVIDIA Control Panel
  UI** by you; the script prints the checklist.

### `NVIDIA-GPU-MSI-Enable.bat` / `-Restore.bat`

- **Advanced, not a guaranteed FPS gain.** Message-Signaled Interrupts can
  lower CPU interrupt overhead per frame, but results vary by driver/hardware.
- The `.bat` files are thin launchers (admin check + pause); the work happens
  in the sidecar `NVIDIA-GPU-MSI-Enable.ps1` / `-Restore.ps1`, which discover
  NVIDIA devices via `Get-PnpDevice -Class Display` matching `VEN_10DE` — no
  hardcoded device path, and no batch-file `&`-escaping issues with driver
  bus IDs like `PCI\VEN_10DE&DEV_...`.
- If the target already uses MSI (`MSISupported=1`) it reports and does
  nothing; otherwise the exact prior `MessageSignaledInterruptProperties`
  subtree (values and kinds) is written to
  `nvidia-backups\msi-<timestamp>\` as a `.reg` restore file *before* the
  change — or a deletion directive when the key did not exist, so "absent"
  state restores exactly. The write is verified by re-reading the value; on
  mismatch the backup is imported back.
- Restore imports the newest backup folder that contains `.reg` files (empty
  folders are ignored) and refuses to guess if no backup exists.
- A **reboot is required** after enabling. Verify with GPU-Z / Device Manager
  (Details → Interrupt Requested) before judging FPS.

## Files produced

| Path | Contents |
|---|---|
| `snapshots\capture-*` | full baseline/applied/reverted snapshots |
| `nvidia-backups\opt-*` | pre-change persistence-mode state |
| `nvidia-backups\msi-*` | pre-change interrupt registry backups |
| `nvidia-backups\collapse-revert-*` | pre-revert GPU/timer tweak state |
| `diff-*.txt` | before/after diffs from `Register-Diff.ps1` |
| `trace-*.etl` | WPR traces from `ETW-Capture.ps1` |

## Keeping in sync with the app DB

The script target lists mirror `database/tweaks`. If a new tweak writes a
registry value/power setting/service not listed here, add it to
`Baseline-Capture.ps1` so future captures still cover the full app surface.
Full detail on each tweak and the conflict map: see
`report-500-60-500.md` in this folder.