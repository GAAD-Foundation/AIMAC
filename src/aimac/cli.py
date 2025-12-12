"""Command-line interface for AIMAC.

Entry point for all CLI commands:
- `aimac init` (alias: `i`) - Initialize/update database schema
- `aimac collect` (alias: `c`) - Run benchmark collection
- `aimac report` (alias: `r`) - Display reports and leaderboards

The main() function is registered as the `aimac` console script in pyproject.toml.

Environment variables (loaded from .env if present):
- AIMAC_LOG_LEVEL: DEBUG, INFO, WARNING, ERROR (default: INFO)
- AIMAC_LOG_FORMAT: plain or json (default: plain)
- AIMAC_LOG_PATH: Log file location (default: ./data/logs/aimac.log)

See also:
- src/aimac/collector.py - collect command implementation
- src/aimac/reporter.py - report command implementation
- README.md - user-facing CLI documentation
"""

import logging
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

from .collector import collect_command
from .database import DatabaseError, MigrationError, check_database_exists, init_database
from .reporter import register_cli as register_reporting_cli
from .reporter import run_reporting as run_reporting


def load_environment() -> None:
    """Load environment variables from .env file if it exists.

    Checks for .env file in current working directory and loads it using dotenv.
    Idempotent - safe to call multiple times. Does nothing if .env doesn't exist.
    """
    env_path = Path('.env')
    if env_path.exists():
        load_dotenv(env_path)


def _validate_log_level(level_str: str) -> int:
    """Validate and return a logging level, falling back to INFO if invalid.

    Args:
        level_str: String representation of log level (e.g., 'DEBUG', 'info', 'Warning')

    Returns:
        Integer log level constant from logging module (e.g., logging.INFO)
        Falls back to logging.INFO if level_str is invalid.

    Note:
        Prints warning to stderr for invalid levels (can't use logging yet as
        we're still configuring it).
    """
    valid_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
    level_upper = level_str.upper()
    if level_upper in valid_levels:
        return getattr(logging, level_upper)
    # Can't use logging yet (we're configuring it), so print to stderr
    print(
        f"Warning: Invalid AIMAC_LOG_LEVEL '{level_str}', using INFO",
        file=sys.stderr
    )
    return logging.INFO


def setup_logging() -> None:
    """Configure logging with console and file handlers.

    Both console and file handlers respect AIMAC_LOG_LEVEL (default: INFO).
    In DEBUG mode, console shows timestamps and logger names for debugging.
    Otherwise, console shows clean message-only output.

    Environment variables:
        AIMAC_LOG_LEVEL: DEBUG, INFO, WARNING, ERROR (default: INFO)
        AIMAC_LOG_FORMAT: plain or json (default: plain) - for file logging
        AIMAC_LOG_PATH: Log file location (default: ./data/logs/aimac.log)

    Note:
        If file logging fails (permissions, invalid path), the CLI continues
        with console logging only. Silences noisy third-party HTTP loggers
        (httpcore, httpx, urllib3, requests) at WARNING level even in DEBUG mode.
    """
    # Load environment first (idempotent, safe if already called by main())
    load_environment()

    log_level_str = os.getenv('AIMAC_LOG_LEVEL', 'INFO')
    log_level = _validate_log_level(log_level_str)
    log_format_type = os.getenv('AIMAC_LOG_FORMAT', 'plain').lower()
    log_path = os.getenv('AIMAC_LOG_PATH', './data/logs/aimac.log')

    # Ensure log directory exists
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    # Configure handlers
    handlers: list[logging.Handler] = []

    # Console handler - respects AIMAC_LOG_LEVEL for console output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    if log_level == logging.DEBUG:
        console_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    else:
        console_format = '%(message)s'

    console_handler.setFormatter(logging.Formatter(console_format))
    handlers.append(console_handler)

    # File handler (always detailed) - wrapped in try/except so CLI works
    # even if file logging fails (permissions, invalid path, etc.)
    if log_path:
        try:
            file_handler = logging.FileHandler(log_path)
            file_handler.setLevel(log_level)

            if log_format_type == 'json':
                file_format = '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'
            else:
                file_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

            file_handler.setFormatter(logging.Formatter(file_format))
            handlers.append(file_handler)
        except OSError as e:
            print(
                f"Warning: Could not create log file '{log_path}': {e}",
                file=sys.stderr
            )

    # Configure the root logger.
    #
    # level=DEBUG: Messages pass through TWO gatekeepers: the logger, then handlers.
    # Setting DEBUG here means "don't pre-filter"—let each handler (console/file)
    # decide its own verbosity. Without this, a logger set to INFO would discard
    # DEBUG messages before they ever reach a file handler that wanted them.
    #
    # force=True: Some libraries call basicConfig() on import. Without force=True,
    # their config would silently win and ours would be ignored.
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=handlers,
        force=True
    )

    # Silence noisy third-party HTTP loggers (even in DEBUG mode)
    for noisy_logger in ('httpcore', 'httpx', 'urllib3', 'requests'):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def init_command() -> int:
    """Initialize or update the AIMAC database schema.

    Idempotent: safe to run multiple times. Applies any new schema files
    that haven't been applied yet.

    Returns:
        0 on success, 1 on failure

    Raises:
        MigrationError: When migration files fail to apply
        DatabaseError: When database connection or operations fail
        FileNotFoundError: When schema directory is missing
    """
    logger = logging.getLogger(__name__)

    try:
        # Check if we're reinitializing or creating new
        if check_database_exists():
            print("  Database already exists, checking for new migrations...\n")
        else:
            print("  Initializing new aimac database...\n")

        # Apply migrations
        applied_count = init_database()

        if applied_count == 0:
            print("  Database is up to date (no new migrations)\n")
        else:
            print(f"[OK] Database initialized successfully ({applied_count} migration{'s' if applied_count != 1 else ''} applied)\n")

        logger.info(f"Database initialization completed. Applied {applied_count} migrations")
        return 0

    except MigrationError as e:
        print(f"[FAIL] Migration failed: {e}", file=sys.stderr)
        logger.error(f"Migration error during init: {e}", exc_info=True)
        return 1

    except DatabaseError as e:
        print(f"[FAIL] Database error: {e}", file=sys.stderr)
        logger.error(f"Database error during init: {e}", exc_info=True)
        return 1

    except FileNotFoundError as e:
        # Note: This assumes FileNotFoundError comes from schema directory lookup
        # in init_database(). If init_database() changes, this message may be misleading.
        print(f"[FAIL] Schema directory not found: {e}", file=sys.stderr)
        print("  Ensure data/schema/ directory exists with your SQL migration files", file=sys.stderr)
        logger.error(f"File not found: {e}")
        return 1

    except Exception as e:
        print(f"[FAIL] Unexpected error: {e}", file=sys.stderr)
        logger.exception("Unexpected error during database initialization")
        return 1




def main(argv: list[str] | None = None) -> int:
    """Main entry point for the `aimac` CLI, registered in pyproject.toml.

    Parses subcommands (init, collect, report) and dispatches to handlers.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:] if None).
              Allows unit tests to call main(['init']) directly.

    Returns:
        Exit code for shell: 0 for success, 1 for failure
    """
    import argparse

    # Python buffers stdout for efficiency, but during long runs we want progress
    # messages to appear immediately, not all at once when the buffer flushes.
    # line_buffering=True flushes after every newline so each print() shows instantly.
    #
    # Some environments (test harnesses, piped output) replace stdout with mocks
    # that lack reconfigure(), so we check before calling to avoid crashes.
    reconfig = getattr(sys.stdout, 'reconfigure', None)
    if callable(reconfig):
        reconfig(line_buffering=True)

    # Ensure .env is loaded for all commands (not just init)
    load_environment()

    # Configure logging for all commands (respects AIMAC_LOG_* env vars)
    setup_logging()

    # Create main parser
    parser = argparse.ArgumentParser(
        description="AIMAC - AI Model Accessibility Checker\nBenchmark LLMs on web accessibility using automated testing",
        prog="aimac",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Quick start:
  aimac init            # First time setup
  aimac collect         # Run benchmarks (takes ~10 min)
  aimac report          # View leaderboard

Examples:
  aimac collect --models openai/gpt-4o,anthropic/claude-sonnet-4  # Test specific models
  aimac collect --refresh              # Force fresh run (bypass all cache tiers)
  aimac r model 1 -v                   # Verbose mode (show all columns)
  aimac r category shopping --format pretty  # Category report as padded columns
  aimac r --format json > out.json     # Export leaderboard to JSON

More help on reporting in the CLI:
  aimac report -h       # See all reporting flags (--format, -v, etc.)
  aimac r help          # See reporting examples and workflows
"""
    )

    # Create subcommands
    subparsers = parser.add_subparsers(
        dest="command",
        title="Commands",
        metavar="{init,i,collect,c,report,r}"
    )

    # Init command
    subparsers.add_parser(
        "init",
        aliases=["i"],
        help="Initialize the database"
    )

    # Collect command
    collect_parser = subparsers.add_parser(
        "collect",
        aliases=["c"],
        help="Run accessibility benchmarks and update leaderboard"
    )
    collect_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force a fresh collection (skip all caches)"
    )
    collect_parser.add_argument(
        "--models",
        type=str,
        metavar="MODEL_IDS",
        help="Comma-separated model IDs to test (e.g., openai/gpt-4o,anthropic/claude-sonnet-4)"
    )

    # Reporting commands (aimac r ...)
    register_reporting_cli(subparsers)

    # Parse arguments
    args = parser.parse_args(argv)

    # Handle commands
    if not args.command:
        parser.print_help()
        return 0

    if args.command in ("init", "i"):
        return init_command()
    elif args.command in ("collect", "c"):
        # Parse --models if provided (comma-separated model IDs)
        models_arg = getattr(args, "models", None)
        model_ids = None
        if models_arg:
            model_ids = [m.strip() for m in models_arg.split(",") if m.strip()]
        return collect_command(
            refresh=getattr(args, "refresh", False),
            model_ids=model_ids,
        )
    elif args.command in ("report", "r"):
        return run_reporting(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
