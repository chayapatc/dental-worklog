"""LINE webhook endpoint."""

import json, os
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify
from db import get_db
from line.parser import _parse_log_message, _fuzzy_match_clinic
from line.helpers import _line_reply, _line_push, _line_verify_signature, _line_quick_reply
from line.guided import handle_guided_message, is_in_guided_flow, _clear_conversation, _auto_create_clinic, _build_work_date, _is_first_log, _mark_first_log_done

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LIFF_ID = os.environ.get("LINE_LIFF_ID", "")
APP_URL = os.environ.get("APP_URL", "http://localhost:5199")

line_bp = Blueprint("line_webhook", __name__)

@line_bp.route("/api/line/webhook", methods=["POST"])
def line_webhook():
    """LINE Messaging API webhook endpoint."""
    body = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")

    if LINE_CHANNEL_SECRET and not _line_verify_signature(body, signature):
        return "Invalid signature", 403

    try:
        events = json.loads(body).get("events", [])
    except json.JSONDecodeError:
        return "Invalid JSON", 400

    if not events:
        return "OK", 200

    db = get_db()

    for ev in events:
        ev_type = ev.get("type", "")
        reply_token = ev.get("replyToken", "")
        source = ev.get("source", {})
        line_user_id = source.get("userId", "")

        if not line_user_id:
            continue

        user_row = db.execute(
            "SELECT id, email, name FROM users WHERE line_user_id = ?",
            (line_user_id,)
        ).fetchone()

        # --- Follow event ---
        if ev_type == "follow":
            if user_row:
                msg = (
                    f"Welcome back, {user_row['name']}! 🦷\n\n"
                    f"Reply with your log:\n"
                    f"vela 4 5000\n\n"
                    f"Or type 'log' for guided logging."
                )
            else:
                bind_url = f"https://liff.line.me/{LIFF_ID}" if LIFF_ID else f"{APP_URL}/line/liff-bind"
                msg = (
                    f"Welcome! 🦷\n\n"
                    f"👉 Tap to link your account:\n"
                    f"{bind_url}\n\n"
                    f"After linking, I'll guide you through\n"
                    f"your first log — tap, don't type."
                )
            _line_reply(reply_token, [{"type": "text", "text": msg}])
            continue

        # --- Only text messages beyond this point ---
        if ev_type != "message" or ev.get("message", {}).get("type") != "text":
            continue

        text = ev["message"]["text"].strip()

        # --- Unbound user ---
        if not user_row:
            bind_url = f"https://liff.line.me/{LIFF_ID}" if LIFF_ID else f"{APP_URL}/line/liff-bind"
            _line_reply(reply_token, [{"type": "text", "text": f"👉 Tap to link your account:\n{bind_url}"}])
            continue

        user_id = user_row["id"]

        # --- Try guided flow first ---
        if is_in_guided_flow(db, line_user_id) or text.strip().lower() in ("log", "🕐 log today", "log today") or \
           text.strip().startswith("__"):
            try:
                result = handle_guided_message(db, text, line_user_id, reply_token, user_id)
                if result is not False:
                    continue
            except Exception as e:
                _clear_conversation(db, line_user_id)
                _line_reply(reply_token, [{"type": "text", "text": "Something went wrong. Try again: vela 4 5000"}])
                continue

        # --- Text-based log ---
        parts = text.split(None, 1)
        if len(parts) < 2:
            _line_reply(reply_token, [{"type": "text", "text": (
                "Format: clinic hours income\n"
                "e.g. vela 4 5000\n\n"
                "Or type 'log' for guided logging."
            )}])
            continue

        clinic_input = parts[0]
        rest_text = parts[1]

        parsed = _parse_log_message(rest_text)
        if parsed is None:
            _line_reply(reply_token, [{"type": "text", "text": (
                "Can't parse that. Try:\n"
                "vela 4 5000      → 4h, ฿5,000\n"
                "vela 4 5000 200e  → + expense\n"
                "vela 4 5000 22    → past date, 22nd\n"
                "vela 4 5000 22/5  → past date, May 22\n\n"
                "Or type 'log' for guided logging."
            )}])
            continue

        date_str, hours, income, expense = parsed

        work_date = _build_work_date(date_str, timezone(timedelta(hours=7)))
        if work_date is None:
            _line_reply(reply_token, [{"type": "text", "text": "Invalid date."}])
            continue

        # Find/Auto-create clinic
        clinics = db.execute(
            "SELECT id, name FROM clinics WHERE user_id = ? AND deleted = 0",
            (user_id,)
        ).fetchall()
        clinic_list = [dict(c) for c in clinics]

        matched = _fuzzy_match_clinic(clinic_input, clinic_list)
        if not matched:
            if len(clinic_list) == 0:
                # No clinics yet — auto-create
                matched = _auto_create_clinic(db, user_id, clinic_input)
            else:
                names = ", ".join(c["name"] for c in clinic_list)
                _line_reply(reply_token, [{"type": "text", "text": (
                    f"'{clinic_input}' not found.\n"
                    f"Your clinics: {names}\n\n"
                    f"Or reply with a new name to add it."
                )}])
                continue

        db.execute(
            "INSERT INTO work_logs (user_id, clinic_id, date, hours, income, expense) VALUES (?,?,?,?,?,?)",
            (user_id, matched["id"], work_date, hours, income, expense)
        )
        db.commit()

        net = income - expense
        rate = f"฿{int(net/hours)}/h" if hours > 0 else "-"
        is_first = _is_first_log(db, user_id)
        _mark_first_log_done(db, user_id)

        if is_first:
            _line_reply(reply_token, [{"type": "text", "text": (
                f"🎉 Done!\n"
                f"{matched['name']} — {hours}h, ฿{int(income)}\n"
                f"Net: ฿{int(net)} ({rate})\n\n"
                f"🕐 Log again anytime from the menu.\n\n"
                f"💡 Pro tip: you can also just type:\n"
                f"  vela 4 5000\n"
                f"  vela 4 5000 200e    ← add expense\n"
                f"  vela 4 5000 22      ← past date, 22nd\n"
                f"  vela 4 5000 22/5    ← past date, May 22\n\n"
                f"📋 Clinics: 👉 {APP_URL.rstrip('/')}"
            )}])
        else:
            _line_reply(reply_token, [{"type": "text", "text": (
                f"✓ {work_date} | {matched['name']}\n"
                f"  {hours}h | ฿{int(income)} | exp ฿{int(expense)}\n"
                f"  Net: ฿{int(net)} ({rate})"
            )}])

    return "OK", 200


