-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/001_models.sql
-- =============================================================================

-- This file defines the schema for the 'models' table, which stores
-- information about AI models from the OpenRouter API. 

-- =============================================================================
-- TABLE DEFINITION
-- =============================================================================

CREATE TABLE IF NOT EXISTS `models` (
    `pk`                INTEGER PRIMARY KEY AUTOINCREMENT, -- primary key

    -- START Direct From OpenRouter API
    `id`                TEXT    UNIQUE NOT NULL, -- eg "cognitivecomputations/dolphin3.0-r1-mistral-24b:free"
    `name`              TEXT    NOT NULL,        -- eg "xAI: Grok Code Fast 1"
    `description`       TEXT    NOT NULL,        -- eg "Grok Code Fast 1 is a speedy and economical reasoning model."
    `context_length`    INTEGER NOT NULL,        -- eg 256000
    `supported_parameters` TEXT NOT NULL CHECK(json_valid(`supported_parameters`)), -- eg '["response_format", "structured_outputs"]'
    `pricing`           TEXT NOT NULL CHECK(json_valid(`pricing`)), -- eg '{"prompt": "0.2", "completion": "1.5"}'
    `created`           INTEGER NOT NULL,        -- eg 1756238927, comes FROM OpenRouter API
    `canonical_slug`    TEXT,                    -- eg "x-ai/grok-code-fast-1" NOTE: not unique in the full openrouter catalog, hence of low value
    `hugging_face_id`   TEXT,                    -- eg "Qwen/Qwen3-Coder-480B-A35B-Instruct"
    -- END Direct From OpenRouter API

    -- Manual override fields - nullable to avoid INSERT failures
    `manual_model_display_name`  TEXT, -- Manual override for the model display name
    `manual_company_display_name` TEXT, -- Manual override for the company display name
    -- NOTE: if we ever find a troublesome model that needs its own system prompt in order to generate a good response, we can add a `manual_system_prompt` field here

    -- Timestamps
    `created_at`         DATETIME DEFAULT (CURRENT_TIMESTAMP),
    `updated_at`         DATETIME DEFAULT (CURRENT_TIMESTAMP)

);

-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Trigger to update updated_at on UPDATE
CREATE TRIGGER IF NOT EXISTS trg_models_updated_at
    AFTER UPDATE ON `models`
    FOR EACH ROW
BEGIN
    UPDATE `models`
    SET updated_at = CURRENT_TIMESTAMP
    WHERE `pk` = NEW.`pk`;
END;