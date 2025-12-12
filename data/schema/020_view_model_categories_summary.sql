-- =============================================================================
-- File: data/schema/020_view_model_categories_summary.sql
-- =============================================================================
-- View: Human-friendly summary for model_categories_summary
-- Purpose: Add model names/slugs, coverage counts/%, violations/page, USD/page,
--          and human-readable category lists for quick inspection.
--
-- Key computed fields:
--   - category_names_csv: Comma-separated list of completed category names
--   - missing_category_names_csv: Categories not yet completed (for partial runs)
--   - coverage_pct: Percentage of 28 enabled categories completed
--   - violations_per_page: Average violations across completed categories
-- =============================================================================

CREATE VIEW IF NOT EXISTS "view_model_categories_summary" AS
SELECT
    mcs.pk,
    mcs.leaderboards_fk_pk AS leaderboard_pk,
    l.created_at           AS leaderboard_created_at,
    mcs.models_fk_pk       AS model_pk,
    vm.company_name,
    vm.model_name,
    vm.company_slug,
    vm.model_slug,
    mcs.ranking,
    mcs.median_weighted_score,
    mcs.avg_axe_score,
    mcs.total_violations,
    mcs.total_cost_usd,
    mcs.avg_cost_per_page,
    mcs.is_complete,
    json_array_length(mcs.categories_array) AS categories_count,
    ROUND(json_array_length(mcs.categories_array) / 28.0, 4) AS coverage_ratio,
    ROUND(json_array_length(mcs.categories_array) * 100.0 / 28.0, 2) AS coverage_pct,
    CASE
        WHEN json_array_length(mcs.categories_array) > 0
            THEN CAST(mcs.total_violations AS REAL) / json_array_length(mcs.categories_array)
        ELSE NULL
    END AS violations_per_page,
    (
        SELECT group_concat(c.name, ', ')
        FROM json_each(mcs.categories_array) AS je
        JOIN categories c ON c.pk = CAST(je.value AS INTEGER)
    ) AS category_names_csv,
    (
        SELECT group_concat(c.category_slug, ',')
        FROM json_each(mcs.categories_array) AS je
        JOIN categories c ON c.pk = CAST(je.value AS INTEGER)
    ) AS category_slugs_csv,
    (
        SELECT group_concat(c.name, ', ')
        FROM categories c
        WHERE c.enabled = 1
          AND NOT EXISTS (
            SELECT 1
            FROM json_each(mcs.categories_array) AS je
            WHERE CAST(je.value AS INTEGER) = c.pk
          )
    ) AS missing_category_names_csv,
    mcs.created_at,
    mcs.updated_at
FROM model_categories_summary mcs
JOIN leaderboards l ON l.pk = mcs.leaderboards_fk_pk
JOIN view_models vm ON vm.pk = mcs.models_fk_pk;

