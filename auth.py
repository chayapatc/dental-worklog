"""Auth routes and helpers — login_required, OAuth, sessions."""

from functools import wraps
from flask import Blueprint, session, redirect, request, url_for, render_template, jsonify
from db import get_db

auth_bp = Blueprint("auth", __name__)


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


@auth_bp.route("/api/me")
def api_me():
    """Return current user info or null."""
    uid = current_user_id()
    if not uid:
        return jsonify(None)
    db = get_db()
    row = db.execute("SELECT id, email, name, avatar_url FROM users WHERE id=?", (uid,)).fetchone()
    return jsonify(dict(row)) if row else jsonify(None)


@auth_bp.route("/auth/login")
def auth_login():
    from app import google
    if not google.client_id:
        return "Google OAuth not configured — set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET", 500
    redirect_uri = url_for("auth.auth_callback", _external=True)
    next_page = request.args.get("next", "/")
    session["oauth_next"] = next_page
    return google.authorize_redirect(redirect_uri)


@auth_bp.route("/auth/callback")
def auth_callback():
    from app import google
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
        db.execute(
            "UPDATE users SET email=?, name=?, avatar_url=? WHERE id=?",
            (email, name, avatar, row["id"]),
        )
        user_id = row["id"]
    else:
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


@auth_bp.route("/auth/logout")
def auth_logout():
    session.clear()
    return redirect("/")


@auth_bp.route("/")
def index():
    return render_template("index.html")
