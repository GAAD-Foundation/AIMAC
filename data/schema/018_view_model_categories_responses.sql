-- =============================================================================
-- File: data/schema/018_view_model_categories_responses.sql
-- =============================================================================
-- View: Human-readable response information with HTML extraction
-- Purpose: Parse raw OpenRouter JSON responses into usable fields:
--   1. Extract HTML from message content (handles ```html blocks, bare HTML)
--   2. Determine success/failure status from multiple error locations
--   3. Surface token counts, cost, and provider information
--
-- HTTP Status Codes (computed, not from API):
--   200 = Valid HTML extracted successfully
--   502 = Invalid JSON response (network/parsing failure)
--   424 = finish_reason was 'error' or 'length' (model failed to complete)
--   500 = Fallback when no specific error code found
--   Other codes come from OpenRouter's error.code or nested provider errors
--
-- HTML Extraction Strategy:
--   Searches for '```html', '<!doctype', or '<html' markers (case-insensitive)
--   and extracts content up to '</html>'. This handles both markdown-wrapped
--   and bare HTML responses from different LLMs.

CREATE VIEW IF NOT EXISTS "view_model_categories_responses" AS
WITH base_data AS (
    SELECT
        resp.pk,
        req.batch,
        req.model,
        req.category,
        resp.response_timestamp AS timestamp,
        resp.attempt_number AS attempt,
        resp.openrouter_response AS response_json,
        json_valid(resp.openrouter_response) AS is_json_valid,
        json_extract(resp.openrouter_response, '$.choices[0].message.content') AS message_content
    FROM model_categories_responses resp
    JOIN view_model_categories_request req ON resp.model_categories_request_fk_pk = req.pk
),
located_html AS (
    SELECT
        base.*,
        base.message_content AS potential_html_string
    FROM base_data AS base
),
parsed_html AS (
    SELECT
        located.*,
        CASE
            WHEN located.potential_html_string IS NOT NULL THEN
                CASE
                    WHEN instr(lower(located.potential_html_string), '```html') > 0 THEN instr(lower(located.potential_html_string), '```html') + 7
                    WHEN instr(lower(located.potential_html_string), '<!doctype') > 0 THEN instr(lower(located.potential_html_string), '<!doctype')
                    WHEN instr(lower(located.potential_html_string), '<html') > 0 THEN instr(lower(located.potential_html_string), '<html')
                    ELSE 0
                END
            ELSE 0
        END AS start_pos,
        CASE
            WHEN located.potential_html_string IS NOT NULL THEN
                CASE
                    WHEN instr(lower(located.potential_html_string), '</html>') > 0 THEN instr(lower(located.potential_html_string), '</html>') + 7
                    ELSE 0
                END
            ELSE 0
        END AS end_pos
    FROM located_html AS located
),
status_fields AS (
    SELECT
        parsed.*,
        nullif(CAST(json_extract(parsed.response_json, '$.http_status') AS INTEGER), 200) AS http_status_code,
        nullif(CAST(json_extract(parsed.response_json, '$.error.code') AS INTEGER), 200) AS error_code,
        CASE
            WHEN parsed.is_json_valid
                 AND json_valid(json_extract(parsed.response_json, '$.error.metadata.raw'))
                 AND json_extract(json_extract(parsed.response_json, '$.error.metadata.raw'), '$.status') IS NOT NULL
            THEN nullif(CAST(json_extract(json_extract(parsed.response_json, '$.error.metadata.raw'), '$.status') AS INTEGER), 200)
            ELSE NULL
        END AS provider_status_code,
        -- NOTE: nested_provider_status extracts $.error.code from nested provider errors.
        -- OpenRouter typically returns integer codes here, but some providers may return
        -- string codes like 'quota_exceeded' or 'budget_exceeded'. If this causes
        -- downstream int() conversion failures, add typeof() = 'integer' check here.
        -- Debug: SELECT DISTINCT json_extract(json_extract(response_json, '$.error.metadata.raw'), '$.error.code')
        --        FROM model_categories_responses WHERE response_json LIKE '%error.metadata.raw%';
        CASE
            WHEN parsed.is_json_valid
                 AND json_valid(json_extract(parsed.response_json, '$.error.metadata.raw'))
            THEN json_extract(json_extract(parsed.response_json, '$.error.metadata.raw'), '$.error.code')
            ELSE NULL
        END AS nested_provider_status
    FROM parsed_html parsed
)
SELECT
    status_fields.pk,
    status_fields.batch,
    status_fields.model,
    status_fields.category,
    status_fields.timestamp,
    status_fields.attempt,
    status_fields.response_json,
    -- NOTE: CASE order matters here. Current logic:
    -- 1. Valid HTML found → 200 (even if finish_reason indicates issues)
    -- 2. Invalid JSON → 502
    -- 3. finish_reason 'error'/'length' → 424
    -- 4. Fallback to error codes from response
    --
    -- This prioritizes "did we get usable HTML?" over finish_reason because
    -- OpenRouter returns 200 even when upstream providers error mid-stream.
    -- If truncated pages with valid <html>...</html> markers slip through,
    -- consider swapping checks 1 and 3 to prioritize finish_reason.
    CASE
        WHEN status_fields.start_pos > 0 AND status_fields.end_pos > status_fields.start_pos THEN 200
        WHEN NOT status_fields.is_json_valid THEN 502
        WHEN lower(json_extract(status_fields.response_json, '$.choices[0].finish_reason')) IN ('error', 'length') THEN 424
        ELSE coalesce(
            status_fields.http_status_code,
            status_fields.error_code,
            status_fields.provider_status_code,
            status_fields.nested_provider_status,
            500
        )
    END AS http_status,
    CASE
        WHEN status_fields.start_pos > 0 AND status_fields.end_pos > status_fields.start_pos
        THEN trim(
            substr(
                status_fields.potential_html_string,
                status_fields.start_pos,
                status_fields.end_pos - status_fields.start_pos
            ),
            char(9) || char(10) || char(13) || ' '
        )
        ELSE NULL
    END AS html_page,
    CASE
        WHEN status_fields.start_pos > 0 AND status_fields.end_pos > status_fields.start_pos THEN 1
        ELSE 0
    END AS html_is_valid,
    coalesce(
        json_extract(status_fields.response_json, '$.error.metadata.provider_name'),
        json_extract(status_fields.response_json, '$.choices[0].error.metadata.provider_name'),
        json_extract(status_fields.response_json, '$.error.metadata.provider'),
        json_extract(status_fields.response_json, '$.choices[0].error.metadata.provider'),
        json_extract(json_extract(status_fields.response_json, '$.error.metadata.raw'), '$.provider_name'),
        json_extract(json_extract(status_fields.response_json, '$.error.metadata.raw'), '$.provider'),
        json_extract(status_fields.response_json, '$.error.provider'),
        json_extract(status_fields.response_json, '$.provider')
    ) AS provider,
    json_extract(status_fields.response_json, '$.system_fingerprint') AS system_fingerprint,
    CASE WHEN status_fields.is_json_valid THEN json_extract(status_fields.response_json, '$.usage.prompt_tokens') ELSE NULL END AS prompt_tokens,
    CASE WHEN status_fields.is_json_valid THEN json_extract(status_fields.response_json, '$.usage.completion_tokens') ELSE NULL END AS completion_tokens,
    CASE WHEN status_fields.is_json_valid THEN json_extract(status_fields.response_json, '$.usage.total_tokens') ELSE NULL END AS total_tokens,
    CASE WHEN status_fields.is_json_valid THEN json_extract(status_fields.response_json, '$.usage.cost') ELSE NULL END AS cost,
    CASE WHEN status_fields.is_json_valid THEN json_extract(status_fields.response_json, '$.choices[0].finish_reason') ELSE NULL END AS finish_reason
FROM status_fields;
