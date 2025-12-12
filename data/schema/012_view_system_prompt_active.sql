-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/012_view_system_prompt_active.sql
-- Purpose: Defines a view `view_system_prompt_active` that exposes the base
--          `system_prompt_active` columns along with human-friendly information
--          from the joined `system_prompts` table. This allows querying the
--          active system prompt while seeing the complete prompt text instead of
--          just the foreign key reference.
-- =============================================================================

CREATE VIEW IF NOT EXISTS view_system_prompt_active AS
SELECT
    -- Base columns from system_prompt_active
    spa.pk,
    spa.system_prompts_fk_pk,
    spa.created_at AS active_created_at,
    spa.updated_at AS active_updated_at,

    -- Human-friendly columns from system_prompts (joined via foreign key)
    sp.prompt,
    sp.created_at AS prompt_created_at,
    sp.updated_at AS prompt_updated_at

FROM system_prompt_active AS spa
-- INNER JOIN fails fast if FK broken; LEFT JOIN would return NULL prompt
-- which Python coerces to string "None" - catastrophic silent failure
INNER JOIN system_prompts AS sp ON spa.system_prompts_fk_pk = sp.pk;