-- 011: LINE chat conversation state for guided Quick Reply flow
-- Tracks in-progress guided logging session per LINE user

CREATE TABLE IF NOT EXISTS line_conversations (
    line_user_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    clinic_name TEXT,
    hours REAL,
    income REAL,
    expense REAL DEFAULT 0,
    date_str TEXT,
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
