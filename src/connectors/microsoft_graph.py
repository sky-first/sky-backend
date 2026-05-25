"""OneDrive + SharePoint connectors (Microsoft Graph).

Both sit on top of the Graph API, so the HTTP transport is shared. Auth
is a pre-issued Graph access token (Bearer). Full OAuth / Microsoft
identity platform flow ships separately — this PR wires data path first.

OneDriveConnector config:
    {
        "auth": {"type": "bearer", "access_token": "..."},
        "folders": [
            {"name": "Shared sales", "path": "/Sales"},         # relative to /me/drive/root
            {"name": "Reports", "drive_id": "b!x", "path": "/"}, # explicit drive
        ]
    }

SharePointConnector config:
    {
        "auth": {"type": "bearer", "access_token": "..."},
        "site_id": "<tenant>.sharepoint.com,<site-guid>,<web-guid>",  # default
        "sites": [
            {"name": "HR site", "site_id": "...", "path": "/Policies"},
            {"name": "Eng wiki", "site_id": "..."},
        ]
    }

execute_query:
  - plain string → path (e.g. "/Sales") in the default scope
  - JSON {"drive_id": "...", "path": "/..."} (OneDrive)
  - JSON {"site_id": "...", "path": "/..."} (SharePoint)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_GRAPH = "https://graph.microsoft.com/v1.0"


def _headers(config: Dict[str, Any]) -> Dict[str, str]:
    token = ((config.get("auth") or {}).get("access_token")
             or (config.get("auth") or {}).get("token"))
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _item_to_row(item: Dict[str, Any]) -> Dict[str, Any]:
    is_folder = "folder" in item
    is_file = "file" in item
    last = item.get("lastModifiedBy") or {}
    user = (last.get("user") or {}).get("displayName")
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "type": "folder" if is_folder else ("file" if is_file else "other"),
        "size_bytes": item.get("size"),
        "mime_type": (item.get("file") or {}).get("mimeType"),
        "modified_at": item.get("lastModifiedDateTime"),
        "modified_by": user,
        "web_url": item.get("webUrl"),
    }


def _children_path(drive_scope: str, path: str) -> str:
    """Compose the Graph endpoint for listing the children of a path.

    drive_scope is the pre-resolved segment, e.g.
        /me/drive
        /drives/{id}
        /sites/{id}/drive
    """
    p = (path or "").strip()
    if p in ("", "/"):
        return f"{drive_scope}/root/children"
    if not p.startswith("/"):
        p = "/" + p
    # URL-escape colons are not needed; Graph tolerates raw paths here.
    return f"{drive_scope}/root:{p}:/children"


class OneDriveConnector(BaseConnector):
    TIMEOUT = 15.0

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        token = ((config.get("auth") or {}).get("access_token"))
        if not token:
            return False
        # /me works on any user-delegated token; returns 200 with profile.
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(f"{_GRAPH}/me", headers=_headers(config))
                return resp.status_code == 200
        except Exception as exc:
            logger.info("OneDrive test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        tables: List[Dict[str, Any]] = []
        for f in config.get("folders") or []:
            tables.append({
                "name": f.get("name") or f.get("path") or "folder",
                "kind": "onedrive_folder",
                "columns": [],
                "metadata": {
                    "path": f.get("path") or "/",
                    "drive_id": f.get("drive_id") or "",
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        drive_id: Optional[str] = None
        path = ""

        if q.startswith("{"):
            try:
                parsed = json.loads(q)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid OneDrive query JSON: {exc}") from exc
            drive_id = parsed.get("drive_id")
            path = parsed.get("path") or ""
        elif q:
            path = q

        drive_scope = f"/drives/{drive_id}" if drive_id else "/me/drive"
        url = f"{_GRAPH}{_children_path(drive_scope, path)}"

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.get(url, headers=_headers(config))
            resp.raise_for_status()
            data = resp.json()

        items = data.get("value") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        return [_item_to_row(it) for it in items]

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows: Dict[str, int] = {}
        for f in config.get("folders") or []:
            try:
                r = await self.execute_query(
                    config,
                    json.dumps({"drive_id": f.get("drive_id"), "path": f.get("path") or "/"}),
                )
                rows[f.get("name") or f.get("path") or "folder"] = len(r)
            except Exception as exc:
                logger.warning("OneDrive sync %s failed: %s", f, exc)
                rows[f.get("name") or "folder"] = 0
        return {"success": True, "rows_by_folder": rows}


class SharePointConnector(BaseConnector):
    TIMEOUT = 15.0

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        token = ((config.get("auth") or {}).get("access_token"))
        if not token:
            return False
        site_id = config.get("site_id")
        url = f"{_GRAPH}/sites/{site_id}" if site_id else f"{_GRAPH}/sites/root"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_headers(config))
                return resp.status_code == 200
        except Exception as exc:
            logger.info("SharePoint test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        tables: List[Dict[str, Any]] = []
        for s in config.get("sites") or []:
            tables.append({
                "name": s.get("name") or s.get("site_id") or "site",
                "kind": "sharepoint_drive",
                "columns": [],
                "metadata": {
                    "site_id": s.get("site_id") or config.get("site_id") or "",
                    "path": s.get("path") or "/",
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        site_id = config.get("site_id")
        path = ""

        if q.startswith("{"):
            try:
                parsed = json.loads(q)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid SharePoint query JSON: {exc}") from exc
            site_id = parsed.get("site_id") or site_id
            path = parsed.get("path") or ""
        elif q:
            path = q

        if not site_id:
            raise ValueError("SharePoint connector requires site_id (config or query)")

        drive_scope = f"/sites/{site_id}/drive"
        url = f"{_GRAPH}{_children_path(drive_scope, path)}"

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.get(url, headers=_headers(config))
            resp.raise_for_status()
            data = resp.json()

        items = data.get("value") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        return [_item_to_row(it) for it in items]

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows: Dict[str, int] = {}
        for s in config.get("sites") or []:
            try:
                r = await self.execute_query(
                    config,
                    json.dumps({"site_id": s.get("site_id") or config.get("site_id"), "path": s.get("path") or "/"}),
                )
                rows[s.get("name") or s.get("site_id") or "site"] = len(r)
            except Exception as exc:
                logger.warning("SharePoint sync %s failed: %s", s, exc)
                rows[s.get("name") or "site"] = 0
        return {"success": True, "rows_by_site": rows}
