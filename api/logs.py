"""Work log CRUD and CSV export routes."""

import io, csv
from datetime import datetime
from flask import Blueprint, request, jsonify, Response
from db import get_db
from auth import login_required, current_user_id

logs_bp = Blueprint("logs", __name__)

# ── Work Logs API ───────────────────────────────────────────────────────
@logs_bp.route("/api/logs", methods=["GET"])
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


@logs_bp.route("/api/logs", methods=["POST"])
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


@logs_bp.route("/api/logs/<int:log_id>", methods=["PUT"])
@login_required
def update_log(log_id):
    """Update an existing work log entry."""
    data = request.get_json(force=True)
    uid = current_user_id()
    db = get_db()

    # Verify ownership
    row = db.execute(
        "SELECT id FROM work_logs WHERE id = ? AND user_id = ?",
        (log_id, uid)
    ).fetchone()
    if not row:
        return jsonify({"error": "Log not found"}), 404

    clinic_id = data.get("clinic_id")
    date = data.get("date", "")
    hours = data.get("hours", 0)
    income = data.get("income", 0)
    expense = data.get("expense", 0)

    if not clinic_id or not date:
        return jsonify({"error": "Clinic and date are required"}), 400

    # Verify clinic ownership
    clinic = db.execute(
        "SELECT id FROM clinics WHERE id = ? AND user_id = ? AND deleted = 0",
        (int(clinic_id), uid)
    ).fetchone()
    if not clinic:
        return jsonify({"error": "Clinic not found"}), 403

    hours_val = float(hours) if hours else 0.0
    db.execute(
        "UPDATE work_logs SET clinic_id=?, date=?, hours=?, income=?, expense=? WHERE id=?",
        (int(clinic_id), date, hours_val, float(income), float(expense), log_id),
    )
    db.commit()
    return jsonify({"id": log_id, "updated": True})


@logs_bp.route("/api/logs/export", methods=["GET"])
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


@logs_bp.route("/api/logs/<int:log_id>", methods=["DELETE"])
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
