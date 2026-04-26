"""Stripe connector — read-only over the official REST API.

Surfaces ``customers``, ``subscriptions``, ``invoices``, ``charges``,
``products`` so revenue agents can monitor them like any other
source.

Auth — restricted secret key (``rk_*``) recommended; full secret
(``sk_*``) accepted. Config:

    {
        "base_url": "https://api.stripe.com",   # default
        "auth": {"type": "bearer", "api_token": "rk_test_..."},
        "objects": [
            {"name": "customers",     "object_type": "customers",     "limit": 100},
            {"name": "subscriptions", "object_type": "subscriptions", "limit": 100}
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

_DEFAULT_BASE = "https://api.stripe.com"
_DEFAULT_LIMIT = 100
_VALID_OBJECTS = {
    "customers",
    "subscriptions",
    "invoices",
    "charges",
    "products",
    "payment_intents",
}


def _headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    token = auth.get("api_token") or auth.get("token")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _base(config: Dict[str, Any]) -> str:
    return (config.get("base_url") or _DEFAULT_BASE).rstrip("/")


class StripeConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        url = f"{_base(config)}/v1/balance"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=_headers(config))
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("stripe.test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        # Stripe doesn't expose a "list of resources" endpoint; we return
        # a fixed catalogue of read-only surfaces.
        tables = [
            {"name": name, "schema": "stripe", "row_count": 0}
            for name in sorted(_VALID_OBJECTS)
        ]
        return {"tables": tables}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        spec = self._parse_query(query)
        kind = spec.get("object_type")
        if kind not in _VALID_OBJECTS:
            raise ValueError(f"unsupported Stripe object '{kind}'")
        limit = int(spec.get("limit") or _DEFAULT_LIMIT)
        starting_after = spec.get("starting_after")

        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if starting_after:
            params["starting_after"] = starting_after

        url = f"{_base(config)}/v1/{kind}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=_headers(config), params=params)
            resp.raise_for_status()
            body = resp.json() or {}
        return body.get("data") or []

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows = 0
        for obj in config.get("objects") or []:
            r = await self.execute_query(config, json.dumps(obj))
            rows += len(r)
        return {"rows_synced": rows}

    def _parse_query(self, query: str) -> Dict[str, Any]:
        q = (query or "").strip()
        if not q:
            return {"object_type": "customers"}
        if q.startswith("{"):
            try:
                return json.loads(q)
            except json.JSONDecodeError:
                pass
        return {"object_type": q}
