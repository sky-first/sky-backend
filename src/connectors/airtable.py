"""Airtable connector — read-only.

Auth — Personal Access Token (``pat...``). Bases and tables are
declared in the config; the connector lists records inside each.

    {
        "auth": {"type": "bearer", "api_token": "pat..."},
        "base_id": "appXXXXXX",
        "objects": [
            {"name": "customers", "object_type": "table", "table": "Customers"}
        ]
    }
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://api.airtable.com"


def _headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    token = auth.get("api_token") or auth.get("token")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _base(config: Dict[str, Any]) -> str:
    return (config.get("base_url") or _DEFAULT_BASE).rstrip("/")


class AirtableConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_base(config)}/v0/meta/whoami",
                    headers=_headers(config),
                )
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("airtable.test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        base_id = config.get("base_id")
        if not base_id:
            return {"tables": []}
        url = f"{_base(config)}/v0/meta/bases/{base_id}/tables"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=_headers(config))
            if resp.status_code != 200:
                return {"tables": []}
            body = resp.json() or {}
        tables = [
            {
                "name": t.get("name"),
                "schema": "airtable",
                "row_count": 0,
                "columns": [
                    {"name": f.get("name"), "type": f.get("type", "text")}
                    for f in (t.get("fields") or [])
                ],
            }
            for t in (body.get("tables") or [])
        ]
        return {"tables": tables}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        spec = self._parse(query)
        base_id = config.get("base_id")
        table = spec.get("table") or "Table"
        url = f"{_base(config)}/v0/{base_id}/{quote(table)}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                url, headers=_headers(config), params={"pageSize": 100}
            )
            resp.raise_for_status()
            body = resp.json() or {}
        return [
            {"id": r.get("id"), **(r.get("fields") or {})}
            for r in (body.get("records") or [])
        ]

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
        if q.startswith("{"):
            try:
                return json.loads(q)
            except json.JSONDecodeError:
                pass
        return {"table": q or "Table"}
