"""Reports API — ranking, trends, income, monthly summary."""

from datetime import datetime, timezone, timedelta, date
from flask import Blueprint, request, jsonify
from db import get_db
from auth import login_required, current_user_id

reports_bp = Blueprint("reports", __name__)

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


@reports_bp.route("/api/reports/ranking")
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


@reports_bp.route("/api/reports/trends")
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


@reports_bp.route("/api/reports/income-ranking")
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
@reports_bp.route("/api/reports/monthly-summary")
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
