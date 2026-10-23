#!/usr/bin/env python3
"""Dental Worklog — Flask + SQLite + Google OAuth (blueprint shell)."""

import hashlib
import os
import secrets
import subprocess

from dotenv import load_dotenv
from flask import Flask, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

from config import SECRET_KEY

app = Flask(__name__)
app.secret_key = SECRET_KEY or secrets.token_hex(32)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.config.update(
    SESSION_COOKIE_SECURE=not app.debug,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


@app.after_request
def add_cache_headers(response):
    if request.path.startswith("/static/") and not app.debug:
        # Static URLs carry ?v=<git hash>, so a new deploy is a new URL.
        # While debug is on the hash doesn't move with every edit, so
        # caching there would serve stale assets during development.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    elif response.content_type and "text/html" in response.content_type:
        # Revalidate HTML, but never no-store: it would block the bfcache.
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ── Database teardown ────────────────────────────────────────────────────
from db import close_db, init_db
app.teardown_appcontext(close_db)


# ── Sandbox auto-login (local development only) ──────────────────────────
# Lets Lighthouse and manual QA reach the authenticated views without a real
# Google session. Two independent conditions must hold: SANDBOX_AUTH=1 in the
# environment AND debug mode on the request. gunicorn runs with debug off, so
# a deployed instance can never auto-login even if the variable leaks in.
SANDBOX_AUTH = os.environ.get("SANDBOX_AUTH") == "1"
if SANDBOX_AUTH:
    print("⚠️  SANDBOX_AUTH=1 set — auto-login only applies while debug is on")


@app.before_request
def _sandbox_auto_login():
    if not SANDBOX_AUTH or not app.debug:
        return
    if session.get("user_id"):
        return
    from db import get_db
    row = get_db().execute(
        "SELECT id FROM users WHERE google_id='sandbox'"
    ).fetchone()
    if row:
        session["user_id"] = row["id"]


# ── OAuth (delegated to auth module) ─────────────────────────────────────
from auth import init_oauth, auth_bp
init_oauth(app)
app.register_blueprint(auth_bp)


# ── Static cache-busting ────────────────────────────────────────────────
def _git_version():
    """Cache-busting token for /static URLs.

    Prefers the git commit. Falls back to a fingerprint of the static files
    when git is unavailable — a systemd unit with a minimal PATH can't find
    git, and a constant like "dev" would freeze stale assets in browsers once
    /static is served with a long cache lifetime.
    """
    root = os.path.dirname(os.path.abspath(__file__))
    for exe in ("git", "/usr/bin/git", "/usr/local/bin/git"):
        try:
            out = subprocess.check_output(
                [exe, "rev-parse", "--short", "HEAD"],
                cwd=root, text=True, stderr=subprocess.DEVNULL,
            ).strip()
            if out:
                return out
        except Exception:
            continue

    try:
        digest = hashlib.sha256()
        static_dir = os.path.join(root, "static")
        for name in sorted(os.listdir(static_dir)):
            st = os.stat(os.path.join(static_dir, name))
            digest.update(f"{name}:{st.st_size}:{st.st_mtime_ns}".encode())
        return digest.hexdigest()[:7]
    except Exception:
        return "dev"

VERSION = _git_version()

@app.context_processor
def inject_version():
    return dict(version=VERSION)


# ── Remaining blueprints ────────────────────────────────────────────────
from api.clinics import clinics_bp
app.register_blueprint(clinics_bp)

from api.logs import logs_bp
app.register_blueprint(logs_bp)

from api.reports import reports_bp
app.register_blueprint(reports_bp)

from api.tracker import tracker_bp
app.register_blueprint(tracker_bp)

from line.webhook import line_bp
app.register_blueprint(line_bp)

from line.bind import line_bind_bp
app.register_blueprint(line_bind_bp)

init_db()

if __name__ == "__main__":
    print("🦷 Dental Worklog running at http://localhost:5199")
    app.run(host="127.0.0.1", port=5199, debug=True)
