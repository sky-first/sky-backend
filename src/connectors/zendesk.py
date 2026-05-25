"""Zendesk Support connector — read-only.

Auth — email + API token (recommended) or OAuth bearer. Subdomain
goes in ``subdomain`` config field.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


def _base(config: Dict[str, Any]) -> str:
    sub = config.get("subdomain", "")
    return f"https://{sub}.zendesk.com/api/v2"


def _headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    headers = {"Accept": "application/json"}
    if auth.get("api_token") and auth.get("email"):
        # Zendesk: "<email>/token:<api_token>"
        creds = f"{auth['email']}/token:{auth['api_token']}".encode()
        headers["Authorization"] = f"Basic {base64.b64encode(creds).decode()}"
    elif auth.get("oauth_token"):
        headers["Authorization"] = f"Bearer {auth['oauth_token']}"
    return headers


_OBJECTS = ("tickets", "users", "organizations", "groups")


class ZendeskConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_base(config)}/users/me.json", headers=_headers(config)
                )
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("zendesk.test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return {"tables": [{"name": o, "schema": "zendesk"} for o in _OBJECTS]}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        spec = self._parse(query)
        kind = spec.get("object_type") or "tickets"
        if kind not in _OBJECTS:
            raise ValueError(f"unsupported Zendesk object '{kind}'")
        url = f"{_base(config)}/{kind}.json?per_page=100"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=_headers(config))
            resp.raise_for_status()
            body = resp.json() or {}
        return body.get(kind) or []

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
            return {"object_type": "tickets"}
        if q.startswith("{"):
            try:
                return json.loads(q)
            except json.JSONDecodeError:
                pass
        return {"object_type": q}
