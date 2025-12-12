-- =============================================================================
-- File: data/schema/015_model_categories_summary.sql
-- =============================================================================

-- model_categories_summary: The rows of a specific report, one for each model.
-- Notes:
--   - Categories are immutable and fixed at 28 enabled items.
--   - `is_complete` is true when all 28 categories have valid SUCCESS data.
--   - `categories_array` stores the list of category PKs that were successfully
--     collected for this model in this leaderboard. This enables fast diffing
--     for partial collections without scanning raw response tables.

-- =============================================================================
-- TABLE DEFINITION
-- =============================================================================

CREATE TABLE IF NOT EXISTS "model_categories_summary" (
    "pk"                    INTEGER PRIMARY KEY AUTOINCREMENT, -- primary key
    "leaderboards_fk_pk"    INTEGER NOT NULL REFERENCES "leaderboards" ("pk") ON DELETE CASCADE,
    "models_fk_pk"           INTEGER NOT NULL REFERENCES "models" ("pk") ON DELETE CASCADE,

    -- ranking (1 = best). Tiebreaker order when median_weighted_score is equal:
    -- 1. median_weighted_score (AIMAC Score) - lower is better
    -- 2. avg_axe_score - lower is better (fewer average violations)
    -- 3. total_violations - lower is better
    -- 4. total_cost_usd - lower is better
    -- 5. model_pk - stable ordering
    -- See: src/aimac/database/_leaderboards.py::_compute_and_update_rankings()
    "ranking"               INTEGER NOT NULL,

    -- scoring aggregates (SUCCESS-only instances)
    "median_weighted_score" REAL    NOT NULL, -- computed over axe_run weighted_score per (model, category)
    "stddev_weighted_score" REAL    DEFAULT NULL, -- sample standard deviation across 28 categories
    "p90_weighted_score"    REAL    DEFAULT NULL, -- 90th percentile across 28 categories

    -- cost aggregates for the exact input instances used by the snapshot
    "total_cost_usd"        REAL    NOT NULL, -- total cost per page is provided by openrouter, tally them up here
    "avg_cost_per_page"     REAL    NOT NULL, -- Used for affordability index in value metrics

    -- Coverage fields
    "is_complete"           BOOLEAN NOT NULL DEFAULT 0, -- true when 28/28 categories succeeded
    "categories_array"      TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid("categories_array")), -- JSON array of category PKs

    -- Accessibility aggregates (latest-success per pair across all batches)
    "avg_axe_score"         REAL    DEFAULT NULL,
    "total_violations"      INTEGER DEFAULT NULL,

    "created_at"            DATETIME DEFAULT (CURRENT_TIMESTAMP),
    "updated_at"            DATETIME DEFAULT (CURRENT_TIMESTAMP)

);

-- =============================================================================
-- INDEXES
-- =============================================================================

CREATE INDEX IF NOT EXISTS "idx_mcs_leaderboard_rank"
    ON "model_categories_summary" ("leaderboards_fk_pk", "ranking");

CREATE UNIQUE INDEX IF NOT EXISTS "ux_mcs_leaderboard_model"
    ON "model_categories_summary" ("leaderboards_fk_pk", "models_fk_pk");

-- =============================================================================
-- TRIGGERS
-- =============================================================================

CREATE TRIGGER IF NOT EXISTS trg_model_categories_summary_updated_at
    AFTER UPDATE ON "model_categories_summary"
    FOR EACH ROW
BEGIN
    UPDATE "model_categories_summary"
    SET "updated_at" = CURRENT_TIMESTAMP
    WHERE "pk" = NEW."pk";
END;
