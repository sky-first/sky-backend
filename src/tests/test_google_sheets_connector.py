"""Tests for src/connectors/google_sheets.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.google_sheets import GoogleSheetsConnector


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
async def test_test_connection_requires_access_token():
    assert await GoogleSheetsConnector().test_connection({}) is False
    assert await GoogleSheetsConnector().test_connection({"auth": {}}) is False


@pytest.mark.asyncio
async def test_test_connection_probes_drive_when_no_spreadsheet_id():
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=_Resp(200))
        ok = await GoogleSheetsConnector().test_connection(
            {"auth": {"access_token": "ya29"}}
        )
    assert ok is True


@pytest.mark.asyncio
async def test_test_connection_uses_spreadsheet_endpoint_when_id_provided():
    captured = {}

    async def fake_get(url, headers=None):
        captured["url"] = url
        return _Resp(200)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        ok = await GoogleSheetsConnector().test_connection(
            {"auth": {"access_token": "ya29"}, "spreadsheet_id": "ABC"}
        )
    assert ok is True
    assert "spreadsheets/ABC" in captured["url"]


@pytest.mark.asyncio
async def test_execute_query_first_row_becomes_headers():
    values = [
        ["id", "name", "price"],
        ["1", "Widget", "10.00"],
        ["2", "Gadget", "25.50"],
    ]

    async def fake_get(url, headers=None):
        return _Resp(200, {"values": values})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await GoogleSheetsConnector().execute_query(
            {"auth": {"access_token": "t"}, "spreadsheet_id": "ABC"},
            "Sheet1!A1:C",
        )
    assert rows == [
        {"id": "1", "name": "Widget", "price": "10.00"},
        {"id": "2", "name": "Gadget", "price": "25.50"},
    ]


@pytest.mark.asyncio
async def test_execute_query_shorter_rows_pad_with_empty_string():
    values = [
        ["a", "b", "c"],
        ["1", "2"],  # c missing
    ]
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=_Resp(200, {"values": values}))
        rows = await GoogleSheetsConnector().execute_query(
            {"auth": {"access_token": "t"}, "spreadsheet_id": "X"},
            "Sheet1!A:C",
        )
    assert rows[0] == {"a": "1", "b": "2", "c": ""}


@pytest.mark.asyncio
async def test_execute_query_json_descriptor_overrides_spreadsheet_id():
    captured = {}

    async def fake_get(url, headers=None):
        captured["url"] = url
        return _Resp(200, {"values": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await GoogleSheetsConnector().execute_query(
            {"auth": {"access_token": "t"}, "spreadsheet_id": "DEFAULT"},
            '{"spreadsheet_id":"OVERRIDE","range":"Orders!A1:Z"}',
        )
    assert "spreadsheets/OVERRIDE/values/Orders!A1:Z" in captured["url"]


@pytest.mark.asyncio
async def test_execute_query_empty_values_returns_empty_list():
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=_Resp(200, {}))
        rows = await GoogleSheetsConnector().execute_query(
            {"auth": {"access_token": "t"}, "spreadsheet_id": "X"},
            "Sheet1!A:B",
        )
    assert rows == []


@pytest.mark.asyncio
async def test_execute_query_rejects_missing_spreadsheet_id():
    with pytest.raises(ValueError, match="spreadsheet_id"):
        await GoogleSheetsConnector().execute_query(
            {"auth": {"access_token": "t"}},
            "Sheet1!A:B",
        )


@pytest.mark.asyncio
async def test_execute_query_rejects_missing_range():
    with pytest.raises(ValueError, match="cell range"):
        await GoogleSheetsConnector().execute_query(
            {"auth": {"access_token": "t"}, "spreadsheet_id": "X"},
            "",
        )
