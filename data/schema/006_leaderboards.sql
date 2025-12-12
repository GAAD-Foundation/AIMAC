-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/006_leaderboards.sql
-- =============================================================================

-- leaderboards: The header for a specific, point-in-time report.
-- Purpose: Defines the schema for the `leaderboards` table, which stores
--   header information about the leaderboard.

-- =============================================================================
-- TABLE DEFINITION
-- =============================================================================

CREATE TABLE IF NOT EXISTS "leaderboards" (
    "pk"                INTEGER PRIMARY KEY AUTOINCREMENT, -- primary key
    "model_sets_fk_pk"  INTEGER NOT NULL REFERENCES "model_sets" ("pk") ON DELETE CASCADE, -- the set of models that were used to generate this leaderboard
    "total_cost_usd"    REAL    NOT NULL CHECK ("total_cost_usd" >= 0), -- the total actual cost to query this leaderboard
    "created_at"        DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    "updated_at"        DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- =============================================================================
-- INDEXES
-- =============================================================================

CREATE INDEX IF NOT EXISTS "idx_leaderboards_modelset_time"
    ON "leaderboards" ("model_sets_fk_pk", "created_at" DESC);

-- =============================================================================
-- TRIGGERS
-- =============================================================================

CREATE TRIGGER IF NOT EXISTS trg_leaderboards_updated_at
    AFTER UPDATE ON "leaderboards"
    FOR EACH ROW
BEGIN
    UPDATE "leaderboards"
    SET "updated_at" = CURRENT_TIMESTAMP
    WHERE "pk" = NEW."pk";
END;