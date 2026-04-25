"""Tests for src/connectors/confluence.py — Confluence as read-only tabular source."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.confluence import ConfluenceConnector


class _Resp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.request = None

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


def _config(**overrides):
    base = {
        "base_url": "https://acme.atlassian.net",
        "auth": {"type": "basic", "email": "user@acme.com", "api_token": "ATATT-x"},
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_test_connection_true_on_200():
    conn = ConfluenceConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None, auth=None):
        captured["url"] = url
        captured["params"] = params
        captured["auth"] = auth
        return _Resp(200, {"results": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        ok = await conn.test_connection(_config())
    assert ok is True
    assert captured["url"].endswith("/wiki/api/v2/spaces")
    assert captured["params"] == {"limit": 1}
    # Basic auth tuple gets passed through to httpx.
    assert captured["auth"] == ("user@acme.com", "ATATT-x")


@pytest.mark.asyncio
async def test_test_connection_false_on_401():
    conn = ConfluenceConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=_Resp(401))
        ok = await conn.test_connection(_config())
    assert ok is False


@pytest.mark.asyncio
async def test_test_connection_false_when_base_url_missing():
    conn = ConfluenceConnector()
    ok = await conn.test_connection({"auth": {"type": "basic", "email": "x", "api_token": "y"}})
    assert ok is False


@pytest.mark.asyncio
async def test_bearer_auth_sends_authorization_header():
    conn = ConfluenceConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None, auth=None):
        captured["headers"] = headers or {}
        captured["auth"] = auth
        return _Resp(200, {"results": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query(
            _config(auth={"type": "bearer", "api_token": "TOKEN"}),
            "spaces",
        )
    assert captured["headers"].get("Authorization") == "Bearer TOKEN"
    # Bearer path doesn't pass an httpx auth tuple.
    assert captured["auth"] is None


@pytest.mark.asyncio
async def test_execute_query_spaces_returns_flattened_rows():
    conn = ConfluenceConnector()
    payload = {
        "results": [
            {"id": "10", "key": "ENG", "name": "Engineering", "type": "global",
             "status": "current", "homepageId": "200", "createdAt": "2026-01-01T00:00:00Z"},
        ],
    }
    captured: dict = {}

    async def fake_get(url, headers=None, params=None, auth=None):
        captured["url"] = url
        return _Resp(200, payload)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(_config(), "spaces")
    assert captured["url"].endswith("/wiki/api/v2/spaces")
    assert rows[0]["key"] == "ENG"
    assert rows[0]["homepage_id"] == "200"


@pytest.mark.asyncio
async def test_execute_query_pages_with_space_id_uses_scoped_endpoint():
    conn = ConfluenceConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None, auth=None):
        captured["url"] = url
        return _Resp(200, {"results": [
            {"id": "p1", "title": "Onboarding", "status": "current",
             "spaceId": "10", "version": {"number": 3}},
        ]})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(
            _config(),
            '{"object_type":"pages","space_id":"10","limit":50}',
        )
    assert captured["url"].endswith("/wiki/api/v2/spaces/10/pages")
    assert rows[0]["title"] == "Onboarding"
    assert rows[0]["version"] == 3


@pytest.mark.asyncio
async def test_execute_query_pages_without_space_id_lists_globally():
    conn = ConfluenceConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None, auth=None):
        captured["url"] = url
        return _Resp(200, {"results": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query(_config(), "pages")
    assert captured["url"].endswith("/wiki/api/v2/pages")


@pytest.mark.asyncio
async def test_execute_query_search_requires_cql():
    conn = ConfluenceConnector()
    with pytest.raises(ValueError, match="cql"):
        await conn.execute_query(_config(), '{"object_type":"search"}')


@pytest.mark.asyncio
async def test_execute_query_search_uses_v1_cql_endpoint():
    conn = ConfluenceConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None, auth=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp(200, {"results": [
            {"title": "Doc", "excerpt": "ex", "url": "/x",
             "lastModified": "2026-04-01",
             "content": {"id": "p1", "type": "page", "space": {"key": "ENG"}}},
        ]})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(
            _config(),
            '{"object_type":"search","cql":"type=page AND space=ENG","limit":10}',
        )
    assert captured["url"].endswith("/wiki/rest/api/search")
    assert captured["params"]["cql"] == "type=page AND space=ENG"
    assert captured["params"]["limit"] == 10
    assert rows[0]["space_key"] == "ENG"
    assert rows[0]["id"] == "p1"


@pytest.mark.asyncio
async def test_execute_query_page_requires_page_id():
    conn = ConfluenceConnector()
    with pytest.raises(ValueError, match="page_id"):
        await conn.execute_query(_config(), '{"object_type":"page"}')


@pytest.mark.asyncio
async def test_execute_query_users_uses_current_user_endpoint():
    conn = ConfluenceConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None, auth=None):
        captured["url"] = url
        return _Resp(200, {
            "accountId": "acc-1", "displayName": "Ada", "email": "ada@acme.com", "active": True,
        })

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(_config(), "users")
    assert captured["url"].endswith("/wiki/rest/api/user/current")
    assert rows[0]["account_id"] == "acc-1"
    assert rows[0]["email"] == "ada@acme.com"


@pytest.mark.asyncio
async def test_execute_query_unknown_object_type_raises():
    conn = ConfluenceConnector()
    with pytest.raises(ValueError, match="Unknown Confluence object_type"):
        await conn.execute_query(_config(), "blocks")


@pytest.mark.asyncio
async def test_execute_query_4xx_surfaces_error_message():
    conn = ConfluenceConnector()
    err = {"message": "API token is invalid"}
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=_Resp(401, err))
        with pytest.raises(Exception, match="API token is invalid"):
            await conn.execute_query(_config(), "spaces")


@pytest.mark.asyncio
async def test_limit_clamped_to_v2_server_cap():
    conn = ConfluenceConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None, auth=None):
        captured["params"] = params
        return _Resp(200, {"results": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query(_config(), '{"object_type":"spaces","limit":9999}')
    assert captured["params"]["limit"] == 250


@pytest.mark.asyncio
async def test_sync_data_returns_rows_by_object():
    conn = ConfluenceConnector()
    config = _config(objects=[
        {"name": "spaces", "object_type": "spaces"},
        {"name": "eng_pages", "object_type": "pages", "space_id": "10"},
    ])

    async def fake_get(url, headers=None, params=None, auth=None):
        if "/api/v2/spaces" in url and "/pages" not in url:
            return _Resp(200, {"results": [{"id": "10", "key": "ENG"}, {"id": "11", "key": "OPS"}]})
        if "/spaces/10/pages" in url:
            return _Resp(200, {"results": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]})
        return _Resp(200, {"results": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        result = await conn.sync_data(config)
    assert result["success"] is True
    assert result["rows_by_object"]["spaces"] == 2
    assert result["rows_by_object"]["eng_pages"] == 3


@pytest.mark.asyncio
async def test_raw_path_bypasses_dispatch():
    conn = ConfluenceConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None, auth=None):
        captured["url"] = url
        return _Resp(200, {"id": "p1", "title": "x"})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(_config(), "/wiki/api/v2/pages/p1")
    assert captured["url"].endswith("/wiki/api/v2/pages/p1")
    assert rows[0]["id"] == "p1"
