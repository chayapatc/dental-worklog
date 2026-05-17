-- 003: Add user_id indexes (safe after 002 ensures columns exist)

CREATE INDEX IF NOT EXISTS idx_logs_user ON work_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_clinics_user ON clinics(user_id);
