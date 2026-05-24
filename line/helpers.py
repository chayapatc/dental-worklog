"""LINE Messaging API helpers — reply, push, signature verification, Quick Reply."""

import hmac, hashlib, base64
import requests as http_requests
import os

# Config loaded from app environment
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")

# ── LINE Chat Logger ─────────────────────────────────────────────────────

def _line_verify_signature(body: bytes, signature: str) -> bool:
    """Verify LINE webhook signature using HMAC-SHA256."""
    if not LINE_CHANNEL_SECRET:
        return False
    import base64
    expected = base64.b64encode(
        hmac.new(LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature)


def _line_reply(reply_token: str, messages: list):
    """Send reply message via LINE Messaging API."""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return
    try:
        resp = http_requests.post(
            "https://api.line.me/v2/bot/message/reply",
            json={"replyToken": reply_token, "messages": messages},
            headers={
                "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=5,
        )
    except Exception:
        pass  # Log silently — don't crash webhook on reply failure


def _line_push(user_id: str, messages: list):
    """Send push message to a LINE user."""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return
    try:
        http_requests.post(
            "https://api.line.me/v2/bot/message/push",
            json={"to": user_id, "messages": messages},
            headers={
                "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=5,
        )
    except Exception:
        pass


# ── Guided Logging Flow (Quick Reply) ─────────────────────────────────────


def _line_quick_reply(text: str, items: list) -> dict:
    """Build a LINE text message with Quick Reply buttons."""
    return {
        "type": "text",
        "text": text,
        "quickReply": {
            "items": [
                {"type": "action", "action": {"type": "message", "label": label, "text": text}}
                for label, text in items
            ]
        }
    }


