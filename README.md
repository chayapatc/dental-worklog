# Dental Worklog

A web app for a dentist to log clinic work hours, income, and expenses, then rank which clinic returns the best net profit.

## Features

### Clinics
- Create, edit, and soft-delete dental clinics
- Assign a color to each clinic (used in charts)
- Soft-delete: hides clinic from lists but preserves existing work logs

### Work Logs
- Log work sessions: clinic, date, hours, income, and expense (lab fees, materials)
- Hard-delete individual log entries with confirmation dialog
- Paginated recent entries (20 per page) showing gross, expense, and net hourly rate
- Export all logs as CSV with one click

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
- Migrations: `001_initial_schema` → `002_legacy_user` → `003_user_id_indexes` → `004_clinic_soft_delete` → `005_clinic_color` → `006_worklog_expense`

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

All `/api/*` routes require authentication (401 if not logged in).

## Hosting & Deployment

### Local Development
```bash
python3 app.py
# Open http://localhost:5199
```

### Production (Google Cloud Always Free)
```
VM:     e2-micro, us-central1-a
IP:     35.253.110.126 (static)
URL:    https://35-253-110-126.nip.io/
Server: nginx → gunicorn → Flask
SSL:    Let's Encrypt via certbot (auto-renews)
Backup: Daily to GCS bucket (30-day retention)
Cost:   $0/month
```

### Environment
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` — Google OAuth credentials
- `SECRET_KEY` — Flask session encryption (required for OAuth)
- `.env` file loads automatically via python-dotenv
- `.env.example` contains placeholder values (safe to commit)
