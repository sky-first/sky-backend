"""Slack connector.

Treats Slack workspaces as a tabular data source. Surfaces channels,
messages, and users so agents can monitor them like any other source.

Auth — Slack uses bot or user OAuth tokens with ``Bearer`` auth. Config:

    {
        "base_url": "https://slack.com/api",   # default — rarely overridden
        "auth": {
            "type": "bearer",
            "api_token": "xoxb-..."            # bot token (preferred) or
                                               # xoxp-... user token
        },
        "objects": [                            # list-surface declaration
            { "name": "public_channels", "object_type": "channels", "filter": "types=public_channel" },
            { "name": "general_messages", "object_type": "messages", "channel_id": "C01234567", "limit": 100 },
            { "name": "users",          "object_type": "users" }
        ]
    }

execute_query forms accepted:
  - empty string                → defaults to ``users``.
  - bare object name (``users``, ``channels``)
  - JSON ``{"object_type": "messages", "channel_id": "C123", "limit": 50}``
  - raw API path starting with ``/``  (e.g. ``/conversations.list?limit=10``)

Required Slack OAuth scopes (bot):
  - ``channels:read`` — list channels
  - ``channels:history`` — read messages
  - ``users:read``   — list users
  - ``users:read.email`` — include emails (optional)

The connector is read-only. It does NOT post messages.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://slack.com/api"
_DEFAULT_LIMIT = 100


def _auth_headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    token = auth.get("api_token") or auth.get("token")
    headers = {"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _channel_to_row(c: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a Slack ``conversation`` object into a flat row."""
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "is_channel": c.get("is_channel"),
        "is_group": c.get("is_group"),
        "is_im": c.get("is_im"),
        "is_private": c.get("is_private"),
        "is_archived": c.get("is_archived"),
        "is_general": c.get("is_general"),
        "num_members": c.get("num_members"),
        "topic": (c.get("topic") or {}).get("value"),
        "purpose": (c.get("purpose") or {}).get("value"),
        "created": c.get("created"),
        "creator": c.get("creator"),
    }


def _user_to_row(u: Dict[str, Any]) -> Dict[str, Any]:
    profile = u.get("profile") or {}
    return {
        "id": u.get("id"),
        "name": u.get("name"),
        "real_name": u.get("real_name") or profile.get("real_name"),
        "display_name": profile.get("display_name"),
        "email": profile.get("email"),
        "title": profile.get("title"),
        "team_id": u.get("team_id"),
        "deleted": u.get("deleted"),
        "is_bot": u.get("is_bot"),
        "is_admin": u.get("is_admin"),
        "tz": u.get("tz"),
        "updated": u.get("updated"),
    }


def _message_to_row(m: Dict[str, Any], channel_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "ts": m.get("ts"),
        "channel_id": channel_id,
        "user": m.get("user"),
        "type": m.get("type"),
        "subtype": m.get("subtype"),
        "text": m.get("text"),
        "thread_ts": m.get("thread_ts"),
        "reply_count": m.get("reply_count"),
        "reactions": m.get("reactions"),
    }


class SlackConnector(BaseConnector):
    """Slack as a read-only tabular source.

    Auth: workspace-scoped Bot or User token via ``Bearer``.
    """

    TIMEOUT = 15.0

    def _base(self, config: Dict[str, Any]) -> str:
        return (config.get("base_url") or _DEFAULT_BASE).rstrip("/")

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """``auth.test`` — Slack's canonical "is this token good?" probe.

        Slack always returns HTTP 200; success/fail is in the JSON body's
        ``ok`` field. We treat ``ok == true`` as success and anything
        else (including network errors) as failure.
        """
        url = f"{self._base(config)}/auth.test"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.post(url, headers=_auth_headers(config))
                if resp.status_code != 200:
                    return False
                data = resp.json()
                return bool(data.get("ok"))
        except Exception as exc:
            logger.info("Slack test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Surface each declared object as a "table" the picker can pin.

        We don't auto-discover the workspace's channels at metadata time
        because (a) it can be a list of thousands and (b) the picker
        flow expects a stable name. Users declare what they care about.
        """
        tables: List[Dict[str, Any]] = []
        for obj in config.get("objects") or []:
            object_type = obj.get("object_type") or "users"
            tables.append({
                "name": obj.get("name") or object_type,
                "kind": "slack_object",
                "columns": _columns_for(object_type),
                "metadata": {
                    "object_type": object_type,
                    "filter": obj.get("filter") or "",
                    "channel_id": obj.get("channel_id"),
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        base = self._base(config)
        q = (query or "").strip()

        object_type: str = "users"
        channel_id: Optional[str] = None
        limit: int = _DEFAULT_LIMIT
        cursor: Optional[str] = None
        raw_path: Optional[str] = None

        if q.startswith("/"):
            raw_path = q
        elif q.startswith("{"):
            try:
                parsed = json.loads(q)
                object_type = parsed.get("object_type") or parsed.get("type") or "users"
                channel_id = parsed.get("channel_id")
                limit = int(parsed.get("limit") or _DEFAULT_LIMIT)
                cursor = parsed.get("cursor")
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid Slack query JSON: {exc}") from exc
        elif q:
            object_type = q

        # Clamp Slack page size — server cap is 200 for most endpoints.
        limit = max(1, min(200, limit))

        if raw_path:
            url = f"{base}{raw_path if raw_path.startswith('/') else '/' + raw_path}"
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config))
                data = _ok_or_raise(resp)
            return _normalise_response(data)

        # Method dispatch by object_type
        if object_type == "channels":
            url = f"{base}/conversations.list"
            params: Dict[str, Any] = {"limit": limit, "exclude_archived": True}
            if cursor:
                params["cursor"] = cursor
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config), params=params)
                data = _ok_or_raise(resp)
            return [_channel_to_row(c) for c in (data.get("channels") or [])]

        if object_type == "users":
            url = f"{base}/users.list"
            params = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config), params=params)
                data = _ok_or_raise(resp)
            return [_user_to_row(u) for u in (data.get("members") or [])]

        if object_type == "messages":
            if not channel_id:
                raise ValueError(
                    "Slack 'messages' object_type requires 'channel_id' "
                    "(e.g. {\"object_type\":\"messages\",\"channel_id\":\"C012\"})."
                )
            url = f"{base}/conversations.history"
            params = {"channel": channel_id, "limit": limit}
            if cursor:
                params["cursor"] = cursor
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config), params=params)
                data = _ok_or_raise(resp)
            return [_message_to_row(m, channel_id=channel_id) for m in (data.get("messages") or [])]

        raise ValueError(f"Unknown Slack object_type: {object_type!r}")

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows_by_object: Dict[str, int] = {}
        for obj in config.get("objects") or []:
            label = obj.get("name") or obj.get("object_type") or "object"
            try:
                rows = await self.execute_query(
                    config,
                    json.dumps({
                        "object_type": obj.get("object_type") or "users",
                        "channel_id": obj.get("channel_id"),
                        "limit": int(obj.get("limit") or _DEFAULT_LIMIT),
                    }),
                )
                rows_by_object[label] = len(rows)
            except Exception as exc:
                logger.warning("Slack sync %s failed: %s", label, exc)
                rows_by_object[label] = 0
        return {"success": True, "rows_by_object": rows_by_object}


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


_COLUMN_DEFS: Dict[str, List[Dict[str, str]]] = {
    "channels": [
        {"name": "id"}, {"name": "name"}, {"name": "is_private"},
        {"name": "is_archived"}, {"name": "num_members"}, {"name": "topic"},
        {"name": "purpose"}, {"name": "created"}, {"name": "creator"},
    ],
    "users": [
        {"name": "id"}, {"name": "name"}, {"name": "real_name"},
        {"name": "display_name"}, {"name": "email"}, {"name": "title"},
        {"name": "team_id"}, {"name": "is_bot"}, {"name": "is_admin"}, {"name": "tz"},
    ],
    "messages": [
        {"name": "ts"}, {"name": "channel_id"}, {"name": "user"},
        {"name": "type"}, {"name": "subtype"}, {"name": "text"},
        {"name": "thread_ts"}, {"name": "reply_count"},
    ],
}


def _columns_for(object_type: str) -> List[Dict[str, str]]:
    return list(_COLUMN_DEFS.get(object_type, []))


def _ok_or_raise(resp: httpx.Response) -> Dict[str, Any]:
    """Slack always returns HTTP 200; the actual status is in ``ok``.

    On ``ok == false`` we raise with the Slack error code (e.g.
    ``invalid_auth``, ``not_in_channel``, ``rate_limited``) so the
    backend's error mapper can translate it to a user-facing copy.
    """
    if resp.status_code != 200:
        resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise httpx.HTTPStatusError(
            f"Slack API error: {data.get('error', 'unknown')}",
            request=resp.request,
            response=resp,
        )
    return data


def _normalise_response(data: Any) -> List[Dict[str, Any]]:
    """Best-effort flatten of an arbitrary raw-path response into rows
    for downstream consumption."""
    if isinstance(data, dict):
        # Common Slack shape — pull the first list-shaped field.
        for key in ("messages", "channels", "members", "files", "results"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    if isinstance(data, list):
        return data
    return [{"value": data}]
