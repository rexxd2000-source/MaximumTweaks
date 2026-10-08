# Manual test checklist — installer & release flow

The NSIS installer had **never been compiled or run anywhere** before
`release.yml` took over building it (no release ever carried an installer
asset). This checklist is the evidence trail for proving the flow works.
Automated tests cover the Python side only; everything below needs a real
Windows box or VM.

## Setup

- Clean Windows 10 or 11 VM, snapshot it before the first test.
- Download from the release under test:
  `MaximumTweaks.exe`, `MaximumTweaks-Setup-<version>.exe`, and both
  `.sha256` files.
- For updater tests you need Python on the VM (`py -m http.server`) to
  serve a local manifest.
- Version visibility: the window title and the Settings page both show
  `Maximum Tweaks v<APP_VERSION>` — record what they show after each
  install/update step.

## A. Interactive install (fresh VM)

1. Run `MaximumTweaks-Setup-<version>.exe` → UAC → wizard (welcome →
   folder → install pages).
2. Finish the wizard. The app does **not** auto-launch (by design).
3. Verify:
   - `<folder>\MaximumTweaks.exe` and `Uninstall.exe` exist.
   - Start menu shortcut **and** desktop shortcut exist.
   - `HKCU\Software\Maximum Tweaks` contains `InstallDir` and
     `Version` = `<version>`.
   - `HKLM\Software\Maximum Tweaks\InstallDir` present.
   - Settings → Apps lists "Maximum Tweaks" with the right version
     (64-bit HKLM uninstall key).
4. Launch from the shortcut; title shows the expected version.

## B. Silent install (fresh VM)

1. Elevated command prompt:
   `MaximumTweaks-Setup-<version>.exe /S`
2. Wait for completion (no UI appears). Verify:
   - Files installed **and both shortcuts exist** — regression guard:
     earlier versions Quit before creating shortcuts, so the first silent
     install left a machine with no shortcuts at all.
   - All registry entries from A.
   - The app auto-launched after install.
3. Record: elevation state of the relaunched app (Task Manager → Details →
   Elevated column) and whether a console window flashed.

## C. NSIS → NSIS updater flow (the critical path)

1. Install via A or B. The app must run **from the registered install
   folder** (`HKCU\Software\Maximum Tweaks\InstallDir`) — that is what
   `is_nsis_installed()` keys off to choose the setup path instead of the
   portable exe swap.
2. Stage a local manifest folder on the VM:
   ```json
   {
     "version": "<higher than installed, matching the setup you serve>",
     "notes": "local updater test",
     "url": "http://127.0.0.1:8000/MaximumTweaks.exe",
     "installer_url": "http://127.0.0.1:8000/MaximumTweaks-Setup-<version>.exe",
     "installer_checksum_url": "http://127.0.0.1:8000/MaximumTweaks-Setup-<version>.exe.sha256"
   }
   ```
   Generate the checksum file next to the setup:
   ```powershell
   $h = (Get-FileHash MaximumTweaks-Setup-<version>.exe -Algorithm SHA256).Hash.ToLower()
   "$h  MaximumTweaks-Setup-<version>.exe" | Out-File MaximumTweaks-Setup-<version>.exe.sha256 -Encoding ascii
   ```
   Serve it: `py -m http.server 8000` in that folder.
3. Start the app with the manifest override (read at startup, so set the
   env var **before** launching):
   ```cmd
   set UPDATE_MANIFEST_URL=http://127.0.0.1:8000/update.json
   MaximumTweaks.exe
   ```
   PowerShell: `$env:UPDATE_MANIFEST_URL = "http://127.0.0.1:8000/update.json"`
4. Settings → **Check for updates** → dialog shows the newer version →
   Restart & Update.
5. Verify:
   - download with progress → checksum verified → setup runs silently
     (no wizard appears),
   - app relaunches, window title / Settings show the new version,
     registry `Version` updated,
   - Start menu + desktop shortcuts still exist,
   - no orphaned console window; app is Responding; exactly one process.
6. Record any updater error text verbatim — on checksum mismatch the
   download is deleted by design (fail-closed), the message says so.

## D. Portable exe swap

1. Copy `MaximumTweaks.exe` to any folder that is **not** the NSIS
   install folder and run it with the same `UPDATE_MANIFEST_URL` env var.
2. Check for updates → the exe downloads, verifies, and swaps itself in
   place (a temporary helper does the replacement), then relaunches.
3. Verify the new version displays and `data\updates\` holds no leftover
   staged downloads.

## E. Uninstall

1. Before uninstalling, create `data\keepme.txt` and a file in `Logs\`
   next to the exe.
2. Run both variants:
   - Settings → Apps → Maximum Tweaks → Uninstall (interactive),
   - `<folder>\Uninstall.exe /S` (silent).
3. Verify after each:
   - `MaximumTweaks.exe` and `Uninstall.exe` gone; the install folder is
     removed **unless user files remain** (then it must stay),
   - `data\keepme.txt` and `Logs\` content **survive**,
   - shortcuts gone, `HKCU\Software\Maximum Tweaks` gone, HKLM uninstall
     entry gone.
4. Reinstall from the same setup → works, registry recreated.

## F. Release CI (maintainer machine, no VM needed)

Push a tag and watch the Release workflow:

1. Builds the exe with the pinned toolchain (Python 3.14 + requirements
   pins) — CI output is the authoritative artifact, never a local build.
2. Compiles the installer (`makensis /DVERSION=<tag version>`) — the log
   prints the resolved `makensis` path and fails loudly if missing.
3. Step summary **"Report artifact hashes and sizes"** shows byte size +
   SHA-256 for both artifacts — paste these lines into the release notes
   or the audit report.
4. **Manifest gate**: `auth_backend\web\update.json` must contain
   `installer_url` plus `installer_checksum_url` (or `installer_sha256`),
   or the workflow fails *before* creating the release.
5. Release created with `prerelease: true` for tags containing `-`
   (e.g. `v2.5.3-rc1`), otherwise a stable release; four assets
   (exe + setup, each with `.sha256`).

## Release prep (before pushing a tag)

1. Regenerate the manifest with `release.ps1 -Version <version>` (its
   `Update-Manifest` writes `installer_url` / `installer_checksum_url`
   deterministically from the tag) — or add the fields by hand. The CI
   gate rejects the release otherwise.
2. For **prerelease** tags (`vX.Y.Z-rcN`) do **not** bump the manifest's
   `version`/`url` — they must keep pointing at the current stable build
   so stable users are never offered a prerelease; the installer fields
   may point at the rc assets (they are never fetched while the manifest
   version is unchanged).
3. Commit + push main first, then tag that commit.

## Observations to record for every test

- Screenshot or verbatim text of any dialog/error.
- Elevation state of the app after an updater-driven install.
- Whether a console window flashes during the portable swap.
- Process count and Responding state after each relaunch.
