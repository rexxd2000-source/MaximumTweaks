# MAXIMUM TWEAKS — License Backend

A small, standalone **FastAPI + Uvicorn** service that owns license validation
for the MAXIMUM TWEAKS desktop app. The desktop app holds **no secrets** and
**cannot generate keys** — it only submits a customer-entered key plus a hashed
device fingerprint and receives a short-lived, HMAC-signed session token back.

## How it works

```
Desktop app ── POST /api/license/activate {key, device_id}
                 └─ validates key format + rate limits
                 └─ binds the key to the device (hardware lock)
                 └─ returns {success, valid, message, session_token,
                             token_exp, license:{key, status, plan, ...}}
                    (HMAC-signed token, TTL)   — or
                    {success:false, valid:false, error, message}

On later launches ── POST /api/license/validate {token, device_id}
                 └─ verifies signature + expiry, checks status
                    (revoked / expired / device mismatch caught here)
                 └─ returns a fresh token
```

All responses — including errors and unmatched routes — are JSON objects with
`success` / `valid` / `error` / `message`; the client never has to unwrap a
`{"detail": ...}` wrapper.

The app caches the token locally for a short **offline grace** period
(`OFFLINE_GRACE_HOURS`, default 24) so it works without internet for a while —
this is *not* a permanent bypass, and the backend remains the authority.

### Public endpoints

| Endpoint                       | Purpose                                                |
|--------------------------------|--------------------------------------------------------|
| `GET /health`                  | Health check                                           |
| `POST /api/license/activate`   | Bind a key to this device; issue a session token     |
| `POST /api/license/validate`   | Verify + refresh a session token                     |
| `POST /api/license/deactivate` | Acknowledge a client-side deactivation               |
| `POST /api/license/checkin`    | Heartbeat (every 5 min): per-PC/day activity + PC-limit enforcement |

### Admin endpoints (Bearer `ADMIN_TOKEN` **or** the HttpOnly `adm` session cookie)

| Endpoint                          | Purpose                                        |
|-----------------------------------|------------------------------------------------|
| `GET /admin`                      | JSON probe (reports `auth`: `discord` or `token`, plus admin names) |
| `GET /admin/me`                   | Login-state probe (cookie/bearer)               |
| `POST /admin/login`               | Exchange `ADMIN_TOKEN` for an HttpOnly `adm` session cookie |
| `POST /admin/logout`              | Clear the session cookie                       |
| `POST /admin/discord/start`       | Begin a Discord sign-in → `{url, state}` for the browser |
| `GET /admin/discord/callback`     | Discord OAuth redirect; allowlist check against `DISCORD_ADMIN_IDS` |
| `GET /admin/discord/poll/{state}` | `waiting`/`ok`/`denied`/`expired`; on `ok` issues the `adm` session cookie |
| `GET /admin/licenses?status=`     | List licenses (filter by status)       |
| `GET /admin/search?q=`            | Search licenses by key / customer / note       |
| `GET /admin/stats`                | Totals by status                                 |
| `POST /admin/generate`            | Generate 1..500 keys (`{count, prefix, duration, plan, customer, note, expires_at}`) |
| `POST /admin/keys`                | Create one key with a plan + PC limit (`{customer, plan: '1m'\|'6m'\|'life', max_pcs: 1..10, note}`) |
| `GET /admin/keys`                 | Admin overview: all keys + per-PC activity aggregates + dashboard stats |
| `GET /admin/keys/{key}/activity`  | 30-day per-PC check-in grid + recent refusals   |
| `DELETE /admin/keys/{key}/pcs/{hwid}` | Free a PC slot immediately                  |
| `DELETE /admin/keys/{key}`        | Permanently delete a license row               |
| `POST /admin/revoke`              | Revoke a key (`{key, reason}`)                |
| `POST /admin/unrevoke`            | Undo a revocation                             |
| `POST /admin/unbind`              | **PC change only**: free a key for a new device |

`duration` is resolved server-side: `1m` → 1-month `monthly` expiry, `6m` →
6-month `custom` expiry, `lifetime` → no expiry. The new mockup-style plans on
`POST /admin/keys` are exact-day based: `1m` = 30 days, `6m` = 180 days,
`life` = never. When `expires_at` is given it wins. `prefix` defaults to
`LICENSE_KEY_PREFIX` (or `MAX`).

**Heartbeat / PC limits.** While the customer app runs it POSTs a check-in
every 5 minutes (`CHECKIN_INTERVAL_S`). The server records one activity row per
key + PC + UTC day and refreshes `last_seen`/`pc_name`. A key allows up to
`max_pcs` distinct PCs within a rolling 30-day window; a PC that goes silent
for 30 days automatically frees its slot. A *new* PC beyond the limit is
refused (its existing PCs keep working) and the attempt is logged to
`key_blocked`, which powers the "X blocked attempts this week" warning in the
admin app — rather than silently displacing an active user.

**Admin UI.** The browser admin panel (`admin_panel.html` at `/admin`) was
removed. Administer licenses from the **native desktop app**
(`../admin_desktop/`, built to `MaximumTweaksAdmin.exe`), which talks to the
JSON endpoints above. Two sign-in paths, chosen by the server:
`auth: "discord"` (preferred) or `auth: "token"`.

With **Discord login**, the desktop app opens the server's authorize URL,
Discord redirects the browser back to `/admin/discord/callback`, the server
checks the account against `DISCORD_ADMIN_IDS`, and the desktop polls
`/admin/discord/poll/{state}` until the handshake completes — the poll
response delivers the HttpOnly `adm` session cookie. The raw `ADMIN_TOKEN`
never reaches the desktop. When Discord is not configured, `/admin` reports
`auth: "token"` and the app falls back to the operator-token box.

Every `/admin/*` API route is independently authenticated server-side with a
constant-time token/cookie check.

There is deliberately **no client-side unbind**: a stolen app copy cannot free
its own license and be re-sold. Support frees a key with `unbind` (or removes a
PC slot with the `DELETE .../pcs/{hwid}` endpoint).

## Setup

1. Install dependencies:

   ```bash
   cd auth_backend
   pip install -r requirements.txt
   ```

2. Create the environment file (fill in real values):

   ```bash
   copy .env.example .env
   ```

   Required variables:

   | Variable            | Description                                             |
   |---------------------|---------------------------------------------------------|
   | `LICENSE_SECRET`    | HMAC token-signing secret (**keep secret**)              |
   | `ADMIN_TOKEN`       | Token for `/admin/*` + panel login (**keep secret**)      |
   | `LICENSE_DB_PATH`   | Path to the SQLite license DB (see Render note below)    |
   | `DATABASE_URL`      | PostgreSQL DSN (Render/Neon). When set, it wins over SQLite |
   | `SESSION_TTL_HOURS` | Session token lifetime (default `72`)                    |
   | `OFFLINE_GRACE_HOURS` | Offline grace after token expiry (default `24`)        |
   | `LICENSE_KEY_PREFIX`| Key prefix, `1-4` letters/digits, default `MAX`          |
   | `ADMIN_SESSION_HOURS` | Admin panel session length (default `12`)             |
   | `TEST_DATABASE_URL` | **Tests only** — dedicated throwaway Postgres, never prod |
   | `DISCORD_CLIENT_ID`     | Discord OAuth application client id (enables Discord admin login) |
   | `DISCORD_CLIENT_SECRET` | Discord OAuth client secret (**keep secret**)                |
   | `DISCORD_ADMIN_IDS`     | Comma-separated Discord user IDs allowed to sign in          |
   | `DISCORD_ADMIN_NAMES`   | Optional `id:Display Name` pairs for friendly labels          |

   Generate the two secrets with:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   python -c "import secrets; print(secrets.token_urlsafe(24))"
   ```

3. Run locally:

   ```bash
   python -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```

   → `http://127.0.0.1:8000/health` should return `{"status":"ok"}`.

## Admin CLI

Works directly against the DB (run it on the machine that owns the DB, e.g.
the Render instance console):

```bash
cd auth_backend
python -m admin generate --count 10 --customer "Alice" --duration lifetime
python -m admin generate --prefix REX --duration 1m --count 5 --customer "Bob"
python -m admin list
python -m admin show MAX-XXXX-XXXX-XXXX
python -m admin revoke MAX-XXXX-XXXX-XXXX --reason "chargeback"
python -m admin unrevoke MAX-XXXX-XXXX-XXXX
python -m admin unbind MAX-XXXX-XXXX-XXXX   # PC change
python -m admin stats
```

`--duration` (1m / 6m / lifetime) mirrors the /admin/generate API and sets the
plan + expiry server-side; an explicit `--expires "YYYY-MM-DD HH:MM:SS"`
overrides it. `--prefix` defaults to `LICENSE_KEY_PREFIX` (MAX).

## Testing

```bash
cd auth_backend
pip install -r requirements-dev.txt
python -m pytest
```

Tests use the FastAPI `TestClient` and a throwaway database — SQLite in a temp
directory by default (no network). If `auth_backend/.env` sets
`TEST_DATABASE_URL` (a dedicated throwaway PostgreSQL, e.g. a
`maximumtweaks_test` database on Neon), the whole suite runs against it
instead. Every test wipes the `licenses` table; never point it at the production
database. The suite promotes `TEST_DATABASE_URL` → `DATABASE_URL` and nothing
else — but note that a bare production `DATABASE_URL` in `.env` would be used
as-is, so always pair it with a throwaway `TEST_DATABASE_URL`.
`test_db_postgres.py` is skipped when no test Postgres is configured.

## Render deployment notes

- Create a **Web Service** from this repo with **Root Directory = `auth_backend`**.
- **Build command**: `pip install -r requirements.txt`
- **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Database**: free-instance filesystems are **ephemeral** — a restart/redeploy
  wipes the DB. Point `DATABASE_URL` at a managed PostgreSQL (e.g. Neon) so
  licenses survive restarts/redeploys. Alternatively attach a **Persistent
  Disk** and set `LICENSE_DB_PATH=/var/data/licenses.db` (or similar on the
  disk), then run `cd auth_backend && python -m admin` from the Render shell
  to generate keys.
- Set `LICENSE_SECRET` and `ADMIN_TOKEN` as Render environment variables,
  never in the repository.
- **Discord admin login** (optional): create an application at
  `https://discord.com/developers/applications`, enable OAuth2, add the redirect
  URI `https://maximumtweaks.onrender.com/admin/discord/callback`, then set
  `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_ADMIN_IDS`
  (`458618658390933507,924289061907218462`) and optionally
  `DISCORD_ADMIN_NAMES` in the Render environment. Until they are set, the
  server keeps reporting `auth: "token"` and the desktop app shows the
  operator-token box.
- The desktop app talks to the same HTTPS origin (`LICENSE_API_URL` in
  `config/app_config.py`), default `https://maximumtweaks.onrender.com`.
- After deploy, `GET /health` must return `{"status":"ok"}` — the app refuses
  keys when the license service is unreachable.

## Security notes

- `LICENSE_SECRET` and `ADMIN_TOKEN` live **only** in the backend environment.
  Nothing is bundled into the desktop EXE.
- Keys are generated with `secrets` and formatted `PREFIX-XXXX-XXXX-XXXX` where
  `PREFIX` is `LICENSE_KEY_PREFIX` (default `MAX`, e.g. `MAX-XXXX-XXXX-XXXX`, 60
  bits of entropy). Keys never encode their plan/duration — that lives in the DB
  record only. Unknown keys return a generic `INVALID_KEY` (no enumeration).
- Activation attempts are rate-limited per key and per IP.
- Tokens are short-lived, stateless, HMAC-SHA256 signed; the device hash is
  the only device identifier the backend ever sees.
