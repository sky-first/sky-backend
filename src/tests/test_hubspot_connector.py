"""Tests for src/connectors/hubspot.py (Bug 5 — app-level monitoring)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.hubspot import HubSpotConnector


class _Resp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


@pytest.mark.asyncio
async def test_test_connection_true_on_200():
    conn = HubSpotConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=_Resp(200))
        ok = await conn.test_connection({"auth": {"type": "bearer", "api_token": "pat-na1-x"}})
    assert ok is True


@pytest.mark.asyncio
async def test_test_connection_false_on_401():
    conn = HubSpotConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=_Resp(401))
        ok = await conn.test_connection({"auth": {"type": "bearer", "api_token": "bad"}})
    assert ok is False


@pytest.mark.asyncio
async def test_get_metadata_exposes_declared_objects_as_tables():
    conn = HubSpotConnector()
    config = {
        "auth": {"type": "bearer", "api_token": "x"},
        "objects": [
            {"name": "contacts", "object_type": "contacts", "properties": ["email"]},
            {"name": "open_deals", "object_type": "deals", "filter": "stage=open"},
        ],
    }
    meta = await conn.get_metadata(config)
    names = [t["name"] for t in meta["tables"]]
    assert names == ["contacts", "open_deals"]
    assert meta["tables"][0]["kind"] == "hubspot_object"
    assert [c["name"] for c in meta["tables"][0]["columns"]] == ["email"]
    assert meta["tables"][1]["metadata"]["filter"] == "stage=open"


@pytest.mark.asyncio
async def test_execute_query_object_type_returns_flattened_rows():
    conn = HubSpotConnector()
    payload = {
        "results": [
            {
                "id": "1",
                "properties": {"firstname": "Ada", "lastname": "Lovelace", "email": "ada@example.com"},
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-04-01T00:00:00Z",
            },
            {"id": "2", "properties": {"firstname": "Bob"}},
        ]
    }
    captured = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp(200, payload)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(
            {"auth": {"type": "bearer", "api_token": "x"}},
            '{"object_type":"contacts","properties":["firstname","lastname","email"],"limit":50}',
        )
    assert captured["url"].endswith("/crm/v3/objects/contacts")
    assert captured["params"]["properties"] == "firstname,lastname,email"
    assert captured["params"]["limit"] == 50
    assert rows[0]["id"] == "1"
    assert rows[0]["firstname"] == "Ada"
    assert rows[0]["email"] == "ada@example.com"
    assert rows[0]["createdAt"] == "2026-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_execute_query_plain_string_uses_it_as_object_type():
    conn = HubSpotConnector()
    captured = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        return _Resp(200, {"results": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query({"auth": {"type": "bearer", "api_token": "x"}}, "deals")
    assert captured["url"].endswith("/crm/v3/objects/deals")


@pytest.mark.asyncio
async def test_execute_query_raw_path_bypasses_crm_route():
    conn = HubSpotConnector()
    captured = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        return _Resp(200, {"results": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query(
            {"auth": {"type": "bearer", "api_token": "x"}},
            "/account-info/v3/details",
        )
    assert captured["url"].endswith("/account-info/v3/details")


@pytest.mark.asyncio
async def test_execute_query_dict_response_still_wraps_to_list():
    conn = HubSpotConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_Resp(200, {"id": "7", "properties": {"name": "Acme"}}),
        )
        rows = await conn.execute_query(
            {"auth": {"type": "bearer", "api_token": "x"}},
            "/crm/v3/objects/companies/7",
        )
    assert len(rows) == 1
    assert rows[0]["id"] == "7"
    assert rows[0]["name"] == "Acme"


@pytest.mark.asyncio
async def test_bearer_header_attached():
    conn = HubSpotConnector()
    captured = {}

    async def fake_get(url, headers=None, params=None):
        captured["headers"] = headers or {}
        return _Resp(200, {})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.test_connection({"auth": {"type": "bearer", "api_token": "pat-na1-TOKEN"}})
    assert captured["headers"].get("Authorization") == "Bearer pat-na1-TOKEN"
