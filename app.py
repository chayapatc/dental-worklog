#!/usr/bin/env python3
"""Dental Worklog — Flask + SQLite + Google OAuth (blueprint shell)."""

import os
import secrets

from dotenv import load_dotenv
from flask import Flask
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()  # load .env file into os.environ

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# Trust proxy headers (Nginx terminates SSL)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Secure session cookies
app.config.update(
    SESSION_COOKIE_SECURE=not app.debug,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# ── Config (loaded by sub-modules via os.environ) ─────────────────────────
# Used by line/helpers.py and line/bind.py
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LIFF_ID = os.environ.get("LINE_LIFF_ID", "")
LINE_OA_BASIC_ID = os.environ.get("LINE_OA_BASIC_ID", "")
APP_URL = os.environ.get("APP_URL", "http://localhost:5199")

# ── OAuth ────────────────────────────────────────────────────────────────
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile https://www.googleapis.com/auth/calendar.readonly"},
)

# ── Database teardown ────────────────────────────────────────────────────
from db import close_db, init_db
app.teardown_appcontext(close_db)


@app.after_request
def add_no_cache_headers(response):
    """Prevent LINE WebView caching."""
    if response.content_type and "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ── Blueprint Registration ───────────────────────────────────────────────
from auth import auth_bp
app.register_blueprint(auth_bp)

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

# Initialize DB on import (for WSGI/production) — idempotent
init_db()

if __name__ == "__main__":
    print("🦷 Dental Worklog running at http://localhost:5199")
    app.run(host="127.0.0.1", port=5199, debug=True)
