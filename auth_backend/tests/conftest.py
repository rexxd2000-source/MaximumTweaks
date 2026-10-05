"""Test isolation: the suite must NEVER touch Neon or the real licenses.db.

``LicenseDB.__init__`` prefers ``DATABASE_URL``, and ``main.py`` calls
``load_dotenv()`` at import time. Without the guard below, running the Discord
tests silently created accounts (``42``, ``999``, ``1``, ``2``) and audit rows
in the production Neon database, plus a wall of DISCORD_LINKED spam.

python-dotenv does not override variables that already exist in
``os.environ``, so pinning the empty strings here - before any test module
imports ``main`` - wins over whatever ``.env`` says.
"""

import os
import tempfile
import pathlib

# --- pin an isolated SQLite file BEFORE main/db are imported ---------------
# ``.env`` sets BOTH DATABASE_URL and TEST_DATABASE_URL to the same Neon
# production database, and every test module does:
#     if os.environ.get("TEST_DATABASE_URL"): os.environ["DATABASE_URL"] = ...
# which silently pointed the whole suite at production. TEST_DATABASE_URL must
# therefore be blanked, not pointed at a path (a non-URL value makes psycopg
# raise "missing = after C:\...").
_ISOLATED_DB = pathlib.Path(tempfile.gettempdir()) / "maximumtweaks_TESTS.db"
os.environ["DATABASE_URL"] = ""          # empty -> sqlite engine
os.environ["TEST_DATABASE_URL"] = ""     # keep the opt-in Postgres tests off
os.environ["LICENSE_DB_PATH"] = str(_ISOLATED_DB)

# Never let a test fire real HTTP at Discord or a mail server.
os.environ.setdefault("WAITLIST_RESEND_API_KEY", "")
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("SMTP_USER", "")
os.environ.setdefault("SMTP_PASS", "")

try:
    if _ISOLATED_DB.exists():
        _ISOLATED_DB.unlink()
except OSError:
    pass


def pytest_report_header(config):
    return ("database isolation: sqlite -> %s "
            "(DATABASE_URL forced empty, Neon unreachable)" % _ISOLATED_DB)


def pytest_sessionfinish(session, exitstatus):
    """Delete the throwaway database once the run is done."""
    try:
        if _ISOLATED_DB.exists():
            _ISOLATED_DB.unlink()
    except OSError:
        pass