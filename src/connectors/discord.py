"""Discord connector — read-only over the bot REST API.

Auth — bot token. Surfaces ``guilds``, ``channels``, ``messages``,
``members``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_BASE = "https://discord.com/api/v10"


def _headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    token = auth.get("api_token") or auth.get("token")
    return (
        {"Authorization": f"Bot {token}", "Accept": "application/json"}
        if token
        else {"Accept": "application/json"}
    )


class DiscordConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_BASE}/users/@me", headers=_headers(config)
                )
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("discord.test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{_BASE}/users/@me/guilds", headers=_headers(config)
            )
            if resp.status_code != 200:
                return {"tables": []}
            guilds = resp.json() or []
        return {
            "tables": [
                {"name": g.get("name", "guild"), "schema": "discord"}
                for g in guilds
            ]
        }

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        spec = self._parse(query)
        kind = spec.get("object_type") or "guilds"
        gid = spec.get("guild_id")
        cid = spec.get("channel_id")
        if kind == "guilds":
            url = f"{_BASE}/users/@me/guilds"
        elif kind == "channels":
            url = f"{_BASE}/guilds/{gid}/channels"
        elif kind == "messages":
            url = f"{_BASE}/channels/{cid}/messages?limit=100"
        elif kind == "members":
            url = f"{_BASE}/guilds/{gid}/members?limit=100"
        else:
            raise ValueError(f"unsupported Discord object '{kind}'")
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
            return {"object_type": "guilds"}
        if q.startswith("{"):
            try:
                return json.loads(q)
            except json.JSONDecodeError:
                pass
        return {"object_type": q}
