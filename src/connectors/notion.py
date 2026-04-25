"""Notion connector.

Treats a Notion workspace as a tabular data source. The Notion data model
is a tree of pages and databases (databases are themselves pages with a
fixed schema), so we surface those two object types plus ``users`` and a
``search`` shortcut.

Auth — Notion uses internal integration secrets via ``Bearer`` auth. The
token is the ``Internal Integration Secret`` you copy from the
integration's settings page (starts with ``secret_`` or, for newer
workspaces, ``ntn_``). Config:

    {
        "base_url": "https://api.notion.com/v1",   # default
        "notion_version": "2022-06-28",             # default
        "auth": {
            "type": "bearer",
            "api_token": "secret_..."
        },
        "objects": [
            { "name": "tasks_db",  "object_type": "database",
              "database_id": "abc-123" },
            { "name": "all_pages", "object_type": "search",
              "filter": "page" },
            { "name": "users",     "object_type": "users" }
        ]
    }

execute_query forms accepted:
  - empty string                 → defaults to ``users``
  - bare object name (``users``, ``databases``, ``pages``)
  - JSON ``{"object_type":"database","database_id":"abc",...}``
  - raw API path starting with ``/`` (e.g. ``/users/me``)

Required scopes are baked into the integration's capabilities — the
connector itself only reads. It does NOT mutate pages or databases.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://api.notion.com/v1"
_DEFAULT_VERSION = "2022-06-28"
_DEFAULT_LIMIT = 100


def _auth_headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    token = auth.get("api_token") or auth.get("token")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Notion-Version": config.get("notion_version") or _DEFAULT_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _plain_text(rich: Any) -> str:
    """Concatenate Notion rich-text array into a flat string."""
    if not isinstance(rich, list):
        return ""
    return "".join((item.get("plain_text") or "") for item in rich)


def _flatten_property(prop: Dict[str, Any]) -> Any:
    """Reduce a Notion property object into a scalar/string row value.

    Notion property values are deeply nested ({"title": [...rich...]});
    BI/insight surfaces want flat columns. We pick the most useful
    representation per type — text for titles/text, ISO strings for
    dates, raw value for numbers/checkboxes/selects.
    """
    if not isinstance(prop, dict):
        return prop
    ptype = prop.get("type")
    if ptype == "title":
        return _plain_text(prop.get("title"))
    if ptype == "rich_text":
        return _plain_text(prop.get("rich_text"))
    if ptype == "number":
        return prop.get("number")
    if ptype == "checkbox":
        return prop.get("checkbox")
    if ptype == "select":
        return (prop.get("select") or {}).get("name")
    if ptype == "multi_select":
        return [s.get("name") for s in (prop.get("multi_select") or [])]
    if ptype == "status":
        return (prop.get("status") or {}).get("name")
    if ptype == "date":
        d = prop.get("date") or {}
        return d.get("start")
    if ptype == "url":
        return prop.get("url")
    if ptype == "email":
        return prop.get("email")
    if ptype == "phone_number":
        return prop.get("phone_number")
    if ptype == "people":
        return [p.get("id") for p in (prop.get("people") or [])]
    if ptype == "files":
        return [(f.get("name") or "") for f in (prop.get("files") or [])]
    if ptype == "relation":
        return [r.get("id") for r in (prop.get("relation") or [])]
    if ptype == "formula":
        f = prop.get("formula") or {}
        return f.get(f.get("type")) if f.get("type") else None
    if ptype == "rollup":
        r = prop.get("rollup") or {}
        return r.get(r.get("type")) if r.get("type") else None
    return prop.get(ptype)


def _database_row_to_flat(page: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a database-row page into ``{id, ...properties, last_edited}``."""
    flat: Dict[str, Any] = {
        "id": page.get("id"),
        "created_time": page.get("created_time"),
        "last_edited_time": page.get("last_edited_time"),
        "url": page.get("url"),
    }
    for name, prop in (page.get("properties") or {}).items():
        flat[name] = _flatten_property(prop)
    return flat


def _page_to_row(page: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce a search/list result to a small set of canonical columns."""
    title = ""
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            title = _plain_text(prop.get("title"))
            break
    return {
        "id": page.get("id"),
        "object": page.get("object"),
        "title": title,
        "url": page.get("url"),
        "parent_type": (page.get("parent") or {}).get("type"),
        "created_time": page.get("created_time"),
        "last_edited_time": page.get("last_edited_time"),
        "archived": page.get("archived"),
    }


def _database_to_row(db: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": db.get("id"),
        "object": db.get("object"),
        "title": _plain_text(db.get("title")),
        "url": db.get("url"),
        "created_time": db.get("created_time"),
        "last_edited_time": db.get("last_edited_time"),
        "archived": db.get("archived"),
        "property_count": len((db.get("properties") or {})),
    }


def _user_to_row(u: Dict[str, Any]) -> Dict[str, Any]:
    person = u.get("person") or {}
    bot = u.get("bot") or {}
    return {
        "id": u.get("id"),
        "name": u.get("name"),
        "type": u.get("type"),
        "email": person.get("email") or (bot.get("workspace_name") if u.get("type") == "bot" else None),
        "avatar_url": u.get("avatar_url"),
    }


class NotionConnector(BaseConnector):
    """Notion as a read-only tabular source.

    Auth: workspace-scoped Internal Integration Secret via ``Bearer``.
    """

    TIMEOUT = 15.0

    def _base(self, config: Dict[str, Any]) -> str:
        return (config.get("base_url") or _DEFAULT_BASE).rstrip("/")

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """``GET /users/me`` — Notion's canonical "is this token good?".

        Notion returns 200 with the bot user for a valid token, 401 for
        invalid_token. Anything else (network, 5xx) we treat as failure
        rather than masking the connector behind a partial green.
        """
        url = f"{self._base(config)}/users/me"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config))
                return resp.status_code == 200
        except Exception as exc:
            logger.info("Notion test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Surface declared objects as tables.

        For ``database`` objects we fetch the actual schema so the
        picker can show real columns rather than just "title".
        """
        tables: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            for obj in config.get("objects") or []:
                object_type = obj.get("object_type") or "pages"
                cols: List[Dict[str, str]] = _columns_for(object_type)
                if object_type == "database" and obj.get("database_id"):
                    try:
                        url = f"{self._base(config)}/databases/{obj['database_id']}"
                        resp = await client.get(url, headers=_auth_headers(config))
                        if resp.status_code == 200:
                            db = resp.json()
                            cols = [
                                {"name": "id"},
                                *[{"name": p} for p in (db.get("properties") or {}).keys()],
                                {"name": "last_edited_time"},
                            ]
                    except Exception as exc:
                        logger.info("Notion describe-db %s failed: %s", obj.get("database_id"), exc)
                tables.append({
                    "name": obj.get("name") or object_type,
                    "kind": "notion_object",
                    "columns": cols,
                    "metadata": {
                        "object_type": object_type,
                        "database_id": obj.get("database_id"),
                        "filter": obj.get("filter") or "",
                    },
                })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        base = self._base(config)
        q = (query or "").strip()

        object_type: str = "users"
        database_id: Optional[str] = None
        page_id: Optional[str] = None
        filter_text: Optional[str] = None
        filter_obj: Optional[Dict[str, Any]] = None
        sorts: Optional[List[Dict[str, Any]]] = None
        limit: int = _DEFAULT_LIMIT
        cursor: Optional[str] = None
        raw_path: Optional[str] = None

        if q.startswith("/"):
            raw_path = q
        elif q.startswith("{"):
            try:
                parsed = json.loads(q)
                object_type = parsed.get("object_type") or parsed.get("type") or "users"
                database_id = parsed.get("database_id")
                page_id = parsed.get("page_id")
                filter_text = parsed.get("filter")
                filter_obj = parsed.get("filter_obj") if isinstance(parsed.get("filter_obj"), dict) else None
                sorts = parsed.get("sorts") if isinstance(parsed.get("sorts"), list) else None
                limit = int(parsed.get("limit") or _DEFAULT_LIMIT)
                cursor = parsed.get("cursor")
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid Notion query JSON: {exc}") from exc
        elif q:
            object_type = q

        # Notion paginates with ``page_size`` capped at 100 server-side.
        limit = max(1, min(100, limit))

        if raw_path:
            url = f"{base}{raw_path if raw_path.startswith('/') else '/' + raw_path}"
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config))
                data = _ok_or_raise(resp)
            return _normalise_response(data)

        if object_type == "users":
            url = f"{base}/users"
            params: Dict[str, Any] = {"page_size": limit}
            if cursor:
                params["start_cursor"] = cursor
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config), params=params)
                data = _ok_or_raise(resp)
            return [_user_to_row(u) for u in (data.get("results") or [])]

        if object_type in ("search", "pages", "databases"):
            url = f"{base}/search"
            body: Dict[str, Any] = {"page_size": limit}
            if cursor:
                body["start_cursor"] = cursor
            if filter_text:
                body["query"] = filter_text
            # Map "pages"/"databases" shortcuts to Notion's filter object.
            if object_type == "pages":
                body["filter"] = {"value": "page", "property": "object"}
            elif object_type == "databases":
                body["filter"] = {"value": "database", "property": "object"}
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.post(url, headers=_auth_headers(config), json=body)
                data = _ok_or_raise(resp)
            results = data.get("results") or []
            if object_type == "databases":
                return [_database_to_row(d) for d in results]
            return [_page_to_row(p) for p in results]

        if object_type == "database":
            if not database_id:
                raise ValueError(
                    "Notion 'database' object_type requires 'database_id' "
                    "(e.g. {\"object_type\":\"database\",\"database_id\":\"abc\"})."
                )
            url = f"{base}/databases/{database_id}/query"
            body = {"page_size": limit}
            if cursor:
                body["start_cursor"] = cursor
            if filter_obj:
                body["filter"] = filter_obj
            if sorts:
                body["sorts"] = sorts
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.post(url, headers=_auth_headers(config), json=body)
                data = _ok_or_raise(resp)
            return [_database_row_to_flat(p) for p in (data.get("results") or [])]

        if object_type == "page":
            if not page_id:
                raise ValueError(
                    "Notion 'page' object_type requires 'page_id'."
                )
            url = f"{base}/pages/{page_id}"
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_auth_headers(config))
                data = _ok_or_raise(resp)
            return [_page_to_row(data)]

        raise ValueError(f"Unknown Notion object_type: {object_type!r}")

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows_by_object: Dict[str, int] = {}
        for obj in config.get("objects") or []:
            label = obj.get("name") or obj.get("object_type") or "object"
            try:
                payload: Dict[str, Any] = {
                    "object_type": obj.get("object_type") or "users",
                    "limit": int(obj.get("limit") or _DEFAULT_LIMIT),
                }
                if obj.get("database_id"):
                    payload["database_id"] = obj["database_id"]
                if obj.get("page_id"):
                    payload["page_id"] = obj["page_id"]
                if obj.get("filter"):
                    payload["filter"] = obj["filter"]
                rows = await self.execute_query(config, json.dumps(payload))
                rows_by_object[label] = len(rows)
            except Exception as exc:
                logger.warning("Notion sync %s failed: %s", label, exc)
                rows_by_object[label] = 0
        return {"success": True, "rows_by_object": rows_by_object}


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


_COLUMN_DEFS: Dict[str, List[Dict[str, str]]] = {
    "users": [
        {"name": "id"}, {"name": "name"}, {"name": "type"},
        {"name": "email"}, {"name": "avatar_url"},
    ],
    "pages": [
        {"name": "id"}, {"name": "title"}, {"name": "url"},
        {"name": "parent_type"}, {"name": "created_time"},
        {"name": "last_edited_time"}, {"name": "archived"},
    ],
    "search": [
        {"name": "id"}, {"name": "object"}, {"name": "title"},
        {"name": "url"}, {"name": "last_edited_time"},
    ],
    "databases": [
        {"name": "id"}, {"name": "title"}, {"name": "url"},
        {"name": "property_count"}, {"name": "last_edited_time"},
    ],
    "database": [
        {"name": "id"}, {"name": "last_edited_time"}, {"name": "url"},
    ],
}


def _columns_for(object_type: str) -> List[Dict[str, str]]:
    return list(_COLUMN_DEFS.get(object_type, []))


def _ok_or_raise(resp: httpx.Response) -> Dict[str, Any]:
    """Raise on non-2xx, surfacing Notion's structured error message.

    Notion error bodies look like:
    ``{"object":"error","status":401,"code":"unauthorized","message":"..."}``.
    We bubble the ``code`` so the backend's error mapper can translate it.
    """
    if resp.status_code >= 400:
        try:
            err = resp.json()
            code = err.get("code") or err.get("status") or resp.status_code
            msg = err.get("message") or "request failed"
        except Exception:
            code = resp.status_code
            msg = "request failed"
        raise httpx.HTTPStatusError(
            f"Notion API error: {code} — {msg}",
            request=resp.request,
            response=resp,
        )
    return resp.json()


def _normalise_response(data: Any) -> List[Dict[str, Any]]:
    """Best-effort flatten of an arbitrary raw-path response into rows."""
    if isinstance(data, dict):
        if isinstance(data.get("results"), list):
            return data["results"]
        return [data]
    if isinstance(data, list):
        return data
    return [{"value": data}]
