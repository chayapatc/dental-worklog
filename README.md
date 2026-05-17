# Dental Worklog

A web app for a dentist to log clinic work hours and income, then rank which clinic returns the best hourly rate.

## Features

### Clinics
- Create, edit, and soft-delete dental clinics
- Assign a color to each clinic (used in ranking charts)
- Soft-delete: hides clinic from lists but preserves existing work logs

### Work Logs
- Log work sessions: clinic, date, hours, and income
- Hard-delete individual log entries with confirmation
- Recent entries table shows computed hourly rate per session

### Ranking Report
- Toggle between **1W** (weekly), **1M** (monthly), **3M** (quarterly), and **6M** (half-year) periods
- Line chart showing historical hourly-rate trends per clinic (color-coded)
- Ranked table of the current period, sorted by average hourly rate
- Clear labels: chart shows trend, table shows current period with exact date

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
- Database-level enforcement: `clinics.user_id NOT NULL REFERENCES users(id)` and `work_logs.user_id NOT NULL REFERENCES users(id)`

## Database Migrations

- All schema changes are done via numbered SQL files in `migrations/`
- `init_db()` only runs the migration runner — never contains inline schema
- Migrations are tracked in the `_migrations` table and run exactly once per database
- All migrations are idempotent: `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ADD COLUMN`, `CREATE INDEX IF NOT EXISTS`
- **Never violate existing data**: no DROP columns, no breaking type changes, always `ADD COLUMN` with safe defaults
- Migration files apply in numeric order: `001_initial_schema.sql`, `002_legacy_user_migration.sql`, `003_user_id_indexes.sql`, `004_clinic_soft_delete.sql`, `005_clinic_color.sql`

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
| GET | `/api/logs` | List recent work logs |
| POST | `/api/logs` | Create work log entry |
| DELETE | `/api/logs/:id` | Hard-delete work log entry |
| GET | `/api/reports/ranking?period=` | Ranking report (weekly/monthly/quarterly/semiyearly) |

All `/api/*` routes require authentication (401 if not logged in).

## Hosting & Deployment

### Local Development
```bash
python3 app.py
# Open http://localhost:5199
```

### Environment
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` — Google OAuth credentials
- `SECRET_KEY` — Flask session encryption (auto-generated if not set)
- `.env` file loads automatically via python-dotenv
- `.env.example` contains placeholder values (safe to commit)

### PythonAnywhere
See `DEPLOY.md` for step-by-step deployment instructions.
URL: `https://chayapatc.pythonanywhere.com`
