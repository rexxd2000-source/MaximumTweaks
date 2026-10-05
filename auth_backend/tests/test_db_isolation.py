"""The test suite must never write to production (Neon) or the real DB file.

These fixtures (``42``, ``999``, ``1``, ``2``) previously leaked into the
Neon database every time the Discord tests ran.
"""
import os
import pathlib
import tempfile


def test_database_url_is_forced_empty():
    assert os.environ.get("DATABASE_URL", "") == "", \
        "tests must run on sqlite; DATABASE_URL must be blank"


def test_test_database_url_is_blanked():
    """Otherwise every test module copies it into DATABASE_URL and the whole
    suite runs against Neon. A non-URL value is worse: psycopg raises."""
    assert os.environ.get("TEST_DATABASE_URL", "").strip() == "", \
        "TEST_DATABASE_URL must be blank during the normal test run"


def test_license_db_points_at_a_temp_file():
    p = os.environ.get("LICENSE_DB_PATH", "")
    assert p, "LICENSE_DB_PATH must be pinned for tests"
    tmp = pathlib.Path(tempfile.gettempdir()).resolve()
    assert tmp in pathlib.Path(p).resolve().parents, \
        f"tests would write outside the temp dir: {p}"


def test_license_db_is_not_the_real_database():
    p = pathlib.Path(os.environ.get("LICENSE_DB_PATH", "")).name
    assert p != "licenses.db", "tests must not write to the real licenses.db"


def test_license_db_reports_sqlite_not_postgres():
    import sys, os as _os
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    for m in ("db", "main"):
        sys.modules.pop(m, None)
    import db
    d = db.LicenseDB()
    assert d._engine == "sqlite", \
        f"expected sqlite, got {d._engine!r} - tests are hitting a real database"


def test_no_production_rows_are_created():
    """Run the discord fixtures, then assert they land in the temp DB only."""
    import sys, os as _os, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    for m in ("db", "main"):
        sys.modules.pop(m, None)
    import db
    d = db.LicenseDB()
    d.create_discord_account("42", "tester")
    assert d.get_discord_account_by_discord_id("42") is not None

    prod = pathlib.Path(__file__).resolve().parent.parent / "licenses.db"
    if prod.exists():
        import sqlite3
        con = sqlite3.connect(str(prod))
        try:
            n = con.execute("SELECT COUNT(*) FROM discord_accounts "
                            "WHERE discord_id='42'").fetchone()[0]
        except sqlite3.OperationalError:
            n = 0
        finally:
            con.close()
        assert n == 0, "fixture leaked into the real licenses.db"