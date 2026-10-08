# Changelog

## v2.5.3 — 2026-10-08

### New
- **Discord sign-in for end users**: login, automatic guild join, staff
  audit line, membership verification (no more trusting a bare 2xx), and
  honest failure screens when a token, guild or bot is misconfigured.
- **Ultra Mode waitlist**: join from the dashboard and send the launch
  email through Resend or SMTP (with deliverability headers, verified
  from-address and per-IP rate limits).
- **License gate screens**: real-time banned / revoked / suspended states
  with full-height cards, wrapped text, elapsed session time and a working
  ban-appeal link.
- **Catalogue release gate** (`tools/audit_tweak_db.py`): schema, duplicate,
  conflict, safety and drift checks that now run in CI before any release.
- **Anti-cheat guard tests**: Fortnite tweaks are provably confined to
  `GameUserSettings.ini`, the fn-* section membership is pinned, and any
  tweak naming an anti-cheat service fails the suite.
- **Release pipeline hardening**: CI now verifies tag == `APP_VERSION`,
  runs both test suites + drift + catalogue gates, smoke-tests the frozen
  exe, and publishes `SHA256SUMS.txt` alongside per-file `.sha256` assets.
- Splash never blocks boot on a slow update check (Skip button + stall
  deadline); update-manifest fetch retries cold-start timeouts.

### Fixed
- **`--dry-run` after `apply`/`revert` was silently ignored** — the CLI
  parsed it as an unknown argument and ran the real apply. Dry-run now
  previews without touching the system (regression-tested).
- **Reverting a service silently changed its startup type**: `sc qc`
  backups (`AUTO_START`/`DEMAND_START`/…) were fed to a mapper that
  defaulted to Manual, so an automatic service (seen live: SysMain) came
  back as Manual. All six tokens now round-trip to their original type.
- **Console window flashed on every GUI launch** — frozen GUI launches now
  hide their console; the CLI keeps its console (exit codes intact).
- Unknown-tier executable detection actually fires again (license tiers).
- Logging: unknown-id, dry-run and blocked results are written to the log
  with tweak id, name, action and result (they used to bypass it).
- Catalogue: 18 duplicate tweaks consolidated (595 → 577) and all 19
  pending REWRITE decisions resolved to KEEP with explicit conflict
  resolutions — every id now appears exactly once.
- Validation-drift check audits the shipped catalogue instead of the
  caller's sample list (no more phantom "stale overrides").
- Publish flow is fully de-tokenized (no PAT anywhere; CI publishes with
  its built-in `GITHUB_TOKEN`), prerelease-safe manifest regeneration, and
  the workflow refuses to release without installer fields.
- NSIS: compiles on stock choco NSIS (no third-party plugins), registers
  in HKLM, shortcuts survive silent installs, uninstaller preserves
  `data\`/`Logs\`, and the unused `BrandingText` warning is gone.
- README "Releasing a new version" section was literal `\n` escape text —
  rewritten to match the real `release.ps1` flow.

### Updated
- Version bump to **2.5.3** everywhere (`APP_VERSION`, NSIS fallback,
  update manifest regenerated at release cut).
- Pinned build toolchain (Python 3.14 + exact PySide6/pyinstaller/psutil)
  with CI as the single source of truth for published artifacts.
- Security pass: no secrets anywhere in tree, history or commit messages;
  `.env` stays ignored/untracked and is byte-verified absent from the exe;
  admin Discord IDs and a hardcoded local user path removed from tracked
  files.
- Manual test checklist rewritten around the real installer/CI flow.
