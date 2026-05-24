"""LINE LIFF binding routes."""

import os
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, session, render_template
from db import get_db
from auth import login_required, current_user_id
from line.helpers import _line_push, _line_quick_reply
from line.guided import TRIGGER_NEW_CLINIC, STATE_AWAITING_CLINIC, _set_conversation

LINE_LIFF_ID = os.environ.get("LINE_LIFF_ID", "")
LINE_OA_BASIC_ID = os.environ.get("LINE_OA_BASIC_ID", "")
APP_URL = os.environ.get("APP_URL", "http://localhost:5199")
LIFF_ID = LINE_LIFF_ID  # alias for template compatibility

line_bind_bp = Blueprint("line_bind", __name__)

# ── LINE Binding (LIFF token flow + Google auth) ─────────────────────────

@line_bind_bp.route("/line/liff-bind")
def liff_bind_page():
    """LIFF entry page — opens in LINE in-app browser.
    Gets LINE user ID via LIFF SDK, creates a binding token,
    then opens system browser for Google OAuth (avoids disallowed_useragent).
    """
    return render_template("liff_bind.html", liff_id=LIFF_ID)


@line_bind_bp.route("/api/line/liff-login", methods=["POST"])
def liff_login():
    """Auto-login via LIFF — sets session if LINE user ID is bound.
    Called from LIFF page after LIFF SDK provides LINE user ID.
    Body: {"line_user_id": "Uxxx"}
    Returns: {"logged_in": true, "user": {...}} or {"logged_in": false}
    """
    data = request.get_json(force=True)
    line_user_id = data.get("line_user_id", "").strip()
    if not line_user_id:
        return jsonify({"error": "Missing line_user_id"}), 400

    db = get_db()
    row = db.execute(
        "SELECT id, email, name, avatar_url FROM users WHERE line_user_id = ?",
        (line_user_id,)
    ).fetchone()

    if not row:
        return jsonify({"logged_in": False})

    session["user_id"] = row["id"]
    return jsonify({
        "logged_in": True,
        "user": {"id": row["id"], "email": row["email"], "name": row["name"]},
    })


@line_bind_bp.route("/line/confirm-bind")
def confirm_bind_page():
    """Confirmation page — opens in system browser after LIFF redirect.
    User must be signed in with Google to confirm binding.
    """
    token = request.args.get("token", "")
    return render_template("line_confirm_bind.html", token=token)


@line_bind_bp.route("/api/line/initiate-bind", methods=["POST"])
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


@line_bind_bp.route("/api/line/confirm-bind", methods=["POST"])
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

    # Send push message to LINE with guided greeting
    line_id = LINE_OA_BASIC_ID.lstrip("@")

    # Look up existing clinics for this user
    clinics = db.execute(
        "SELECT id, name FROM clinics WHERE user_id = ? AND deleted = 0 ORDER BY name",
        (uid,)
    ).fetchall()
    items = [(c["name"], c["name"]) for c in clinics][:12]
    items.append(("+ Add New Clinic", TRIGGER_NEW_CLINIC))

    _set_conversation(db, line_user_id, STATE_AWAITING_CLINIC)
    _line_push(line_user_id, [
        _line_quick_reply(
            "✅ Account linked!\n\nLet's log your first entry.\n\nWhich clinic?",
            items
        )
    ])

    return jsonify({
        "bound": True,
        "line_user_id": line_user_id,
        "line_display_name": row["line_display_name"],
        "line_url": f"https://line.me/R/ti/p/@{line_id}" if line_id else "",
    })


@line_bind_bp.route("/api/line/status")
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


@line_bind_bp.route("/api/line/bind", methods=["POST"])
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


@line_bind_bp.route("/api/line/unbind", methods=["POST"])
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
