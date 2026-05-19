-- 006: Add expense column to work_logs for tracking costs (lab fees, materials, etc.)
-- Default 0 so existing data is unaffected

ALTER TABLE work_logs ADD COLUMN expense REAL NOT NULL DEFAULT 0;
