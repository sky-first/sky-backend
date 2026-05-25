"""GitLab connector — read-only over the v4 REST API.

Auth — Personal Access Token with ``read_api`` scope. Surfaces
``projects``, ``issues``, ``merge_requests``, ``commits``, ``users``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://gitlab.com/api/v4"


def _base(config: Dict[str, Any]) -> str:
    return (config.get("base_url") or _DEFAULT_BASE).rstrip("/")


def _headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    token = auth.get("api_token") or auth.get("token")
    return {"Accept": "application/json", "PRIVATE-TOKEN": token or ""}


class GitLabConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{_base(config)}/user", headers=_headers(config))
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("gitlab.test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{_base(config)}/projects?membership=true&per_page=100",
                headers=_headers(config),
            )
            if resp.status_code != 200:
                return {"tables": []}
            projects = resp.json() or []
        return {
            "tables": [
                {"name": p.get("path_with_namespace", "project"), "schema": "gitlab"}
                for p in projects
            ]
        }

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        spec = self._parse(query)
        kind = spec.get("object_type") or "projects"
        pid = spec.get("project_id")
        if kind == "projects":
            url = f"{_base(config)}/projects?membership=true&per_page=100"
        elif kind == "issues":
            url = (
                f"{_base(config)}/projects/{pid}/issues?per_page=100"
                if pid
                else f"{_base(config)}/issues?scope=all&per_page=100"
            )
        elif kind == "merge_requests":
            url = (
                f"{_base(config)}/projects/{pid}/merge_requests?per_page=100"
                if pid
                else f"{_base(config)}/merge_requests?scope=all&per_page=100"
            )
        elif kind == "commits":
            url = f"{_base(config)}/projects/{pid}/repository/commits?per_page=100"
        elif kind == "users":
            url = f"{_base(config)}/users?per_page=100"
        else:
            raise ValueError(f"unsupported GitLab object '{kind}'")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=_headers(config))
            resp.raise_for_status()
            return resp.json() or []

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows = 0
        for obj in config.get("objects") or []:
            r = await self.execute_query(config, json.dumps(obj))
            rows += len(r)
        return {"rows_synced": rows}

    def _parse(self, query: str) -> Dict[str, Any]:
        q = (query or "").strip()
        if not q:
            return {"object_type": "projects"}
        if q.startswith("{"):
            try:
                return json.loads(q)
            except json.JSONDecodeError:
                pass
        return {"object_type": q}
