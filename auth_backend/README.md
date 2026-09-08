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

| Endpoint                    | Purpose                                                |
|-----------------------------|--------------------------------------------------------|
| `GET /health`               | Health check                                           |
| `POST /api/license/activate`  | Bind a key to this device; issue a session token     |
| `POST /api/license/validate`  | Verify + refresh a session token                     |
| `POST /api/license/deactivate`| Acknowledge a client-side deactivation               |

### Admin endpoints (Bearer `ADMIN_TOKEN`)

| Endpoint            | Purpose                                        |
|---------------------|------------------------------------------------|
| `GET /admin/licenses?status=` | List licenses (filter by status)       |
| `GET /admin/search?q=`  | Search licenses by key / customer / note       |
| `GET /admin/stats`  | Totals by status                                 |
| `POST /admin/generate` | Generate 1..500 keys (`{count, plan, customer, note, expires_at}`) |
| `POST /admin/revoke`   | Revoke a key (`{key, reason}`)                |
| `POST /admin/unrevoke` | Undo a revocation                             |
| `POST /admin/unbind`   | **PC change only**: free a key for a new device |

There is deliberately **no client-side unbind**: a stolen app copy cannot free
its own license and be re-sold. Support frees a key with `unbind`.

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
   | `ADMIN_TOKEN`       | Bearer token for `/admin/*` (**keep secret**)            |
   | `LICENSE_DB_PATH`   | Path to the SQLite license DB (see Render note below)    |
   | `SESSION_TTL_HOURS` | Session token lifetime (default `72`)                    |
   | `OFFLINE_GRACE_HOURS` | Offline grace after token expiry (default `24`)        |

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
python -m admin generate --count 10 --customer "Alice"
python -m admin list
python -m admin show MAX-XXXX-XXXX-XXXX
python -m admin revoke MAX-XXXX-XXXX-XXXX --reason "chargeback"
python -m admin unrevoke MAX-XXXX-XXXX-XXXX
python -m admin unbind MAX-XXXX-XXXX-XXXX   # PC change
python -m admin stats
```

## Testing

```bash
cd auth_backend
pip install -r requirements-dev.txt
python -m pytest
```

Tests use a throwaway SQLite DB and the FastAPI `TestClient` (no network).

## Render deployment notes

- Create a **Web Service** from this repo with **Root Directory = `auth_backend`**.
- **Build command**: `pip install -r requirements.txt`
- **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Free-instance filesystems are **ephemeral** — a restart/redeploy wipes the
  DB. Attach a **Persistent Disk** to the service and set
  `LICENSE_DB_PATH=/var/data/licenses.db` (or similar on the disk), then run
  `cd auth_backend && python -m admin` from the Render shell to generate keys.
- Set `LICENSE_SECRET` and `ADMIN_TOKEN` as Render environment variables,
  never in the repository.
- The desktop app talks to the same HTTPS origin (`LICENSE_API_URL` in
  `config/app_config.py`), default `https://maximumtweaks.onrender.com`.
- After deploy, `/health` must report the license service — the app will
  refuse keys while the old Discord-auth backend is live.

## Security notes

- `LICENSE_SECRET` and `ADMIN_TOKEN` live **only** in the backend environment.
  Nothing is bundled into the desktop EXE.
- Keys are generated with `secrets` and formatted `MAX-XXXX-XXXX-XXXX`
  (60 bits). Unknown keys return a generic `INVALID_KEY` (no enumeration).
- Activation attempts are rate-limited per key and per IP.
- Tokens are short-lived, stateless, HMAC-SHA256 signed; the device hash is
  the only device identifier the backend ever sees.
