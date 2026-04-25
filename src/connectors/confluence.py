"""Confluence Cloud connector.

Treats a Confluence wiki as a tabular data source by surfacing spaces,
pages and users so agents can monitor knowledge bases the same way
they monitor Jira issues or HubSpot lists.

Auth — Atlassian Cloud is Basic auth with ``email : api_token`` (same
token model as Jira). Server/Data-Center instances accept Bearer.
Config shape:

    {
        "base_url": "https://your-tenant.atlassian.net",
        "auth": {
            "type": "basic" | "bearer",
            "email": "user@example.com",     # basic
            "api_token": "ATATT...",         # basic or bearer
        },
        "objects": [
            {"name": "eng_pages", "object_type": "pages", "space_id": "12345"},
            {"name": "all_spaces", "object_type": "spaces"},
            {"name": "users", "object_type": "users"}
        ]
    }

execute_query forms accepted:
  - empty string                 → defaults to ``spaces``
  - bare object name (``spaces``, ``pages``, ``users``)
  - JSON ``{"object_type":"pages","space_id":"123","limit":50}``
  - JSON ``{"object_type":"search","cql":"type=page AND space=ENG"}``
  - raw API path starting with ``/`` (e.g. ``/wiki/api/v2/spaces``)

Required Atlassian scopes (Confluence read-only):
  - ``read:space:confluence``
  - ``read:page:confluence``
  - ``read:user:confluence``

Read-only — does NOT create or update pages.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 50  # Confluence v2 default page size; max 250.
_API_V2 = "/wiki/api/v2"
_API_V1 = "/wiki/rest/api"  # CQL search lives only on v1.


def _auth_tuple(config: Dict[str, Any]) -> Optional[tuple[str, str]]:
    auth = config.get("auth") or {}
    if (auth.get("type") or "basic").lower() == "basic":
        email = auth.get("email") or auth.get("username")
        token = auth.get("api_token") or auth.get("token") or auth.get("password")
        if email and token:
            return (email, token)
    return None


def _auth_headers(config: Dict[str, Any]) -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    auth = config.get("auth") or {}
    if (auth.get("type") or "").lower() == "bearer" and auth.get("api_token"):
        headers["Authorization"] = f"Bearer {auth['api_token']}"
    return headers


def _space_to_row(s: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": s.get("id"),
        "key": s.get("key"),
        "name": s.get("name"),
        "type": s.get("type"),
        "status": s.get("status"),
        "homepage_id": s.get("homepageId"),
        "created_at": s.get("createdAt"),
    }


def _page_to_row(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": p.get("id"),
        "title": p.get("title"),
        "status": p.get("status"),
        "space_id": p.get("spaceId"),
        "parent_id": p.get("parentId"),
        "author_id": p.get("authorId"),
        "created_at": p.get("createdAt"),
        "version": (p.get("version") or {}).get("number"),
    }


def _user_to_row(u: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "account_id": u.get("accountId"),
        "account_type": u.get("accountType"),
        "display_name": u.get("displayName") or u.get("publicName"),
        "email": u.get("email") or u.get("emailAddress"),
        "active": u.get("active"),
    }


def _search_hit_to_row(h: Dict[str, Any]) -> Dict[str, Any]:
    """v1 CQL search returns ``{content: {...}, title, excerpt, url}``."""
    content = h.get("content") or {}
    return {
        "id": content.get("id"),
        "type": content.get("type"),
        "title": h.get("title") or content.get("title"),
        "excerpt": h.get("excerpt"),
        "space_key": (content.get("space") or {}).get("key"),
        "url": h.get("url"),
        "last_modified": h.get("lastModified"),
    }


class ConfluenceConnector(BaseConnector):
    """Confluence Cloud as a read-only tabular source."""

    TIMEOUT = 15.0

    def _base(self, config: Dict[str, Any]) -> str:
        return (config.get("base_url") or "").rstrip("/")

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """``GET /wiki/api/v2/spaces?limit=1`` is the cheapest probe.

        Confluence has no dedicated whoami endpoint on v2; one space
        listing tells us the auth + base_url combination is valid in
        a single round trip.
        """
        base = self._base(config)
        if not base:
            return False
        url = f"{base}{_API_V2}/spaces"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(
                    url,
                    headers=_auth_headers(config),
                    auth=_auth_tuple(config),
                    params={"limit": 1},
                )
                return resp.status_code == 200
        except Exception as exc:
            logger.info("Confluence test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        tables: List[Dict[str, Any]] = []
        for obj in config.get("objects") or []:
            object_type = obj.get("object_type") or "spaces"
            tables.append({
                "name": obj.get("name") or object_type,
                "kind": "confluence_object",
                "columns": _columns_for(object_type),
                "metadata": {
                    "object_type": object_type,
                    "space_id": obj.get("space_id"),
                    "cql": obj.get("cql") or "",
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        base = self._base(config)
        if not base:
            raise ValueError("Confluence connector requires 'base_url'.")
        q = (query or "").strip()

        object_type: str = "spaces"
        space_id: Optional[str] = None
        page_id: Optional[str] = None
        cql: Optional[str] = None
        limit: int = _DEFAULT_LIMIT
        cursor: Optional[str] = None
        raw_path: Optional[str] = None

        if q.startswith("/"):
            raw_path = q
        elif q.startswith("{"):
            try:
                parsed = json.loads(q)
                object_type = parsed.get("object_type") or parsed.get("type") or "spaces"
                space_id = parsed.get("space_id")
                page_id = parsed.get("page_id")
                cql = parsed.get("cql")
                limit = int(parsed.get("limit") or _DEFAULT_LIMIT)
                cursor = parsed.get("cursor")
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid Confluence query JSON: {exc}") from exc
        elif q:
            object_type = q

        # Confluence v2 caps ``limit`` at 250.
        limit = max(1, min(250, limit))

        if raw_path:
            url = f"{base}{raw_path if raw_path.startswith('/') else '/' + raw_path}"
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(
                    url,
                    headers=_auth_headers(config),
                    auth=_auth_tuple(config),
                )
                data = _ok_or_raise(resp)
            return _normalise_response(data)

        common_kwargs = {
            "headers": _auth_headers(config),
            "auth": _auth_tuple(config),
        }

        if object_type == "spaces":
            url = f"{base}{_API_V2}/spaces"
            params: Dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, params=params, **common_kwargs)
                data = _ok_or_raise(resp)
            return [_space_to_row(s) for s in (data.get("results") or [])]

        if object_type == "pages":
            # If ``space_id`` is supplied, scope listing to that space —
            # otherwise list pages globally (capped at ``limit``).
            if space_id:
                url = f"{base}{_API_V2}/spaces/{space_id}/pages"
            else:
                url = f"{base}{_API_V2}/pages"
            params = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, params=params, **common_kwargs)
                data = _ok_or_raise(resp)
            return [_page_to_row(p) for p in (data.get("results") or [])]

        if object_type == "page":
            if not page_id:
                raise ValueError(
                    "Confluence 'page' object_type requires 'page_id' "
                    "(e.g. {\"object_type\":\"page\",\"page_id\":\"123\"})."
                )
            url = f"{base}{_API_V2}/pages/{page_id}"
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, **common_kwargs)
                data = _ok_or_raise(resp)
            return [_page_to_row(data)]

        if object_type == "users":
            # Confluence v2 doesn't expose a top-level user list. Surface
            # the bot/account caller via /users/current as a single row,
            # which is enough for the picker to validate "users" exists
            # without 404ing the workspace.
            url = f"{base}{_API_V1}/user/current"
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, **common_kwargs)
                data = _ok_or_raise(resp)
            return [_user_to_row(data)]

        if object_type == "search":
            if not cql:
                raise ValueError(
                    "Confluence 'search' object_type requires 'cql' "
                    "(e.g. {\"object_type\":\"search\",\"cql\":\"type=page\"})."
                )
            url = f"{base}{_API_V1}/search"
            params = {"cql": cql, "limit": limit}
            if cursor:
                params["start"] = cursor
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, params=params, **common_kwargs)
                data = _ok_or_raise(resp)
            return [_search_hit_to_row(h) for h in (data.get("results") or [])]

        raise ValueError(f"Unknown Confluence object_type: {object_type!r}")

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows_by_object: Dict[str, int] = {}
        for obj in config.get("objects") or []:
            label = obj.get("name") or obj.get("object_type") or "object"
            try:
                payload: Dict[str, Any] = {
                    "object_type": obj.get("object_type") or "spaces",
                    "limit": int(obj.get("limit") or _DEFAULT_LIMIT),
                }
                if obj.get("space_id"):
                    payload["space_id"] = obj["space_id"]
                if obj.get("page_id"):
                    payload["page_id"] = obj["page_id"]
                if obj.get("cql"):
                    payload["cql"] = obj["cql"]
                rows = await self.execute_query(config, json.dumps(payload))
                rows_by_object[label] = len(rows)
            except Exception as exc:
                logger.warning("Confluence sync %s failed: %s", label, exc)
                rows_by_object[label] = 0
        return {"success": True, "rows_by_object": rows_by_object}


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


_COLUMN_DEFS: Dict[str, List[Dict[str, str]]] = {
    "spaces": [
        {"name": "id"}, {"name": "key"}, {"name": "name"},
        {"name": "type"}, {"name": "status"}, {"name": "homepage_id"},
        {"name": "created_at"},
    ],
    "pages": [
        {"name": "id"}, {"name": "title"}, {"name": "status"},
        {"name": "space_id"}, {"name": "parent_id"}, {"name": "author_id"},
        {"name": "created_at"}, {"name": "version"},
    ],
    "users": [
        {"name": "account_id"}, {"name": "display_name"},
        {"name": "email"}, {"name": "active"},
    ],
    "search": [
        {"name": "id"}, {"name": "type"}, {"name": "title"},
        {"name": "excerpt"}, {"name": "space_key"}, {"name": "url"},
        {"name": "last_modified"},
    ],
}


def _columns_for(object_type: str) -> List[Dict[str, str]]:
    return list(_COLUMN_DEFS.get(object_type, []))


def _ok_or_raise(resp: httpx.Response) -> Dict[str, Any]:
    if resp.status_code >= 400:
        try:
            err = resp.json()
            msg = err.get("message") or err.get("error", {}).get("message") or "request failed"
        except Exception:
            msg = "request failed"
        raise httpx.HTTPStatusError(
            f"Confluence API error {resp.status_code}: {msg}",
            request=resp.request,
            response=resp,
        )
    return resp.json()


def _normalise_response(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        if isinstance(data.get("results"), list):
            return data["results"]
        return [data]
    if isinstance(data, list):
        return data
    return [{"value": data}]
