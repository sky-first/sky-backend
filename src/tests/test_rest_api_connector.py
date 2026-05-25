"""Tests for src/connectors/rest_api.py (Bug 5 — first real non-SQL connector)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.connectors.rest_api import RestAPIConnector


# CR-002 (PR #235) added an SSRF guard that calls
# ``socket.getaddrinfo(host)`` BEFORE the HTTP layer fires. Tests that
# use ``api.example.com`` (the RFC 2606 documentation TLD) fail in any
# environment whose DNS doesn't resolve that host — notably the GitHub
# Actions runner (and offline laptops). Auto-applied to every test in
# this file: no-op the validator, since these tests are about HTTP
# behavior, not SSRF coverage. SSRF is exercised separately in
# ``test_url_allowlist.py``.
@pytest.fixture(autouse=True)
def _bypass_ssrf_dns(monkeypatch):
    monkeypatch.setattr(
        "src.connectors.rest_api.validate_outbound_url",
        lambda url, **_kw: url,
    )


class _MockResp:
    def __init__(self, status_code: int, json_data=None, text: str = "", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {"content-type": "application/json"}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom", request=None, response=httpx.Response(self.status_code)
            )


@pytest.mark.asyncio
async def test_test_connection_returns_true_on_2xx():
    conn = RestAPIConnector()
    with patch("src.connectors.rest_api._request", new=AsyncMock(return_value=_MockResp(200))):
        assert await conn.test_connection({"base_url": "https://api.example.com"}) is True


@pytest.mark.asyncio
async def test_test_connection_accepts_401_since_endpoint_is_reachable():
    # 401 means "alive but needs auth" — still reachable, not a server failure.
    conn = RestAPIConnector()
    with patch("src.connectors.rest_api._request", new=AsyncMock(return_value=_MockResp(401))):
        assert await conn.test_connection({"base_url": "https://api.example.com"}) is True


@pytest.mark.asyncio
async def test_test_connection_returns_false_on_5xx():
    conn = RestAPIConnector()
    with patch("src.connectors.rest_api._request", new=AsyncMock(return_value=_MockResp(503))):
        assert await conn.test_connection({"base_url": "https://api.example.com"}) is False


@pytest.mark.asyncio
async def test_test_connection_returns_false_when_base_url_missing():
    conn = RestAPIConnector()
    assert await conn.test_connection({}) is False


@pytest.mark.asyncio
async def test_execute_query_list_response_passes_through():
    conn = RestAPIConnector()
    rows = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
    with patch(
        "src.connectors.rest_api._request",
        new=AsyncMock(return_value=_MockResp(200, json_data=rows)),
    ):
        result = await conn.execute_query(
            {"base_url": "https://api.example.com"}, "/orders"
        )
    assert result == rows


@pytest.mark.asyncio
async def test_execute_query_dict_response_wraps_to_list():
    conn = RestAPIConnector()
    payload = {"status": "ok"}
    with patch(
        "src.connectors.rest_api._request",
        new=AsyncMock(return_value=_MockResp(200, json_data=payload)),
    ):
        result = await conn.execute_query(
            {"base_url": "https://api.example.com"}, "/health"
        )
    assert result == [payload]


@pytest.mark.asyncio
async def test_execute_query_non_json_returns_text_row():
    conn = RestAPIConnector()
    with patch(
        "src.connectors.rest_api._request",
        new=AsyncMock(
            return_value=_MockResp(
                200, text="plain text", headers={"content-type": "text/plain"}
            )
        ),
    ):
        result = await conn.execute_query(
            {"base_url": "https://api.example.com"}, "/ping"
        )
    assert result == [{"text": "plain text"}]


@pytest.mark.asyncio
async def test_execute_query_json_descriptor_with_method_and_params():
    # When the query is a JSON descriptor, method + params flow through.
    conn = RestAPIConnector()
    captured = {}

    async def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        captured["body"] = kwargs.get("body")
        return _MockResp(200, json_data=[{"ok": True}])

    with patch("src.connectors.rest_api._request", new=fake_request):
        descriptor = (
            '{"method":"POST","path":"/search","params":{"q":"hello"},'
            '"body":{"filters":["a"]}}'
        )
        await conn.execute_query({"base_url": "https://api.example.com"}, descriptor)

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.example.com/search"
    assert captured["params"] == {"q": "hello"}
    assert captured["body"] == {"filters": ["a"]}


@pytest.mark.asyncio
async def test_execute_query_missing_base_url_raises():
    conn = RestAPIConnector()
    with pytest.raises(ValueError, match="base_url"):
        await conn.execute_query({}, "/orders")


@pytest.mark.asyncio
async def test_get_metadata_exposes_declared_endpoints_as_tables():
    conn = RestAPIConnector()
    config = {
        "base_url": "https://api.example.com",
        "endpoints": [
            {"name": "orders", "path": "/orders", "method": "GET"},
            {"name": "customers", "path": "/customers"},
        ],
    }
    meta = await conn.get_metadata(config)
    assert len(meta["tables"]) == 2
    names = [t["name"] for t in meta["tables"]]
    assert "orders" in names and "customers" in names
    assert meta["tables"][0]["kind"] == "rest_endpoint"


@pytest.mark.asyncio
async def test_bearer_auth_header_is_attached():
    conn = RestAPIConnector()
    captured_headers = {}

    async def fake_request(method, url, **kwargs):
        captured_headers.update(kwargs.get("headers") or {})
        return _MockResp(200, json_data={})

    with patch("src.connectors.rest_api._request", new=fake_request):
        await conn.execute_query(
            {
                "base_url": "https://api.example.com",
                "auth": {"type": "bearer", "token": "secret-123"},
            },
            "/ping",
        )
    assert captured_headers.get("Authorization") == "Bearer secret-123"


@pytest.mark.asyncio
async def test_apikey_auth_uses_custom_header_name():
    conn = RestAPIConnector()
    captured_headers = {}

    async def fake_request(method, url, **kwargs):
        captured_headers.update(kwargs.get("headers") or {})
        return _MockResp(200, json_data={})

    with patch("src.connectors.rest_api._request", new=fake_request):
        await conn.execute_query(
            {
                "base_url": "https://api.example.com",
                "auth": {"type": "apikey", "token": "k", "header_name": "X-My-Key"},
            },
            "/ping",
        )
    assert captured_headers.get("X-My-Key") == "k"
