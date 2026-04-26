"""Trello connector — read-only.

Auth: API key + token (legacy OAuth1 token, simplest for read-only).
Config:

    {
        "auth": {"api_key": "...", "api_token": "..."},
        "objects": [
            {"name": "boards",  "object_type": "boards"},
            {"name": "lists",   "object_type": "lists",  "board_id": "..."},
            {"name": "cards",   "object_type": "cards",  "board_id": "..."}
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

_BASE = "https://api.trello.com/1"


def _params(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    return {"key": auth.get("api_key", ""), "token": auth.get("api_token", "")}


class TrelloConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_BASE}/members/me", params=_params(config)
                )
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("trello.test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{_BASE}/members/me/boards", params=_params(config)
            )
            if resp.status_code != 200:
                return {"tables": []}
            boards = resp.json() or []
        return {
            "tables": [
                {"name": b.get("name", "board"), "schema": "trello"}
                for b in boards
            ]
        }

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        spec = self._parse(query)
        kind = spec.get("object_type") or "boards"
        bid = spec.get("board_id")
        if kind == "boards":
            url = f"{_BASE}/members/me/boards"
        elif kind == "lists":
            url = f"{_BASE}/boards/{bid}/lists"
        elif kind == "cards":
            url = f"{_BASE}/boards/{bid}/cards"
        else:
            raise ValueError(f"unsupported Trello object '{kind}'")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=_params(config))
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
            return {"object_type": "boards"}
        if q.startswith("{"):
            try:
                return json.loads(q)
            except json.JSONDecodeError:
                pass
        return {"object_type": q}
