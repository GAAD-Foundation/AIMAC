"""Tests for CLI logging and init error handling."""

from __future__ import annotations

import logging

from aimac import cli


def test_setup_logging_respects_env_and_json(tmp_path, monkeypatch):
    log_file = tmp_path / "aimac.log"
    monkeypatch.setenv("AIMAC_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("AIMAC_LOG_FORMAT", "json")
    monkeypatch.setenv("AIMAC_LOG_PATH", str(log_file))

    # Reset root logger so basicConfig reconfigures
    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)
    cli.setup_logging()

    logger = logging.getLogger("aimac.test")
    logger.debug("hello json")
    # Ensure handlers flush to disk
    logging.shutdown()

    # Ensure file written with JSON-like content
    assert log_file.exists()
    content = log_file.read_text()
    assert "hello json" in content
    assert content.strip().startswith("{")


def test_setup_logging_no_file_when_path_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIMAC_LOG_LEVEL", "INFO")
    monkeypatch.setenv("AIMAC_LOG_FORMAT", "plain")
    monkeypatch.setenv("AIMAC_LOG_PATH", "")

    cli.setup_logging()

    # Log a warning (goes to console handler only). No file should be created.
    logging.getLogger("aimac.test").warning("warn message")
    # No files under tmp_path since path was empty
    assert not any(tmp_path.iterdir())


def test_init_command_migration_error(monkeypatch, capsys):
    # Force fresh init path and a migration error
    # Patch symbols imported into cli module
    monkeypatch.setattr("aimac.cli.check_database_exists", lambda: False)
    def _raise():
        raise cli.MigrationError("boom")
    monkeypatch.setattr("aimac.cli.init_database", lambda: _raise())

    rc = cli.init_command()
    captured = capsys.readouterr()
    assert rc == 1
    assert "Migration failed" in captured.err  # Errors go to stderr
