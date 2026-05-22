# Dental Worklog

A web app for a dentist to log clinic work hours, income, and expenses, then rank which clinic returns the best net profit.

## Features

### Clinics
- Create, edit, and soft-delete dental clinics
- Assign a color to each clinic via preset swatches or custom color picker
- Soft-delete: hides clinic from lists but preserves existing work logs

### Work Logs
- Log work sessions: clinic, date, hours, income, and expense (lab fees, materials)
- Hard-delete individual log entries with confirmation dialog
- Paginated recent entries (20 per page) showing gross, expense, and net hourly rate
- Export all logs as CSV with one click

### Tracker
- Show a monthly calendar, each day show `count` of worklog on that day.
- Link with user's google calendar to show events are on that day.

### LINE Chat Logger
- Connect LINE Official Account to log work entries via chat
- Secure LIFF-based binding (LINE user ID never exposed in URL)
- Binding flow: tap LIFF link in LINE → Google sign-in → auto-bind
- Super concise format: `{clinic} {hours} {income}i? {expense}e? {date}?`
- `h`/`i`/`e` suffixes or positional: `vela 4 5000`, `mjh 1 i1000 e500`, `vela 500e`
- Optional date suffix via `d/m` format: `vela 4 5000 22/5` = May 22 this year
- No date specified → defaults to today (Bangkok time)
- Case-insensitive fuzzy clinic matching (handles typos and partial names)
- Green LINE badge in header when connected

**Setup:** Create LINE OA + Messaging API channel + LIFF app (endpoint: `/line/liff-bind`).
Set `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_CHANNEL_SECRET`, `LINE_LIFF_ID` in `.env`.

### Trends (merged Rate + Income Ranking)
- Metric toggle: **Hourly Rate** or **Net Income**
- Period toggle: **1W** (weekly), **1M** (monthly), **3M** (quarterly), **6M** (half-year)
- Line chart showing historical trends per clinic (color-coded)
- Ranked table of the current period, sorted by the selected metric
- Hourly rate = (total income − total expense) / total hours

### Net Income Report
- Custom date range picker with month-to-date default
- Ranks clinics by total net income within the selected date range
- Table shows hours, gross income, expense, net income, and net hourly rate per clinic

### Monthly P&amp;L
- Year selector (current year down to 3 years back)
- Combo chart: green bars = income, red bars = expense, blue line = net income
- Shows all 12 months even if zero
- Summary line with total income, expenses, and net for the year

### Authentication
- Sign in with Google account via OAuth 2.0 (OpenID Connect)
- Each user's clinics and work logs are private and isolated
- Session persists until logout; logout clears session and returns to login screen
- First-time login auto-creates a user profile from Google account info

## Data Model

- Every clinic belongs to exactly one user (enforced by `user_id` FK)
- Every work log belongs to exactly one user (enforced by `user_id` FK)
- Work logs reference clinics owned by the same user
- All API queries filter by the authenticated user's ID — no cross-user data leakage

## Database Migrations

- All schema changes are done via numbered SQL files in `migrations/`
- `init_db()` only runs the migration runner — never contains inline schema
- Migrations are tracked in the `_migrations` table and run exactly once per database
- All migrations are idempotent: `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ADD COLUMN`, `CREATE INDEX IF NOT EXISTS`
- **Never violate existing data**: no DROP columns, no breaking type changes
- Migrations: `001_initial_schema` → `002_legacy_user` → `003_user_id_indexes` → `004_clinic_soft_delete` → `005_clinic_color` → `006_worklog_expense` → `007_allow_zero_hours` → `008_line_binding` → `009_binding_tokens`

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3 + Flask + SQLite |
| Frontend | Vanilla HTML/CSS/JS + Chart.js (CDN) |
| CSS Framework | Pico CSS v2 (dark theme, responsive) |
| Auth | authlib (Google OAuth 2.0) |
| Database | Single-file SQLite (`dental.db`) |
| Charts | Chart.js 4.4 |

No build step, no bundler, no Node.js required.

## Testing

```bash
python3 -m pytest test_parser.py -v
```

45 branch-coverage unit tests for the LINE message parser and fuzzy clinic matcher.
Pre-commit hook runs them automatically — blocks commit on failure.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/me` | Current user or null |
| GET | `/api/clinics` | List active clinics (with colors) |
| POST | `/api/clinics` | Create clinic (name, color) |
| PUT | `/api/clinics/:id` | Rename clinic / change color |
| DELETE | `/api/clinics/:id` | Soft-delete (hide from list) |
| GET | `/api/logs?page=&per_page=` | Paginated work logs (20 per page) |
| POST | `/api/logs` | Create work log (clinic, date, hours, income, expense) |
| DELETE | `/api/logs/:id` | Hard-delete work log entry |
| GET | `/api/logs/export` | Export all logs as CSV |
| GET | `/api/reports/ranking?period=` | Trends data (weekly/monthly/quarterly/semiyearly) |
| GET | `/api/reports/income-ranking?start=&end=` | Net Income report with date range |
| GET | `/api/reports/monthly-summary?year=` | Monthly P&amp;L: income, expense, net for 12 months |
| GET | `/api/line/status` | LINE binding status for current user |
| POST | `/api/line/bind` | Bind LINE account (Google auth + LIFF) |
| POST | `/api/line/unbind` | Unbind LINE account |
| POST | `/api/line/webhook` | LINE Messaging API webhook (no auth) |
| GET | `/line/liff-bind` | LIFF binding page (opens in LINE in-app browser) |

All `/api/*` routes require authentication (401 if not logged in), except `/api/line/webhook`.

## Hosting & Deployment

### Local Development
```bash
python3 app.py
# Open http://localhost:5199
```

### Environment
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` — Google OAuth credentials
- `SECRET_KEY` — Flask session encryption (required for OAuth)
- `.env` file loads automatically via python-dotenv
- `.env.example` contains placeholder values (safe to commit)
