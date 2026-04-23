"""Dropbox connector.

Auth: Dropbox access token (OAuth Bearer or a long-lived access token
with the right scopes). Config:

    {
        "auth": {"type": "bearer", "access_token": "sl.B..."},
        "folders": [
            {"name": "Shared sales", "path": "/Sales"},
            {"name": "Archive search", "path": "/Archive", "recursive": True}
        ]
    }

execute_query:
  - plain string → treated as path prefix (`""` for root)
  - JSON {"path": "...", "recursive": bool, "limit": N}
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_LIST_FOLDER = "https://api.dropboxapi.com/2/files/list_folder"
_GET_CURRENT_ACCOUNT = "https://api.dropboxapi.com/2/users/get_current_account"


def _headers(config: Dict[str, Any]) -> Dict[str, str]:
    token = ((config.get("auth") or {}).get("access_token")
             or (config.get("auth") or {}).get("token"))
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _entry_to_row(e: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": e.get("id"),
        "name": e.get("name"),
        "path": e.get("path_display") or e.get("path_lower"),
        "type": e.get(".tag"),
        "size_bytes": e.get("size"),
        "modified_at": e.get("server_modified") or e.get("client_modified"),
        "is_downloadable": e.get("is_downloadable"),
    }


class DropboxConnector(BaseConnector):
    TIMEOUT = 15.0

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        token = ((config.get("auth") or {}).get("access_token"))
        if not token:
            return False
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                # Dropbox's get_current_account: POST with no body is fine.
                resp = await client.post(_GET_CURRENT_ACCOUNT, headers={
                    "Authorization": f"Bearer {token}",
                })
                return resp.status_code == 200
        except Exception as exc:
            logger.info("Dropbox test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        tables: List[Dict[str, Any]] = []
        for f in config.get("folders") or []:
            tables.append({
                "name": f.get("name") or f.get("path") or "folder",
                "kind": "dropbox_folder",
                "columns": [],
                "metadata": {
                    "path": f.get("path") or "",
                    "recursive": bool(f.get("recursive", False)),
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        path = ""
        recursive = False
        limit = 200

        if q.startswith("{"):
            try:
                parsed = json.loads(q)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid Dropbox query JSON: {exc}") from exc
            path = parsed.get("path", "")
            recursive = bool(parsed.get("recursive", False))
            limit = int(parsed.get("limit") or 200)
        elif q:
            # plain path — caller may pass "/Sales" or empty for root.
            path = q

        # Dropbox requires empty-string for root, not "/".
        if path == "/":
            path = ""

        body = {"path": path, "recursive": recursive, "limit": max(1, min(2000, limit))}
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(_LIST_FOLDER, headers=_headers(config), json=body)
            resp.raise_for_status()
            data = resp.json()

        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            return []
        return [_entry_to_row(e) for e in entries]

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows_by_folder: Dict[str, int] = {}
        for f in config.get("folders") or []:
            try:
                rows = await self.execute_query(
                    config,
                    json.dumps({
                        "path": f.get("path") or "",
                        "recursive": bool(f.get("recursive", False)),
                        "limit": 200,
                    }),
                )
                rows_by_folder[f.get("name") or f.get("path") or "folder"] = len(rows)
            except Exception as exc:
                logger.warning("Dropbox sync %s failed: %s", f, exc)
                rows_by_folder[f.get("name") or "folder"] = 0
        return {"success": True, "rows_by_folder": rows_by_folder}
