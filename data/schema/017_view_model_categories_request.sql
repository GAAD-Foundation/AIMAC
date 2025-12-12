-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/017_view_model_categories_request.sql
-- =============================================================================

-- View: Human-readable request information with model/category names
-- Purpose: Display-friendly version of model_categories_request with resolved names
--          and computed fields for easier CLI/reporting queries

-- =============================================================================
-- VIEW DEFINITION
-- =============================================================================

CREATE VIEW IF NOT EXISTS "view_model_categories_request" AS
SELECT
    -- Core identifiers
    req.pk,
    req.batches_fk_pk AS batch,
    m.name AS model,
    c.name AS category,
    req.created_at AS timestamp,
    -- Full request body for downstream consumers
    req.openrouter_request_body

FROM model_categories_request AS req
JOIN models AS m ON req.models_fk_pk = m.pk
JOIN categories AS c ON req.categories_fk_pk = c.pk;
