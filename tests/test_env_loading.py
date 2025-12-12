"""Tests for environment variable loading behavior in the CLI.

Ensures the CLI properly loads .env files at startup before argument parsing,
allowing environment-based configuration without explicit export commands.
"""

from __future__ import annotations

import os
import sys


def test_cli_loads_dotenv(tmp_path, monkeypatch):
    """Ensure CLI loads .env before argument parsing without side effects.

    Isolation:
    - Uses a temp CWD with its own .env
    - Patches sys.argv so no subcommand runs
    - Cleans up the injected env var after
    """
    # Create isolated .env in temp dir
    env_file = tmp_path / ".env"
    env_file.write_text("AIMAC_TEST_SENTINEL=xyz\n")

    # Ensure sentinel not already present
    os.environ.pop("AIMAC_TEST_SENTINEL", None)

    # Change CWD to temp dir so CLI finds this .env
    cwd_before = os.getcwd()
    os.chdir(tmp_path)

    try:
        # Patch argv so main prints help and exits quickly
        monkeypatch.setattr(sys, "argv", ["aimac"])  # no subcommand

        from aimac.cli import main  # import here so module state is stable per test

        rc = main()
        assert rc == 0
        assert os.environ.get("AIMAC_TEST_SENTINEL") == "xyz"
    finally:
        # Cleanup and restore CWD
        os.environ.pop("AIMAC_TEST_SENTINEL", None)
        os.chdir(cwd_before)

