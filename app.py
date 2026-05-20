#!/usr/bin/env python3
"""Dental Worklog — Flask + SQLite + Google OAuth."""

import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, jsonify, redirect, request, render_template, session, url_for
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()  # load .env file into os.environ

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# Trust proxy headers (Nginx terminates SSL)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Secure session cookies (Secure in prod, Lax SameSite to protect against CSRF)
app.config.update(
    SESSION_COOKIE_SECURE=not app.debug,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
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
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    where = "WHERE wl.user_id = ?"
    params = [uid]
    if clinic_id:
        where += " AND wl.clinic_id = ?"
        params.append(int(clinic_id))

    # Total count
    count_query = f"""
        SELECT COUNT(*) FROM work_logs wl
        JOIN clinics c ON wl.clinic_id = c.id
        {where}
    """
    total = db.execute(count_query, params).fetchone()[0]

    # Paginated rows
    offset = (page - 1) * per_page
    rows_query = f"""
        SELECT wl.id, wl.date, wl.hours, wl.income, wl.expense, wl.clinic_id, c.name AS clinic_name
        FROM work_logs wl
        JOIN clinics c ON wl.clinic_id = c.id
        {where}
        ORDER BY wl.date DESC LIMIT ? OFFSET ?
    """
    rows = db.execute(rows_query, params + [per_page, offset]).fetchall()

    total_pages = max(1, (total + per_page - 1) // per_page)
    return jsonify({
        "logs": [dict(r) for r in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    })


@app.route("/api/logs", methods=["POST"])
@login_required
def create_log():
    data = request.get_json(force=True)
    clinic_id = data.get("clinic_id")
    date = data.get("date")
    hours = data.get("hours")
    income = data.get("income")
    expense = data.get("expense", 0)

    errors = []
    if not clinic_id:
        errors.append("clinic_id is required")
    if not date:
        errors.append("date is required")
    if hours is None or hours < 0:
        errors.append("hours must be >= 0")
    if income is None or income < 0:
        errors.append("income must be >= 0")
    if expense is None or expense < 0:
        errors.append("expense must be >= 0")
    if errors:
        return jsonify({"error": ", ".join(errors)}), 400

    db = get_db()
    uid = current_user_id()

    # Verify that the clinic exists, belongs to the current user, and is not deleted
    clinic = db.execute(
        "SELECT id FROM clinics WHERE id=? AND user_id=? AND deleted=0",
        (int(clinic_id), uid)
    ).fetchone()
    if not clinic:
        return jsonify({"error": "Clinic not found or does not belong to user"}), 403

    hours_val = float(hours) if hours else 0.0
    cur = db.execute(
        "INSERT INTO work_logs (user_id, clinic_id, date, hours, income, expense) VALUES (?,?,?,?,?,?)",
        (uid, int(clinic_id), date, hours_val, float(income), float(expense)),
    )
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.route("/api/logs/export", methods=["GET"])
@login_required
def export_logs():
    """Export all work logs for the current user as CSV."""
    import io
    import csv
    from flask import Response

    db = get_db()
    uid = current_user_id()

    rows = db.execute("""
        SELECT wl.date, c.name AS clinic_name, wl.hours, wl.income, wl.expense,
               (wl.income - wl.expense) AS net_income
        FROM work_logs wl
        JOIN clinics c ON wl.clinic_id = c.id
        WHERE wl.user_id = ?
        ORDER BY wl.date DESC
    """, (uid,)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row (with UTF-8 BOM for Excel compatibility)
    output.write('\ufeff')
    writer.writerow(["Date", "Clinic", "Hours", "Gross Income (฿)", "Expense (฿)", "Net Income (฿)", "Hourly Rate (฿/h)"])

    for r in rows:
        rate = round(r["net_income"] / r["hours"], 2) if r["hours"] > 0 else 0
        writer.writerow([
            r["date"],
            r["clinic_name"],
            r["hours"],
            r["income"],
            r["expense"],
            r["net_income"],
            rate
        ])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename=dental_worklog_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return response


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


def _quarter_start(d):
    """Return YYYY-QN of the quarter containing date d."""
    dt = _parse_date(d)
    if dt is None:
        return None
    quarter = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{quarter}"


def _half_start(d):
    """Return YYYY-HN of the half-year containing date d."""
    dt = _parse_date(d)
    if dt is None:
        return None
    half = 1 if dt.month <= 6 else 2
    return f"{dt.year}-H{half}"


@app.route("/api/reports/ranking")
@login_required
def ranking_report():
    period = request.args.get("period", "weekly")
    db = get_db()
    uid = current_user_id()

    rows = db.execute("""
        SELECT wl.date, wl.hours, wl.income, wl.expense, c.name AS clinic_name, wl.clinic_id, c.color
        FROM work_logs wl
        JOIN clinics c ON wl.clinic_id = c.id
        WHERE wl.user_id = ?
        ORDER BY wl.date DESC
    """, (uid,)).fetchall()

    # Map period to bucketing function
    bucket_fn = {
        "weekly": _week_start,
        "monthly": _month_start,
        "quarterly": _quarter_start,
        "semiyearly": _half_start,
    }.get(period, _week_start)

    groups = {}
    for r in rows:
        bucket = bucket_fn(r["date"])
        if bucket is None:
            continue
        key = (bucket, r["clinic_id"])
        if key not in groups:
            groups[key] = {"period": bucket, "clinic_id": r["clinic_id"],
                           "clinic_name": r["clinic_name"], "color": r["color"],
                           "total_hours": 0, "total_income": 0, "total_expense": 0}
        groups[key]["total_hours"] += r["hours"]
        groups[key]["total_income"] += r["income"]
        groups[key]["total_expense"] += r["expense"]

    result = []
    for g in groups.values():
        net = g["total_income"] - g["total_expense"]
        rate = round(net / g["total_hours"], 2) if g["total_hours"] > 0 else 0
        g["hourly_rate"] = rate
        g["net_income"] = net
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
        SELECT wl.date, wl.hours, wl.income, wl.expense, c.name AS clinic_name, wl.clinic_id, c.color
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

    # Map period to bucketing function
    bucket_fn = {
        "weekly": _week_start,
        "monthly": _month_start,
        "quarterly": _quarter_start,
        "semiyearly": _half_start,
    }.get(period, _week_start)

    groups = {}
    for r in rows:
        bucket = bucket_fn(r["date"])
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


@app.route("/api/reports/income-ranking")
@login_required
def income_ranking():
    """Rank clinics by total net income within a date range. Default: month-to-date (UTC)."""
    now = datetime.now(timezone.utc)
    start = request.args.get("start", now.replace(day=1).strftime("%Y-%m-%d"))
    end = request.args.get("end", now.strftime("%Y-%m-%d"))
    db = get_db()
    uid = current_user_id()

    rows = db.execute("""
        SELECT c.id AS clinic_id, c.name AS clinic_name, c.color,
               SUM(wl.hours) AS total_hours,
               SUM(wl.income) AS total_income,
               SUM(wl.expense) AS total_expense
        FROM work_logs wl
        JOIN clinics c ON wl.clinic_id = c.id
        WHERE wl.user_id = ? AND wl.date >= ? AND wl.date <= ?
        GROUP BY c.id
    """, (uid, start, end)).fetchall()

    result = []
    for r in rows:
        net = r["total_income"] - r["total_expense"]
        rate = round(net / r["total_hours"], 2) if r["total_hours"] > 0 else 0
        result.append({
            "clinic_id": r["clinic_id"],
            "clinic_name": r["clinic_name"],
            "color": r["color"],
            "total_hours": round(r["total_hours"], 1),
            "total_income": r["total_income"],
            "total_expense": r["total_expense"],
            "net_income": net,
            "hourly_rate": rate,
        })

    result.sort(key=lambda x: -x["net_income"])
    return jsonify({
        "start": start,
        "end": end,
        "rankings": result,
    })


# ── Monthly Summary (bar chart + line) ─────────────────────────────────
@app.route("/api/reports/monthly-summary")
@login_required
def monthly_summary():
    """Return 12 months of income, expense, net for a given year."""
    year = request.args.get("year", datetime.now(timezone.utc).year, type=int)
    db = get_db()
    uid = current_user_id()

    rows = db.execute("""
        SELECT wl.date, wl.income, wl.expense
        FROM work_logs wl
        WHERE wl.user_id = ? AND wl.date >= ? AND wl.date < ?
    """, (uid, f"{year}-01-01", f"{year + 1}-01-01")).fetchall()

    months = [{"month": m, "income": 0.0, "expense": 0.0, "net": 0.0} for m in range(1, 13)]
    for r in rows:
        try:
            m = int(r["date"].split("-")[1])
            months[m - 1]["income"] += r["income"]
            months[m - 1]["expense"] += r["expense"]
            months[m - 1]["net"] += r["income"] - r["expense"]
        except (ValueError, IndexError):
            continue

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for i, m in enumerate(months):
        m["label"] = month_names[i]

    return jsonify({"year": year, "months": months})


# ── Main ─────────────────────────────────────────────────────────────────

# Initialize DB on import (for WSGI/production) — idempotent, safe to call repeatedly
init_db()

if __name__ == "__main__":
    print(" Dental Worklog running at http://localhost:5199")
    app.run(host="127.0.0.1", port=5199, debug=True)
