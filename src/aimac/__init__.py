"""AIMAC - AI Model Accessibility Checker.

Benchmark LLMs on web accessibility by having them generate HTML pages
and scoring them with axe-core automated testing.

Quick start:
    aimac init      # Initialize database
    aimac collect   # Run benchmarks
    aimac report    # View leaderboard

Public API exports database utilities for programmatic access.
See README.md for full documentation.
"""

__version__ = "1.0.0"

from .database import DatabaseError, MigrationError, check_database_exists, get_connection, init_database

__all__ = [
    "DatabaseError",
    "MigrationError",
    "check_database_exists",
    "get_connection",
    "init_database",
]
