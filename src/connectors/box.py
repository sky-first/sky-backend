"""Box connector.

Treats a Box account as a tabular data source by surfacing folders
and files. Mirrors the Drive/Dropbox connectors' read-only stance —
exposes metadata (id, name, size, modified_at, owner, parent) so
agents can monitor a folder the same way they monitor a database
table or a CRM list.

Auth — Box uses OAuth 2.0 with Bearer access tokens. Either:
  - A short-lived access token from the OAuth flow (production), or
  - A developer token from the Box developer console (dev/test only —
    expires in 60 minutes).

Config:

    {
        "base_url": "https://api.box.com/2.0",   # default — rarely overridden
        "auth": {
            "type": "bearer",
            "access_token": "..."
        },
        "objects": [
            {"name": "shared",  "object_type": "items", "folder_id": "0"},
            {"name": "engineering", "object_type": "items", "folder_id": "12345"},
            {"name": "users",   "object_type": "users"}
        ]
    }

execute_query forms accepted:
  - empty string                 → defaults to ``items`` of root folder.
  - bare object name (``users``, ``items``)
  - JSON ``{"object_type":"items","folder_id":"123","limit":100}``
  - raw API path starting with ``/`` (e.g. ``/users/me``).

Required Box scopes (read-only):
  - ``base_explorer``       — list folder contents
  - ``base_preview``        — read file metadata

Read-only — does NOT upload, copy, or delete.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://api.box.com/2.0"
_DEFAULT_LIMIT = 100  # Box default; max 1000 server-side.
_ROOT_FOLDER_ID = "0"  # Box's literal root.


def _auth_headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    token = (
        auth.get("access_token")
        or auth.get("api_token")
        or auth.get("token")
    )
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _item_to_row(item: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a Box ``file`` or ``folder`` entry into a flat row."""
    parent = item.get("parent") or {}
    owner = item.get("owned_by") or item.get("created_by") or {}
    return {
        "id": item.get("id"),
        "type": item.get("type"),
        "name": item.get("name"),
        "size": item.get("size"),
        "parent_id": parent.get("id"),
        "parent_name": parent.get("name"),
        "owner": owner.get("login") or owner.get("name"),
        "created_at": item.get("created_at"),
        "modified_at": item.get("modified_at"),
        "sha1": item.get("sha1"),
        "shared_link_url": (item.get("shared_link") or {}).get("url"),
    }


def _user_to_row(u: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": u.get("id"),
        "name": u.get("name"),
        "login": u.get("login"),
        "status": u.get("status"),
        "role": u.get("role"),
        "language": u.get("language"),
        "created_at": u.get("created_at"),
    }


class BoxConnector(BaseConnector):
    """Box as a read-only tabular source.

    Auth: OAuth 2.0 access token via ``Bearer``.
    """

    TIMEOUT = 15.0

    def _base(self, config: Dict[str, Any]) -> str:
        return (config.get("base_url") or _DEFAULT_BASE).rstrip("/")

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """``GET /users/me`` — Box's canonical token-validity probe.

        Returns 200 with the user payload for a valid token, 401 for
        ``invalid_token`` or expired developer tokens.
        """
        url = f"{self._base(config)}/users/me"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config))
                return resp.status_code == 200
        except Exception as exc:
            logger.info("Box test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        tables: List[Dict[str, Any]] = []
        for obj in config.get("objects") or []:
            object_type = obj.get("object_type") or "items"
            tables.append({
                "name": obj.get("name") or object_type,
                "kind": "box_object",
                "columns": _columns_for(object_type),
                "metadata": {
                    "object_type": object_type,
                    "folder_id": obj.get("folder_id") or _ROOT_FOLDER_ID,
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        base = self._base(config)
        q = (query or "").strip()

        object_type: str = "items"
        folder_id: str = _ROOT_FOLDER_ID
        file_id: Optional[str] = None
        limit: int = _DEFAULT_LIMIT
        offset: int = 0
        raw_path: Optional[str] = None

        if q.startswith("/"):
            raw_path = q
        elif q.startswith("{"):
            try:
                parsed = json.loads(q)
                object_type = parsed.get("object_type") or parsed.get("type") or "items"
                folder_id = parsed.get("folder_id") or _ROOT_FOLDER_ID
                file_id = parsed.get("file_id")
                limit = int(parsed.get("limit") or _DEFAULT_LIMIT)
                offset = int(parsed.get("offset") or 0)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid Box query JSON: {exc}") from exc
        elif q:
            object_type = q

        # Box caps limit at 1000 server-side for /folders/{id}/items.
        limit = max(1, min(1000, limit))

        if raw_path:
            url = f"{base}{raw_path if raw_path.startswith('/') else '/' + raw_path}"
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config))
                data = _ok_or_raise(resp)
            return _normalise_response(data)

        if object_type == "items":
            url = f"{base}/folders/{folder_id}/items"
            params = {
                "limit": limit,
                "offset": offset,
                "fields": (
                    "id,type,name,size,parent,owned_by,created_by,"
                    "created_at,modified_at,sha1,shared_link"
                ),
            }
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(
                    url, headers=_auth_headers(config), params=params,
                )
                data = _ok_or_raise(resp)
            return [_item_to_row(i) for i in (data.get("entries") or [])]

        if object_type == "file":
            if not file_id:
                raise ValueError(
                    "Box 'file' object_type requires 'file_id' "
                    "(e.g. {\"object_type\":\"file\",\"file_id\":\"123\"})."
                )
            url = f"{base}/files/{file_id}"
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config))
                data = _ok_or_raise(resp)
            return [_item_to_row(data)]

        if object_type == "users":
            url = f"{base}/users"
            params = {"limit": limit, "offset": offset}
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(
                    url, headers=_auth_headers(config), params=params,
                )
                data = _ok_or_raise(resp)
            return [_user_to_row(u) for u in (data.get("entries") or [])]

        raise ValueError(f"Unknown Box object_type: {object_type!r}")

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows_by_object: Dict[str, int] = {}
        for obj in config.get("objects") or []:
            label = obj.get("name") or obj.get("object_type") or "object"
            try:
                payload: Dict[str, Any] = {
                    "object_type": obj.get("object_type") or "items",
                    "limit": int(obj.get("limit") or _DEFAULT_LIMIT),
                }
                if obj.get("folder_id"):
                    payload["folder_id"] = obj["folder_id"]
                if obj.get("file_id"):
                    payload["file_id"] = obj["file_id"]
                rows = await self.execute_query(config, json.dumps(payload))
                rows_by_object[label] = len(rows)
            except Exception as exc:
                logger.warning("Box sync %s failed: %s", label, exc)
                rows_by_object[label] = 0
        return {"success": True, "rows_by_object": rows_by_object}


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


_COLUMN_DEFS: Dict[str, List[Dict[str, str]]] = {
    "items": [
        {"name": "id"}, {"name": "type"}, {"name": "name"},
        {"name": "size"}, {"name": "parent_id"}, {"name": "owner"},
        {"name": "created_at"}, {"name": "modified_at"},
    ],
    "users": [
        {"name": "id"}, {"name": "name"}, {"name": "login"},
        {"name": "status"}, {"name": "role"}, {"name": "created_at"},
    ],
    "file": [
        {"name": "id"}, {"name": "name"}, {"name": "size"},
        {"name": "owner"}, {"name": "modified_at"},
    ],
}


def _columns_for(object_type: str) -> List[Dict[str, str]]:
    return list(_COLUMN_DEFS.get(object_type, []))


def _ok_or_raise(resp: httpx.Response) -> Dict[str, Any]:
    """Raise on non-2xx, surfacing Box's structured error code.

    Box error bodies look like:
    ``{"type":"error","status":401,"code":"unauthorized",...,"message":"..."}``.
    Surfacing ``code`` lets the backend's error mapper translate it to
    user-facing copy.
    """
    if resp.status_code >= 400:
        try:
            err = resp.json()
            code = err.get("code") or resp.status_code
            msg = err.get("message") or "request failed"
        except Exception:
            code = resp.status_code
            msg = "request failed"
        raise httpx.HTTPStatusError(
            f"Box API error: {code} — {msg}",
            request=resp.request,
            response=resp,
        )
    return resp.json()


def _normalise_response(data: Any) -> List[Dict[str, Any]]:
    """Best-effort flatten of an arbitrary raw-path response into rows."""
    if isinstance(data, dict):
        if isinstance(data.get("entries"), list):
            return data["entries"]
        return [data]
    if isinstance(data, list):
        return data
    return [{"value": data}]
