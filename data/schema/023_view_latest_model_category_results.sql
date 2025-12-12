-- =============================================================================
-- File: data/schema/023_view_latest_model_category_results.sql
-- =============================================================================
-- View: Latest successful result per (model, category) across all batches
-- Purpose: Find the most recent accessibility test that produced valid HTML
--          and axe-core results for each model/category combination.
--
-- "Successful" means:
--   - An axe_runs record exists (only created for HTTP 200 responses with valid HTML)
--   - Uses run_timestamp (when axe-core analyzed the page) for ordering
--
-- Why this matters:
--   - Models may succeed on retry or in later batches
--   - This view surfaces the best available data regardless of batch
--   - Snapshot leaderboards use point-in-time data; this is live/current
--
-- Window functions (ROW_NUMBER) select the most recent result when multiple
-- successful runs exist for the same model/category pair.
-- =============================================================================

CREATE VIEW IF NOT EXISTS "view_latest_model_category_results" AS
WITH latest_axe AS (
    SELECT
        ar.model_categories_request_fk_pk AS request_pk,
        req.models_fk_pk AS model_pk,
        req.categories_fk_pk AS category_pk,
        ar.weighted_score,
        ar.total_violations,
        ar.run_timestamp,
        ROW_NUMBER() OVER (
            PARTITION BY req.models_fk_pk, req.categories_fk_pk
            ORDER BY ar.run_timestamp DESC
        ) AS rn
    FROM axe_runs AS ar
    JOIN model_categories_request AS req
      ON req.pk = ar.model_categories_request_fk_pk
), latest_resp AS (
    SELECT
        r.model_categories_request_fk_pk AS request_pk,
        r.attempt_number,
        r.response_timestamp,
        r.openrouter_response,
        ROW_NUMBER() OVER (
            PARTITION BY r.model_categories_request_fk_pk
            ORDER BY r.response_timestamp DESC
        ) AS rn
    FROM model_categories_responses AS r
)
SELECT
    la.model_pk,
    vm.company_name,
    vm.model_name,
    la.category_pk,
    c.name AS category_name,
    c.category_slug,
    la.weighted_score,
    la.total_violations,
    la.run_timestamp,
    lr.attempt_number AS response_attempt,
    CASE WHEN json_valid(lr.openrouter_response) THEN json_extract(lr.openrouter_response, '$.usage.prompt_tokens') END AS prompt_tokens,
    CASE WHEN json_valid(lr.openrouter_response) THEN json_extract(lr.openrouter_response, '$.usage.completion_tokens') END AS completion_tokens,
    CASE WHEN json_valid(lr.openrouter_response) THEN json_extract(lr.openrouter_response, '$.usage.total_tokens') END AS total_tokens,
    CASE WHEN json_valid(lr.openrouter_response) THEN json_extract(lr.openrouter_response, '$.usage.cost') END AS cost_usd,
    ap.html_path,
    ap.png_path,
    ap.axe_path
FROM latest_axe AS la
JOIN view_models AS vm ON vm.pk = la.model_pk
JOIN categories AS c ON c.pk = la.category_pk
LEFT JOIN latest_resp AS lr
       ON lr.request_pk = la.request_pk AND lr.rn = 1
LEFT JOIN view_artifact_paths AS ap
       ON ap.request_pk = la.request_pk
WHERE la.rn = 1;

