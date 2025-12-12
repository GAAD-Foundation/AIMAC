-- =============================================================================
-- File: data/schema/025_axe_rules.sql
-- Purpose: Persist axe rule metadata (help text, URLs, version history) so
--          reporting no longer depends on re-parsing axe JSON files.
-- =============================================================================

-- =============================================================================
-- TABLE DEFINITION
-- =============================================================================

CREATE TABLE IF NOT EXISTS axe_rules (
    -- rule_id is the axe-core rule identifier (e.g., "color-contrast", "image-alt")
    rule_id             TEXT PRIMARY KEY,
    -- help is human-readable description from axe-core (e.g., "Elements must have sufficient color contrast")
    help                TEXT NOT NULL,
    -- help_url links to Deque's documentation for this rule (may be NULL for custom rules)
    help_url            TEXT,
    -- Version tracking: populated from axe-core testEngine.version when rules are first/last seen
    -- Useful for tracking rule changes across axe-core upgrades
    first_seen_version  TEXT,
    last_seen_version   TEXT,
    created_at          DATETIME DEFAULT (CURRENT_TIMESTAMP),
    updated_at          DATETIME DEFAULT (CURRENT_TIMESTAMP)
);

-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Trigger to update updated_at on UPDATE
CREATE TRIGGER IF NOT EXISTS trg_axe_rules_updated_at
    AFTER UPDATE ON axe_rules
    FOR EACH ROW
BEGIN
    UPDATE axe_rules
    SET updated_at = CURRENT_TIMESTAMP
    WHERE rule_id = NEW.rule_id;
END;
