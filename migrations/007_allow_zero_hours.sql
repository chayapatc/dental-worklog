-- 007: Allow hours >= 0 (previously hours > 0 required).
-- SQLite cannot ALTER CHECK constraints. Must recreate the table.

PRAGMA foreign_keys=OFF;

CREATE TABLE work_logs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 0 REFERENCES users(id) ON DELETE CASCADE,
    clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    hours REAL NOT NULL DEFAULT 0 CHECK(hours >= 0),
    income REAL NOT NULL DEFAULT 0 CHECK(income >= 0),
    expense REAL NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

INSERT INTO work_logs_new SELECT id, user_id, clinic_id, date, hours, income, expense, created_at FROM work_logs;

DROP TABLE work_logs;

ALTER TABLE work_logs_new RENAME TO work_logs;

CREATE INDEX IF NOT EXISTS idx_logs_date ON work_logs(date);
CREATE INDEX IF NOT EXISTS idx_logs_clinic ON work_logs(clinic_id);

PRAGMA foreign_keys=ON;
