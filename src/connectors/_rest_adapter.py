"""Generic REST adapter — powers the long tail of connectors that
share the same shape: bearer-token auth + ``GET /<resource>`` listing.

Every connector that fits the pattern declares:

  * ``BASE`` — root URL.
  * ``RESOURCE_MAP`` — {kind: path} (e.g. ``"customers": "/v3/customers"``).
  * Optional ``AUTH_FN`` — overrides the default ``Authorization: Bearer``.
  * Optional ``DATA_KEY`` — when the API wraps results in ``{"data": [...]}``,
    the adapter unwraps to the list.

Each connector subclasses :class:`RestAdapterConnector` and provides
those class attrs. The four BaseConnector methods come for free.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


def _bearer_headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    token = auth.get("api_token") or auth.get("token") or ""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class RestAdapterConnector(BaseConnector):
    """Subclass + set BASE + RESOURCE_MAP. The rest is free."""

    BASE: str = ""
    RESOURCE_MAP: Dict[str, str] = {}
    AUTH_FN: Optional[Callable[[Dict[str, Any]], Dict[str, str]]] = None
    DATA_KEY: Optional[str] = None
    PROBE_PATH: Optional[str] = None  # for test_connection
    DEFAULT_KIND: str = ""

    @classmethod
    def _resolve_base(cls, config: Dict[str, Any]) -> str:
        return (config.get("base_url") or cls.BASE).rstrip("/")

    @classmethod
    def _headers(cls, config: Dict[str, Any]) -> Dict[str, str]:
        fn = cls.AUTH_FN or _bearer_headers
        return fn(config)

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        path = self.PROBE_PATH or next(iter(self.RESOURCE_MAP.values()), "")
        url = f"{self._resolve_base(config)}{path}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=self._headers(config))
            return resp.status_code in (200, 204)
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s.test_connection failed: %s", type(self).__name__, exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        # Generic adapter cannot enumerate endpoints — declare the
        # known surface from RESOURCE_MAP keys.
        return {
            "tables": [
                {"name": name, "schema": type(self).__name__.replace("Connector", "").lower()}
                for name in sorted(self.RESOURCE_MAP)
            ]
        }

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        spec = self._parse(query)
        kind = (spec.get("object_type") or self.DEFAULT_KIND or next(iter(self.RESOURCE_MAP), "")).lower()
        path = self.RESOURCE_MAP.get(kind)
        if not path:
            raise ValueError(f"unsupported {type(self).__name__} object '{kind}'")
        url = f"{self._resolve_base(config)}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self._headers(config))
            resp.raise_for_status()
            body = resp.json() or {}
        if isinstance(body, list):
            return body
        if self.DATA_KEY and isinstance(body.get(self.DATA_KEY), list):
            return body[self.DATA_KEY]
        # Heuristic — return any list-valued top-level key if there is
        # exactly one (Mailchimp / Discord / etc. all do this).
        list_keys = [k for k, v in body.items() if isinstance(v, list)]
        if len(list_keys) == 1:
            return body[list_keys[0]]
        return [body]

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
            return {"object_type": self.DEFAULT_KIND or next(iter(self.RESOURCE_MAP), "")}
        if q.startswith("{"):
            try:
                return json.loads(q)
            except json.JSONDecodeError:
                pass
        return {"object_type": q}
