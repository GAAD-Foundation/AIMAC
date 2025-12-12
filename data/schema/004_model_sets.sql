-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/004_model_sets.sql
-- =============================================================================

-- This file defines the schema for the 'model_sets' table, which stores
-- unique sets of models for reports. Each set is identified by a
-- canonicalized JSON array (lowercased, deduplicated, sorted, no spaces) to ensure
-- uniqueness and prevent duplicates.

-- The sorted model list is used to uniquely identify a set of models for a report.
-- It is used in the leaderboards table to identify the set of models that were
-- used to generate a leaderboard.
-- If the model set has an existing valid leaderboard, we can skip the entire
-- report generation process and simply display the pre-existing leaderboard.

-- Canonicalization rules enforced by triggers:
-- 1. All model IDs must be lowercase
-- 2. All spaces removed from model IDs
-- 3. Duplicates removed
-- 4. Sorted alphabetically
-- 5. Stored as compact JSON array (no spaces between elements)

-- =============================================================================
-- TABLE DEFINITION
-- =============================================================================

CREATE TABLE IF NOT EXISTS "model_sets" (
    "pk"                   INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Python must insert a canonicalized JSON array. Database triggers validate.
    "sorted_model_list"    TEXT NOT NULL CHECK(json_valid("sorted_model_list")),
    "created_at"           DATETIME DEFAULT (CURRENT_TIMESTAMP),
    "updated_at"           DATETIME DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE("sorted_model_list")
);

-- =============================================================================
-- TRIGGERS - Timestamp Management
-- =============================================================================

CREATE TRIGGER IF NOT EXISTS trg_model_sets_updated_at
    AFTER UPDATE ON "model_sets"
    FOR EACH ROW
BEGIN
    UPDATE "model_sets"
    SET "updated_at" = CURRENT_TIMESTAMP
    WHERE "pk" = NEW."pk";
END;

-- =============================================================================
-- TRIGGERS - Canonicalization Validation
-- =============================================================================

-- Validates that inserted data is properly canonicalized.
-- If validation fails, the INSERT is rejected with a descriptive error message.
-- NOTE: COALESCE handles NULL from empty/non-text arrays (X != NULL → NULL, not TRUE)
CREATE TRIGGER IF NOT EXISTS trg_model_sets_validate_canonical_insert
    BEFORE INSERT ON "model_sets"
    FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN COALESCE(
            NEW.sorted_model_list != (
                SELECT json_group_array(v)
                FROM (
                    SELECT DISTINCT lower(replace(value, ' ', '')) AS v
                    FROM json_each(NEW.sorted_model_list)
                    WHERE type = 'text' AND trim(value) != ''
                    ORDER BY v
                )
            ),
            1  -- NULL means empty/non-text array, treat as invalid
        )
        THEN RAISE(ABORT, 'sorted_model_list must be canonical: lowercase, deduped, sorted, no spaces, non-empty text elements only')
    END;
END;

-- Same validation for UPDATEs
-- NOTE: COALESCE handles NULL from empty/non-text arrays (X != NULL → NULL, not TRUE)
CREATE TRIGGER IF NOT EXISTS trg_model_sets_validate_canonical_update
    BEFORE UPDATE OF sorted_model_list ON "model_sets"
    FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN COALESCE(
            NEW.sorted_model_list != (
                SELECT json_group_array(v)
                FROM (
                    SELECT DISTINCT lower(replace(value, ' ', '')) AS v
                    FROM json_each(NEW.sorted_model_list)
                    WHERE type = 'text' AND trim(value) != ''
                    ORDER BY v
                )
            ),
            1  -- NULL means empty/non-text array, treat as invalid
        )
        THEN RAISE(ABORT, 'sorted_model_list must be canonical: lowercase, deduped, sorted, no spaces, non-empty text elements only')
    END;
END;