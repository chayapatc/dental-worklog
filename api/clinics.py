"""Clinic CRUD API routes."""

from flask import Blueprint, request, jsonify
from db import get_db
from auth import login_required, current_user_id

clinics_bp = Blueprint("clinics", __name__)

# ── Clinics API ──────────────────────────────────────────────────────────
@clinics_bp.route("/api/clinics", methods=["GET"])
@login_required
def list_clinics():
    db = get_db()
    rows = db.execute(
        "SELECT id, name, color FROM clinics WHERE user_id=? AND deleted=0 ORDER BY name",
        (current_user_id(),),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@clinics_bp.route("/api/clinics", methods=["POST"])
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


@clinics_bp.route("/api/clinics/<int:clinic_id>", methods=["PUT"])
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


@clinics_bp.route("/api/clinics/<int:clinic_id>", methods=["DELETE"])
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
