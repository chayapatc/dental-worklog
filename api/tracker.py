"""Tracker calendar API — worklogs + Google Calendar events."""

from datetime import datetime, timezone, timedelta
from calendar import monthrange
from flask import Blueprint, request, jsonify, session
from db import get_db
from auth import login_required, current_user_id

tracker_bp = Blueprint("tracker", __name__)

# ── Tracker (monthly calendar + Google Calendar) ────────────────────────
@tracker_bp.route("/api/tracker/worklogs")
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


@tracker_bp.route("/api/tracker/events")
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
