-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/021_view_leaderboard_active_summary.sql
-- =============================================================================
-- View: Active leaderboard with human-friendly model summaries
-- Purpose: Filter view_model_categories_summary to the currently active
--          leaderboard and include activation and model set context.
-- =============================================================================

CREATE VIEW IF NOT EXISTS "view_leaderboard_active_summary" AS
SELECT
    vas.*,                       -- summary fields
    vla.active_created_at,
    vla.active_updated_at,
    vla.sorted_model_list
FROM view_leaderboard_active AS vla
JOIN view_model_categories_summary AS vas
  ON vas.leaderboard_pk = vla.leaderboards_fk_pk
ORDER BY vas.ranking ASC;

