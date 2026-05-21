-- LINE user binding: add line_user_id to users table for LINE OA integration
-- Allows linking a LINE account to a dental worklog user

ALTER TABLE users ADD COLUMN line_user_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_line_user_id ON users(line_user_id) WHERE line_user_id IS NOT NULL;
