-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/011_system_prompt_active.sql
-- =============================================================================

-- system_prompt_active: Singleton pointer to the currently active system prompt.
-- Ensures exactly one active system prompt at a time for model evaluations.
-- This avoids boolean flags spread across rows and provides a clear, auditable
-- activation timestamp.

-- =============================================================================
-- TABLE DEFINITION
-- =============================================================================

CREATE TABLE IF NOT EXISTS "system_prompt_active" (
    "pk"                     INTEGER PRIMARY KEY CHECK (pk = 1),
    "system_prompts_fk_pk"   INTEGER NOT NULL UNIQUE
        REFERENCES "system_prompts" ("pk") ON DELETE CASCADE,

    -- Timestamps
    "created_at"             DATETIME DEFAULT (CURRENT_TIMESTAMP),
    "updated_at"             DATETIME DEFAULT (CURRENT_TIMESTAMP)
);

-- =============================================================================
-- INDEXES
-- =============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS idx_system_prompt_active_fk
    ON "system_prompt_active" ("system_prompts_fk_pk");

-- =============================================================================
-- TRIGGERS
-- =============================================================================

CREATE TRIGGER IF NOT EXISTS trg_system_prompt_active_updated_at
    AFTER UPDATE ON "system_prompt_active"
    FOR EACH ROW
BEGIN
    UPDATE "system_prompt_active"
    SET "updated_at" = CURRENT_TIMESTAMP
    WHERE "pk" = NEW."pk";
END;

-- =============================================================================
-- INITIAL DATA
-- =============================================================================

-- Insert initial system prompt (moved from 010_system_prompts.sql to ensure
-- last_insert_rowid() works correctly within same transaction context)
INSERT INTO "system_prompts" ("prompt") VALUES (
'You are a lead web developer at a top digital agency, tasked with creating a one-page website for a new client based on the given specifications, delivered as an HTML file. First non-whitespace char ''<'', last non-whitespace char ''>''. Use the following services to generate placeholder images where needed:
- placehold.co (text): https://placehold.co/[{w}x{h}|{size}][/{bg-color}/{text-color}]?text={text}&font=[lato|lora|montserrat|noto sans|open sans|oswald|playfair display|poppins|pt sans|raleway|roboto|source sans|source sans pro]
- picsum.photos (photos): https://picsum.photos/[{w}/{h}|{size}]?[grayscale][&blur={1-10}]
- pravatar.cc (avatars): https://i.pravatar.cc/{size}?u={identifier}
Choose sizes appropriate to layout.'
);

-- Set the initial system prompt as active (references the INSERT above via last_insert_rowid())
INSERT INTO "system_prompt_active" ("pk", "system_prompts_fk_pk")
VALUES (1, last_insert_rowid());