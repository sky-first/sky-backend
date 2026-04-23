"""REST API connector.

First real non-SQL data source (Bug 5). Lets the user register a
generic HTTP endpoint as a "connection" so the rest of the platform
(agents, chat, dashboards) can treat it the same way it treats a
database.

Contract:
    config = {
        "base_url": "https://api.example.com",
        "headers": { "Authorization": "Bearer ..." },   # optional
        "auth": { "type": "bearer" | "basic" | "apikey" | "none",
                  "token": "...",          # bearer / apikey
                  "username": "...",       # basic
                  "password": "...",       # basic
                  "header_name": "X-API-Key" },  # apikey
        "endpoints": [
            { "name": "orders", "path": "/orders", "method": "GET" }
        ]   # optional — acts as the "tables" list
    }

    execute_query(config, query) — ``query`` is a JSON-encoded dict
    ``{"path": "/orders", "method": "GET", "params": {...}, "body": {...}}``
    or a plain path string. Returns a list of dicts (normalised from
    the JSON response).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT = 15.0


def _build_auth_headers(config: Dict[str, Any]) -> Dict[str, str]:
    """Normalise the auth config into a request header dict."""
    headers: Dict[str, str] = dict(config.get("headers") or {})
    auth = config.get("auth") or {}
    atype = (auth.get("type") or "none").lower()
    if atype == "bearer" and auth.get("token"):
        headers["Authorization"] = f"Bearer {auth['token']}"
    elif atype == "apikey" and auth.get("token"):
        header_name = auth.get("header_name") or "X-API-Key"
        headers[header_name] = auth["token"]
    # basic auth is handled via httpx's `auth` arg, not headers — see
    # _request() below.
    return headers


def _basic_auth_tuple(config: Dict[str, Any]) -> Optional[tuple[str, str]]:
    auth = config.get("auth") or {}
    if (auth.get("type") or "").lower() == "basic" and auth.get("username"):
        return (auth["username"], auth.get("password") or "")
    return None


async def _request(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    basic: Optional[tuple[str, str]],
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.request(
            method.upper(),
            url,
            headers=headers,
            auth=basic,
            params=params,
            json=body if body is not None else None,
        )


class RestAPIConnector(BaseConnector):
    """Treat an HTTP endpoint like a data source."""

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        base_url = (config.get("base_url") or "").rstrip("/")
        if not base_url:
            return False
        try:
            resp = await _request(
                "GET",
                base_url,
                headers=_build_auth_headers(config),
                basic=_basic_auth_tuple(config),
            )
            # 2xx / 3xx / even 401 all mean "reachable" — we don't
            # require 200 because many API roots redirect or require
            # auth. 5xx is what we treat as "server is sick".
            return resp.status_code < 500
        except Exception as exc:
            logger.info("rest_api test_connection failed for %s: %s", base_url, exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Expose user-declared endpoints as "tables".

        We don't crawl the API — most aren't OpenAPI-typed and probing
        is brittle. The user declares endpoints at registration time;
        the RAG treats each endpoint as a table-like artifact so agents
        can pick specific ones via DataSourcePicker.
        """
        endpoints = config.get("endpoints") or []
        tables: List[Dict[str, Any]] = []
        for ep in endpoints:
            name = ep.get("name") or ep.get("path") or "endpoint"
            tables.append({
                "name": name,
                "columns": [],  # unknown until first response; RAG will learn.
                "kind": "rest_endpoint",
                "metadata": {
                    "path": ep.get("path") or "/",
                    "method": (ep.get("method") or "GET").upper(),
                    "description": ep.get("description") or "",
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        """Run the query.

        `query` may be:
          - a plain path string ("/orders")
          - a JSON string describing method / path / params / body
        The response is normalised to a list of dicts. Arrays pass
        through; single objects become a 1-element list; non-JSON
        responses become [{"text": "..."}] so downstream code always
        sees a tabular shape.
        """
        base_url = (config.get("base_url") or "").rstrip("/")
        if not base_url:
            raise ValueError("REST API connector requires base_url")

        method = "GET"
        path = ""
        params: Optional[Dict[str, Any]] = None
        body: Optional[Dict[str, Any]] = None

        q = (query or "").strip()
        if q.startswith("{"):
            try:
                parsed = json.loads(q)
                method = (parsed.get("method") or "GET").upper()
                path = parsed.get("path") or ""
                params = parsed.get("params")
                body = parsed.get("body")
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid REST query JSON: {exc}") from exc
        else:
            path = q

        url = f"{base_url}{path if path.startswith('/') else '/' + path}" if path else base_url

        resp = await _request(
            method,
            url,
            headers=_build_auth_headers(config),
            basic=_basic_auth_tuple(config),
            params=params,
            body=body,
        )
        resp.raise_for_status()

        content_type = (resp.headers.get("content-type") or "").lower()
        if "application/json" not in content_type:
            return [{"text": resp.text[:2000]}]

        data = resp.json()
        if isinstance(data, list):
            # Ensure every item is a dict-like row; wrap scalars.
            return [item if isinstance(item, dict) else {"value": item} for item in data]
        if isinstance(data, dict):
            return [data]
        return [{"value": data}]

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """For APIs, sync == ping every declared endpoint and surface
        row counts. Keeps the same contract as SQL connectors so the
        scheduler doesn't need to special-case REST."""
        rows_by_endpoint: Dict[str, int] = {}
        for ep in config.get("endpoints") or []:
            try:
                result = await self.execute_query(config, ep.get("path") or "/")
                rows_by_endpoint[ep.get("name") or ep.get("path") or "endpoint"] = len(result)
            except Exception as exc:
                logger.warning("REST sync — endpoint %s failed: %s", ep, exc)
                rows_by_endpoint[ep.get("name") or "endpoint"] = 0
        return {"success": True, "rows_by_endpoint": rows_by_endpoint}
