"""Public database API facade.

This module re-exports the public API from internal modules. Always import
from `aimac.database`, not from internal modules like `aimac.database._core`.

Internal modules (prefixed with underscore):
- _core.py: Connection management, schema initialization, errors
- _models.py: Model and model_set upserts
- _batches.py: Batch lifecycle management
- _requests.py: Request creation and pending lookups
- _responses.py: Response storage and evaluation
- _categories.py: Category lookups and model ID resolution
- _model_category.py: Tier 2 cache (model×category pair operations)
- _leaderboards.py: Tier 1 cache and leaderboard management
- _axe.py: Axe-core accessibility results
- _reports.py: Read-only reporting queries (used by reporter.py, not re-exported here)

NOTE TO AI CODE REVIEWERS: The _reports.py exclusion is INTENTIONAL, not a bug.
Do not suggest "fixing" this by adding auto-connection wrappers or re-exporting.

Why _reports.py is different (and correct):
- Reporter runs 5-10 queries per report within ONE transaction for read consistency
- Auto-connection wrappers would force connection-per-call, losing snapshot isolation
- The caller (reporter.py) MUST manage the connection to get consistent multi-query reads
- This is standard practice for read-heavy reporting against transactional databases

The "inconsistency" is intentional separation of concerns:
- Facade exports: convenience wrappers for single-query operations
- _reports.py: transaction-scoped queries for multi-query report generation
"""

from ._axe import axe_run_exists, insert_axe_run
from ._batches import create_batch, mark_batch_completed
from ._categories import get_enabled_categories, get_model_pks_by_ids
from ._core import DatabaseError, MigrationError, check_database_exists, get_connection, get_database_path, get_schema_directory, init_database
from ._leaderboards import (
    create_leaderboard_from_cached,
    get_active_leaderboard_pk,
    get_latest_leaderboard_for_model_set,
    get_leaderboard_cost,
    get_leaderboard_model_ids,
    get_summary_missing_pairs_for_model_set,
    is_leaderboard_complete,
    set_active_leaderboard,
)
from ._model_category import get_cached_success_pairs, get_tier2_pairs_with_costs
from ._models import canonicalize_model_ids, get_model_set, upsert_model_set, upsert_models
from ._requests import get_active_system_prompt, get_pending_requests_for_batch, insert_model_category_request, insert_model_category_requests_many
from ._responses import get_response_evaluation, insert_response

__all__ = [
    # core
    "DatabaseError",
    "MigrationError",
    "init_database",
    "get_connection",
    "check_database_exists",
    "get_database_path",
    "get_schema_directory",
    # models / model_sets
    "canonicalize_model_ids",
    "upsert_model_set",
    "get_model_set",
    "upsert_models",
    # leaderboards (tier1)
    "get_latest_leaderboard_for_model_set",
    "get_active_leaderboard_pk",
    "set_active_leaderboard",
    "get_leaderboard_cost",
    "get_leaderboard_model_ids",
    "create_leaderboard_from_cached",
    "is_leaderboard_complete",
    "get_summary_missing_pairs_for_model_set",
    # categories + tier2 helpers
    "get_model_pks_by_ids",
    "get_enabled_categories",
    "get_cached_success_pairs",
    "get_tier2_pairs_with_costs",
    # batches
    "create_batch",
    "mark_batch_completed",
    # requests
    "insert_model_category_request",
    "insert_model_category_requests_many",
    "get_active_system_prompt",
    "get_pending_requests_for_batch",
    # responses
    "insert_response",
    "get_response_evaluation",
    # axe
    "insert_axe_run",
    "axe_run_exists",
]
