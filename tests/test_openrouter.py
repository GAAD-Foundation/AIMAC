"""Tests for OpenRouter API client."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from aimac.openrouter import send_completion


def test_fetch_top_models_uses_hardcoded_headers(monkeypatch):
    """Verify fetch_top_models passes expected hardcoded headers."""
    from aimac import openrouter as or_mod

    calls = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, headers=None):
            calls["url"] = url
            calls["headers"] = headers
            return FakeResponse()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    with patch.object(or_mod, "httpx") as mock_httpx:
        mock_httpx.Client.return_value = FakeClient()
        or_mod.fetch_top_models("programming")

    hdrs = calls.get("headers", {})
    assert hdrs.get("Authorization") == "Bearer test"
    assert hdrs.get("Content-Type") == "application/json"
    assert hdrs.get("HTTP-Referer") == "https://aimac.ai"
    assert hdrs.get("X-Title") == "AIMAC: AI Model Accessibility Checker"
    assert hdrs.get("User-Agent") == "AIMAC/1.0 (+https://aimac.ai)"


def test_fetch_top_models_with_category_adds_query_param(monkeypatch):
    """Verify fetch_top_models(category='programming') adds ?category=programming to URL."""
    from aimac import openrouter as or_mod

    calls = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, headers=None):
            calls["url"] = url
            return FakeResponse()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    with patch.object(or_mod, "httpx") as mock_httpx:
        mock_httpx.Client.return_value = FakeClient()
        or_mod.fetch_top_models("programming")

    assert calls["url"] == "https://openrouter.ai/api/v1/models?category=programming"


def test_fetch_top_models_without_category_no_query_param(monkeypatch):
    """Verify fetch_top_models(category=None) fetches ALL models without query param."""
    from aimac import openrouter as or_mod

    calls = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, headers=None):
            calls["url"] = url
            return FakeResponse()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    with patch.object(or_mod, "httpx") as mock_httpx:
        mock_httpx.Client.return_value = FakeClient()
        or_mod.fetch_top_models(category=None)

    # No query parameter when category is None
    assert calls["url"] == "https://openrouter.ai/api/v1/models"
    assert "?category=" not in calls["url"]


@pytest.mark.asyncio
async def test_send_completion_success():
    """Successful completion should return parsed response."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "<html>Test</html>"}}],
        "usage": {"total_tokens": 100}
    }

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    result = await send_completion(mock_client, {"model": "test/model"})

    assert result["status"] == 200
    assert "json" in result


@pytest.mark.asyncio
async def test_send_completion_headers(monkeypatch):
    """Verify hardcoded headers are used in send_completion."""
    from aimac import openrouter as or_mod

    # AsyncClient.post returns our mock response, but we want to capture headers
    captured = {}

    async def fake_post(url, *, headers=None, json=None, timeout=None):
        captured["headers"] = headers
        r = Mock()
        r.status_code = 200
        r.json.return_value = {"choices": [], "usage": {}}
        return r

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    client = Mock(spec=httpx.AsyncClient)
    client.post = AsyncMock(side_effect=fake_post)

    await or_mod.send_completion(client, {"model": "x"})

    hdrs = captured.get("headers", {})
    assert hdrs.get("Authorization") == "Bearer test"
    assert hdrs.get("Content-Type") == "application/json"
    assert hdrs.get("HTTP-Referer") == "https://aimac.ai"
    assert hdrs.get("X-Title") == "AIMAC: AI Model Accessibility Checker"
    assert hdrs.get("User-Agent") == "AIMAC/1.0 (+https://aimac.ai)"


@pytest.mark.asyncio
async def test_send_completion_network_error():
    """Network errors should return status -1."""
    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))

    result = await send_completion(mock_client, {"model": "test/model"})

    assert result["status"] == -1
    assert "error" in result.get("json", {})


@pytest.mark.asyncio
async def test_send_completion_rate_limit():
    """429 rate limit should be properly captured."""
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.json.return_value = {
        "error": {"code": 429, "message": "Rate limit exceeded"}
    }

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    result = await send_completion(mock_client, {"model": "test/model"})

    assert result["status"] == 429


@pytest.mark.asyncio
async def test_send_completion_timeout():
    """Timeout errors should be handled gracefully."""
    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timeout"))

    result = await send_completion(mock_client, {"model": "test/model"})

    assert result["status"] == -1


@pytest.mark.asyncio
async def test_send_completion_auth_error():
    """401 auth errors should be captured."""
    mock_response = Mock()
    mock_response.status_code = 401
    mock_response.json.return_value = {
        "error": {"code": 401, "message": "Invalid API key"}
    }

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    result = await send_completion(mock_client, {"model": "test/model"})

    assert result["status"] == 401
