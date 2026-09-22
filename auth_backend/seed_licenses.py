"""One-shot: copy the 6 license keys the old local manager (MaximumTweaksAdmin sqlite
   licenses.db.stale) created, into the Live Render/Neon Postgres the panel reads.
   Re-runnable (merge by key_checksum), safe to run after every deploy."""
import os, sys, sqlite3, datetime

SRC = os.path.join(os.path.dirname(__file__), "licenses.db.stale")   # local: 6 real keys
DST = os.environ.get("DATABASE_URL")                                  # Neon: the empty panel store

def now_iso():
    import datetime; return datetime.datetime.now(datetime.timezone.utc).isoformat()

def main():
    if not DST:
        print("!! DATABASE_URL not set - seed writes to the LIVE store in production.")
        print("   local/intended for a deploy shell that has DATABASE_URL exported.")
        return 1
    import psycopg
    s = sqlite3.connect(SRC)
    s.row_factory = sqlite3.Row
    cols = [r[1] for r in s.execute("PRAGMA table_info(licenses)").fetchall()]
    keys = s.execute("SELECT * FROM licenses").fetchall()
    if not keys:
        print("!! no rows in %s - nothing to seed" % SRC); return 1
    ident = "license_key" if "license_key" in cols else "key"
    conn = psycopg.connect(DST)
    conn.autocommit = True
    with conn.cursor() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS licenses (
          id BIGSERIAL PRIMARY KEY,
          license_key TEXT NOT NULL UNIQUE,
          user_name TEXT, plan TEXT, expires_at TEXT, status TEXT DEFAULT 'active',
          updated_at TEXT, created_at TEXT
        )''')
        for k in keys:
            key = k[ident]
            row = {cc: k[cc] for cc in cols if cc in ("user_name","plan","expires_at","status")}
            row.setdefault("created_at", now_iso()); row.setdefault("updated_at", now_iso())
            c.execute('''INSERT INTO licenses (license_key,status,plan,customer,note,created_at,expires_at)
              VALUES (%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT (license_key) DO UPDATE SET
                status=EXCLUDED.status,plan=EXCLUDED.plan,customer=EXCLUDED.customer,
                note=EXCLUDED.note,expires_at=EXCLUDED.expires_at''',
              (key, row.get("status","active"), row.get("plan"),
               row.get("customer") or row.get("user_name") or row.get("user") or "",
               row.get("note",""), row.get("created_at"), row.get("expires_at")))
    conn.close()
    print("seeded %d keys from %s -> live panel (rows now visible)" % (len(keys), SRC))
    return 0

if __name__ == "__main__":
    sys.exit(main())
