"""Guided logging flow — Quick Reply state machine.

Public interface (3 functions):
  handle_guided_message(db, text, line_user_id, reply_token, user_id) -> Response | None
  start_guided_flow(db, line_user_id, user_id) -> dict
  is_in_guided_flow(db, line_user_id) -> bool

Everything else is private implementation.
"""

import os, re
from datetime import datetime, timezone, timedelta
from config import APP_URL
from line.parser import _fuzzy_match_clinic
from line.helpers import _line_reply, _line_quick_reply
from db import get_db

# ── Internal constants ────────────────────────────────────────────────────

_STATE_CLINIC = "awaiting_clinic"
_STATE_NEW_CLINIC = "awaiting_new_clinic"
_STATE_HOURS = "awaiting_hours"
_STATE_INCOME = "awaiting_income"
_STATE_DATE = "awaiting_date"

_TRIGGER_NEW_CLINIC = "__new_clinic__"
_TRIGGER_LOG_TODAY = "__log_today__"
_TRIGGER_HOURS_PREFIX = "__hours_"
_TRIGGER_DATE_TODAY = "__date_today__"
_TRIGGER_DATE_YESTERDAY = "__date_yesterday__"

# ── Public interface (3 functions) ────────────────────────────────────────

def handle_guided_message(db, text: str, line_user_id: str, reply_token: str, user_id: int):
    """Process one turn of the guided flow. Returns reply dict if handled, None if not."""
    return _handle_guided_flow(db, reply_token, line_user_id, user_id, text)


def start_guided_flow(db, line_user_id: str, user_id: int) -> dict:
    """Begin guided flow and return the opening Quick Reply message.
    Caller sends this via _line_push or _line_reply."""
    clinics = db.execute(
        "SELECT id, name FROM clinics WHERE user_id = ? AND deleted = 0 ORDER BY name",
        (user_id,)
    ).fetchall()
    items = [(c["name"], c["name"]) for c in clinics][:12]
    items.append(("+ Add New Clinic", _TRIGGER_NEW_CLINIC))
    _set_conversation(db, line_user_id, _STATE_CLINIC)
    return _line_quick_reply(
        "✅ Account linked!\n\nLet's log your first entry.\n\nWhich clinic?",
        items
    )


def is_in_guided_flow(db, line_user_id: str) -> bool:
    """Check if this LINE user has an active guided flow session."""
    return _get_conversation(db, line_user_id) is not None


# ── Private implementation ────────────────────────────────────────────────

def _auto_create_clinic(db, user_id: int, name: str) -> dict:
    cursor = db.execute(
        "INSERT INTO clinics (user_id, name) VALUES (?, ?)",
        (user_id, name)
    )
    db.commit()
    return {"id": cursor.lastrowid, "name": name}


def _get_conversation(db, line_user_id: str) -> dict | None:
    row = db.execute(
        "SELECT * FROM line_conversations WHERE line_user_id = ?",
        (line_user_id,)
    ).fetchone()
    return dict(row) if row else None


def _set_conversation(db, line_user_id: str, state: str, **kwargs):
    data = {
        "line_user_id": line_user_id,
        "state": state,
        "clinic_name": kwargs.get("clinic_name"),
        "hours": kwargs.get("hours"),
        "income": kwargs.get("income"),
        "expense": kwargs.get("expense", 0),
        "date_str": kwargs.get("date_str"),
    }
    db.execute(
        """INSERT OR REPLACE INTO line_conversations
           (line_user_id, state, clinic_name, hours, income, expense, date_str, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))""",
        (data["line_user_id"], data["state"], data["clinic_name"],
         data["hours"], data["income"], data["expense"], data["date_str"])
    )
    db.commit()


def _clear_conversation(db, line_user_id: str):
    db.execute("DELETE FROM line_conversations WHERE line_user_id = ?", (line_user_id,))
    db.commit()


def _is_first_log(db, user_id: int) -> bool:
    row = db.execute(
        "SELECT first_log_done FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return not (row and row["first_log_done"])


def _mark_first_log_done(db, user_id: int):
    db.execute("UPDATE users SET first_log_done = 1 WHERE id = ?", (user_id,))
    db.commit()


def _build_work_date(date_str: str | None, tz) -> str | None:
    if date_str:
        month, day = date_str.split("-")
        year = datetime.now(tz).year
        try:
            full = f"{year}-{month}-{day}"
            datetime.strptime(full, "%Y-%m-%d")
            return full
        except ValueError:
            return None
    return datetime.now(tz).strftime("%Y-%m-%d")


def _handle_guided_flow(db, reply_token, line_user_id, user_id, text):
    conv = _get_conversation(db, line_user_id)
    bangkok_tz = timezone(timedelta(hours=7))

    # Entry: start guided flow
    if text.strip() == _TRIGGER_LOG_TODAY or (
        conv is None and text.strip().lower() in ("log", "🕐 log today", "log today")
    ):
        clinics = db.execute(
            "SELECT id, name FROM clinics WHERE user_id = ? AND deleted = 0 ORDER BY name",
            (user_id,)
        ).fetchall()
        items = [(c["name"], c["name"]) for c in clinics][:12]
        items.append(("+ Add New Clinic", _TRIGGER_NEW_CLINIC))
        _set_conversation(db, line_user_id, _STATE_CLINIC)
        _line_reply(reply_token, [_line_quick_reply("Which clinic?", items)])
        return

    if conv is None:
        return False  # Not in guided flow

    state = conv["state"]

    # State: AWAITING_CLINIC
    if state == _STATE_CLINIC:
        if text.strip() == _TRIGGER_NEW_CLINIC:
            _set_conversation(db, line_user_id, _STATE_NEW_CLINIC)
            _line_reply(reply_token, [{"type": "text", "text": "Type the new clinic name:"}])
            return
        clinics = db.execute(
            "SELECT id, name FROM clinics WHERE user_id = ? AND deleted = 0",
            (user_id,)
        ).fetchall()
        matched = _fuzzy_match_clinic(text.strip(), [dict(c) for c in clinics])
        if not matched:
            matched = _auto_create_clinic(db, user_id, text.strip())
        _set_conversation(db, line_user_id, _STATE_HOURS, clinic_name=matched["name"])
        items = [
            ("1h", _TRIGGER_HOURS_PREFIX + "1"),
            ("2h", _TRIGGER_HOURS_PREFIX + "2"),
            ("3h", _TRIGGER_HOURS_PREFIX + "3"),
            ("4h", _TRIGGER_HOURS_PREFIX + "4"),
            ("5h", _TRIGGER_HOURS_PREFIX + "5"),
            ("6h", _TRIGGER_HOURS_PREFIX + "6"),
            ("7h", _TRIGGER_HOURS_PREFIX + "7"),
            ("8h", _TRIGGER_HOURS_PREFIX + "8"),
            ("Custom", _TRIGGER_HOURS_PREFIX + "custom"),
        ]
        _line_reply(reply_token, [_line_quick_reply(f"{matched['name']} — how many hours?", items)])
        return

    # State: AWAITING_NEW_CLINIC
    if state == _STATE_NEW_CLINIC:
        name = text.strip()
        if not name:
            _line_reply(reply_token, [{"type": "text", "text": "Please type a clinic name:"}])
            return
        clinics = db.execute(
            "SELECT id, name FROM clinics WHERE user_id = ? AND deleted = 0",
            (user_id,)
        ).fetchall()
        matched = _fuzzy_match_clinic(name, [dict(c) for c in clinics])
        if not matched:
            matched = _auto_create_clinic(db, user_id, name)
        _set_conversation(db, line_user_id, _STATE_HOURS, clinic_name=matched["name"])
        items = [
            ("1h", _TRIGGER_HOURS_PREFIX + "1"),
            ("2h", _TRIGGER_HOURS_PREFIX + "2"),
            ("3h", _TRIGGER_HOURS_PREFIX + "3"),
            ("4h", _TRIGGER_HOURS_PREFIX + "4"),
            ("5h", _TRIGGER_HOURS_PREFIX + "5"),
            ("6h", _TRIGGER_HOURS_PREFIX + "6"),
            ("7h", _TRIGGER_HOURS_PREFIX + "7"),
            ("8h", _TRIGGER_HOURS_PREFIX + "8"),
            ("Custom", _TRIGGER_HOURS_PREFIX + "custom"),
        ]
        _line_reply(reply_token, [_line_quick_reply(f"{matched['name']} added! How many hours?", items)])
        return

    # State: AWAITING_HOURS
    if state == _STATE_HOURS:
        t = text.strip()
        if t.startswith(_TRIGGER_HOURS_PREFIX):
            val = t[len(_TRIGGER_HOURS_PREFIX):]
            if val == "custom":
                _line_reply(reply_token, [{"type": "text", "text": "Type the hours (e.g. 4.5):"}])
                return
            hours = float(val)
        else:
            try:
                hours = float(t)
            except ValueError:
                _line_reply(reply_token, [{"type": "text", "text": "Please enter a number (e.g. 4 or 4.5):"}])
                return
        _set_conversation(db, line_user_id, _STATE_INCOME,
                         clinic_name=conv["clinic_name"], hours=hours)
        _line_reply(reply_token, [{"type": "text", "text": "Income today? (type amount, e.g. 5000)"}])
        return

    # State: AWAITING_INCOME
    if state == _STATE_INCOME:
        try:
            income = float(text.strip())
        except ValueError:
            _line_reply(reply_token, [{"type": "text", "text": "Please enter a number (e.g. 5000):"}])
            return
        _set_conversation(db, line_user_id, _STATE_DATE,
                         clinic_name=conv["clinic_name"], hours=conv["hours"], income=income)
        items = [
            ("Today", _TRIGGER_DATE_TODAY),
            ("Yesterday", _TRIGGER_DATE_YESTERDAY),
        ]
        _line_reply(reply_token, [_line_quick_reply(
            "Date? (type 22 or 22/5)", items
        )])
        return

    # State: AWAITING_DATE
    if state == _STATE_DATE:
        t = text.strip()
        if t == _TRIGGER_DATE_TODAY:
            date_str = None
        elif t == _TRIGGER_DATE_YESTERDAY:
            yesterday = datetime.now(bangkok_tz) - timedelta(days=1)
            date_str = f"{yesterday.month:02d}-{yesterday.day:02d}"
        else:
            m = re.match(r'^(\d{1,2})/(\d{1,2})$', t)
            if m:
                day, month = int(m.group(1)), int(m.group(2))
                if 1 <= day <= 31 and 1 <= month <= 12:
                    date_str = f"{month:02d}-{day:02d}"
                else:
                    _line_reply(reply_token, [{"type": "text", "text": "Invalid date. Try: 22/5 or just 22"}])
                    return
            elif re.match(r'^\d{1,2}$', t):
                day = int(t)
                if 1 <= day <= 31:
                    date_str = f"{datetime.now(bangkok_tz).month:02d}-{day:02d}"
                else:
                    _line_reply(reply_token, [{"type": "text", "text": "Invalid day. Try 1-31."}])
                    return
            else:
                _line_reply(reply_token, [{"type": "text", "text": "Type a day (22) or d/m (22/5) or tap Today:"}])
                return

        work_date = _build_work_date(date_str, bangkok_tz)
        if work_date is None:
            _line_reply(reply_token, [{"type": "text", "text": "Invalid date. Try again."}])
            return

        clinic_name = conv["clinic_name"]
        hours = float(conv["hours"])
        income = float(conv["income"])
        expense = float(conv.get("expense", 0))

        clinics = db.execute(
            "SELECT id, name FROM clinics WHERE user_id = ? AND deleted = 0",
            (user_id,)
        ).fetchall()
        matched = _fuzzy_match_clinic(clinic_name, [dict(c) for c in clinics])
        if not matched:
            matched = _auto_create_clinic(db, user_id, clinic_name)

        db.execute(
            "INSERT INTO work_logs (user_id, clinic_id, date, hours, income, expense) VALUES (?,?,?,?,?,?)",
            (user_id, matched["id"], work_date, hours, income, expense)
        )
        db.commit()

        net = income - expense
        rate = f"฿{int(net/hours)}/h" if hours > 0 else "-"
        is_first = _is_first_log(db, user_id)
        _mark_first_log_done(db, user_id)
        _clear_conversation(db, line_user_id)

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
        return

    return False  # Unknown state
