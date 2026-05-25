# Dental Worklog — Project Context

> Read this first. 60 seconds to understand the project.

## What

A web app for a dentist to log clinic work hours and income, then rank which clinic returns best. Dual interface: web app + LINE chat bot.

## Domain Glossary

| Term | Meaning |
|------|---------|
| **Clinic** | A dental workplace. Has name, color, belongs to one user. Soft-deleted. |
| **Work Log** | One shift at a clinic: date, hours, income, expense. Belongs to one user + one clinic. |
| **Net Income** | income − expense |
| **Hourly Rate** | net income / hours |
| **LINE OA** | LINE Official Account — the chat bot |
| **LIFF** | LINE Front-end Framework — embeds web pages inside LINE app |
| **Binding** | Linking a LINE account to a Dental Worklog user account |
| **Guided Flow** | Step-by-step Quick Reply logging (tap, don't type) |
| **Quick Reply** | LINE buttons that send a hidden trigger text when tapped |
| **Trigger** | `__new_clinic__`, `__hours_4`, `__date_today__` — hidden strings from Quick Reply buttons |

## Architecture

```
app.py             (62 lines)   Flask shell + blueprint registration
config.py          (17 lines)   Single source of truth for all env vars
db.py              (81 lines)   SQLite connection + migration runner
auth.py            (106 lines)  OAuth routes + login_required + google client

core/              Domain logic (zero Flask/LINE dependencies)
  parser.py        (151 lines)  parse_log_message(), fuzzy_match_clinic() — 48 tests

api/               REST API blueprints
  clinics.py       (87 lines)   Clinic CRUD
  logs.py          (203 lines)  Work log CRUD + CSV export + PUT for inline edit
  reports.py       (227 lines)  Ranking, trends, P&L reports
  tracker.py       (112 lines)  Calendar + Google Calendar events

line/              LINE chat bot blueprints
  helpers.py       (73 lines)   _line_reply(), _line_push(), _line_verify_signature(), _line_quick_reply()
  parser.py        (8 lines)    Backward-compat re-exports from core.parser
  guided.py        (326 lines)  Quick Reply state machine — 3 public: handle_guided_message, start_guided_flow, is_in_guided_flow
  webhook.py       (183 lines)  LINE webhook dispatch + text logging fallback
  bind.py          (198 lines)  LIFF binding routes + post-bind push

templates/
  index.html       SPA — login, nav, all views
  liff_bind.html   LIFF entry — auto-login or bind
  line_confirm_bind.html  Post-bind confirmation with "Back to LINE Chat" button

static/
  app.js           Main application JS
```

## Key Design Decisions

1. **Blueprints, not monolith** — each domain gets its own file
2. **config.py is the only place that reads os.environ**
3. **core/parser.py has zero LINE dependencies** — usable by web UI in future
4. **Guided flow has 3 public functions** — internals are private
5. **auth.py owns the Google OAuth client** — no circular imports
6. **Migrations are numbered SQL files** — idempotent, tracked in `_migrations` table
7. **Never DROP columns, never break existing data**
8. **No commit/push/deploy without user approval**

## Tech

| Layer | Tech |
|-------|------|
| Backend | Python 3 + Flask + SQLite |
| Frontend | Vanilla HTML/CSS/JS + Chart.js (CDN) + Pico CSS v2 dark |
| Auth | authlib (Google OAuth 2.0) |
| LINE | LIFF v2 + Messaging API |
| Host | GCP Compute Engine + Nginx + Gunicorn |
| Domain | 35-253-110-126.nip.io |

## Setup

```bash
# .env required vars:
SECRET_KEY, APP_URL
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, LINE_LIFF_ID, LINE_OA_BASIC_ID

# Run
python3 app.py  # → http://localhost:5199

# Test
python3 -m pytest test_parser.py -q  # 48 tests
```

## LINE Flow (quick reference)

```
Follow OA → "Tap to link" → LIFF page → Google sign-in → bind
→ Push: "Which clinic?" with Quick Reply → guided 4-step: clinic → hours → income → date → 🎉
→ Pro tip reveals text shorthand: vela 4 5000

Daily: type "log" → guided flow, or type "vela 4 5000" → instant
```

## Current LIMITATIONS

- CSV export opens as text in LINE WebView (no download)
- No expense step in guided flow (text shorthand only)
- Rich Menu not configured yet
