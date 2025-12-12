# ARCHITECTURE.md

## Overview
AIMAC measures how well AI models (GPT-4o, Claude Sonnet 4, Gemini 2.5 Pro, etc.) generate accessible HTML. It asks each model to create web pages for common scenarios (shopping, news, education), then runs automated accessibility tests to find issues like missing alt text, poor color contrast, or broken keyboard navigation.

The results rank models by accessibility quality, helping developers choose models that produce more inclusive web content.

### User Workflows

**First-time setup:**
```
aimac init
  └─> Creates database and applies schema migrations
      └─> Required before first `aimac collect`
```

**Running benchmarks:**
```
aimac collect
  ├─> Fetch models from OpenRouter API
  ├─> For each model × each enabled category:
  │   ├─> Check cache (skip if already tested)
  │   ├─> Generate HTML via model API
  │   ├─> Take screenshot of rendered page
  │   └─> Run axe-core accessibility audit (industry-standard accessibility testing engine)
  │
  └─> Store results and create leaderboard
```

**Viewing results:**
```
aimac report
  └─> Query database for active leaderboard
      ├─> Leaderboard: all models ranked by accessibility score
      ├─> Model detail: one model's results across all categories
      └─> Category detail: all models compared within one category
```

### End-to-End: How One Test Flows

A single test (e.g., GPT-4 generating a "Shopping" page) flows through the system:

1. **Check cache** — Skip if we already have valid results for this model×category pair
2. **Send prompt** — Request HTML from the model via OpenRouter API
3. **Validate response** — Extract HTML, check it's well-formed
4. **Screenshot** — Render HTML in headless browser, capture PNG
5. **Accessibility audit** — Run axe-core, collect violations with severity levels
6. **Store results** — Save to database: prompt, HTML, screenshot path, violations
7. **Aggregate** — After all pairs complete, compute rankings and create leaderboard

### Data Authority

**The database is the single source of truth.** All test results, costs, and audit findings live in the SQLite database. Files on disk (HTML, screenshots) are output artifacts.

## Project Structure
```
src/aimac/
├── cli.py              # Command-line interface (init, collect)
├── collector.py        # Model collection orchestration
├── executor.py         # Async request execution with retries
├── artifacts.py        # Artifact writing (HTML, JSON files)
├── axe_scorer.py       # Axe-core accessibility scoring
├── formatting.py       # Score/cost display formatting (adaptive decimals)
├── openrouter.py       # OpenRouter API client
├── reporter.py         # CLI report generation
├── screenshotter.py    # Screenshot + axe-core accessibility analysis (Playwright)
├── utils.py            # Shared utilities (env parsing, statistics)
├── vendor/             # Vendored libraries
│   └── axe.min.js      # Axe-core accessibility testing engine
└── database/           # Database package (public API via __init__.py)
    ├── __init__.py     # Facade: re-exports stable database API
    ├── _axe.py         # Axe-core result storage
    ├── _batches.py     # Batch lifecycle (create/mark)
    ├── _categories.py  # Enabled categories + cache lookups
    ├── _core.py        # DB init, connections, migrations
    ├── _leaderboards.py# Leaderboard helpers + activation
    ├── _models.py      # Models + model_sets helpers
    ├── _reports.py     # Report data queries
    ├── _requests.py    # Request insertion + system prompt
    └── _responses.py   # Response storage and evaluation
```

## Data Flow

### Model Collection (`aimac collect`)
1. **API Fetch**: `openrouter.fetch_top_models()` retrieves programming models from OpenRouter
2. **Snapshot**: Models are saved to `data/snapshots/models/YYYY-MM-DD_HH-MM.json` for debugging/inspection
3. **Database Upsert**: `database.upsert_models()` inserts or updates models while preserving manual overrides
4. **Model Set Cache Key**: Extract model IDs and call `database.upsert_model_set(model_ids)` to create/reuse a canonical set for downstream reports

### Caching & Reuse

The collector uses a three-level cache to avoid redundant API calls. Each call costs money and time, so if we've already evaluated a model×category pair, we reuse that work.

**What's a model×category pair?** One model (e.g., `gpt-4o`) tested against one accessibility category (e.g., "Shopping"). A complete benchmark tests every model against every enabled category.

#### Cache Levels

The system checks caches in order, returning as soon as it finds enough data:

**Level 1: Complete Leaderboard**
- **Checks**: Does a finalized leaderboard already exist for this exact set of models?
- **On hit**: Activates that leaderboard and exits. No API calls needed.
- **On miss**: Proceeds to Level 2.

**Level 2: All Summaries Present**
- **Checks**: Do we have cached results for every model×category pair? (Each needs: successful response, screenshot, and axe audit)
- **On hit**: Creates a new leaderboard from cached data, activates it, exits.
- **On miss**: Proceeds to Level 3.

**Level 3: Partial Results**
- **Checks**: Which model×category pairs have valid cached results?
- **Action**: Reuses cached pairs, only calls the API for missing pairs.

#### Bypassing the Cache

Pass `--refresh` to ignore all caches and re-run all API calls. Useful when you've updated the system prompt or want fresh results.

## API Endpoints

### Fetch Models
- **Endpoint**: `https://openrouter.ai/api/v1/models?category=programming`
- **Method**: GET
- **Headers**: Includes API key, referer, title, and user-agent for tracking

### Generate Completions
- **Endpoint**: `https://openrouter.ai/api/v1/chat/completions`
- **Method**: POST
- **Purpose**: Generates HTML content for accessibility testing

## Database Schema

### Models Table
- Stores model metadata from OpenRouter API
- Includes manual override fields for display names
- Uses JSON columns for flexible API data storage

### View (`view_models`)
- Computed fields for company/model names and slugs
- Extracts pricing and feature support from JSON
- See "Database Views" section for full list

### Batches Table
- Tracks individual `aimac collect` execution runs
- Contains `batch_date` (YYYYMMDD) and `batch_time` (HHMMSS) for organizing output files
- Records execution timing (`started_at`, `completed_at`) for performance monitoring
- Used in output directory structure: `output/{batch_date}/{batch_time}/batch_{pk}/...`

### Categories Table
- Seeds 29 standard web categories from WebAIM Million benchmark
- Each category has a complete user prompt for generating test web pages
- Contains `enabled` flag (28 enabled, 1 disabled)
- The categories match the categorization used in the WebAIM Million Report: https://webaim.org/projects/million/#categories
- The one disabled category is "Adult Content". WebAIM needed it to analyze the top million websites, but we do not generate adult content.

### Model Sets Table
- Stores unique combinations of models used for leaderboard reports
- Acts as a cache key: identical model combinations share the same `model_sets.pk`
- Enforces canonical format via database triggers to prevent duplicates

**Canonicalization Rules:**
1. All model IDs converted to lowercase
2. Duplicates removed
3. Sorted alphabetically
4. All spaces stripped from model IDs
5. Stored as compact JSON array (no whitespace)

**Example:** `["anthropic/claude-3-opus","google/gemini-pro","openai/gpt-4"]`

### Leaderboards Table
- References `model_sets.pk` to identify which models were tested
- Stores aggregated results (total cost, scores, violations)
- Foreign key relationship enables transaction-safe multi-table operations

#### Ranking Algorithm
Models within a leaderboard are ranked using the following tie-breaking sequence (all ASC, lower is better):

1. **Primary**: `median_weighted_score` — Median accessibility score across all 28 categories
2. **Tie 1**: `avg_axe_score` — Mean accessibility score (average of all category scores)
3. **Tie 2**: `total_violations` — Total number of WCAG violations across all categories
4. **Tie 3**: `total_cost_usd` — Total API cost for generating all test pages

If models have identical values for all four metrics, they receive the same rank (genuine tie).

We also compute reliability metrics per model across categories: Standard Deviation ("Consistency") and P90 (90th percentile). These help interpret results and provide tie context, but do not influence ranking.

### Axe Rules Table
- Stores metadata for axe-core rules (help text, URLs, version history)
- Populated during ingestion to serve as a single source of truth for rule labels
- Enables reporting without re-parsing thousands of JSON files

### System Prompts Table
- Stores historical system prompts used for generating test HTML
- Singleton `system_prompt_active` table tracks which prompt is currently active
- Allows prompt versioning and A/B testing

### Database Views
Views provide denormalized access to foreign key relationships:
- **view_models**: Exposes computed company/model names and pricing
- **view_leaderboards**: Joins leaderboards with model_sets to show model lists
- **view_leaderboard_active**: Shows currently active leaderboard with full details
- **view_system_prompt_active**: Shows active system prompt with complete text

### Request Execution
When running benchmarks, `executor.py` sends requests to OpenRouter:
- Uses `httpx.AsyncClient` with configurable concurrency (default 50, via `OPENROUTER_CONCURRENCY`)
- Implements exponential backoff for transient failures (see "Error Handling" for details)
- Saves all attempts to `model_categories_responses` table
- Writes artifacts via `artifacts.py` (HTML, request/response JSON)

### Accessibility Testing (Axe-core Integration)
After HTML generation and screenshots, AIMAC runs axe-core accessibility audits:
- `axe_scorer.py` analyzes violation JSON and computes weighted scores
- Only Serious and Critical violations count (Minor and Moderate are ignored)
- Base scoring: Critical = 5 points, Serious = 2 points
- **Dampening algorithm**: Repeated instances of the same rule use log2 dampening to prevent a single rule from dominating scores:
  - Critical violations: k=0.75 dampening factor
  - Serious violations: k=0.50 dampening factor
  - `color-contrast` rule override: k=0.33 (most common violation, heavily dampened)
- `database/_axe.py` stores results:
  - `axe_runs`: Score summary and JSON path (FK to `model_categories_request`)
  - `axe_rule_breakdown`: Per-rule violation counts (for aggregations)
  - `axe_rules`: Rule metadata (help text, URLs, version) to avoid re-parsing JSON
- Full axe JSON preserved to `output/.../axe_results/{request_id}.json`

Helpers exposed via `aimac.database`:
- `insert_axe_run(...)` - Upserts run, breakdowns, and rule metadata
- `get_rule_counts_for_requests(conn, request_pks)` - Aggregates top violations

### Scoring Rationale

Why these weights and formulas? We validated rankings for stability and fairness.

**Severity weights (Critical=5, Serious=2)**
- Critical violations (empty buttons, missing labels) completely block assistive technology users
- Serious violations (poor contrast) create barriers but don't fully block access
- The 2.5:1 ratio reflects this real-world impact difference

**Logarithmic dampening**
- Prevents one repeated issue from dominating scores (e.g., one bad CSS color causing 50 identical violations)
- Color-contrast uses extra dampening (k=0.33 vs 0.50) because it represents 70-100% of all violations

**Validation results**
- Top 2 and bottom 4 ranks: highly stable (99%+ bootstrap confidence)
- Mid-tier ranks (6-16): category-dependent variance reflecting genuine performance differences
- No HTML complexity bias: models generating larger, feature-rich pages aren't penalized unfairly

### Screenshot Pipeline
Screenshot and accessibility testing are processed inline via executor.py's async worker loop, not as a separate batch phase. Implementation is in screenshotter.py using Playwright:
- Worker formula: `min(24, max(2, cpu_count * 4))` — 4 workers per CPU core, capped at 24
- Each worker processes one screenshot at a time
- Configurable timeouts for page load, images, fonts
- Memory model: ~100-300MB per worker
- Artifacts: `{request_id}.png` (1280x720 viewport) alongside HTML files

Configuration (via `.env`):
- `SCREENSHOT_TIMEOUT_MS=10000` - Page load timeout
- `SCREENSHOT_WAIT_IMAGES_MS=3000` - Image settling time
- `SCREENSHOT_WAIT_FONTS_MS=2000` - Font loading wait

### Reporting System
CLI reporting reads directly from the database:

**CLI Reporter (`reporter.py`)**:
- Subcommands: `leaderboard`, `model <id>`, `category <slug>`
- Output formats: TSV (default), Pretty (padded), JSON
- Fuzzy search for models/categories
- Verbose mode (`-v`) adds severity breakdowns and reliability metrics
  (Consistency = StdDev, plus P90) where applicable

**Accessibility-first design:**
- TSV default works with screen readers, grep, cut, and Unix pipes
- No ANSI colors or Unicode decorations that break assistive technology
- Plain text output ensures compatibility with all terminals

Data queries live in `database/_reports.py` (internal module, not public facade).

### Database Triggers
Triggers enforce data integrity and automation:
- **Auto-update timestamps**: `updated_at` columns automatically updated on row changes
- **Canonicalization validation**: `model_sets` triggers reject non-canonical JSON (must be lowercase, sorted, deduplicated, no spaces)
- **Singleton enforcement**: `*_active` tables enforce single-row constraint via `CHECK (pk = 1)`

### Error Handling & Failure Modes

AIMAC's pipeline has multiple failure points. Here's what happens when each component fails:

**OpenRouter API Failures:**
- Rate limiting (HTTP 429) and transient errors (500, 502, 503): Retried with exponential backoff (up to 4 attempts)
- Terminal errors (401, 403, 404): No retry, marked as failed immediately
- Evidence: `model_categories_responses` table stores every attempt with status

**Invalid Model Responses:**
- Empty or malformed HTML: Marked as invalid, blocks that model×category pair
- Output truncated (token limit): Retried up to 3 times, then marked failed
- Evidence: `view_model_categories_responses.html_is_valid` and `finish_reason` fields

**Screenshot Failures:**
- Timeouts and Playwright errors: Retried once after 30s delay
- Missing HTML file: No retry (shouldn't happen if HTTP succeeded)
- Evidence: Missing `{request_id}.png` file

**Axe Audit Failures:**
- Script injection timeout: Retried once after 30s delay
- Database write error: No retry
- Evidence: Missing row in `axe_runs` table for that request

**Partial Batch Completion:**
- If any HTTP or screenshot fails: Leaderboard creation blocked entirely
- If all HTTP/screenshots succeed but axe incomplete: Leaderboard created but NOT activated
- Previous active leaderboard remains active
- Re-running `aimac collect` reuses cached successes and only retries failures

**Configuration (via `.env`):**
```bash
OPENROUTER_CONCURRENCY=50            # Concurrent API requests
OPENROUTER_MAX_RETRY_ATTEMPTS=4      # Retries for transient failures
OPENROUTER_MAX_BACKOFF_SECONDS=30    # Max delay between retries
```

### Dependencies
- **httpx**: Modern HTTP client for API calls
- **python-dotenv**: Environment variable management
- **sqlite3**: Built-in database (no external DB required)

### Security & Secrets

**Credentials:** AIMAC requires one secret: `OPENROUTER_API_KEY` for accessing AI models. Store it in `.env` (never committed; `.gitignore` enforces this). Copy `.env.example` to `.env` and add your key from https://openrouter.ai/keys.

**Data Privacy:** All generated HTML is synthetic test content—no real user data. OpenRouter may log model responses per their privacy policy. AIMAC stores prompts and responses locally in the SQLite database.

**Authentication:** None. AIMAC is a local CLI tool for benchmarking, not a web service.

## Prompt Randomization (Anti-Overfitting Strategy)

AIMAC's prompts are public, which creates a risk: AI companies could train models to recognize and optimize for specific prompt patterns, inflating benchmark scores without genuine accessibility improvements. Prompt randomization prevents this.

### Why It Matters

If prompts were static, a model could learn:
- "When I see 'themes similar to: Consulting Services, Industry Insights' → produce this exact HTML pattern"
- This would make benchmark scores meaningless, they'd measure prompt memorization, not accessibility capability

### How It Works

Each category prompt contains placeholder patterns like:
```
themes similar to: "Consulting Services", "Industry Insights", "Client Success"
```

At runtime, AIMAC replaces these with random selections from larger pools:
```
themes similar to: "Digital Transformation", "Growth Acceleration", "Partnership Stories"
```

**Implementation:**
1. `categories.prompt_fragments` column stores JSON pools of interchangeable text
2. `prompt_randomizer.py` matches regex patterns and substitutes random selections
3. A seed is generated per request for reproducibility during debugging

### Fragment Types

Each category has pools for 6 fragment types:
- **nav_links**: Navigation menu items (Services, About, Pricing...)
- **section_themes**: Content section headings (Industry Insights, Client Success...)
- **terminology**: Domain-specific vocabulary (scalability, ROI optimization...)
- **ctas**: Call-to-action buttons (Get Started, Schedule Demo...)
- **engagement**: Interactive elements (ROI calculator, assessment quiz...)
- **sidebar**: Sidebar content types (market insights, expert tips...)

### Combinatorial Space

With ~15 options per fragment type, selecting 3 from each:
- Per type: C(15,3) = 455 combinations
- With 6 types: 455^6 ≈ **8.8 trillion unique prompt variants**

Even testing all 28 categories repeatedly, enumeration is computationally infeasible.

### Reproducibility

Each request stores a random seed. To replay the exact prompt sent:
```python
from aimac.prompt_randomizer import randomize_prompt
prompt = randomize_prompt(user_prompt, fragments, seed=stored_seed)
```

### What Stays Constant

- **System prompt**: The role definition ("You are a lead web developer...") is static
- **Core instructions**: Accessibility requirements, output format, image service URLs
- **Category context**: The general domain (e.g., "business website", "shopping page")

Only the example lists within prompts are randomized, the semantic meaning is preserved.

### Public Prompts

Because of randomization, AIMAC can publish prompts transparently on aimac.ai:
- Users can inspect exactly what we ask models to generate
- AI companies cannot game the benchmark by memorizing specific patterns
- Researchers can reproduce methodology

## Test Architecture

**Hermetic Isolation** (enforced by `conftest.py`):
- Network blocked: `httpx.Client` and `socket.create_connection` patched to raise
- Dummy API key: `OPENROUTER_API_KEY="test"` forced
- Temp filesystem: `AIMAC_DATA_DIR` points to per-test temp directory
- Temp database: Patch `get_connection()` to use isolated SQLite files

**Test Organization**:
- `test_critical_safety.py` - MUST NEVER FAIL (API calls, manual overrides)
- `test_smoke.py` - End-to-end happy paths
- `test_tier1_cache.py`, `test_tier2_cache.py` - Cache logic
- `test_check_all_caches.py` - Integration of all cache layers (tests `resolve_caches`)
- `test_collector_integration.py` - Full collect workflow
- `test_regressions.py` - Bug regression tests (add when fixing bugs)

**Conditional Skips**:
Some tests skip gracefully if Playwright browser isn't installed (e.g., CI without GUI). These are expected and safe.

## Scoring Validation

The scoring methodology was validated through sensitivity analysis to ensure rankings are stable and fair.

**Key findings:**
- Dampening prevents rank volatility from duplicate violations
- Removing dampening causes median collapse (13+ models tie at 2.0)
- Bootstrap analysis confirms top-tier and bottom-tier rankings are stable (99%+ confidence)
- Mid-tier variance reflects genuine performance differences across categories
- Current configuration balances stability and discrimination
