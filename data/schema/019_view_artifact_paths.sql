-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/019_view_artifact_paths.sql
-- =============================================================================
-- View: Artifact paths for all requests
-- Purpose: Provide a view of the artifact paths for all requests
-- =============================================================================

CREATE VIEW IF NOT EXISTS view_artifact_paths AS
SELECT
    r.pk AS request_pk,
    b.pk AS batch_pk,
    b.batch_date,
    b.batch_time,
    vm.company_slug,
    vm.model_slug,
    c.category_slug,
    -- HTML output path
    'output/' || b.batch_date || '/' || b.batch_time || '/batch_' || b.pk
    || '/' || vm.company_slug || '/' || vm.model_slug || '/' || c.category_slug
    || '/' || r.pk || '.html' AS html_path,

    -- PNG output path
    'output/' || b.batch_date || '/' || b.batch_time || '/batch_' || b.pk
    || '/' || vm.company_slug || '/' || vm.model_slug || '/' || c.category_slug
    || '/' || r.pk || '.png' AS png_path,

    -- Accessibility report path
    'output/' || b.batch_date || '/' || b.batch_time || '/batch_' || b.pk
    || '/' || vm.company_slug || '/' || vm.model_slug || '/' || c.category_slug
    || '/' || r.pk || '.axe.json' AS axe_path,

    -- Request data path
    'output/' || b.batch_date || '/' || b.batch_time || '/batch_' || b.pk
    || '/' || vm.company_slug || '/' || vm.model_slug || '/' || c.category_slug
    || '/' || r.pk || '.request.json' AS request_json_path,

    -- Response data path
    'output/' || b.batch_date || '/' || b.batch_time || '/batch_' || b.pk
    || '/' || vm.company_slug || '/' || vm.model_slug || '/' || c.category_slug
    || '/' || r.pk || '.response.json' AS response_json_path

FROM model_categories_request r
JOIN batches b ON r.batches_fk_pk = b.pk
JOIN models m ON r.models_fk_pk = m.pk
JOIN view_models vm ON vm.pk = m.pk
JOIN categories c ON r.categories_fk_pk = c.pk;
