-- 010: Track whether user has completed first LINE chat log
-- Used for first-log celebration message vs normal confirmation

ALTER TABLE users ADD COLUMN first_log_done INTEGER DEFAULT 0;
