#!/usr/bin/env python3
"""Dental Worklog — Flask + SQLite + Google OAuth (blueprint shell)."""

import os
import secrets

from dotenv import load_dotenv
from flask import Flask
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

from config import SECRET_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from config import LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, LINE_LIFF_ID, LINE_OA_BASIC_ID, APP_URL

app = Flask(__name__)
app.secret_key = SECRET_KEY or secrets.token_hex(32)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.config.update(
    SESSION_COOKIE_SECURE=not app.debug,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# ── OAuth ────────────────────────────────────────────────────────────────
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile https://www.googleapis.com/auth/calendar.readonly"},
)

# ── DB Teardown ─────────────────────────────────────────────────────────
from db import close_db, init_db
app.teardown_appcontext(close_db)


@app.after_request
def add_no_cache_headers(response):
    if response.content_type and "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ── Blueprints ──────────────────────────────────────────────────────────
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

init_db()

if __name__ == "__main__":
    print("🦷 Dental Worklog running at http://localhost:5199")
    app.run(host="127.0.0.1", port=5199, debug=True)
