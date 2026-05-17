# Goal
- App for a dentist to log their clinic workhours and income to rank which clinic returns best

# User
- A dentist

# Use cases
- Create a list of dental clinics
- Log work hour contains clinic, hours, income and working date
- Edit a previously logged work entry
- Delete a work log entry
- Delete a clinic (cascades to its work logs)
- View a ranking report which clinic returns best to worst monthly and weekly
- View a weekly/monthly avg. trend of each clinic
- Export work logs as CSV for external analysis

# Data Model & Ownership
- Every clinic belongs to exactly one user (enforced by `user_id` FK)
- Every work log belongs to exactly one user (enforced by `user_id` FK)
- A work log references a clinic that also belongs to the same user
- All API queries filter by the authenticated user's ID — no cross-user data leakage
- Database-level enforcement: `clinics.user_id NOT NULL REFERENCES users(id)` and
  `work_logs.user_id NOT NULL REFERENCES users(id)`

# Authentication
- Sign in with Google account via OAuth 2.0 (OpenID Connect)
- Each user's clinics and work logs are private and isolated
- Session persists until logout or browser close
- Logout clears session and returns to login screen
- First-time login auto-creates a user profile from Google account info

# Database Schema & Migrations
- All schema changes MUST be done via numbered SQL migration files in `migrations/`
- Never modify `init_db()` to contain inline schema — it only runs the migration runner
- Migrations are tracked in the `_migrations` table and run exactly once per DB
- All migrations must be idempotent (use `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ADD COLUMN`, `CREATE INDEX IF NOT EXISTS`)
- **Never violate existing data** — never DROP columns, never change column types in breaking ways, always use ALTER TABLE ADD COLUMN with safe defaults
- Migration files are applied in numeric order

# Tech Stack
- Backend: Python 3 + Flask + SQLite
- Frontend: Vanilla HTML/CSS/JS + Chart.js (CDN)
- Auth: authlib (Google OAuth)
- Database: Single-file SQLite (dental.db)
- No build step, no bundler, no Node.js required

# Hosting & Deployment
- Development: `python3 app.py` runs on http://localhost:5199
- OAuth requires `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` env vars
- OAuth redirect URI must be configured in Google Cloud Console
- Production: deploy behind a reverse proxy (nginx/Caddy) with HTTPS
- Set `SECRET_KEY` env var for session encryption in production
- Database is self-contained; backup by copying `dental.db`
