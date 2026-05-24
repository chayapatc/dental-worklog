"""Database connection, teardown, and migration runner."""

import sqlite3
from pathlib import Path
from flask import g

DATABASE = "dental.db"


def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
    return db


def close_db(exception=None):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def init_db():
    """Run pending migrations from migrations/ directory. Idempotent and safe."""
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys=ON")

    # Ensure migration tracking table exists (always safe — idempotent)
    db.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # Get already-applied migrations
    applied = {r[0] for r in db.execute("SELECT name FROM _migrations").fetchall()}

    # Discover migration files
    migrations_dir = Path(__file__).parent / "migrations"
    if not migrations_dir.is_dir():
        db.close()
        return

    files = sorted(migrations_dir.glob("*.sql"))

    for f in files:
        if f.name in applied:
            continue

        sql = f.read_text()

        # ── Special handling for legacy column migration ──────────────
        if f.name == "002_legacy_user_migration.sql":
            cols_clinics = {r[1] for r in db.execute("PRAGMA table_info(clinics)").fetchall()}
            cols_logs = {r[1] for r in db.execute("PRAGMA table_info(work_logs)").fetchall()}
            if "user_id" not in cols_clinics:
                db.execute("INSERT OR IGNORE INTO users (google_id, email, name) VALUES ('legacy','','Legacy User')")
                legacy_id = db.execute("SELECT id FROM users WHERE google_id='legacy'").fetchone()[0]
                db.execute(f"ALTER TABLE clinics ADD COLUMN user_id INTEGER DEFAULT {legacy_id}")
                db.execute("UPDATE clinics SET user_id=? WHERE user_id IS NULL", (legacy_id,))
            if "user_id" not in cols_logs:
                db.execute("ALTER TABLE work_logs ADD COLUMN user_id INTEGER DEFAULT 0")
                db.execute("""
                    UPDATE work_logs SET user_id = (
                        SELECT COALESCE(c.user_id, 1) FROM clinics c WHERE c.id = work_logs.clinic_id
                    )
                """)
                db.execute("UPDATE work_logs SET user_id=(SELECT id FROM users WHERE google_id='legacy') WHERE user_id=0")

        # Run the SQL (idempotent — uses IF NOT EXISTS / OR IGNORE)
        db.executescript(sql)

        # Record that this migration was applied
        db.execute("INSERT INTO _migrations (name) VALUES (?)", (f.name,))
        db.commit()

    db.close()
