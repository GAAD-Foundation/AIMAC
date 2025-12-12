-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/009_view_leaderboard_active.sql
-- Purpose: Defines a view `view_leaderboard_active` that exposes the base
--          `leaderboard_active` columns along with human-friendly information from
--          the joined `leaderboards` and `model_sets` tables. This allows querying
--          the active leaderboard while seeing complete details including the model
--          list, cost, and timestamps.
-- =============================================================================

CREATE VIEW IF NOT EXISTS view_leaderboard_active AS
SELECT
    -- Base columns from leaderboard_active
    la.pk,
    la.leaderboards_fk_pk,
    la.created_at AS active_created_at,
    la.updated_at AS active_updated_at,

    -- Human-friendly columns from leaderboards (joined via foreign key)
    l.model_sets_fk_pk,
    l.total_cost_usd,
    l.created_at AS leaderboard_created_at,
    l.updated_at AS leaderboard_updated_at,

    -- Human-friendly columns from model_sets (joined via leaderboards)
    ms.sorted_model_list

FROM leaderboard_active AS la
LEFT JOIN leaderboards AS l ON la.leaderboards_fk_pk = l.pk
LEFT JOIN model_sets AS ms ON l.model_sets_fk_pk = ms.pk;