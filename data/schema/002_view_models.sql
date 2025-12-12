-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/002_view_models.sql
-- Purpose: Defines a view `view_models` that exposes the base `models` columns
--          along with derived/computed fields for convenience. Computations
--          previously defined as GENERATED columns in `001_models.sql` are
--          implemented here using SQLite expressions and JSON functions.
-- =============================================================================

CREATE VIEW IF NOT EXISTS view_models AS
SELECT
    -- Base columns (from models)
    m.pk,
    m.id,
    -- Company and model names with normalization and manual override support
    COALESCE(
        m.manual_company_display_name, -- Use override if it exists
        CASE
            WHEN INSTR(m.name, ':') > 0
            THEN TRIM(REPLACE(REPLACE(SUBSTR(m.name, 1, INSTR(m.name, ':') - 1), '-', ' '), '_', ' '))
            -- Fallback: extract and capitalize company name from id field (e.g., "openrouter/model" -> "Openrouter")
            WHEN INSTR(m.id, '/') > 0
            THEN (
                UPPER(SUBSTR(
                    TRIM(REPLACE(REPLACE(SUBSTR(m.id, 1, INSTR(m.id, '/') - 1), '-', ' '), '_', ' ')),
                    1, 1
                )) ||
                SUBSTR(
                    TRIM(REPLACE(REPLACE(SUBSTR(m.id, 1, INSTR(m.id, '/') - 1), '-', ' '), '_', ' ')),
                    2
                )
            )
            ELSE NULL
        END
    ) AS company_name,

    COALESCE(
        m.manual_model_display_name, -- Use override if it exists
        CASE
            WHEN INSTR(m.name, ':') > 0
            THEN TRIM(REPLACE(REPLACE(SUBSTR(m.name, INSTR(m.name, ':') + 1), '-', ' '), '_', ' '))
            ELSE TRIM(REPLACE(REPLACE(m.name, '-', ' '), '_', ' ')) -- Full name with normalization if no colon
        END
    ) AS model_name,
    m.description,

    -- company and model slugs generated from "id" for use in output/{batch_date}/{batch_time}/batch_{batch_id}/{company_slug}/{model_slug}/{category_slug}/{instance_uuid}.{html|png|axe.json}
    CASE
        WHEN INSTR(m.id, '/') > 0
        THEN SUBSTR(m.id, 1, INSTR(m.id, '/') - 1)
    END AS company_slug,

    CASE
        WHEN INSTR(m.id, '/') > 0
        THEN SUBSTR(m.id, INSTR(m.id, '/') + 1)
    END AS model_slug,

    -- Computed columns moved from table schema
    -- Booleans: 1 if present, 0 otherwise
    -- NOTE: The original plan was to add response_format for all models that support it, which in practice means all models but Anthropic's Claude models
    -- but since different scaffolding would add more potential confounding factors for evaluation, we're going to stick with system and user prompts only.
    -- Hence these two fields aren't going to really be needed, but it's great for monitoring how many models support these parameters at a glance. When Anthropic
    -- adds response_format and structured_outputs, we can switch to using those instead.
    CASE WHEN EXISTS (
        SELECT 1
        FROM json_each(m.supported_parameters) AS sp
        WHERE sp.value = 'response_format'
    ) THEN 1 ELSE 0 END AS response_format,

    CASE WHEN EXISTS (
        SELECT 1
        FROM json_each(m.supported_parameters) AS sp
        WHERE sp.value = 'structured_outputs'
    ) THEN 1 ELSE 0 END AS structured_outputs,

    -- Pricing extracted from JSON, cast to REAL and multiplied by 1,000,000 to provide a human-readable price per million tokens
    CAST(COALESCE(NULLIF(json_extract(m.pricing, '$.prompt'), ''), '0') AS REAL) * 1000000     AS prompt_price_per_million,
    CAST(COALESCE(NULLIF(json_extract(m.pricing, '$.completion'), ''), '0') AS REAL) * 1000000 AS completion_price_per_million,

    -- DEPRECATED: cost_type was used during early testing for free model collection.
    -- Retained for backward compatibility but not used in current workflows.
    CASE
        WHEN (m.id LIKE '%:free') THEN 'free'
        ELSE 'paid'
    END AS cost_type,

    m.created_at,
    m.updated_at

FROM models AS m;
