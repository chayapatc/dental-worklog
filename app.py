#!/usr/bin/env python3
"""Dental Worklog — Flask + SQLite + Google OAuth."""

import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, jsonify, redirect, request, render_template, session, url_for
from authlib.integrations.flask_client import OAuth

load_dotenv()  # load .env file into os.environ

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
DATABASE = "dental.db"

# ── OAuth Config ─────────────────────────────────────────────────────────
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# ── Database ─────────────────────────────────────────────────────────────
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
    return db


@app.teardown_appcontext
def close_db(exception):
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


# ── Auth Helpers ─────────────────────────────────────────────────────────
def login_required(f):
    """Decorator: return 401 JSON if not logged in."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated


def current_user_id():
    return session.get("user_id")


# ── Auth Routes ──────────────────────────────────────────────────────────
@app.route("/api/me")
def api_me():
    """Return current user info or null."""
    uid = current_user_id()
    if not uid:
        return jsonify(None)
    db = get_db()
    row = db.execute("SELECT id, email, name, avatar_url FROM users WHERE id=?", (uid,)).fetchone()
    return jsonify(dict(row)) if row else jsonify(None)


@app.route("/auth/login")
def auth_login():
    if not google.client_id:
        return "Google OAuth not configured — set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET", 500
    redirect_uri = url_for("auth_callback", _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route("/auth/callback")
def auth_callback():
    token = google.authorize_access_token()
    userinfo = token.get("userinfo")
    if not userinfo:
        return "Failed to get user info from Google", 400

    google_id = userinfo["sub"]
    email = userinfo.get("email", "")
    name = userinfo.get("name", email)
    avatar = userinfo.get("picture", "")

    db = get_db()
    row = db.execute("SELECT id FROM users WHERE google_id=?", (google_id,)).fetchone()
    if row:
        # Existing user — update profile
        db.execute(
            "UPDATE users SET email=?, name=?, avatar_url=? WHERE id=?",
            (email, name, avatar, row["id"]),
        )
        user_id = row["id"]
    else:
        # New user
        cur = db.execute(
            "INSERT INTO users (google_id, email, name, avatar_url) VALUES (?,?,?,?)",
            (google_id, email, name, avatar),
        )
        user_id = cur.lastrowid
    db.commit()

    session["user_id"] = user_id
    return redirect("/")


@app.route("/auth/logout")
def auth_logout():
    session.clear()
    return redirect("/")


# ── SPA Entry ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


# ── Clinics API ──────────────────────────────────────────────────────────
@app.route("/api/clinics", methods=["GET"])
@login_required
def list_clinics():
    db = get_db()
    rows = db.execute(
        "SELECT id, name, color FROM clinics WHERE user_id=? AND deleted=0 ORDER BY name",
        (current_user_id(),),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/clinics", methods=["POST"])
@login_required
def create_clinic():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    color = data.get("color", "#38bdf8").strip()
    if not name:
        return jsonify({"error": "Clinic name is required"}), 400
    try:
        db = get_db()
        cur = db.execute(
            "INSERT INTO clinics (user_id, name, color) VALUES (?,?,?)",
            (current_user_id(), name, color),
        )
        db.commit()
        return jsonify({"id": cur.lastrowid, "name": name, "color": color}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Clinic already exists"}), 409


@app.route("/api/clinics/<int:clinic_id>", methods=["PUT"])
@login_required
def update_clinic(clinic_id):
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    color = data.get("color", "").strip()
    if not name:
        return jsonify({"error": "Clinic name is required"}), 400

    db = get_db()
    uid = current_user_id()
    row = db.execute(
        "SELECT id FROM clinics WHERE id=? AND user_id=? AND deleted=0",
        (clinic_id, uid),
    ).fetchone()
    if not row:
        return jsonify({"error": "Clinic not found"}), 404

    try:
        if color:
            db.execute("UPDATE clinics SET name=?, color=? WHERE id=?", (name, color, clinic_id))
        else:
            db.execute("UPDATE clinics SET name=? WHERE id=?", (name, clinic_id))
        db.commit()
        return jsonify({"id": clinic_id, "name": name, "color": color or None})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Clinic name already exists"}), 409


@app.route("/api/clinics/<int:clinic_id>", methods=["DELETE"])
@login_required
def delete_clinic(clinic_id):
    db = get_db()
    uid = current_user_id()
    row = db.execute(
        "SELECT id FROM clinics WHERE id=? AND user_id=? AND deleted=0",
        (clinic_id, uid),
    ).fetchone()
    if not row:
        return jsonify({"error": "Clinic not found"}), 404

    db.execute("UPDATE clinics SET deleted=1 WHERE id=?", (clinic_id,))
    db.commit()
    return jsonify({"deleted": True})


# ── Work Logs API ───────────────────────────────────────────────────────
@app.route("/api/logs", methods=["GET"])
@login_required
def list_logs():
    db = get_db()
    uid = current_user_id()
    clinic_id = request.args.get("clinic_id")

    query = """
        SELECT wl.id, wl.date, wl.hours, wl.income, wl.clinic_id, c.name AS clinic_name
        FROM work_logs wl
        JOIN clinics c ON wl.clinic_id = c.id
        WHERE wl.user_id = ?
    """
    params = [uid]
    if clinic_id:
        query += " AND wl.clinic_id = ?"
        params.append(int(clinic_id))
    query += " ORDER BY wl.date DESC LIMIT 200"

    rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/logs", methods=["POST"])
@login_required
def create_log():
    data = request.get_json(force=True)
    clinic_id = data.get("clinic_id")
    date = data.get("date")
    hours = data.get("hours")
    income = data.get("income")

    errors = []
    if not clinic_id:
        errors.append("clinic_id is required")
    if not date:
        errors.append("date is required")
    if hours is None or hours <= 0:
        errors.append("hours must be > 0")
    if income is None or income < 0:
        errors.append("income must be >= 0")
    if errors:
        return jsonify({"error": ", ".join(errors)}), 400

    db = get_db()
    uid = current_user_id()
    cur = db.execute(
        "INSERT INTO work_logs (user_id, clinic_id, date, hours, income) VALUES (?,?,?,?,?)",
        (uid, int(clinic_id), date, float(hours), float(income)),
    )
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.route("/api/logs/<int:log_id>", methods=["DELETE"])
@login_required
def delete_log(log_id):
    db = get_db()
    uid = current_user_id()
    row = db.execute(
        "SELECT id FROM work_logs WHERE id=? AND user_id=?",
        (log_id, uid),
    ).fetchone()
    if not row:
        return jsonify({"error": "Log entry not found"}), 404

    db.execute("DELETE FROM work_logs WHERE id=?", (log_id,))
    db.commit()
    return jsonify({"deleted": True})


# ── Reports API ──────────────────────────────────────────────────────────
def _parse_date(d):
    if isinstance(d, datetime):
        return d
    try:
        return datetime.strptime(d, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _week_start(d):
    dt = _parse_date(d)
    return (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d") if dt else None


def _month_start(d):
    dt = _parse_date(d)
    return dt.strftime("%Y-%m") if dt else None


@app.route("/api/reports/ranking")
@login_required
def ranking_report():
    period = request.args.get("period", "weekly")
    db = get_db()
    uid = current_user_id()

    rows = db.execute("""
        SELECT wl.date, wl.hours, wl.income, c.name AS clinic_name, wl.clinic_id, c.color
        FROM work_logs wl
        JOIN clinics c ON wl.clinic_id = c.id
        WHERE wl.user_id = ?
        ORDER BY wl.date DESC
    """, (uid,)).fetchall()

    groups = {}
    for r in rows:
        bucket = _week_start(r["date"]) if period == "weekly" else _month_start(r["date"])
        if bucket is None:
            continue
        key = (bucket, r["clinic_id"])
        if key not in groups:
            groups[key] = {"period": bucket, "clinic_id": r["clinic_id"],
                           "clinic_name": r["clinic_name"], "color": r["color"],
                           "total_hours": 0, "total_income": 0}
        groups[key]["total_hours"] += r["hours"]
        groups[key]["total_income"] += r["income"]

    result = []
    for g in groups.values():
        rate = round(g["total_income"] / g["total_hours"], 2) if g["total_hours"] > 0 else 0
        g["hourly_rate"] = rate
        result.append(g)

    result.sort(key=lambda x: (x["period"], -x["hourly_rate"]), reverse=True)
    return jsonify(result)


@app.route("/api/reports/trends")
@login_required
def trends_report():
    period = request.args.get("period", "weekly")
    clinic_id = request.args.get("clinic_id")
    db = get_db()
    uid = current_user_id()

    query = """
        SELECT wl.date, wl.hours, wl.income, c.name AS clinic_name, wl.clinic_id, c.color
        FROM work_logs wl
        JOIN clinics c ON wl.clinic_id = c.id
        WHERE wl.user_id = ?
    """
    params = [uid]
    if clinic_id:
        query += " AND wl.clinic_id = ?"
        params.append(int(clinic_id))
    query += " ORDER BY wl.date ASC"

    rows = db.execute(query, params).fetchall()

    groups = {}
    for r in rows:
        bucket = _week_start(r["date"]) if period == "weekly" else _month_start(r["date"])
        if bucket is None:
            continue
        key = (bucket, r["clinic_id"])
        if key not in groups:
            groups[key] = {"period": bucket, "clinic_id": r["clinic_id"],
                           "clinic_name": r["clinic_name"], "color": r["color"],
                           "total_hours": 0, "total_income": 0}
        groups[key]["total_hours"] += r["hours"]
        groups[key]["total_income"] += r["income"]

    result = []
    for g in groups.values():
        rate = round(g["total_income"] / g["total_hours"], 2) if g["total_hours"] > 0 else 0
        g["hourly_rate"] = rate
        result.append(g)

    result.sort(key=lambda x: x["period"])
    return jsonify(result)


# ── Main ─────────────────────────────────────────────────────────────────

# Initialize DB on import (for WSGI/production) — idempotent, safe to call repeatedly
init_db()

if __name__ == "__main__":
    print(" Dental Worklog running at http://localhost:5199")
    app.run(host="127.0.0.1", port=5199, debug=True)
