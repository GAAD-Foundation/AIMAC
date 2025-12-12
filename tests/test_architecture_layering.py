"""Architecture layering tests to enforce separation of concerns.

These tests enforce that SQL queries stay in the database layer where they belong.
"""

from pathlib import Path
import re

import pytest


def get_source_files(directory: str, exclude_dirs: set[str] | None = None) -> list[Path]:
    """Get all Python files in a directory, excluding specified subdirectories."""
    exclude_dirs = exclude_dirs or set()
    src_root = Path("src/aimac")
    target = src_root / directory if directory else src_root
    
    files = []
    for path in target.rglob("*.py"):
        # Check if any excluded dir is in the path
        if any(excluded in path.parts for excluded in exclude_dirs):
            continue
        files.append(path)
    return files


def has_sql_queries(file_path: Path) -> tuple[bool, list[tuple[int, str]]]:
    """Check if a file contains SQL queries (cursor.execute or conn.execute).
    
    Returns (has_sql, violations) where violations is a list of (line_num, line_content).
    """
    violations = []
    
    try:
        content = file_path.read_text(encoding="utf-8")
        for i, line in enumerate(content.splitlines(), start=1):
            # Match cursor.execute(...) or conn.execute(...)
            if re.search(r'\b(cursor|conn)\.execute\s*\(', line):
                violations.append((i, line.strip()))
    except Exception as e:
        pytest.fail(f"Failed to read {file_path}: {e}")
    
    return bool(violations), violations


def test_no_sql_outside_database_layer():
    """Enforce that SQL queries only exist in src/aimac/database/ modules.
    
    All SQL queries have been moved to database/_reports.py.
    This test now enforces that no new SQL queries are added outside the database layer.
    """
    # Get all Python files outside the database/ directory
    non_database_files = get_source_files("", exclude_dirs={"database", "__pycache__"})
    
    violations_by_file = {}
    
    for file_path in non_database_files:
        has_sql, violations = has_sql_queries(file_path)
        if has_sql:
            violations_by_file[file_path] = violations
    
    if violations_by_file:
        error_msg = ["SQL queries found outside database/ layer:"]
        for file_path, violations in violations_by_file.items():
            rel_path = file_path.relative_to(Path("src/aimac"))
            error_msg.append(f"\n  {rel_path}:")
            for line_num, line_content in violations:
                error_msg.append(f"    Line {line_num}: {line_content[:80]}")
        
        error_msg.append("\n\nArchitectural Rule:")
        error_msg.append("  SQL queries must live in src/aimac/database/ modules")
        error_msg.append("  Move these queries to database/_reports.py or another database/* module")
        
        pytest.fail("\n".join(error_msg))


def test_database_layer_structure_exists():
    """Sanity check: Verify the database layer exists with expected structure."""
    database_dir = Path("src/aimac/database")
    assert database_dir.exists(), "database/ directory should exist"
    
    # Check key database modules exist
    expected_modules = [
        "__init__.py",
        "_core.py",
        "_reports.py",
        "_models.py",
        "_leaderboards.py",
    ]
    
    for module in expected_modules:
        module_path = database_dir / module
        assert module_path.exists(), f"Expected database module {module} to exist"


def test_database_modules_can_have_sql():
    """Positive test: database/ modules SHOULD contain SQL queries."""
    database_files = get_source_files("database")
    
    # At least one database module should have SQL
    has_any_sql = False
    for file_path in database_files:
        has_sql, _ = has_sql_queries(file_path)
        if has_sql:
            has_any_sql = True
            break
    
    assert has_any_sql, "database/ modules should contain SQL queries (this is expected)"

