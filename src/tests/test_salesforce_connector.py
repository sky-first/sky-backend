"""Tests for src/connectors/salesforce.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.salesforce import SalesforceConnector


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
async def test_test_connection_requires_token_and_instance():
    conn = SalesforceConnector()
    assert await conn.test_connection({}) is False
    assert await conn.test_connection({"instance_url": "https://x.my.salesforce.com"}) is False
    assert await conn.test_connection({"auth": {"access_token": "t"}}) is False


@pytest.mark.asyncio
async def test_test_connection_true_on_200():
    conn = SalesforceConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=_Resp(200))
        ok = await conn.test_connection({
            "instance_url": "https://x.my.salesforce.com",
            "auth": {"access_token": "tok"},
        })
    assert ok is True


@pytest.mark.asyncio
async def test_execute_query_object_name_generates_soql_and_flattens_attributes():
    conn = SalesforceConnector()
    payload = {
        "records": [
            {"attributes": {"type": "Account", "url": "/x"}, "Id": "001", "Name": "Acme"},
            {"attributes": {"type": "Account"}, "Id": "002", "Name": "Globex"},
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
            {"instance_url": "https://x.my.salesforce.com", "auth": {"access_token": "t"}},
            "Account",
        )
    assert captured["params"]["q"] == "SELECT Id, Name FROM Account LIMIT 100"
    assert rows[0] == {"Id": "001", "Name": "Acme"}
    assert rows[1] == {"Id": "002", "Name": "Globex"}


@pytest.mark.asyncio
async def test_execute_query_accepts_full_soql_string():
    conn = SalesforceConnector()
    captured = {}

    async def fake_get(url, headers=None, params=None):
        captured["params"] = params
        return _Resp(200, {"records": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query(
            {"instance_url": "https://x.my.salesforce.com", "auth": {"access_token": "t"}},
            "SELECT Id, Name, Industry FROM Account WHERE Industry = 'Tech'",
        )
    assert captured["params"]["q"] == "SELECT Id, Name, Industry FROM Account WHERE Industry = 'Tech'"


@pytest.mark.asyncio
async def test_execute_query_json_descriptor():
    conn = SalesforceConnector()
    captured = {}

    async def fake_get(url, headers=None, params=None):
        captured["params"] = params
        return _Resp(200, {"records": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query(
            {"instance_url": "https://x.my.salesforce.com", "auth": {"access_token": "t"}},
            '{"soql":"SELECT Id FROM Opportunity LIMIT 5"}',
        )
    assert captured["params"]["q"] == "SELECT Id FROM Opportunity LIMIT 5"


@pytest.mark.asyncio
async def test_execute_query_rejects_empty_and_missing_url():
    conn = SalesforceConnector()
    with pytest.raises(ValueError, match="instance_url"):
        await conn.execute_query({}, "Account")
    with pytest.raises(ValueError):
        await conn.execute_query({"instance_url": "https://x.my.salesforce.com"}, "")
    with pytest.raises(ValueError, match="soql"):
        await conn.execute_query({"instance_url": "https://x.my.salesforce.com"}, '{"other":"x"}')


@pytest.mark.asyncio
async def test_get_metadata_lists_declared_objects_as_tables():
    conn = SalesforceConnector()
    meta = await conn.get_metadata({
        "objects": [
            {"name": "Accounts", "object_type": "Account"},
            {"name": "Opportunities", "object_type": "Opportunity"},
        ]
    })
    assert [t["name"] for t in meta["tables"]] == ["Accounts", "Opportunities"]
    assert meta["tables"][0]["kind"] == "salesforce_sobject"


@pytest.mark.asyncio
async def test_bearer_token_sets_authorization_header():
    conn = SalesforceConnector()
    captured = {}

    async def fake_get(url, headers=None, params=None):
        captured["headers"] = headers or {}
        return _Resp(200, {"records": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query(
            {"instance_url": "https://x.my.salesforce.com", "auth": {"access_token": "SECRET"}},
            "Account",
        )
    assert captured["headers"]["Authorization"] == "Bearer SECRET"
