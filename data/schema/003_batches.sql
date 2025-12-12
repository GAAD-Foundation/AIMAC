-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/003_batches.sql
-- =============================================================================

-- This file defines the schema for the 'batches' table, which stores
-- operational records of individual `aimac collect` executions. Used in
-- the directory structure under `output` once html, screenshots and
-- axe.json files are generated.

-- =============================================================================
-- TABLE DEFINITION
-- =============================================================================

CREATE TABLE IF NOT EXISTS "batches" (
    -- used in output/{batch_date}/{batch_time}/batch_{batches.id}/{company_slug}/{model_slug}/{category_slug}/{model_categories_request.pk}.(html|png|axe.json)
    "pk"          INTEGER PRIMARY KEY AUTOINCREMENT,
    "batch_date"  INTEGER NOT NULL, -- e.g., 20250823
    "batch_time"  INTEGER NOT NULL, -- e.g., 103015 (NOTE: leading zeros dropped, 090001→90001)
    -- NOTE: batch_time as INTEGER loses leading zeros. Times before 10:00 sort
    -- oddly in directory listings (4522 < 103015 alphabetically). Both Python
    -- insert and SQL view use the same integer, so paths match - this is cosmetic.

    -- useful for historical tracking of batch execution lengths
    "started_at"  DATETIME NOT NULL,
    "completed_at" DATETIME
);