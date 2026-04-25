"""Tests for src/connectors/box.py — Box as read-only tabular source."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.box import BoxConnector


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
    base = {"auth": {"type": "bearer", "access_token": "tok-1"}}
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_test_connection_true_on_200():
    conn = BoxConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_Resp(200, {"id": "1", "name": "me"})
        )
        ok = await conn.test_connection(_config())
    assert ok is True


@pytest.mark.asyncio
async def test_test_connection_false_on_401():
    conn = BoxConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_Resp(401, {"code": "unauthorized"})
        )
        ok = await conn.test_connection(_config())
    assert ok is False


@pytest.mark.asyncio
async def test_test_connection_uses_bearer_authorization_header():
    conn = BoxConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["headers"] = headers or {}
        return _Resp(200, {})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.test_connection(_config())
    assert captured["headers"].get("Authorization") == "Bearer tok-1"


@pytest.mark.asyncio
async def test_get_metadata_exposes_declared_objects_as_tables():
    conn = BoxConnector()
    config = _config(objects=[
        {"name": "shared", "object_type": "items", "folder_id": "0"},
        {"name": "engineering", "object_type": "items", "folder_id": "12345"},
        {"name": "users", "object_type": "users"},
    ])
    meta = await conn.get_metadata(config)
    names = [t["name"] for t in meta["tables"]]
    assert names == ["shared", "engineering", "users"]
    assert meta["tables"][0]["metadata"]["folder_id"] == "0"
    assert meta["tables"][1]["metadata"]["folder_id"] == "12345"


@pytest.mark.asyncio
async def test_execute_query_items_lists_root_when_no_folder_given():
    conn = BoxConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp(200, {"entries": [
            {"id": "11", "type": "folder", "name": "Engineering",
             "parent": {"id": "0", "name": "All Files"},
             "modified_at": "2026-04-01T00:00:00Z"},
            {"id": "22", "type": "file", "name": "roadmap.pdf",
             "size": 4096, "sha1": "abc",
             "owned_by": {"login": "ada@acme.com"},
             "modified_at": "2026-04-02T00:00:00Z"},
        ]})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(_config(), "items")
    # Root folder is "0".
    assert captured["url"].endswith("/folders/0/items")
    # We always request the read-only metadata fields.
    assert "size" in captured["params"]["fields"]
    assert rows[0]["id"] == "11"
    assert rows[0]["type"] == "folder"
    assert rows[1]["owner"] == "ada@acme.com"
    assert rows[1]["sha1"] == "abc"


@pytest.mark.asyncio
async def test_execute_query_items_with_folder_id_uses_correct_endpoint():
    conn = BoxConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        return _Resp(200, {"entries": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query(
            _config(),
            '{"object_type":"items","folder_id":"12345","limit":50}',
        )
    assert captured["url"].endswith("/folders/12345/items")


@pytest.mark.asyncio
async def test_execute_query_file_requires_file_id():
    conn = BoxConnector()
    with pytest.raises(ValueError, match="file_id"):
        await conn.execute_query(_config(), '{"object_type":"file"}')


@pytest.mark.asyncio
async def test_execute_query_file_returns_single_item_row():
    conn = BoxConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        return _Resp(200, {
            "id": "22", "type": "file", "name": "roadmap.pdf", "size": 4096,
            "owned_by": {"login": "ada@acme.com"},
            "modified_at": "2026-04-02T00:00:00Z",
        })

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(
            _config(),
            '{"object_type":"file","file_id":"22"}',
        )
    assert captured["url"].endswith("/files/22")
    assert len(rows) == 1
    assert rows[0]["id"] == "22"


@pytest.mark.asyncio
async def test_execute_query_users_returns_flattened_user_rows():
    conn = BoxConnector()
    payload = {"entries": [
        {"id": "U1", "name": "Ada Lovelace", "login": "ada@acme.com",
         "status": "active", "role": "admin", "created_at": "2024-01-01T00:00:00Z"},
    ]}
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        return _Resp(200, payload)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(_config(), "users")
    assert captured["url"].endswith("/users")
    assert rows[0]["login"] == "ada@acme.com"
    assert rows[0]["role"] == "admin"


@pytest.mark.asyncio
async def test_execute_query_raw_path_bypasses_dispatch():
    conn = BoxConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        return _Resp(200, {"id": "1", "name": "me"})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(_config(), "/users/me")
    assert captured["url"].endswith("/users/me")
    assert rows[0]["id"] == "1"


@pytest.mark.asyncio
async def test_execute_query_unknown_object_type_raises():
    conn = BoxConnector()
    with pytest.raises(ValueError, match="Unknown Box object_type"):
        await conn.execute_query(_config(), "shares")


@pytest.mark.asyncio
async def test_execute_query_4xx_surfaces_box_error_code():
    conn = BoxConnector()
    err = {"type": "error", "status": 401, "code": "unauthorized",
           "message": "Auth token expired"}
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_Resp(401, err)
        )
        with pytest.raises(Exception, match="unauthorized"):
            await conn.execute_query(_config(), "items")


@pytest.mark.asyncio
async def test_limit_clamped_to_1000():
    conn = BoxConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["params"] = params
        return _Resp(200, {"entries": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query(_config(), '{"object_type":"items","limit":99999}')
    assert captured["params"]["limit"] == 1000


@pytest.mark.asyncio
async def test_offset_passes_through_to_pagination():
    conn = BoxConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["params"] = params
        return _Resp(200, {"entries": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query(_config(), '{"object_type":"items","offset":250}')
    assert captured["params"]["offset"] == 250


@pytest.mark.asyncio
async def test_sync_data_returns_rows_by_object():
    conn = BoxConnector()
    config = _config(objects=[
        {"name": "shared", "object_type": "items", "folder_id": "0"},
        {"name": "users", "object_type": "users"},
    ])

    async def fake_get(url, headers=None, params=None):
        if "/folders/0/items" in url:
            return _Resp(200, {"entries": [{"id": "1"}, {"id": "2"}, {"id": "3"}]})
        if url.endswith("/users"):
            return _Resp(200, {"entries": [{"id": "U1"}]})
        return _Resp(200, {"entries": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        result = await conn.sync_data(config)
    assert result["success"] is True
    assert result["rows_by_object"]["shared"] == 3
    assert result["rows_by_object"]["users"] == 1
