"""Tests for src/connectors/slack.py — Slack as read-only tabular source."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.slack import SlackConnector


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


@pytest.mark.asyncio
async def test_test_connection_true_when_ok_true():
    """Slack always returns 200; the real status is ``data.ok``."""
    conn = SlackConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=_Resp(200, {"ok": True, "user": "U1", "team": "T1"})
        )
        ok = await conn.test_connection({"auth": {"api_token": "xoxb-good"}})
    assert ok is True


@pytest.mark.asyncio
async def test_test_connection_false_when_ok_false():
    """``ok=false`` (e.g. invalid_auth) is the failure case Slack uses."""
    conn = SlackConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=_Resp(200, {"ok": False, "error": "invalid_auth"})
        )
        ok = await conn.test_connection({"auth": {"api_token": "xoxb-bad"}})
    assert ok is False


@pytest.mark.asyncio
async def test_test_connection_false_on_non_200():
    conn = SlackConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=_Resp(500, {})
        )
        ok = await conn.test_connection({"auth": {"api_token": "x"}})
    assert ok is False


@pytest.mark.asyncio
async def test_get_metadata_exposes_declared_objects_as_tables():
    conn = SlackConnector()
    config = {
        "auth": {"api_token": "x"},
        "objects": [
            {"name": "public_channels", "object_type": "channels", "filter": "types=public_channel"},
            {"name": "general_messages", "object_type": "messages", "channel_id": "C01"},
            {"name": "users", "object_type": "users"},
        ],
    }
    meta = await conn.get_metadata(config)
    names = [t["name"] for t in meta["tables"]]
    assert names == ["public_channels", "general_messages", "users"]
    assert meta["tables"][0]["kind"] == "slack_object"
    assert meta["tables"][1]["metadata"]["channel_id"] == "C01"
    user_cols = [c["name"] for c in meta["tables"][2]["columns"]]
    assert "email" in user_cols and "real_name" in user_cols


@pytest.mark.asyncio
async def test_execute_query_users_returns_flattened_rows():
    conn = SlackConnector()
    payload = {
        "ok": True,
        "members": [
            {
                "id": "U1",
                "name": "ada",
                "real_name": "Ada Lovelace",
                "team_id": "T1",
                "is_bot": False,
                "profile": {"display_name": "ada", "email": "ada@example.com", "title": "Eng"},
            },
            {"id": "USLACKBOT", "name": "slackbot", "is_bot": True, "profile": {}},
        ],
    }
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers or {}
        return _Resp(200, payload)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(
            {"auth": {"api_token": "xoxb-tok"}},
            "users",
        )
    assert captured["url"].endswith("/users.list")
    assert captured["headers"].get("Authorization") == "Bearer xoxb-tok"
    assert len(rows) == 2
    assert rows[0]["id"] == "U1"
    assert rows[0]["email"] == "ada@example.com"
    assert rows[0]["display_name"] == "ada"


@pytest.mark.asyncio
async def test_execute_query_channels_dispatches_to_conversations_list():
    conn = SlackConnector()
    payload = {
        "ok": True,
        "channels": [
            {
                "id": "C01",
                "name": "general",
                "is_channel": True,
                "is_private": False,
                "is_archived": False,
                "num_members": 42,
                "topic": {"value": "watercooler"},
                "purpose": {"value": "company-wide"},
                "created": 1700000000,
                "creator": "U1",
            }
        ],
    }
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp(200, payload)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(
            {"auth": {"api_token": "x"}},
            '{"object_type":"channels","limit":50,"cursor":"abc"}',
        )
    assert captured["url"].endswith("/conversations.list")
    assert captured["params"]["limit"] == 50
    assert captured["params"]["cursor"] == "abc"
    assert captured["params"]["exclude_archived"] is True
    assert rows[0]["id"] == "C01"
    assert rows[0]["topic"] == "watercooler"
    assert rows[0]["num_members"] == 42


@pytest.mark.asyncio
async def test_execute_query_messages_requires_channel_id():
    conn = SlackConnector()
    with pytest.raises(ValueError, match="channel_id"):
        await conn.execute_query(
            {"auth": {"api_token": "x"}},
            '{"object_type":"messages","limit":10}',
        )


@pytest.mark.asyncio
async def test_execute_query_messages_dispatches_to_conversations_history():
    conn = SlackConnector()
    payload = {
        "ok": True,
        "messages": [
            {"ts": "1700000000.000100", "user": "U1", "type": "message", "text": "hello"},
        ],
    }
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp(200, payload)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(
            {"auth": {"api_token": "x"}},
            '{"object_type":"messages","channel_id":"C01","limit":25}',
        )
    assert captured["url"].endswith("/conversations.history")
    assert captured["params"]["channel"] == "C01"
    assert captured["params"]["limit"] == 25
    assert rows[0]["channel_id"] == "C01"
    assert rows[0]["text"] == "hello"


@pytest.mark.asyncio
async def test_execute_query_raw_path_bypasses_dispatch():
    conn = SlackConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        return _Resp(200, {"ok": True, "team": {"id": "T1", "name": "Acme"}})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        rows = await conn.execute_query(
            {"auth": {"api_token": "x"}},
            "/team.info",
        )
    assert captured["url"].endswith("/team.info")
    # Raw path response with no list field is wrapped to a single row.
    assert isinstance(rows, list)


@pytest.mark.asyncio
async def test_execute_query_empty_string_defaults_to_users():
    conn = SlackConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["url"] = url
        return _Resp(200, {"ok": True, "members": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query({"auth": {"api_token": "x"}}, "")
    assert captured["url"].endswith("/users.list")


@pytest.mark.asyncio
async def test_execute_query_raises_on_slack_error_body():
    """``ok=false`` from Slack must raise so the error mapper can translate it."""
    conn = SlackConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_Resp(200, {"ok": False, "error": "invalid_auth"})
        )
        with pytest.raises(Exception, match="invalid_auth"):
            await conn.execute_query({"auth": {"api_token": "x"}}, "users")


@pytest.mark.asyncio
async def test_execute_query_unknown_object_type_raises():
    conn = SlackConnector()
    with pytest.raises(ValueError, match="Unknown Slack object_type"):
        await conn.execute_query({"auth": {"api_token": "x"}}, "files")


@pytest.mark.asyncio
async def test_sync_data_returns_rows_by_object():
    conn = SlackConnector()
    config = {
        "auth": {"api_token": "x"},
        "objects": [
            {"name": "users", "object_type": "users"},
            {"name": "channels", "object_type": "channels"},
        ],
    }

    async def fake_get(url, headers=None, params=None):
        if url.endswith("/users.list"):
            return _Resp(200, {"ok": True, "members": [{"id": "U1", "profile": {}}]})
        if url.endswith("/conversations.list"):
            return _Resp(200, {"ok": True, "channels": [{"id": "C1"}, {"id": "C2"}]})
        return _Resp(200, {"ok": True})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        result = await conn.sync_data(config)
    assert result["success"] is True
    assert result["rows_by_object"]["users"] == 1
    assert result["rows_by_object"]["channels"] == 2


@pytest.mark.asyncio
async def test_limit_clamped_to_slack_server_cap():
    """Slack caps ``limit`` at 200 server-side; we clamp client-side too."""
    conn = SlackConnector()
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["params"] = params
        return _Resp(200, {"ok": True, "members": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.execute_query(
            {"auth": {"api_token": "x"}},
            '{"object_type":"users","limit":9999}',
        )
    assert captured["params"]["limit"] == 200
