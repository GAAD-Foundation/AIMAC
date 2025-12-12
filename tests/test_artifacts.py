"""Tests for artifact writing utilities."""

import json
from pathlib import Path

from aimac.artifacts import write_artifacts, write_retry_summary


def test_write_artifacts_first_attempt(tmp_path):
    """First attempt writes request, response (at base path), and HTML."""
    req_path = str(tmp_path / "test.request.json")
    resp_path = str(tmp_path / "test.response.json")
    html_path = str(tmp_path / "test.html")

    request_body = {"model": "test/model", "messages": []}
    response_json = {"status": 200, "data": "ok"}
    html_content = "<html><body>Test</body></html>"

    results = write_artifacts(
        req_path, resp_path, html_path,
        request_body, response_json, html_content,
        attempt_number=1
    )

    assert results["request"] is True
    assert results["response"] is True
    assert results["html"] is True

    # Verify files exist and contain correct data
    assert Path(req_path).exists()
    # Attempt 1 uses base path (matches DB's view_artifact_paths.response_json_path)
    assert Path(resp_path).exists()
    assert Path(html_path).exists()

    with open(html_path) as f:
        assert f.read() == html_content


def test_write_artifacts_retry_skips_request(tmp_path):
    """Retry attempts should not rewrite request JSON, and response gets suffix."""
    req_path = str(tmp_path / "test.request.json")
    resp_path = str(tmp_path / "test.response.json")

    results = write_artifacts(
        req_path, resp_path, None,
        {}, {"status": 503}, None,
        attempt_number=2  # Retry
    )

    assert results["request"] is False  # Not written on retry
    assert results["response"] is True
    assert not Path(req_path).exists()
    # Retry uses suffixed path
    assert not Path(resp_path).exists()  # Base path NOT written
    assert Path(resp_path.replace(".response.json", ".response.attempt2.json")).exists()


def test_write_artifacts_no_html_on_failure(tmp_path):
    """Failed attempts should not write HTML."""
    req_path = str(tmp_path / "test.request.json")
    resp_path = str(tmp_path / "test.response.json")
    html_path = str(tmp_path / "test.html")

    results = write_artifacts(
        req_path, resp_path, html_path,
        {}, {"status": 500}, None,  # No HTML content
        attempt_number=1
    )

    assert results["request"] is True
    assert results["response"] is True
    assert results["html"] is False  # HTML not written
    assert not Path(html_path).exists()


def test_write_retry_summary(tmp_path):
    """Retry summary should write to batch root."""
    batch_root = tmp_path / "batch_123"
    artifact_path = str(batch_root / "company" / "model" / "category" / "file.html")

    summary = {"total_requests": 10, "total_retries": 3}
    write_retry_summary(artifact_path, summary)

    summary_file = batch_root / "retry_summary.json"
    assert summary_file.exists()

    with open(summary_file) as f:
        data = json.load(f)
        assert data["total_requests"] == 10
        assert data["total_retries"] == 3


def test_write_retry_summary_no_path():
    """Retry summary should handle None path gracefully."""
    # Should not raise
    write_retry_summary(None, {"total_requests": 10})


def test_write_artifacts_creates_parent_dirs(tmp_path):
    """Artifact writing should create parent directories."""
    deep_path = tmp_path / "a" / "b" / "c" / "d"
    req_path = str(deep_path / "test.request.json")
    resp_path = str(deep_path / "test.response.json")

    results = write_artifacts(
        req_path, resp_path, None,
        {"test": "data"}, {"status": 200}, None,
        attempt_number=1
    )

    assert results["request"] is True
    assert results["response"] is True
    assert Path(req_path).exists()
