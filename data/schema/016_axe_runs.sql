-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/016_axe_runs.sql
-- =============================================================================

-- This file defines the schema for the 'axe_runs' table, which stores
-- accessibility test results from axe-core analysis of generated HTML.
--
-- Each axe run corresponds to one model_categories_request and contains:
-- - Violation counts (total, critical, serious) for WCAG compliance
-- - Weighted accessibility score using logarithmic dampening
-- - Path to the full JSON report on disk
-- - Timestamp when the analysis was performed
--
-- Only successful requests (HTTP 200) are analyzed with axe-core.
-- Failed requests are not stored in this table.

-- =============================================================================
-- TABLE DEFINITION
-- =============================================================================

CREATE TABLE IF NOT EXISTS "axe_runs" (
    "pk"                          INTEGER PRIMARY KEY AUTOINCREMENT, -- Primary key for the axe run record

    -- Foreign key to the request that was analyzed (one-to-one relationship)
    "model_categories_request_fk_pk" INTEGER NOT NULL UNIQUE REFERENCES "model_categories_request" ("pk") ON DELETE CASCADE,

    -- Accessibility violation counts (WCAG AA only: serious + critical)
    "total_violations"            INTEGER NOT NULL, -- Total number of accessibility violations found
    "critical_violations"         INTEGER NOT NULL, -- Number of critical WCAG violations (complete barriers)
    "serious_violations"          INTEGER NOT NULL, -- Number of serious WCAG violations (significant barriers)

    -- Accessibility scoring using logarithmic dampening (lower is better)
    "weighted_score"              REAL NOT NULL,    -- Weighted accessibility score (0.0 = perfect, higher = worse)

    -- Filesystem path to the full axe-core JSON report
    "axe_json_path"               TEXT NOT NULL,    -- Relative path to axe report JSON file

    -- Timestamps for audit trail
    "run_timestamp"               DATETIME NOT NULL, -- When axe-core analysis was performed
    "created_at"                  DATETIME DEFAULT (CURRENT_TIMESTAMP),
    "updated_at"                  DATETIME DEFAULT (CURRENT_TIMESTAMP)

);

-- =============================================================================
-- INDEXES - Performance Optimizations
-- =============================================================================

-- Note: No index needed on model_categories_request_fk_pk - UNIQUE constraint creates one

-- Index for sorting by accessibility score (lower is better)
CREATE INDEX IF NOT EXISTS "idx_axe_runs_weighted_score"
    ON "axe_runs" ("weighted_score" ASC);

-- Index for sorting by violation count (higher is worse)
CREATE INDEX IF NOT EXISTS "idx_axe_runs_total_violations"
    ON "axe_runs" ("total_violations" DESC);

-- =============================================================================
-- TRIGGERS - Timestamp Management
-- =============================================================================

-- Trigger to automatically update the updated_at timestamp when rows are modified
CREATE TRIGGER IF NOT EXISTS trg_axe_runs_updated_at
    AFTER UPDATE ON "axe_runs"
    FOR EACH ROW
BEGIN
    UPDATE "axe_runs"
    SET "updated_at" = CURRENT_TIMESTAMP
    WHERE "pk" = NEW."pk";
END;
