# Maximum Tweaks Admin (desktop)

A native, red-and-black desktop panel for managing license keys — no browser
needed. It talks directly to the hosted license backend
(`https://maximumtweaks.onrender.com`), the same service the web admin panel
uses.

## How it works

1. You sign in with the operator `ADMIN_TOKEN` (the one in `auth_backend/.env`).
   The app exchanges it once for the server's **HttpOnly session cookie** and
   never re-sends or stores the raw token.
2. The dashboard shows live totals (total / unused / active / expired /
   revoked), a key generator (count, prefix, duration, customer, note) and a
   searchable license table with copy / revoke / un-revoke / unbind actions.
3. Generated keys copy straight to the clipboard, ready to send to a customer.

A key's duration (1 month / 6 months / lifetime) lives **only in the database
record** — keys never encode it. Prefixes are `MAX` by default (`MAX`,
`REX`, `MTW`… up to 4 letters/digits).

## Run from source

```bash
cd <repo root>
pip install PySide6
python -m admin_desktop.main
```

## Build the shareable EXE

```bash
cd admin_desktop
.\build.ps1
```

This produces **`dist\MaximumTweaksAdmin.exe`** — a single one-file, windowed
executable (no install, no console). Share that one file with anyone who
should manage licenses. They sign in with the admin token.

## Security notes

- The admin token is **not** baked into the EXE — each user signs in with it.
- The app holds the session cookie in memory only and forgets it on sign-out.
- Every request uses the real `/admin/*` server-side auth; the desktop app is
  just an operator UI.
- The server base URL is editable on the login screen (defaults to the live
  server).