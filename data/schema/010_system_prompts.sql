-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/010_system_prompts.sql
-- =============================================================================

-- system_prompts: Stores system prompts used for model evaluations.
-- Purpose: Maintains a historical record of all system prompts, allowing
--          tracking of prompt changes over time. The active prompt is
--          referenced via the system_prompt_active singleton table.

-- =============================================================================
-- TABLE DEFINITION
-- =============================================================================

CREATE TABLE IF NOT EXISTS "system_prompts" (
    "pk"         INTEGER PRIMARY KEY AUTOINCREMENT,
    "prompt"    TEXT NOT NULL,
    "created_at" DATETIME DEFAULT (CURRENT_TIMESTAMP),
    "updated_at" DATETIME DEFAULT (CURRENT_TIMESTAMP)
);

-- =============================================================================
-- TRIGGERS
-- =============================================================================

CREATE TRIGGER IF NOT EXISTS trg_system_prompts_updated_at
    AFTER UPDATE ON "system_prompts"
    FOR EACH ROW
BEGIN
    UPDATE "system_prompts"
    SET "updated_at" = CURRENT_TIMESTAMP
    WHERE "pk" = NEW."pk";
END;

-- =============================================================================
-- INITIAL DATA
-- =============================================================================

-- Initial data moved to 011_system_prompt_active.sql to ensure last_insert_rowid()
-- works correctly within same transaction context.