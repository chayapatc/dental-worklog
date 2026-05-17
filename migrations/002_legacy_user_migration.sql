-- 002: Add user_id columns to pre-auth databases (legacy migration)
-- Only runs if clinics or work_logs lack the user_id column

-- Create a legacy user for orphaned data
INSERT OR IGNORE INTO users (google_id, email, name) VALUES ('legacy', '', 'Legacy User');

-- Add user_id to clinics if missing
-- SQLite does not support IF NOT EXISTS for ALTER TABLE, so we check via application logic
-- This migration is safe to re-run: the app checks column existence before ALTER
