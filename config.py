"""Application config — single source of truth for environment variables."""

import os

# Flask
SECRET_KEY = os.environ.get("SECRET_KEY", "")
APP_URL = os.environ.get("APP_URL", "http://localhost:5199")

# Google OAuth
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# LINE Messaging API
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_LIFF_ID = os.environ.get("LINE_LIFF_ID", "")
LINE_OA_BASIC_ID = os.environ.get("LINE_OA_BASIC_ID", "")
