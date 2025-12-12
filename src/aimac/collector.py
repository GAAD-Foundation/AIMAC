"""Orchestration for the `aimac collect` command.

This is the main entry point for benchmark data collection. The collect workflow:
1. Fetches current programming models from OpenRouter API
2. Upserts models to database and creates a model_set for this run
3. Checks caches (Tier 1: leaderboard, Tier 1b: summary, Tier 2: responses)
4. Prepares and executes any missing model×category requests
5. Creates/activates leaderboard if all requests succeeded

Cache hierarchy (in order of preference):
- Tier 1: Complete leaderboard exists for this exact model_set → activate it
- Tier 1b: Summary cache has all pairs → create leaderboard from cached costs
- Tier 2: Response cache (individual successes) → create leaderboard if complete
- Cache miss: Execute pending requests, then create leaderboard

Failure handling:
- ANY HTTP or screenshot failures block leaderboard creation
- Previous active leaderboard remains active on failure
- This protects published results from incomplete data

See also:
- src/aimac/cli.py - CLI command that calls collect_command()
- src/aimac/executor.py - async execution of pending requests
- src/aimac/openrouter.py - API client for fetching models
- README.md - user-facing documentation for collect command
"""

import asyncio
from datetime import datetime
import json
import logging
import os
from pathlib import Path
from typing import NamedTuple

from .database import (
    create_batch,
    create_leaderboard_from_cached,
    get_active_leaderboard_pk,
    get_active_system_prompt,
    get_enabled_categories,
    get_latest_leaderboard_for_model_set,
    get_leaderboard_cost,
    get_leaderboard_model_ids,
    get_model_pks_by_ids,
    get_summary_missing_pairs_for_model_set,
    get_tier2_pairs_with_costs,
    insert_model_category_requests_many,
    is_leaderboard_complete,
    mark_batch_completed,
    set_active_leaderboard,
    upsert_model_set,
    upsert_models,
)
from .executor import execute_pending_requests
from .openrouter import fetch_top_models
from .prompt_randomizer import generate_seed, randomize_prompt

logger = logging.getLogger(__name__)

# Models where Bedrock has lower output token limits than Anthropic direct.
# Opus: 32K on Bedrock vs 64K on Anthropic/Google Vertex.
# We exclude Bedrock to get full output capacity for long HTML generation.
BEDROCK_LIMITED_MODELS = {"claude-opus-4", "claude-opus-4.5"}

# DeepSeek native API enforces 8K output limit; DeepInfra doesn't.
DEEPSEEK_LIMITED_MODELS = {"deepseek-v3.2"}

# Soft preference: try these providers first, but allow fallback to others.
PREFER_PROVIDERS: dict[str, list[str]] = {
    "deepseek-v3.2": ["DeepInfra"],  # 100% success vs 33% on DeepSeek native
}


def _get_provider_config(model_id: str) -> dict:
    """Get provider routing config, excluding Bedrock for models with lower limits.

    Bedrock limits Opus models to 32K output tokens vs 64K on Anthropic direct.
    DeepSeek native API limits output to 8K tokens; DeepInfra has no such ceiling.
    """
    base_config = {"sort": "throughput"}
    model_slug = model_id.split("/")[-1] if "/" in model_id else model_id
    ignore_providers: list[str] = []

    # Hard ban: Bedrock for Opus models
    if any(opus in model_slug for opus in BEDROCK_LIMITED_MODELS):
        logger.debug(f"Excluding Amazon Bedrock for {model_id} (32K output limit)")
        ignore_providers.append("amazon-bedrock")

    if any(ds in model_slug for ds in DEEPSEEK_LIMITED_MODELS):
        logger.debug(f"Excluding DeepSeek provider for {model_id} (8K output limit)")
        ignore_providers.append("deepseek")

    if ignore_providers:
        base_config["ignore"] = ignore_providers

    for pattern, preferred in PREFER_PROVIDERS.items():
        if pattern in model_slug:
            logger.debug(f"Preferring {preferred} for {model_id} (higher output limits)")
            base_config["order"] = preferred
            base_config["allow_fallbacks"] = True
            break

    return base_config


def collect_command(refresh: bool = False, model_ids: list[str] | None = None) -> int:
    """Main entry point for 'aimac collect' command.

    Args:
        refresh: If True, skip all caches and re-run all model×category pairs.
                 Default False uses cache hierarchy to minimize API calls.
        model_ids: If provided, test these specific models instead of fetching
                   OpenRouter's top programming models. Validates against DB.

    Returns:
        0 on success (all requests completed, leaderboard created)
        1 on failure (any HTTP or screenshot failures)

    The return code determines whether CI/CD should proceed with deployment.
    """
    try:
        print("  Starting model collection...\n")

        if model_ids:
            # Step 1: Custom model list - fetch ALL models to get full metadata
            print(f"  Using {len(model_ids)} specified model(s): {', '.join(model_ids)}\n")
            all_models = fetch_top_models(category=None)
            print(f"  Fetched {len(all_models)} total models from OpenRouter\n")

            # Step 2: Filter to specified IDs (case-insensitive matching)
            requested_lower = {mid.lower() for mid in model_ids}
            models = [m for m in all_models if m["id"].lower() in requested_lower]

            # Step 3: Validate all requested IDs were found
            found_lower = {m["id"].lower() for m in models}
            missing = [mid for mid in model_ids if mid.lower() not in found_lower]
            if missing:
                print(f"  [FAIL] Models not found on OpenRouter: {', '.join(sorted(missing))}\n")
                return 1

            print(f"  Matched {len(models)} model(s) with full metadata\n")
        else:
            # Step 1: Default - fetch top programming models from OpenRouter
            models = fetch_top_models(category="programming")
            # Step 2: print the model count to the console
            print(f"  Fetched {len(models)} programming models\n")

            # Step 3: Save to dated file for inspection (not caching)
            saved_file = save_models_to_file(models)
            print(f"  Saved models for inspection to {saved_file}\n")

        # Step 4: Upsert models to database (all have full metadata now)
        upserted_count = upsert_models(models)
        print(f"  Updated {upserted_count} models in database\n")

        # Step 5: Create model_set entry
        if not (model_ids := [m["id"] for m in models]):
            raise ValueError("No model IDs found")
        model_set_pk = upsert_model_set(model_ids)
        print(f"  Created model_set (pk={model_set_pk}) with {len(model_ids)} models\n")

        # Step 6: Either skip caches entirely (--refresh flag) or run unified cache checks
        # Capture current active leaderboard state for diffing
        old_active_pk = get_active_leaderboard_pk()
        old_models = get_leaderboard_model_ids(old_active_pk) if old_active_pk else set()

        # Show model changes immediately (before cache checks or API calls)
        new_models = set(model_ids)
        print_leaderboard_diff(old_models, new_models)

        # Fetch categories once for use in either refresh or partial cache paths
        categories = get_enabled_categories()

        batch_pk: int | None = None
        if refresh:
            print("  Refresh requested — skipping all caches\n")
            batch_pk = prepare_all_requests(model_ids, categories)
        else:
            check = resolve_caches(model_set_pk, model_ids, old_models)
            if check.fully_cached:
                print("  Collection complete!\n")
                return 0
            # Prepare any missing requests
            if check.missing_pairs:
                batch_pk = prepare_partial_requests(check.missing_pairs, model_ids, categories)

        # Step 7: Execute batch if prepared
        results: dict | None = None
        if batch_pk is not None:
            results = _execute_and_complete_batch(batch_pk, model_set_pk, model_ids, old_models)

        if results and (results.get('failed', 0) > 0 or results.get('screenshot_failed', 0) > 0):
            print("  [WARN] Collection finished with failures — active leaderboard unchanged.\n")
            return 1

        print("[OK] Collection complete!\n")
        return 0

    except Exception as e:
        print(f"[FAIL] Collection failed: {e}\n")
        logger.exception("Error during model collection")
        return 1


#
# Helper Functions
#

def activate_leaderboard_on_cache_hit(model_set_pk: int, old_models: set[str]) -> bool:
    """Tier 1 cache: check if a complete leaderboard already exists for this model_set.

    This is the fastest cache path - if we've already computed rankings for this
    exact set of models, we can skip all API calls and just activate the existing
    leaderboard.

    Returns True on cache hit (leaderboard activated), False on miss (prints reason).
    """

    leaderboard_pk = get_latest_leaderboard_for_model_set(model_set_pk)
    if leaderboard_pk is None:
        print("  LEADERBOARD CACHE MISS — No leaderboard for this model set\n")
        return False

    # Treat as a true cache hit only if the latest leaderboard is complete
    if not is_leaderboard_complete(leaderboard_pk):
        print("  LEADERBOARD CACHE PARTIAL — Latest leaderboard incomplete\n")
        return False

    cost = get_leaderboard_cost(leaderboard_pk)
    if cost is not None:
        print(
            f"[CACHE HIT] LEADERBOARD — #{leaderboard_pk} complete, previous_cost=${cost:.2f}\n"
        )
    else:
        print(f"[CACHE HIT] LEADERBOARD — #{leaderboard_pk} complete\n")

    set_active_leaderboard(leaderboard_pk)
    print("  Active leaderboard updated\n")
    return True


def save_models_to_file(models: list[dict]) -> str:
    """Save models list to dated JSON file for inspection and debugging.

    NOT a cache - purely for human inspection of what OpenRouter returned.
    Files accumulate in data/snapshots/models/ with timestamps.
    """
    # Create directory structure
    data_dir = os.getenv('AIMAC_DATA_DIR', './data')
    snapshots_dir = Path(data_dir) / 'snapshots' / 'models'
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    # Create dated filename
    date_str = datetime.now().strftime('%Y-%m-%d_%H-%M')
    filename = f"{date_str}.json"
    filepath = snapshots_dir / filename

    # Save with pretty formatting for readability
    with open(filepath, 'w') as f:
        json.dump(models, f, indent=2)

    logger.info(f"Saved {len(models)} models to {filepath}")
    return str(filepath)


def print_leaderboard_diff(old_models: set[str], new_models: set[str]) -> None:
    """Print the difference between old and new model sets.

    Displays added and removed models in sorted order. If no changes,
    prints nothing. Used to show model changes before cache checks.

    Args:
        old_models: Model IDs from previous active leaderboard.
        new_models: Model IDs from current fetch.
    """
    added = sorted(new_models - old_models)
    removed = sorted(old_models - new_models)

    if not added and not removed:
        return

    print("  Changes from previous leaderboard:")
    if removed:
        print(f"    - Removed: {', '.join(removed)}")
    if added:
        print(f"    + Added:   {', '.join(added)}")
    print("")


def build_openrouter_request_body(model_id: str, system_prompt: str, user_prompt: str) -> dict:
    """Construct the OpenRouter request body for a model×category pair.

    Includes provider routing (throughput sort, Bedrock exclusion for Opus),
    usage tracking, and reasoning exclusion (some models put HTML in reasoning).
    """
    max_tokens = os.getenv("AIMAC_MAX_TOKENS")
    return {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "usage": {"include": True},
        "reasoning": {"exclude": True},  # GLM models were putting the HTML in the reasoning field, so we exclude it from the response
        "provider": _get_provider_config(model_id),
        **({"max_tokens": int(max_tokens)} if max_tokens else {}),
    }


class CacheCheck(NamedTuple):
    """Result of cache checks.

    Attributes:
        fully_cached: True if no further work is needed (leaderboard active from cache).
        missing_pairs: Set of (model_pk, category_pk) that need requests; empty when fully cached
          or when no work is needed (e.g., no categories/models enabled).
    """
    fully_cached: bool
    missing_pairs: set[tuple[int, int]]


def _tier2_cache_check_from_set(
    model_set_pk: int,
) -> tuple[CacheCheck, set[tuple[int, int]], dict[tuple[int, int], float]]:
    """Tier 2 cache: check individual successful responses.

    Falls back to this when Tier 1 (leaderboard) and Tier 1b (summary) miss.
    Computes which model×category pairs have successful responses already.

    Returns (CacheCheck, full_pairs, costs) where costs dict contains the latest
    cost for each cached pair. This consolidates the previous two-query pattern
    (get pairs then get costs) into a single DB round trip.
    """
    full_pairs, costs = get_tier2_pairs_with_costs(model_set_pk)
    cached_pairs = set(costs.keys())

    if not full_pairs:
        return CacheCheck(False, set()), full_pairs, costs

    if cached_pairs == full_pairs:
        return CacheCheck(True, set()), full_pairs, costs

    missing = full_pairs - cached_pairs
    return CacheCheck(False, missing), full_pairs, costs


def prepare_all_requests(
    model_ids: list[str],
    categories: list[tuple[int, str, str, str | None]],
) -> int | None:
    """Prepare requests for ALL model×category pairs (refresh mode).

    Use this when you want to re-run all pairs regardless of cache state.
    Caller provides categories to avoid redundant DB queries.

    Args:
        model_ids: List of model IDs to prepare requests for.
        categories: List of (pk, slug, user_prompt, fragments) from get_enabled_categories().

    Returns:
        batch_pk: Primary key of created batch, or None if no pairs to prepare.
    """
    id_to_pk = get_model_pks_by_ids(model_ids)
    model_pks = list(id_to_pk.values())
    category_pks = [pk for (pk, _slug, _prompt, _fragments) in categories]

    if not model_pks or not category_pks:
        print("  No enabled categories or models; nothing to run\n")
        return None

    all_pairs = {(m, c) for m in model_pks for c in category_pks}
    return _prepare_requests_for_pairs(all_pairs, id_to_pk, categories)


def prepare_partial_requests(
    missing_pairs: set[tuple[int, int]],
    model_ids: list[str],
    categories: list[tuple[int, str, str, str | None]],
) -> int | None:
    """Prepare requests for specific model×category pairs (partial cache mode).

    Use this when cache checks identified specific pairs that need requests.
    Caller provides categories to avoid redundant DB queries.

    Args:
        missing_pairs: Set of (model_pk, category_pk) tuples to prepare.
        model_ids: List of model IDs to map to PKs.
        categories: List of (pk, slug, user_prompt, fragments) from get_enabled_categories().

    Returns:
        batch_pk: Primary key of created batch, or None if no pairs to prepare.
    """
    if not missing_pairs:
        return None

    id_to_pk = get_model_pks_by_ids(model_ids)
    return _prepare_requests_for_pairs(missing_pairs, id_to_pk, categories)


def _prepare_requests_for_pairs(
    pairs: set[tuple[int, int]],
    id_to_pk: dict[str, int],
    categories: list[tuple[int, str, str, str | None]],
) -> int | None:
    """Internal: create batch and request rows for the given pairs.

    Args:
        pairs: Set of (model_pk, category_pk) tuples to prepare.
        id_to_pk: Mapping from model ID strings to PKs.
        categories: List of (pk, slug, user_prompt, fragments) tuples.

    Returns:
        batch_pk or None if no rows to insert.
    """
    if not pairs:
        return None

    batch_pk = create_batch()
    spk, system_prompt = get_active_system_prompt()

    # Build lookup maps restricted to needed pairs only
    need_model_pks = {m for (m, _c) in pairs}
    pk_to_id = {v: k for k, v in id_to_pk.items() if v in need_model_pks}
    need_category_pks = {c for (_m, c) in pairs}
    cat_map = {
        pk: (slug, prompt, fragments)
        for (pk, slug, prompt, fragments) in categories
        if pk in need_category_pks
    }

    rows: list[tuple[int, int, int, str]] = []
    for (m_pk, c_pk) in pairs:
        model_id = pk_to_id[m_pk]
        _slug, user_prompt, fragments = cat_map[c_pk]

        # Randomize prompt using fragments to prevent benchmark gaming
        seed = generate_seed()
        randomized_prompt = randomize_prompt(user_prompt, fragments, seed)

        # NOTE: If model-specific parameters are needed, add them here after creating
        # a field in models table. See lastmac-cso for tracking.
        body = build_openrouter_request_body(model_id, system_prompt, randomized_prompt)
        body_json = json.dumps(body, separators=(",", ":"))
        rows.append((m_pk, c_pk, spk, body_json))

    if not rows:
        print("  No requests to prepare (0 rows)\n")
        return None

    inserted = insert_model_category_requests_many(batch_pk, rows)
    print(f"  Prepared {inserted} request(s) in batch {batch_pk}\n")
    return batch_pk


def resolve_caches(
    model_set_pk: int,
    model_ids: list[str],
    old_models: set[str],
) -> CacheCheck:
    """Unified cache resolution through the Tier 1 → 1b → 2 hierarchy.

    Tries caches in order of speed/completeness:
    1. Tier 1: Existing complete leaderboard for this model_set
    2. Tier 1b: Summary cache (all pairs have summaries) → create leaderboard
    3. Tier 2: Response cache (individual successes) → create leaderboard if complete

    On any full hit, creates/activates leaderboard and returns fully_cached=True.
    On partial hit, returns missing_pairs for caller to execute.
    """
    # Leaderboard cache (Tier 1)
    if activate_leaderboard_on_cache_hit(model_set_pk, old_models):
        return CacheCheck(True, set())

    # Summary cache (Tier 1b) — use model_categories_summary for missing pairs
    full_pairs, missing_pairs = get_summary_missing_pairs_for_model_set(model_set_pk)

    if full_pairs and not missing_pairs:
        # Full hit per summary; ensure an active leaderboard exists or create one.
        # IMPORTANT: summary and tier2 are NOT independent data sources. Summary's
        # categories_array is populated from tier2 costs.keys() when leaderboards are
        # created (see _create_leaderboard_from_cached). A pair in summary MUST have
        # had axe_runs at creation time, and we never delete axe_runs, so tier2 will
        # always find all pairs that summary reports. len(costs) == len(full_pairs)
        # is guaranteed by construction, not by accident.
        _, costs = get_tier2_pairs_with_costs(model_set_pk)
        total_cost = sum(costs.values())
        leaderboard_pk = create_leaderboard_from_cached(model_set_pk, costs)
        print(f"[CACHE HIT] FULL SUMMARY — {len(full_pairs)} combos, previous_cost=${total_cost:.2f}")
        if is_leaderboard_complete(leaderboard_pk):
            set_active_leaderboard(leaderboard_pk)
            print(f"  Created leaderboard {leaderboard_pk} from summary cache and marked it active\n")
        else:
            print(f"  Created leaderboard {leaderboard_pk} from summary cache but it is incomplete; not marking active\n")
        return CacheCheck(True, set())

    if missing_pairs:
        total = len(full_pairs)
        cached = total - len(missing_pairs)
        if cached > 0:
            print(f"[CACHE PARTIAL] SUMMARY — {cached}/{total} combos cached\n")
        return CacheCheck(False, missing_pairs)

    # Response cache (Tier 2) — fallback to derive from model_set_pk via SQL joins
    check, full_pairs, costs = _tier2_cache_check_from_set(model_set_pk)

    # Nothing to do?
    if not check.fully_cached and not check.missing_pairs:
        print("  No models or categories\n")
        return check

    # Full hit — create and activate leaderboard
    if check.fully_cached:
        total_cost = sum(costs.values())
        leaderboard_pk = create_leaderboard_from_cached(model_set_pk, costs)
        print(f"[CACHE HIT] FULL RESPONSE — {len(full_pairs)} combos, previous_cost=${total_cost:.2f}")
        if is_leaderboard_complete(leaderboard_pk):
            set_active_leaderboard(leaderboard_pk)
            print(f"  Created leaderboard {leaderboard_pk} from cache and marked it active\n")
        else:
            print(f"  Created leaderboard {leaderboard_pk} but it is incomplete; not marking active\n")
        return CacheCheck(True, set())

    # Partial cache — compute coverage for messaging
    if check.missing_pairs:
        total = len(full_pairs)
        cached = total - len(check.missing_pairs)
        if cached > 0:
            print(f"[CACHE PARTIAL] RESPONSE — {cached}/{total} combos cached\n")
    return check


def _execute_and_complete_batch(batch_pk: int, model_set_pk: int, model_ids: list[str], old_models: set[str]) -> dict:
    """Execute batch, handle failures, and create leaderboard if all succeeded.

    This is the workhorse after cache misses. Runs the async executor, prints
    progress/summaries, and gates leaderboard creation on 100% success.

    Returns the executor results dict for caller to check failure counts.
    """
    print(f"  Executing pending requests for batch {batch_pk}...\n")
    results = asyncio.run(execute_pending_requests(batch_pk))

    # Primary completion message
    print(
        f"  Completed in {results['elapsed_minutes']:.1f}m: "
        f"{results['succeeded']} succeeded, {results['failed']} failed\n"
    )

    # Show retry statistics if any retries occurred
    total_retries = results.get('total_retries', 0)
    requests_with_retries = results.get('requests_with_retries', 0)
    if total_retries > 0:
        retry_rate = (requests_with_retries / results['succeeded']) * 100 if results['succeeded'] > 0 else 0
        retry_rate_pct = round(retry_rate, 1)
        print(
            f"  Stats: {retry_rate_pct}% retry rate, "
            f"{requests_with_retries} requests had retries ({total_retries} attempts)\n"
        )

        # Show timing insights from instrumentation
        retry_summary = results.get('retry_summary', {})
        timing = retry_summary.get('timing_ms', {})
        if timing:
            http_wait = timing.get('http_queue_wait', {})
            http_rtt = timing.get('http_roundtrip', {})
            if http_wait.get('avg_ms', 0) > 1000:  # Show if avg wait > 1 second
                print(f"  Performance: HTTP queue wait avg={http_wait.get('avg_ms', 0)/1000:.1f}s, "
                      f"roundtrip avg={http_rtt.get('avg_ms', 0)/1000:.1f}s")

    # Screenshot summary (streaming pipeline prints per-item; summarize here)
    if 'screenshot_total' in results:
        total = results.get('screenshot_total', 0)
        succ = results.get('screenshot_succeeded', 0)
        fail = results.get('screenshot_failed', 0)
        skipped = results.get('screenshot_skipped', 0)
        print(f"  Screenshots: [OK] {succ}/{total} ([FAIL] {fail}), skipped {skipped}")
        axe_total = results.get('axe_total', 0)
        axe_ok = results.get('axe_succeeded', 0)
        axe_fail = results.get('axe_failed', 0)
        print(f"  Axe: [OK] {axe_ok}/{axe_total} ([FAIL] {axe_fail})")
        axe_timing = results.get('axe_timing_ms') or {}
        if axe_timing:
            inj_p95 = float(axe_timing.get('inject_p95', 0.0) or 0.0)
            run_p95 = float(axe_timing.get('run_p95', 0.0) or 0.0)
            logger.debug(f"Axe timing: inject p95={inj_p95:.0f}ms, run p95={run_p95:.0f}ms")
            if run_p95 > 1000:
                logger.warning("Axe run p95 exceeds 1000ms threshold")
        reasons = results.get('axe_failure_reasons') or {}
        if reasons:
            # Compact reason breakdown
            pairs = ", ".join(f"{k}={v}" for k, v in reasons.items())
            print(f"  Axe fail reasons: {pairs}\n")

    # Mark batch completed at true end-of-run (deploy path: fail loudly if this breaks)
    mark_batch_completed(batch_pk)

    # Block leaderboard creation on ANY failures (HTTP or screenshots)
    http_failed = results.get('failed', 0)
    screenshot_failed = results.get('screenshot_failed', 0)
    if http_failed > 0 or screenshot_failed > 0:
        # Print model-level failure summary for diagnosis
        model_failures = results.get('llm_failure_by_model') or {}
        if model_failures:
            print("  Model failures:")
            for model, info in sorted(model_failures.items(), key=lambda x: -x[1]['count']):
                # info['reasons'] is a dict of {reason: count}
                reasons = info.get('reasons', {})
                if reasons:
                    reasons_str = ', '.join(f"{r}:{c}" for r, c in sorted(reasons.items()))
                else:
                    reasons_str = 'unknown'
                print(f"    {model}: {info['count']} ({reasons_str})")
            print()
        print(f"  [WARN] Batch had failures (HTTP: {http_failed}, screenshots: {screenshot_failed}) — NOT creating leaderboard\n")
        print("  Previous leaderboard remains active\n")
        return results

    # Create and activate leaderboard after screenshots/axe so summaries include latest axe metrics
    _full_pairs, costs = get_tier2_pairs_with_costs(model_set_pk)
    leaderboard_pk = create_leaderboard_from_cached(model_set_pk, costs)
    if is_leaderboard_complete(leaderboard_pk):
        set_active_leaderboard(leaderboard_pk)
        print(f"  Created leaderboard {leaderboard_pk} and marked it active\n")
    else:
        print(f"  Created leaderboard {leaderboard_pk} but it is incomplete; not marking active\n")
    return results
