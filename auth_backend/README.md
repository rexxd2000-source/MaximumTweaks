# REX TWEAKS — Discord Authentication Backend

A small, standalone **FastAPI + Uvicorn** service that owns the Discord OAuth2
flow, the Discord **Client Secret** and the **bot token**, so the desktop app
never sees them.

Verifying adds the user **into** REX TWEAKS server with the `guilds.join`
OAuth scope (they don't need to have joined beforehand) and then assigns them
the **Verified** role. Success is only reported when **both** the server join
AND the role assignment succeed.

## How it works

```
Desktop app  ──open in browser──▶  /auth/discord/login?state=…   (302)
                                    └─▶ Discord OAuth2 consent page
                                           user authorizes
                                           ▼
                                  /auth/discord/callback?code=…&state=…
                                           │  backend validates state,
                                           │  exchanges code (secret stays
                                           │  server-side)
                                           │  1. fetch /users/@me  (identity)
                                           │  2. add user to the server via
                                           │     the OAuth token (guilds.join)
                                           │  3. confirm membership via the bot
                                           │  4. assign Verified role via the bot
                                           │  5. confirm the role stuck
                                           ▼
                          browser: "success, close this tab" page
Desktop app  ◀──poll /auth/discord/status?state=…──  username / id /
                                                      member / verified_role
```

### Endpoints

| Endpoint                     | Purpose                                                        |
|------------------------------|----------------------------------------------------------------|
| `GET /health`                | Health check                                                   |
| `GET /auth/discord/login`    | Registers a login attempt and redirects to Discord             |
| `GET /auth/discord/callback` | Discord redirect; joins the server + assigns the Verified role |
| `GET /auth/discord/status`   | Polled by the desktop app to retrieve the result               |

### OAuth scopes used

- `identify` — Discord user id, username, global name, avatar
- `email` — email address + verified-email flag
- `guilds.join` — lets the backend add the user to the server (they do NOT
  need to be in the server already, and they do NOT need a prior role)

Membership and role checks run through the **bot** (`guilds/members`), so the
user token needs no extra read scopes.

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

   | Variable                | Description                                            |
   |-------------------------|--------------------------------------------------------|
   | `DISCORD_CLIENT_ID`     | Discord application Client ID                          |
   | `DISCORD_CLIENT_SECRET` | Discord application Client Secret (**keep secret**)    |
   | `DISCORD_REDIRECT_URI`  | Public callback URL of this backend (see below)        |
   | `DISCORD_GUILD_ID`      | REX TWEAKS Discord server id                           |
   | `DISCORD_ROLE_ID`       | Verified role id to assign                             |
   | `DISCORD_BOT_TOKEN`     | REX TWEAKS bot token (**keep secret**)                 |

3. Run the server locally:

   ```bash
   python -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```

   → `http://127.0.0.1:8000/health` should return `{"status":"ok"}`.

## Discord Developer Portal

In your application at https://discord.com/developers/applications:

1. **OAuth2 → Redirects** — add **exactly** (no trailing slash):

   ```
   http://127.0.0.1:8000/auth/discord/callback
   ```

   For a real deployment this is `https://your-domain.com/auth/discord/callback`
   and must match `DISCORD_REDIRECT_URI` exactly.
2. **Bot** — create the bot and reveal its token into `.env` as
   `DISCORD_BOT_TOKEN`.
3. Invite the bot to REX TWEAKS server and confirm:
   - it is **in the server** (required for `guilds.join` adds),
   - its role is **above the Verified role** (a bot can only assign roles below
     its own top role),
   - it has the **Manage Roles** permission.

No OAuth scopes need to be preselected in the portal — the backend requests
`identify email guilds.join` at login time.

## Testing

```bash
pip install pytest
python -m pytest
```

The tests mock the Discord API (no live Discord calls) and cover the
join + role-assignment flow including failure paths.

## Desktop application

The desktop app reads one setting — `AUTH_SERVER_URL` in
`config/app_config.py` — and opens
`{AUTH_SERVER_URL}/auth/discord/login?state=…` in the browser, then polls
`/auth/discord/status`. For local development:

```python
AUTH_SERVER_URL = "http://127.0.0.1:8000"
```

Point it at the real HTTPS domain before releasing to other users.

## Security notes

- The Client Secret and Bot token live **only** in the backend `.env` /
  environment. They are never sent to the desktop app and never logged.
- OAuth authorization codes and access tokens are exchanged and discarded
  server-side; nothing sensitive is persisted (in-memory sessions only).
- `state` tokens are random, single-use and expire after 10 minutes
  (CSRF protection).
- Login results are stored in memory keyed by `state` and expire after
  10 minutes.

## Production checklist

- Run behind HTTPS (Caddy/nginx/Traefik) with a real domain.
- Update `DISCORD_REDIRECT_URI` + the portal Redirect to the HTTPS URL.
- Set `AUTH_SERVER_URL` in the desktop app to the same HTTPS origin.
- Keep the bot private (disable the public-bot toggle) and restrict its
  permissions to Manage Roles.
- Optionally set `HOST`/`PORT` via `uvicorn` flags; do not expose the raw
  server publicly without TLS.