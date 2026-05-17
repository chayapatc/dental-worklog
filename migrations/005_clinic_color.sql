-- 005: Add color column to clinics for chart line coloring

ALTER TABLE clinics ADD COLUMN color TEXT NOT NULL DEFAULT '#38bdf8';
