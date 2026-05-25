"""Mailchimp connector — read-only over the Marketing API."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


def _headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    token = auth.get("api_token") or auth.get("token")
    headers = {"Accept": "application/json"}
    if token:
        # Mailchimp accepts either Bearer (OAuth) or Basic (API key).
        if (token or "").startswith(("oauth_", "Bearer ")):
            headers["Authorization"] = f"Bearer {token.removeprefix('Bearer ').strip()}"
        else:
            import base64

            encoded = base64.b64encode(f"anystring:{token}".encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
    return headers


def _server(config: Dict[str, Any]) -> str:
    """Mailchimp is data-center routed — the API key suffix (``-us21``)
    or an explicit ``server`` config field decides the host."""
    server = config.get("server")
    if server:
        return server.strip()
    auth = config.get("auth") or {}
    token = auth.get("api_token") or ""
    if "-" in token:
        return token.rsplit("-", 1)[-1]
    return "us1"


def _base(config: Dict[str, Any]) -> str:
    return f"https://{_server(config)}.api.mailchimp.com/3.0"


class MailchimpConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(_base(config) + "/ping", headers=_headers(config))
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("mailchimp.test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "tables": [
                {"name": "lists", "schema": "mailchimp"},
                {"name": "campaigns", "schema": "mailchimp"},
                {"name": "automations", "schema": "mailchimp"},
                {"name": "reports", "schema": "mailchimp"},
            ]
        }

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        spec = self._parse(query)
        kind = spec.get("object_type") or "lists"
        url = f"{_base(config)}/{kind}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=_headers(config), params={"count": 100})
            resp.raise_for_status()
            body = resp.json() or {}
        # Mailchimp wraps lists in `<kind>` arrays inconsistently.
        for k in (kind, "lists", "campaigns", "automations", "reports"):
            if isinstance(body.get(k), list):
                return body[k]
        return []

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
            return {"object_type": "lists"}
        if q.startswith("{"):
            try:
                return json.loads(q)
            except json.JSONDecodeError:
                pass
        return {"object_type": q}
