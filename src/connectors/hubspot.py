"""HubSpot connector.

App-level connector exposing CRM objects (contacts / companies / deals /
tickets / custom objects) as rows so agents can monitor them like any
other data source.

Auth: HubSpot uses private-app access tokens with `Bearer` auth. Config:

    {
        "base_url": "https://api.hubapi.com",   # defaults to this
        "auth": {
            "type": "bearer",
            "api_token": "pat-na1-..."
        },
        "objects": [                             # optional list surface
            { "name": "contacts", "object_type": "contacts", "properties": ["email", "lifecyclestage"] },
            { "name": "open_deals", "object_type": "deals", "filter": "dealstage=presentationscheduled" }
        ]
    }

execute_query:
  - string starting with "/" → raw path against HubSpot API
  - JSON { "object_type": "deals", "properties": [...], "after": "...", "limit": 50 }
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://api.hubapi.com"
_DEFAULT_LIMIT = 50


def _auth_headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    headers = {"Accept": "application/json"}
    token = auth.get("api_token") or auth.get("token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _object_to_row(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten HubSpot's `{id, properties: {...}, createdAt, updatedAt}`
    into a flat row. Keep `id` top-level so downstream joins work."""
    props = obj.get("properties") or {}
    row = {"id": obj.get("id")}
    for k, v in props.items():
        row[k] = v
    if obj.get("createdAt"):
        row["createdAt"] = obj["createdAt"]
    if obj.get("updatedAt"):
        row["updatedAt"] = obj["updatedAt"]
    return row


class HubSpotConnector(BaseConnector):
    """Treats HubSpot CRM objects as tabular rows."""

    TIMEOUT = 15.0

    def _base(self, config: Dict[str, Any]) -> str:
        return (config.get("base_url") or _DEFAULT_BASE).rstrip("/")

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """Ping the account info endpoint. 200 confirms the token is
        valid and has account-level access."""
        url = f"{self._base(config)}/account-info/v3/details"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config))
                return resp.status_code == 200
        except Exception as exc:
            logger.info("HubSpot test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Surface each declared object as a "table" the DataSourcePicker
        can pin. We don't auto-discover custom objects (requires a
        separate /crm/v3/schemas call per install); users list what
        they care about at config time."""
        tables: List[Dict[str, Any]] = []
        for obj in config.get("objects") or []:
            tables.append({
                "name": obj.get("name") or obj.get("object_type") or "object",
                "kind": "hubspot_object",
                "columns": [{"name": p} for p in (obj.get("properties") or [])],
                "metadata": {
                    "object_type": obj.get("object_type") or "contacts",
                    "filter": obj.get("filter") or "",
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        base = self._base(config)
        q = (query or "").strip()

        object_type: str = "contacts"
        properties: Optional[List[str]] = None
        after: Optional[str] = None
        limit = _DEFAULT_LIMIT
        raw_path: Optional[str] = None

        if q.startswith("/"):
            raw_path = q
        elif q.startswith("{"):
            try:
                parsed = json.loads(q)
                object_type = parsed.get("object_type") or parsed.get("type") or "contacts"
                properties = parsed.get("properties")
                after = parsed.get("after")
                limit = int(parsed.get("limit") or _DEFAULT_LIMIT)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid HubSpot query JSON: {exc}") from exc
        elif q:
            object_type = q

        if raw_path:
            url = f"{base}{raw_path if raw_path.startswith('/') else '/' + raw_path}"
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config))
                resp.raise_for_status()
                data = resp.json()
        else:
            url = f"{base}/crm/v3/objects/{object_type}"
            params: Dict[str, Any] = {"limit": max(1, min(100, limit))}
            if properties:
                params["properties"] = ",".join(properties)
            if after:
                params["after"] = after
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config), params=params)
                resp.raise_for_status()
                data = resp.json()

        if isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
            return [_object_to_row(item) for item in data["results"]]
        if isinstance(data, dict):
            return [_object_to_row(data)]
        if isinstance(data, list):
            return [_object_to_row(item) if isinstance(item, dict) else {"value": item} for item in data]
        return [{"value": data}]

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows_by_object: Dict[str, int] = {}
        for obj in config.get("objects") or []:
            try:
                rows = await self.execute_query(
                    config,
                    json.dumps({
                        "object_type": obj.get("object_type") or "contacts",
                        "properties": obj.get("properties"),
                        "limit": 50,
                    }),
                )
                rows_by_object[obj.get("name") or obj.get("object_type") or "object"] = len(rows)
            except Exception as exc:
                logger.warning("HubSpot sync %s failed: %s", obj, exc)
                rows_by_object[obj.get("name") or "object"] = 0
        return {"success": True, "rows_by_object": rows_by_object}
