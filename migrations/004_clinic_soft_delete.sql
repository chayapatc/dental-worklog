-- 004: Add soft-delete support to clinics
-- deleted=0 means active, deleted=1 means hidden from list
-- Prior work_logs remain intact (FK is not cascaded on soft-delete)

ALTER TABLE clinics ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_clinics_deleted ON clinics(deleted);
