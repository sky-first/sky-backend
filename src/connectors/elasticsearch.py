"""ElasticSearch / OpenSearch connector — read-only.

Auth — Basic (user/pass) or ApiKey. Surfaces ``indices`` (metadata)
and runs ``_search`` queries against any index.

    {
        "base_url": "https://es.example:9200",
        "auth": {"type": "basic", "user": "elastic", "password": "..."},
        "objects": [
            {"name": "users-search", "object_type": "search", "index": "users",
             "body": {"size": 100, "query": {"match_all": {}}}}
        ]
    }
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


def _headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if auth.get("api_key"):
        headers["Authorization"] = f"ApiKey {auth['api_key']}"
    elif auth.get("user") and auth.get("password"):
        encoded = base64.b64encode(
            f"{auth['user']}:{auth['password']}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {encoded}"
    return headers


def _base(config: Dict[str, Any]) -> str:
    return (config.get("base_url") or "").rstrip("/")


class ElasticsearchConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=config.get("verify_tls", True)) as client:
                resp = await client.get(f"{_base(config)}/", headers=_headers(config))
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("elasticsearch.test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=20.0, verify=config.get("verify_tls", True)) as client:
            resp = await client.get(
                f"{_base(config)}/_cat/indices?format=json",
                headers=_headers(config),
            )
            if resp.status_code != 200:
                return {"tables": []}
            indices = resp.json() or []
        return {
            "tables": [
                {
                    "name": i.get("index"),
                    "schema": "elasticsearch",
                    "row_count": int(i.get("docs.count") or 0),
                }
                for i in indices
            ]
        }

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        spec = self._parse(query)
        index = spec.get("index", "_all")
        body = spec.get("body") or {"size": 100, "query": {"match_all": {}}}
        async with httpx.AsyncClient(timeout=30.0, verify=config.get("verify_tls", True)) as client:
            resp = await client.post(
                f"{_base(config)}/{index}/_search",
                headers=_headers(config),
                json=body,
            )
            resp.raise_for_status()
            payload = resp.json() or {}
        hits = (payload.get("hits") or {}).get("hits") or []
        return [{"_id": h.get("_id"), **(h.get("_source") or {})} for h in hits]

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
        return {"index": q or "_all"}
