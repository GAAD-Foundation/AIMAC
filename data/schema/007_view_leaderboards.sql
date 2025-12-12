-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/007_view_leaderboards.sql
-- Purpose: Defines a view `view_leaderboards` that exposes the base `leaderboards`
--          columns along with human-friendly information from the joined `model_sets`
--          table. This allows querying leaderboards while seeing the actual model list
--          instead of just the foreign key reference.
-- =============================================================================

CREATE VIEW IF NOT EXISTS view_leaderboards AS
SELECT
    -- Base columns from leaderboards
    l.pk,
    l.model_sets_fk_pk,
    l.total_cost_usd,
    l.created_at,
    l.updated_at,

    -- Human-friendly columns from model_sets (joined via foreign key)
    ms.sorted_model_list

FROM leaderboards AS l
INNER JOIN model_sets AS ms ON l.model_sets_fk_pk = ms.pk;