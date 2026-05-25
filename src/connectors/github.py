"""GitHub connector.

Treats a GitHub organization (or a single repo) as a tabular data
source. Surfaces ``repos``, ``issues``, ``pulls``, ``commits``,
``users`` so agents can monitor them like any other source.

Auth — Personal Access Token (PAT) or fine-grained token. Read-only;
no write API is exposed by the connector. Config:

    {
        "base_url": "https://api.github.com",   # default
        "owner":    "sky-first",                # required
        "repo":     "sky-poc-backend",          # optional — when absent,
                                                #   org-level surfaces only
        "auth": {
            "type": "bearer",
            "api_token": "ghp_..."
        },
        "objects": [
            { "name": "repos",   "object_type": "repos" },
            { "name": "issues",  "object_type": "issues",  "state": "open" },
            { "name": "pulls",   "object_type": "pulls",   "state": "all" },
            { "name": "commits", "object_type": "commits", "limit": 100 }
        ]
    }
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://api.github.com"
_DEFAULT_LIMIT = 100


def _headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    token = auth.get("api_token") or auth.get("token")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "sky-platform-connector",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _base(config: Dict[str, Any]) -> str:
    return (config.get("base_url") or _DEFAULT_BASE).rstrip("/")


class GitHubConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        url = f"{_base(config)}/user"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=_headers(config))
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("github.test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        owner = config.get("owner")
        if not owner:
            return {"tables": []}
        async with httpx.AsyncClient(timeout=20.0) as client:
            url = f"{_base(config)}/orgs/{owner}/repos?per_page=100"
            resp = await client.get(url, headers=_headers(config))
            if resp.status_code == 404:
                # Fall back to user-level repo listing.
                url = f"{_base(config)}/users/{owner}/repos?per_page=100"
                resp = await client.get(url, headers=_headers(config))
            resp.raise_for_status()
            repos = resp.json() or []
        tables = [
            {
                "name": f"{owner}/{r.get('name')}",
                "schema": "github",
                "row_count": r.get("size", 0),
                "columns": [],
            }
            for r in repos
        ]
        return {"tables": tables}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        owner = config.get("owner")
        repo = config.get("repo")
        spec = self._parse_query(query)
        kind = spec.get("object_type") or "repos"
        limit = int(spec.get("limit") or _DEFAULT_LIMIT)
        path: Optional[str] = spec.get("path")
        async with httpx.AsyncClient(timeout=30.0) as client:
            if path:
                url = f"{_base(config)}{path}"
            elif kind == "repos":
                url = f"{_base(config)}/orgs/{owner}/repos?per_page={limit}"
            elif kind == "issues":
                state = spec.get("state", "open")
                url = (
                    f"{_base(config)}/repos/{owner}/{repo}/issues"
                    f"?state={state}&per_page={limit}"
                )
            elif kind == "pulls":
                state = spec.get("state", "open")
                url = (
                    f"{_base(config)}/repos/{owner}/{repo}/pulls"
                    f"?state={state}&per_page={limit}"
                )
            elif kind == "commits":
                url = f"{_base(config)}/repos/{owner}/{repo}/commits?per_page={limit}"
            elif kind == "users":
                url = f"{_base(config)}/orgs/{owner}/members?per_page={limit}"
            else:
                raise ValueError(f"unsupported GitHub object_type '{kind}'")

            resp = await client.get(url, headers=_headers(config))
            if resp.status_code == 404 and kind == "users":
                return []
            resp.raise_for_status()
            return resp.json() or []

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        objects = config.get("objects") or []
        rows = 0
        for obj in objects:
            spec = json.dumps(obj)
            r = await self.execute_query(config, spec)
            rows += len(r)
        return {"rows_synced": rows, "objects": len(objects)}

    def _parse_query(self, query: str) -> Dict[str, Any]:
        q = (query or "").strip()
        if not q:
            return {"object_type": "repos"}
        if q.startswith("/"):
            return {"path": q}
        if q.startswith("{"):
            try:
                return json.loads(q)
            except json.JSONDecodeError:
                pass
        return {"object_type": q}
