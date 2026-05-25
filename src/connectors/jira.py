"""Jira Cloud connector.

Addresses the user ask: "agentes nao devem apenas ser raso, mas deve
pensar que pessoa irao querer monitorar por exemplo automacoes dentro
de apps como JIRA…"

This is an app-level connector — the entity isn't a SQL table, it's a
JQL-filtered issue list, a project, a board, etc. The base connector
contract still applies: `test_connection`, `get_metadata`
(projects + saved filters), `execute_query` (run JQL, return issues as
rows so agents + chat can reason about them).

Auth: Atlassian Cloud requires Basic auth with `email : api_token`.
Optionally `bearer` for server/data-center instances. Config shape:

    {
        "base_url": "https://your-tenant.atlassian.net",
        "auth": {
            "type": "basic" | "bearer",
            "email": "user@example.com",     # basic
            "api_token": "ATATT...",         # basic or bearer
        },
        "jql_presets": [                     # optional — acts as "tables"
            { "name": "p0_bugs", "jql": "project=X AND priority=Highest" }
        ]
    }

execute_query(config, query):
  - plain string: treated as JQL
  - JSON {"jql": "...", "fields": ["..."], "max_results": 50}
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_FIELDS = [
    "summary", "status", "priority", "assignee", "reporter",
    "created", "updated", "issuetype", "project", "labels",
]


def _auth_tuple(config: Dict[str, Any]) -> Optional[tuple[str, str]]:
    auth = config.get("auth") or {}
    atype = (auth.get("type") or "basic").lower()
    if atype == "basic":
        email = auth.get("email") or auth.get("username")
        token = auth.get("api_token") or auth.get("token") or auth.get("password")
        if email and token:
            return (email, token)
    return None


def _auth_headers(config: Dict[str, Any]) -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    auth = config.get("auth") or {}
    if (auth.get("type") or "").lower() == "bearer" and auth.get("api_token"):
        headers["Authorization"] = f"Bearer {auth['api_token']}"
    return headers


def _issue_to_row(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a Jira issue into a tabular row so downstream SQL-ish
    rendering in the chat/widgets continues to work unchanged."""
    fields = issue.get("fields") or {}
    status = (fields.get("status") or {}).get("name")
    priority = (fields.get("priority") or {}).get("name")
    issuetype = (fields.get("issuetype") or {}).get("name")
    project = (fields.get("project") or {}).get("key") or (fields.get("project") or {}).get("name")
    assignee = (fields.get("assignee") or {}).get("displayName")
    reporter = (fields.get("reporter") or {}).get("displayName")
    labels = fields.get("labels") or []
    return {
        "key": issue.get("key"),
        "summary": fields.get("summary"),
        "status": status,
        "priority": priority,
        "assignee": assignee,
        "reporter": reporter,
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "issuetype": issuetype,
        "project": project,
        "labels": ",".join(labels) if isinstance(labels, list) else labels,
    }


class JiraConnector(BaseConnector):
    """Agent-ready Jira Cloud connector — returns issues as rows."""

    TIMEOUT = 15.0

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        base = (config.get("base_url") or "").rstrip("/")
        if not base:
            return False
        # GET /rest/api/3/myself returns the authenticated user; 401/403
        # tell us auth is broken; 200 confirms credentials + instance.
        url = f"{base}/rest/api/3/myself"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config), auth=_auth_tuple(config))
                return resp.status_code == 200
        except Exception as exc:
            logger.info("Jira test_connection failed for %s: %s", base, exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Treat Jira projects + saved JQL presets as "tables" so the
        DataSourcePicker / agent scan UI can pin specific subsets.
        Projects come from the live API; presets come from config.
        """
        base = (config.get("base_url") or "").rstrip("/")
        tables: List[Dict[str, Any]] = []
        if base:
            try:
                async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                    resp = await client.get(
                        f"{base}/rest/api/3/project/search?maxResults=50",
                        headers=_auth_headers(config),
                        auth=_auth_tuple(config),
                    )
                    resp.raise_for_status()
                    body = resp.json()
                    for p in (body.get("values") or []):
                        tables.append({
                            "name": p.get("key") or p.get("name"),
                            "kind": "jira_project",
                            "columns": [],
                            "metadata": {
                                "id": str(p.get("id") or ""),
                                "name": p.get("name"),
                                "type": "project",
                            },
                        })
            except Exception as exc:
                logger.warning("Jira get_metadata project fetch failed: %s", exc)
        for preset in config.get("jql_presets") or []:
            tables.append({
                "name": preset.get("name") or "preset",
                "kind": "jira_saved_jql",
                "columns": [],
                "metadata": {
                    "jql": preset.get("jql") or "",
                    "type": "saved_jql",
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        base = (config.get("base_url") or "").rstrip("/")
        if not base:
            raise ValueError("Jira connector requires base_url")

        jql = ""
        fields = _DEFAULT_FIELDS
        max_results = 50
        q = (query or "").strip()
        if q.startswith("{"):
            try:
                parsed = json.loads(q)
                jql = parsed.get("jql") or ""
                fields = parsed.get("fields") or _DEFAULT_FIELDS
                max_results = int(parsed.get("max_results") or 50)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid Jira query JSON: {exc}") from exc
        else:
            jql = q

        if not jql:
            raise ValueError("Jira execute_query requires JQL text or {'jql': '...'}")

        url = f"{base}/rest/api/3/search"
        body = {"jql": jql, "fields": fields, "maxResults": max(1, min(100, max_results))}
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(
                url,
                headers={**_auth_headers(config), "Content-Type": "application/json"},
                auth=_auth_tuple(config),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        issues = data.get("issues") or []
        return [_issue_to_row(issue) for issue in issues]

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Run every saved JQL preset and report row counts — same
        contract as the REST connector so the scheduler treats Jira
        like any other data source."""
        rows_by_preset: Dict[str, int] = {}
        for preset in config.get("jql_presets") or []:
            try:
                rows = await self.execute_query(
                    config,
                    json.dumps({"jql": preset.get("jql") or "", "max_results": 50}),
                )
                rows_by_preset[preset.get("name") or "preset"] = len(rows)
            except Exception as exc:
                logger.warning("Jira sync preset %s failed: %s", preset, exc)
                rows_by_preset[preset.get("name") or "preset"] = 0
        return {"success": True, "rows_by_preset": rows_by_preset}
