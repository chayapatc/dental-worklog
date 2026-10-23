#!/usr/bin/env python3
"""Seed a scratch database with a demo user, clinics and work logs.

Used by the sandbox audit flow: Lighthouse needs populated, authenticated views,
not empty ones. Never touches the real database unless you point it there.

    DB_PATH=dental-sandbox.db .venv/bin/python scripts/seed_demo.py
    DB_PATH=dental-sandbox.db .venv/bin/python scripts/seed_demo.py --reset
"""

import argparse
import datetime
import os
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CLINICS = [
    ("Vela Yim", "#38bdf8"),
    ("Smile Family", "#4ade80"),
    ("JK Dental", "#fbbf24"),
    ("Banmai Clinic", "#f472b6"),
]

GOOGLE_ID = "sandbox"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("DB_PATH", "dental-sandbox.db"))
    ap.add_argument("--reset", action="store_true", help="delete existing sandbox data first")
    ap.add_argument("--months", type=int, default=6)
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    # db.init_db() reads DB_PATH at import time, so set it before importing.
    os.environ["DB_PATH"] = str(db_path)

    from db import init_db
    init_db()

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    row = db.execute("SELECT id FROM users WHERE google_id=?", (GOOGLE_ID,)).fetchone()
    if row and args.reset:
        uid = row["id"]
        db.execute("DELETE FROM work_logs WHERE user_id=?", (uid,))
        db.execute("DELETE FROM clinics WHERE user_id=?", (uid,))
        db.execute("DELETE FROM users WHERE id=?", (uid,))
        db.commit()
        row = None

    if row:
        uid = row["id"]
        existing = db.execute(
            "SELECT COUNT(*) FROM work_logs WHERE user_id=?", (uid,)
        ).fetchone()[0]
        if existing:
            print(f"Sandbox data already present ({existing} logs). Use --reset to rebuild.")
            return
    else:
        uid = db.execute(
            "INSERT INTO users (google_id, email, name, avatar_url) VALUES (?,?,?,?)",
            (GOOGLE_ID, "sandbox@local", "Sandbox Dentist", ""),
        ).lastrowid
        db.commit()

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clinic_ids = []
    for name, color in CLINICS:
        cid = db.execute(
            "INSERT INTO clinics (user_id, name, color, deleted, created_at) VALUES (?,?,?,0,?)",
            (uid, name, color, now),
        ).lastrowid
        clinic_ids.append(cid)

    rng = random.Random(42)
    today = datetime.date.today()
    logs = []
    for m in range(args.months):
        month_start = (today.replace(day=1) - datetime.timedelta(days=30 * m)).replace(day=1)
        # Shifts cluster on days 11-31, matching how real data looks.
        for day in sorted(rng.sample(range(11, 29), 8)):
            date = month_start.replace(day=day)
            if date > today:
                continue
            hours = rng.choice([4, 5, 6, 8, 10, 12, 16])
            income = rng.choice([7000, 9000, 11000, 12500, 15000, 18500, 22000, 24850])
            expense = rng.choice([0, 0, 0, 0, 200, 500, 1200])
            logs.append((uid, rng.choice(clinic_ids), date.isoformat(), hours, income, expense, now))

    db.executemany(
        "INSERT INTO work_logs (user_id, clinic_id, date, hours, income, expense, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        logs,
    )
    db.commit()

    print(f"seeded {len(logs)} logs across {len(clinic_ids)} clinics for sandbox user id={uid}")
    print(f"database: {db_path}")
    db.close()


if __name__ == "__main__":
    main()
