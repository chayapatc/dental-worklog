#!/usr/bin/env python3
"""Dental Worklog — Flask + SQLite + Google OAuth."""

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import requests as http_requests
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

# ── LINE Config ─────────────────────────────────────────────────────────
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LIFF_ID = os.environ.get("LINE_LIFF_ID", "")
# App URL for LINE binding deep link (must be set)
APP_URL = os.environ.get("APP_URL", "http://localhost:5199")

# ── OAuth Config ─────────────────────────────────────────────────────────
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile https://www.googleapis.com/auth/calendar.readonly"},
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
    # Store next page in session for post-login redirect
    next_page = request.args.get("next", "/")
    session["oauth_next"] = next_page
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
    session["google_token"] = token.get("access_token")
    next_page = session.pop("oauth_next", "/")
    return redirect(next_page)


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


# ── Tracker (monthly calendar + Google Calendar) ────────────────────────
@app.route("/api/tracker/worklogs")
@login_required
def tracker_worklogs():
    """Return per-day worklog counts for a month."""
    import calendar as cal_mod
    year = request.args.get("year", datetime.now(timezone.utc).year, type=int)
    month = request.args.get("month", datetime.now(timezone.utc).month, type=int)
    db = get_db()
    uid = current_user_id()

    rows = db.execute("""
        SELECT wl.date, c.name AS clinic_name, c.color, COUNT(*) AS cnt
        FROM work_logs wl
        JOIN clinics c ON wl.clinic_id = c.id
        WHERE wl.user_id = ? AND wl.date >= ? AND wl.date < ?
        GROUP BY wl.date, wl.clinic_id
        ORDER BY wl.date
    """, (uid, f"{year}-{month:02d}-01",
         f"{year + (month // 12)}-{(month % 12) + 1:02d}-01")).fetchall()

    days_in_month = cal_mod.monthrange(year, month)[1]
    first_weekday = cal_mod.monthrange(year, month)[0]  # 0=Mon

    days = {}
    for day in range(1, days_in_month + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        days[date_str] = {"date": date_str, "day": day, "weekday": (first_weekday + day - 1) % 7, "clinics": [], "total": 0}

    for r in rows:
        if r["date"] in days:
            days[r["date"]]["clinics"].append({
                "clinic_name": r["clinic_name"],
                "color": r["color"],
                "count": r["cnt"],
            })
            days[r["date"]]["total"] += r["cnt"]

    return jsonify({
        "year": year, "month": month,
        "days_in_month": days_in_month,
        "first_weekday": first_weekday,
        "days": list(days.values()),
    })


@app.route("/api/tracker/events")
@login_required
def tracker_events():
    """Fetch Google Calendar events for a month using stored access token."""
    year = request.args.get("year", datetime.now(timezone.utc).year, type=int)
    month = request.args.get("month", datetime.now(timezone.utc).month, type=int)
    token = session.get("google_token")
    if not token:
        return jsonify({"events": [], "error": "No Google token — re-login to grant calendar access"})

    time_min = f"{year}-{month:02d}-01T00:00:00Z"
    from calendar import monthrange
    last_day = monthrange(year, month)[1]
    time_max = f"{year}-{month:02d}-{last_day}T23:59:59Z"

    try:
        resp = http_requests.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            params={
                "timeMin": time_min, "timeMax": time_max,
                "singleEvents": "true", "orderBy": "startTime",
                "maxResults": 100,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code == 401:
            session.pop("google_token", None)
            return jsonify({"events": [], "error": "Calendar token expired — re-login"})
        data = resp.json()
        events = []
        for ev in data.get("items", []):
            start = ev.get("start", {}).get("date") or ev.get("start", {}).get("dateTime", "")
            end = ev.get("end", {}).get("date") or ev.get("end", {}).get("dateTime", "")
            summary = ev.get("summary", "Busy")
            if not start:
                continue

            start_date = datetime.strptime(start[:10], "%Y-%m-%d").date()
            end_date = datetime.strptime(end[:10], "%Y-%m-%d").date() if end else start_date
            end_date_exclusive = end_date  # Google uses exclusive end for all-day events

            # Expand multi-day events across each day they span
            current = start_date
            while current < end_date_exclusive:
                events.append({
                    "date": current.strftime("%Y-%m-%d"),
                    "summary": summary,
                })
                current += timedelta(days=1)
        return jsonify({"events": events})
    except Exception:
        return jsonify({"events": [], "error": "Calendar unavailable"})


# ── LINE Chat Logger ─────────────────────────────────────────────────────

def _line_verify_signature(body: bytes, signature: str) -> bool:
    """Verify LINE webhook signature using HMAC-SHA256."""
    if not LINE_CHANNEL_SECRET:
        return False
    import base64
    expected = base64.b64encode(
        hmac.new(LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature)


def _line_reply(reply_token: str, messages: list):
    """Send reply message via LINE Messaging API."""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return
    try:
        resp = http_requests.post(
            "https://api.line.me/v2/bot/message/reply",
            json={"replyToken": reply_token, "messages": messages},
            headers={
                "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=5,
        )
    except Exception:
        pass  # Log silently — don't crash webhook on reply failure


def _line_push(user_id: str, messages: list):
    """Send push message to a LINE user."""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return
    try:
        http_requests.post(
            "https://api.line.me/v2/bot/message/push",
            json={"to": user_id, "messages": messages},
            headers={
                "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=5,
        )
    except Exception:
        pass


def _fuzzy_match_clinic(input_name: str, clinics: list) -> dict | None:
    """Match user input to closest clinic name (case-insensitive, no spaces)."""
    clean = input_name.lower().replace(" ", "").strip()
    if not clean:
        return None

    # Build normalized clinic names
    normalized = [
        {"clinic": c, "clean": c["name"].lower().replace(" ", "")}
        for c in clinics
    ]

    # 1. Exact match on normalized name
    for n in normalized:
        if clean == n["clean"]:
            return n["clinic"]

    # 2. Input is substring of clinic name or vice versa
    for n in normalized:
        if clean in n["clean"] or n["clean"] in clean:
            return n["clinic"]

    # 3. Levenshtein distance — accept if edit distance <= 30% of longer string
    def levenshtein(a, b):
        if len(a) < len(b):
            return levenshtein(b, a)
        if len(b) == 0:
            return len(a)
        prev = range(len(b) + 1)
        for i, ca in enumerate(a):
            curr = [i + 1]
            for j, cb in enumerate(b):
                curr.append(min(
                    prev[j + 1] + 1,      # deletion
                    curr[j] + 1,            # insertion
                    prev[j] + (0 if ca == cb else 1),  # substitution
                ))
            prev = curr
        return prev[-1]

    best = None
    best_dist = 999
    for n in normalized:
        d = levenshtein(clean, n["clean"])
        max_len = max(len(clean), len(n["clean"]))
        if max_len > 0 and d / max_len <= 0.3 and d < best_dist:
            best = n["clinic"]
            best_dist = d

    return best


def _parse_log_message(text: str) -> tuple | None:
    """Parse a LINE message into (hours, income, expense) or None on failure.
    
    Format: {hours} {income}i? {expense}e?
    - h suffix = hours (e.g. "4h")
    - i prefix/suffix = income (e.g. "i5000" or "5000i")
    - e prefix/suffix = expense (e.g. "e500" or "500e")
    - Bare numbers assigned positionally: hours, income, expense
    """
    tokens = text.strip().split()
    if not tokens:
        return None

    hours = 0.0
    income = 0.0
    expense = 0.0
    has_explicit = {"hours": False, "income": False, "expense": False}
    positional = []

    for token in tokens:
        t = token.lower().strip()

        # h suffix: "4h", "0.5h"
        m = re.match(r'^(\d+(?:\.\d+)?)h$', t)
        if m:
            hours = float(m.group(1))
            has_explicit["hours"] = True
            continue

        # i prefix: "i5000"
        m = re.match(r'^i(\d+(?:\.\d+)?)$', t)
        if m:
            income = float(m.group(1))
            has_explicit["income"] = True
            continue

        # i suffix: "5000i"
        m = re.match(r'^(\d+(?:\.\d+)?)i$', t)
        if m:
            income = float(m.group(1))
            has_explicit["income"] = True
            continue

        # e prefix: "e500"
        m = re.match(r'^e(\d+(?:\.\d+)?)$', t)
        if m:
            expense = float(m.group(1))
            has_explicit["expense"] = True
            continue

        # e suffix: "500e"
        m = re.match(r'^(\d+(?:\.\d+)?)e$', t)
        if m:
            expense = float(m.group(1))
            has_explicit["expense"] = True
            continue

        # Pure number
        m = re.match(r'^(\d+(?:\.\d+)?)$', t)
        if m:
            positional.append(float(m.group(1)))
            continue

        # Unrecognized token
        return None

    # Assign positional values to unset fields
    pos_idx = 0
    if not has_explicit["hours"] and pos_idx < len(positional):
        hours = positional[pos_idx]; pos_idx += 1
    if not has_explicit["income"] and pos_idx < len(positional):
        income = positional[pos_idx]; pos_idx += 1
    if not has_explicit["expense"] and pos_idx < len(positional):
        expense = positional[pos_idx]; pos_idx += 1

    # Require at least one meaningful value
    if hours == 0 and income == 0 and expense == 0:
        return None

    return (hours, income, expense)


@app.route("/api/line/webhook", methods=["POST"])
def line_webhook():
    """LINE Messaging API webhook endpoint."""
    body = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")

    # Verify signature (skip if LINE_CHANNEL_SECRET not configured — dev mode)
    if LINE_CHANNEL_SECRET and not _line_verify_signature(body, signature):
        return "Invalid signature", 403

    try:
        events = json.loads(body).get("events", [])
    except json.JSONDecodeError:
        return "Invalid JSON", 400

    if not events:
        return "OK", 200

    db = get_db()

    for ev in events:
        ev_type = ev.get("type", "")
        reply_token = ev.get("replyToken", "")
        source = ev.get("source", {})
        line_user_id = source.get("userId", "")

        if not line_user_id:
            continue

        # Find the bound dental worklog user
        user_row = db.execute(
            "SELECT id, email, name FROM users WHERE line_user_id = ?",
            (line_user_id,)
        ).fetchone()

        if ev_type == "follow":
            # User added the OA — send greeting with bind link
            if user_row:
                msg = (
                    f"Welcome back, {user_row['name']}! 🦷\n\n"
                    f"Format: {{clinic}} {{hours}} {{income}} {{expense}}\n"
                    f"Examples:\n"
                    f"• vela 4 5000\n"
                    f"• mjh 1 i1000 e500\n"
                    f"• vela 500e\n\n"
                    f"Reply with your log entry now."
                )
            else:
                bind_url = f"https://liff.line.me/{LIFF_ID}" if LIFF_ID else f"{APP_URL}/line/liff-bind"
                msg = (
                    f"Welcome to Dental Worklog! 🦷\n\n"
                    f"Tap to bind your account:\n"
                    f"{bind_url}\n\n"
                    f"After binding, log entries like:\n"
                    f"vela 4 5000"
                )
            _line_reply(reply_token, [{"type": "text", "text": msg}])
            continue

        if ev_type != "message" or ev.get("message", {}).get("type") != "text":
            continue

        text = ev["message"]["text"].strip()

        if not user_row:
            # User hasn't bound yet
            bind_url = f"https://liff.line.me/{LIFF_ID}" if LIFF_ID else f"{APP_URL}/line/liff-bind"
            _line_reply(reply_token, [{"type": "text", "text": f"Tap to bind your account:\n{bind_url}"}])
            continue

        user_id = user_row["id"]

        # Parse the message: first token = clinic, rest = values
        parts = text.strip().split(None, 1)  # split into [clinic, rest]
        if len(parts) < 2:
            _line_reply(reply_token, [{"type": "text", "text": (
                "Format: {clinic} {hours} {income} {expense}\n\n"
                "Examples:\n"
                "vela 4 5000\n"
                "mjh 1 i1000 e500\n"
                "vela 500e\n\n"
                "h=hours i=income e=expense"
            )}])
            continue

        clinic_input = parts[0]
        rest_text = parts[1]

        # Parse values
        parsed = _parse_log_message(rest_text)
        if parsed is None:
            _line_reply(reply_token, [{"type": "text", "text": (
                "Can't parse that. Format: {hours} {income}i? {expense}e?\n\n"
                "Examples:\n"
                "4 5000        → 4h, income 5000\n"
                "4h 5000i      → 4h, income 5000\n"
                "i1000 e500    → income 1000, expense 500\n"
                "500e          → expense 500"
            )}])
            continue

        hours, income, expense = parsed

        # Fuzzy match clinic
        clinics = db.execute(
            "SELECT id, name FROM clinics WHERE user_id = ? AND deleted = 0",
            (user_id,)
        ).fetchall()
        clinic_list = [dict(c) for c in clinics]

        matched = _fuzzy_match_clinic(clinic_input, clinic_list)
        if not matched:
            names = ", ".join(c["name"] for c in clinic_list) or "(no clinics)"
            _line_reply(reply_token, [{"type": "text", "text": (
                f"Clinic '{clinic_input}' not found.\n"
                f"Your clinics: {names}"
            )}])
            continue

        # Create the log entry (today's date in Bangkok time)
        bangkok_tz = timezone(timedelta(hours=7))
        today = datetime.now(bangkok_tz).strftime("%Y-%m-%d")

        db.execute(
            "INSERT INTO work_logs (user_id, clinic_id, date, hours, income, expense) VALUES (?,?,?,?,?,?)",
            (user_id, matched["id"], today, hours, income, expense),
        )
        db.commit()

        # Build confirmation
        net = income - expense
        rate = f"฿{int(net/hours)}/h" if hours > 0 else "-"
        _line_reply(reply_token, [{"type": "text", "text": (
            f"✓ Logged: {matched['name']}\n"
            f"  {hours}h | ฿{int(income)} | exp ฿{int(expense)}\n"
            f"  Net: ฿{int(net)} ({rate})"
        )}])

    return "OK", 200


# ── LINE Binding (LIFF token flow + Google auth) ─────────────────────────

@app.route("/line/liff-bind")
def liff_bind_page():
    """LIFF entry page — opens in LINE in-app browser.
    Gets LINE user ID via LIFF SDK, creates a binding token,
    then opens system browser for Google OAuth (avoids disallowed_useragent).
    """
    return render_template("liff_bind.html", liff_id=LIFF_ID)


@app.route("/line/confirm-bind")
def confirm_bind_page():
    """Confirmation page — opens in system browser after LIFF redirect.
    User must be signed in with Google to confirm binding.
    """
    token = request.args.get("token", "")
    return render_template("line_confirm_bind.html", token=token)


@app.route("/api/line/initiate-bind", methods=["POST"])
def initiate_bind():
    """Create a binding token for LIFF → Google OAuth flow.
    No auth required — called from LIFF SDK in LINE browser.
    Body: {"line_user_id": "Uxxx", "line_display_name": "Name"}
    Returns: {"token": "uuid", "url": "https://app/line/confirm-bind?token=uuid"}
    """
    data = request.get_json(force=True)
    line_user_id = data.get("line_user_id", "").strip()
    line_display_name = data.get("line_display_name", "").strip()
    if not line_user_id:
        return jsonify({"error": "Missing line_user_id"}), 400

    import uuid
    token = uuid.uuid4().hex
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")

    db = get_db()
    # Clean expired tokens
    db.execute("DELETE FROM line_binding_tokens WHERE expires_at < datetime('now')")
    db.execute(
        "INSERT INTO line_binding_tokens (token, line_user_id, line_display_name, expires_at) VALUES (?,?,?,?)",
        (token, line_user_id, line_display_name, expires),
    )
    db.commit()

    confirm_url = f"{APP_URL.rstrip('/')}/line/confirm-bind?token={token}"
    return jsonify({"token": token, "url": confirm_url})


@app.route("/api/line/confirm-bind", methods=["POST"])
@login_required
def confirm_bind():
    """Confirm LINE binding — called from system browser after Google auth.
    Body: {"token": "uuid"}
    """
    data = request.get_json(force=True)
    token = data.get("token", "").strip()
    if not token:
        return jsonify({"error": "Missing token"}), 400

    db = get_db()
    row = db.execute(
        "SELECT line_user_id, line_display_name FROM line_binding_tokens WHERE token = ? AND expires_at > datetime('now')",
        (token,)
    ).fetchone()

    if not row:
        return jsonify({"error": "Invalid or expired binding token. Try again from LINE."}), 410

    line_user_id = row["line_user_id"]
    uid = current_user_id()

    # Check if already bound to another user
    existing = db.execute(
        "SELECT id FROM users WHERE line_user_id = ? AND id != ?",
        (line_user_id, uid)
    ).fetchone()
    if existing:
        db.execute("DELETE FROM line_binding_tokens WHERE token = ?", (token,))
        db.commit()
        return jsonify({"error": "This LINE account is already bound to another user."}), 409

    # Bind
    db.execute("UPDATE users SET line_user_id = ? WHERE id = ?", (line_user_id, uid))
    db.execute("DELETE FROM line_binding_tokens WHERE token = ?", (token,))
    db.commit()

    return jsonify({"bound": True, "line_user_id": line_user_id, "line_display_name": row["line_display_name"]})


@app.route("/api/line/status")
@login_required
def line_binding_status():
    """Return LINE binding status for the current user."""
    db = get_db()
    row = db.execute(
        "SELECT line_user_id FROM users WHERE id = ?",
        (current_user_id(),)
    ).fetchone()
    return jsonify({
        "bound": bool(row and row["line_user_id"]),
        "line_user_id": row["line_user_id"] if row else None,
    })


@app.route("/api/line/bind", methods=["POST"])
@login_required
def line_bind():
    """Legacy: direct POST bind (kept for backward compatibility).
    Body: {"line_user_id": "Uxxx"}
    """
    data = request.get_json(force=True)
    line_user_id = data.get("line_user_id", "").strip()
    if not line_user_id:
        return jsonify({"error": "Missing line_user_id"}), 400

    db = get_db()
    uid = current_user_id()

    existing = db.execute(
        "SELECT id FROM users WHERE line_user_id = ? AND id != ?",
        (line_user_id, uid)
    ).fetchone()
    if existing:
        return jsonify({"error": "This LINE account is already bound to another user."}), 409

    db.execute("UPDATE users SET line_user_id = ? WHERE id = ?", (line_user_id, uid))
    db.commit()

    return jsonify({"bound": True, "line_user_id": line_user_id})


@app.route("/api/line/unbind", methods=["POST"])
@login_required
def line_unbind():
    """Unbind LINE from current user."""
    db = get_db()
    db.execute(
        "UPDATE users SET line_user_id = NULL WHERE id = ?",
        (current_user_id(),)
    )
    db.commit()
    return jsonify({"bound": False})


# ── Main ─────────────────────────────────────────────────────────────────

# Initialize DB on import (for WSGI/production) — idempotent, safe to call repeatedly
init_db()

if __name__ == "__main__":
    print(" Dental Worklog running at http://localhost:5199")
    app.run(host="127.0.0.1", port=5199, debug=True)
