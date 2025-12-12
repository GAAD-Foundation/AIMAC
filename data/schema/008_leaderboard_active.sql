-- =============================================================================
-- File: data/schema/008_leaderboard_active.sql
-- =============================================================================

-- leaderboard_active: Singleton pointer to the currently active leaderboard.
-- Ensures exactly one active leaderboard at a time via pk CHECK (pk = 1).
-- This avoids boolean flags spread across rows and provides a clear audit trail.

-- =============================================================================
-- TABLE DEFINITION
-- =============================================================================

CREATE TABLE IF NOT EXISTS "leaderboard_active" (
    "pk"                 INTEGER PRIMARY KEY CHECK (pk = 1),
    "leaderboards_fk_pk" INTEGER NOT NULL UNIQUE
        REFERENCES "leaderboards" ("pk") ON DELETE CASCADE,

    -- Timestamps (created_at is row creation time, not activation time)
    "created_at"         DATETIME DEFAULT (CURRENT_TIMESTAMP),
    "updated_at"         DATETIME DEFAULT (CURRENT_TIMESTAMP)
);

-- =============================================================================
-- TRIGGERS
-- =============================================================================

CREATE TRIGGER IF NOT EXISTS trg_leaderboard_active_updated_at
    AFTER UPDATE ON "leaderboard_active"
    FOR EACH ROW
BEGIN
    UPDATE "leaderboard_active"
    SET "updated_at" = CURRENT_TIMESTAMP
    WHERE "pk" = NEW."pk";
END;


