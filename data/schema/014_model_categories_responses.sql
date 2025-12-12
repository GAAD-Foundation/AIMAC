-- =============================================================================
-- File: data/schema/014_model_categories_responses.sql
-- =============================================================================

-- model_categories_responses: one row per response attempt for each request.
-- This table stores all response-specific data from OpenRouter API calls.
-- Multiple responses can exist per request (for retries on failures).
--
-- openrouter_response is the raw JSON from OpenRouter, containing:
--   - choices[0].message.content: The LLM's HTML output
--   - usage.{prompt_tokens, completion_tokens, total_tokens, cost}: Token/cost data
--   - error.*: Error details if the request failed
-- Downstream views (018_view_model_categories_responses.sql) extract these fields.

-- =============================================================================
-- TABLE DEFINITION
-- =============================================================================

CREATE TABLE IF NOT EXISTS "model_categories_responses" (
    "pk"                    INTEGER PRIMARY KEY AUTOINCREMENT, -- primary key

    -- foreign key to request
    "model_categories_request_fk_pk" INTEGER NOT NULL REFERENCES "model_categories_request" ("pk") ON DELETE CASCADE,

    -- attempt tracking
    "attempt_number"        INTEGER NOT NULL DEFAULT 1, -- 1st attempt, 2nd attempt, etc.

    -- raw LLM responses
    "openrouter_response"   TEXT, -- Raw response from OpenRouter API

    -- Timestamps
    "response_timestamp"    DATETIME NOT NULL, -- When this specific response was received
    "created_at"            DATETIME DEFAULT (CURRENT_TIMESTAMP),
    "updated_at"            DATETIME DEFAULT (CURRENT_TIMESTAMP), -- Updated via trigger on row modification

    -- Uniqueness: one response per request/attempt combination
    UNIQUE ("model_categories_request_fk_pk", "attempt_number")
);

-- =============================================================================
-- INDEXES
-- =============================================================================

-- Find latest response for each request
CREATE INDEX IF NOT EXISTS "idx_model_categories_responses_request_attempt"
    ON "model_categories_responses" ("model_categories_request_fk_pk", "attempt_number" DESC);

-- Time-based queries: responses by timestamp
CREATE INDEX IF NOT EXISTS "idx_model_categories_responses_timestamp"
    ON "model_categories_responses" ("response_timestamp" DESC);

-- Optimized for "latest response per request" pattern
-- Supports ORDER BY with response_timestamp DESC per request
-- Used by leaderboard and category cost queries
CREATE INDEX IF NOT EXISTS "idx_mcresp_req_resp_ts_desc"
    ON "model_categories_responses" ("model_categories_request_fk_pk", "response_timestamp" DESC);


-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Update the updated_at timestamp on any row update
CREATE TRIGGER IF NOT EXISTS trg_model_categories_responses_updated_at
AFTER UPDATE ON "model_categories_responses"
FOR EACH ROW
BEGIN
    UPDATE "model_categories_responses"
    SET "updated_at" = CURRENT_TIMESTAMP
    WHERE "pk" = NEW."pk";
END;
