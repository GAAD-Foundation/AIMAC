-- =============================================================================
-- File: data/schema/024_axe_rule_breakdown.sql
-- =============================================================================

-- Stores per-rule violation counts from axe-core analysis.
--
-- Each row represents one axe-core rule with its violation count for a specific run.
-- rule_id values come from axe-core (e.g., "color-contrast", "image-alt", "label").
-- See https://github.com/dequelabs/axe-core/blob/develop/doc/rule-descriptions.md

-- =============================================================================
-- TABLE DEFINITION
-- =============================================================================

CREATE TABLE IF NOT EXISTS axe_rule_breakdown (
    pk INTEGER PRIMARY KEY AUTOINCREMENT,
    axe_runs_fk_pk INTEGER NOT NULL REFERENCES axe_runs(pk) ON DELETE CASCADE,
    rule_id TEXT NOT NULL,
    violation_count INTEGER NOT NULL,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP)
);

-- =============================================================================
-- INDEXES
-- =============================================================================

-- Composite UNIQUE index: one row per rule per run (enforces business invariant)
-- Also covers queries that filter by axe_runs_fk_pk (leftmost column)
CREATE UNIQUE INDEX IF NOT EXISTS idx_rule_breakdown_run_rule
    ON axe_rule_breakdown(axe_runs_fk_pk, rule_id);

