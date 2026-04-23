"""Tests for src/connectors/jira.py (Bug 5 — app-level monitoring)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.connectors.jira import JiraConnector


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
async def test_test_connection_returns_true_on_200():
    conn = JiraConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=_Resp(200))
        ok = await conn.test_connection({
            "base_url": "https://t.atlassian.net",
            "auth": {"type": "basic", "email": "e@x.com", "api_token": "t"},
        })
    assert ok is True


@pytest.mark.asyncio
async def test_test_connection_returns_false_on_401():
    conn = JiraConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=_Resp(401))
        ok = await conn.test_connection({
            "base_url": "https://t.atlassian.net",
            "auth": {"type": "basic", "email": "e@x.com", "api_token": "bad"},
        })
    assert ok is False


@pytest.mark.asyncio
async def test_test_connection_returns_false_when_base_url_missing():
    conn = JiraConnector()
    assert await conn.test_connection({}) is False


@pytest.mark.asyncio
async def test_get_metadata_lists_projects_plus_presets():
    conn = JiraConnector()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_Resp(200, {
                "values": [
                    {"id": "1", "key": "ENG", "name": "Engineering"},
                    {"id": "2", "key": "MKT", "name": "Marketing"},
                ]
            })
        )
        meta = await conn.get_metadata({
            "base_url": "https://t.atlassian.net",
            "auth": {"type": "basic", "email": "e@x.com", "api_token": "t"},
            "jql_presets": [{"name": "p0_bugs", "jql": "priority=Highest"}],
        })
    names = [t["name"] for t in meta["tables"]]
    assert "ENG" in names and "MKT" in names and "p0_bugs" in names
    preset = next(t for t in meta["tables"] if t["name"] == "p0_bugs")
    assert preset["kind"] == "jira_saved_jql"
    assert preset["metadata"]["jql"] == "priority=Highest"


@pytest.mark.asyncio
async def test_execute_query_with_plain_jql_flattens_issues():
    conn = JiraConnector()
    issues = {
        "issues": [
            {
                "key": "ENG-1",
                "fields": {
                    "summary": "Crash on login",
                    "status": {"name": "To Do"},
                    "priority": {"name": "High"},
                    "assignee": {"displayName": "Ada"},
                    "reporter": {"displayName": "Bob"},
                    "issuetype": {"name": "Bug"},
                    "project": {"key": "ENG", "name": "Engineering"},
                    "labels": ["backend", "urgent"],
                    "created": "2026-04-01T00:00:00Z",
                    "updated": "2026-04-22T00:00:00Z",
                },
            }
        ]
    }
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=_Resp(200, issues)
        )
        rows = await conn.execute_query(
            {"base_url": "https://t.atlassian.net", "auth": {"type": "basic", "email": "e@x.com", "api_token": "t"}},
            "project = ENG AND status != Done",
        )
    assert len(rows) == 1
    assert rows[0]["key"] == "ENG-1"
    assert rows[0]["summary"] == "Crash on login"
    assert rows[0]["status"] == "To Do"
    assert rows[0]["priority"] == "High"
    assert rows[0]["assignee"] == "Ada"
    assert rows[0]["project"] == "ENG"
    assert rows[0]["labels"] == "backend,urgent"


@pytest.mark.asyncio
async def test_execute_query_accepts_json_descriptor_with_custom_fields():
    conn = JiraConnector()
    captured = {}

    async def fake_post(url, headers=None, auth=None, json=None):
        captured["url"] = url
        captured["json"] = json
        return _Resp(200, {"issues": []})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(side_effect=fake_post)
        await conn.execute_query(
            {"base_url": "https://t.atlassian.net", "auth": {"type": "basic", "email": "e@x.com", "api_token": "t"}},
            '{"jql":"priority=Highest","fields":["summary","priority"],"max_results":10}',
        )
    assert captured["url"].endswith("/rest/api/3/search")
    assert captured["json"]["jql"] == "priority=Highest"
    assert captured["json"]["fields"] == ["summary", "priority"]
    assert captured["json"]["maxResults"] == 10


@pytest.mark.asyncio
async def test_execute_query_rejects_empty_jql():
    conn = JiraConnector()
    with pytest.raises(ValueError, match="JQL"):
        await conn.execute_query({"base_url": "https://t.atlassian.net"}, "")


@pytest.mark.asyncio
async def test_execute_query_rejects_invalid_json():
    conn = JiraConnector()
    with pytest.raises(ValueError, match="Invalid Jira query JSON"):
        await conn.execute_query({"base_url": "https://t.atlassian.net"}, "{not-json")


@pytest.mark.asyncio
async def test_execute_query_rejects_missing_base_url():
    conn = JiraConnector()
    with pytest.raises(ValueError, match="base_url"):
        await conn.execute_query({}, "project=ENG")


@pytest.mark.asyncio
async def test_bearer_auth_flavour_sets_header_instead_of_basic_tuple():
    conn = JiraConnector()
    captured = {}

    async def fake_get(url, headers=None, auth=None):
        captured["headers"] = headers or {}
        captured["auth"] = auth
        return _Resp(200)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=fake_get)
        await conn.test_connection({
            "base_url": "https://t.atlassian.net",
            "auth": {"type": "bearer", "api_token": "srv-token"},
        })
    assert captured["headers"].get("Authorization") == "Bearer srv-token"
    assert captured["auth"] is None  # no basic tuple
