-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/022_view_leaderboard_missing_categories.sql
-- =============================================================================
-- View: Missing categories per model per leaderboard
-- Purpose: Gap analysis for incomplete models by listing enabled categories
--          that are not present in categories_array for each model.
-- =============================================================================

CREATE VIEW IF NOT EXISTS "view_leaderboard_missing_categories" AS
SELECT
    mcs.leaderboards_fk_pk AS leaderboard_pk,
    mcs.models_fk_pk       AS model_pk,
    vm.company_name,
    vm.model_name,
    c.pk                   AS category_pk,
    c.name                 AS category_name,
    c.category_slug
FROM model_categories_summary AS mcs
JOIN view_models AS vm ON vm.pk = mcs.models_fk_pk
JOIN categories AS c ON c.enabled = 1
WHERE NOT EXISTS (
    SELECT 1
    FROM json_each(mcs.categories_array) AS je
    WHERE CAST(je.value AS INTEGER) = c.pk
)
ORDER BY leaderboard_pk, model_pk, c.name;

