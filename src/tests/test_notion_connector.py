"""Tests for src/connectors/notion.py — Notion as a read-only tabular source."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.notion import NotionConnector


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
    base = {"auth": {"type": "bearer", "api_token": "secret_x"}}
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_test_connection_true_on_200():
    conn = NotionConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_Resp(200, {"object": "user", "id": "bot-1"})
        )
        ok = await conn.test_connection(_config())
    assert ok is True


@pytest.mark.asyncio
async def test_test_connection_false_on_401():
    conn = NotionConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=_Resp(401))
        ok = await conn.test_connection(_config())
    assert ok is False


@pytest.mark.asyncio
async def test_test_connection_uses_bearer_and_notion_version_header():
    conn = NotionConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["headers"] = headers or {}
        return _Resp(200, {})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.test_connection(_config(notion_version="2022-06-28"))
    assert captured["headers"]["Authorization"] == "Bearer secret_x"
    assert captured["headers"]["Notion-Version"] == "2022-06-28"


@pytest.mark.asyncio
async def test_get_metadata_describes_database_columns_when_database_id_provided():
    conn = NotionConnector()
    db_payload = {
        "object": "database",
        "id": "db-1",
        "properties": {
            "Name": {"id": "p1", "type": "title"},
            "Status": {"id": "p2", "type": "status"},
            "Owner": {"id": "p3", "type": "people"},
        },
    }

    async def fake_get(url, headers=None, params=None):
        if url.endswith("/databases/db-1"):
            return _Resp(200, db_payload)
        return _Resp(404, {})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        meta = await conn.get_metadata(
            _config(objects=[{"name": "tasks", "object_type": "database", "database_id": "db-1"}])
        )
    cols = [c["name"] for c in meta["tables"][0]["columns"]]
    assert "Name" in cols and "Status" in cols and "Owner" in cols
    assert meta["tables"][0]["metadata"]["database_id"] == "db-1"


@pytest.mark.asyncio
async def test_execute_query_users_lists_and_flattens():
    conn = NotionConnector()
    payload = {
        "results": [
            {"id": "u1", "name": "Ada", "type": "person", "person": {"email": "ada@example.com"}},
            {"id": "u2", "name": "Bot", "type": "bot", "bot": {"workspace_name": "Acme"}},
        ],
        "next_cursor": None,
    }
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp(200, payload)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(_config(), "users")
    assert captured["url"].endswith("/users")
    assert captured["params"]["page_size"] == 100
    assert rows[0]["email"] == "ada@example.com"
    assert rows[1]["email"] == "Acme"  # bot uses workspace_name


@pytest.mark.asyncio
async def test_execute_query_database_flattens_properties():
    """Database rows get their nested property objects reduced to scalars."""
    conn = NotionConnector()
    page = {
        "id": "p1",
        "created_time": "2026-01-01T00:00:00.000Z",
        "last_edited_time": "2026-04-01T00:00:00.000Z",
        "url": "https://www.notion.so/p1",
        "properties": {
            "Title":  {"type": "title",     "title": [{"plain_text": "Ship feature"}]},
            "Status": {"type": "status",    "status": {"name": "Done"}},
            "Score":  {"type": "number",    "number": 42},
            "Open":   {"type": "checkbox",  "checkbox": True},
            "Due":    {"type": "date",      "date": {"start": "2026-04-30"}},
            "Tags":   {"type": "multi_select", "multi_select": [{"name": "p0"}, {"name": "infra"}]},
        },
    }
    captured: dict = {}

    async def fake_post(url, headers=None, json=None):
        captured["url"] = url
        captured["body"] = json
        return _Resp(200, {"results": [page]})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(side_effect=fake_post)
        rows = await conn.execute_query(
            _config(),
            '{"object_type":"database","database_id":"db-1","limit":50}',
        )
    assert captured["url"].endswith("/databases/db-1/query")
    assert captured["body"]["page_size"] == 50
    assert rows[0]["Title"] == "Ship feature"
    assert rows[0]["Status"] == "Done"
    assert rows[0]["Score"] == 42
    assert rows[0]["Open"] is True
    assert rows[0]["Due"] == "2026-04-30"
    assert rows[0]["Tags"] == ["p0", "infra"]


@pytest.mark.asyncio
async def test_execute_query_database_requires_database_id():
    conn = NotionConnector()
    with pytest.raises(ValueError, match="database_id"):
        await conn.execute_query(_config(), '{"object_type":"database"}')


@pytest.mark.asyncio
async def test_execute_query_pages_uses_search_with_object_filter():
    conn = NotionConnector()
    captured: dict = {}

    async def fake_post(url, headers=None, json=None):
        captured["url"] = url
        captured["body"] = json
        return _Resp(200, {"results": [
            {"id": "p1", "object": "page", "url": "u",
             "properties": {"Name": {"type": "title", "title": [{"plain_text": "Doc"}]}},
             "parent": {"type": "workspace"}},
        ]})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(side_effect=fake_post)
        rows = await conn.execute_query(_config(), "pages")
    assert captured["url"].endswith("/search")
    assert captured["body"]["filter"] == {"value": "page", "property": "object"}
    assert rows[0]["title"] == "Doc"


@pytest.mark.asyncio
async def test_execute_query_databases_filters_to_database_object():
    conn = NotionConnector()
    captured: dict = {}

    async def fake_post(url, headers=None, json=None):
        captured["body"] = json
        return _Resp(200, {"results": [
            {"id": "db-1", "object": "database", "title": [{"plain_text": "Tasks"}],
             "properties": {"Name": {}, "Status": {}}, "url": "u"},
        ]})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(side_effect=fake_post)
        rows = await conn.execute_query(_config(), "databases")
    assert captured["body"]["filter"] == {"value": "database", "property": "object"}
    assert rows[0]["title"] == "Tasks"
    assert rows[0]["property_count"] == 2


@pytest.mark.asyncio
async def test_execute_query_raw_path_bypasses_dispatch():
    conn = NotionConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        return _Resp(200, {"object": "user", "id": "bot-1", "name": "MyBot"})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(_config(), "/users/me")
    assert captured["url"].endswith("/users/me")
    assert rows[0]["id"] == "bot-1"


@pytest.mark.asyncio
async def test_execute_query_unknown_object_type_raises():
    conn = NotionConnector()
    with pytest.raises(ValueError, match="Unknown Notion object_type"):
        await conn.execute_query(_config(), "blocks")


@pytest.mark.asyncio
async def test_execute_query_4xx_surfaces_notion_error_code():
    conn = NotionConnector()
    err = {"object": "error", "status": 401, "code": "unauthorized", "message": "API token is invalid."}
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=_Resp(401, err))
        with pytest.raises(Exception, match="unauthorized"):
            await conn.execute_query(_config(), "users")


@pytest.mark.asyncio
async def test_limit_clamped_to_notion_server_cap():
    conn = NotionConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["params"] = params
        return _Resp(200, {"results": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query(_config(), '{"object_type":"users","limit":9999}')
    assert captured["params"]["page_size"] == 100


@pytest.mark.asyncio
async def test_sync_data_returns_rows_by_object():
    conn = NotionConnector()
    config = _config(objects=[
        {"name": "users", "object_type": "users"},
        {"name": "tasks", "object_type": "database", "database_id": "db-1"},
    ])

    async def fake_get(url, headers=None, params=None):
        return _Resp(200, {"results": [{"id": "u1", "name": "A", "type": "person", "person": {}}]})

    async def fake_post(url, headers=None, json=None):
        return _Resp(200, {"results": [{"id": "p1", "properties": {}}, {"id": "p2", "properties": {}}]})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(side_effect=fake_post)
        result = await conn.sync_data(config)
    assert result["success"] is True
    assert result["rows_by_object"]["users"] == 1
    assert result["rows_by_object"]["tasks"] == 2
