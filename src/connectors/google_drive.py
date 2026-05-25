"""Google Drive connector — lists files so agents can monitor document
folders, exports, or arbitrary drive contents as rows.

Auth: pre-issued OAuth access token (same posture as Google Sheets —
full OAuth flow ships separately).

Config:

    {
        "auth": {"type": "bearer", "access_token": "ya29.a0..."},
        "folders": [                                # optional "tables"
            {"name": "Sales docs", "folder_id": "1AbC..."},
            {"name": "Shared with me", "q": "sharedWithMe and mimeType != 'application/vnd.google-apps.folder'"}
        ]
    }

execute_query:
  - plain string treated as a folder id → lists children
  - JSON {"folder_id": "...", "q": "...", "page_size": N, "fields": "..."}
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_BASE = "https://www.googleapis.com/drive/v3"
_DEFAULT_FIELDS = "files(id,name,mimeType,modifiedTime,size,webViewLink,parents,owners)"


def _headers(config: Dict[str, Any]) -> Dict[str, str]:
    token = ((config.get("auth") or {}).get("access_token")
             or (config.get("auth") or {}).get("token"))
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _file_to_row(f: Dict[str, Any]) -> Dict[str, Any]:
    owners = f.get("owners") or []
    return {
        "id": f.get("id"),
        "name": f.get("name"),
        "mime_type": f.get("mimeType"),
        "modified_at": f.get("modifiedTime"),
        "size_bytes": f.get("size"),
        "link": f.get("webViewLink"),
        "parent_id": (f.get("parents") or [None])[0],
        "owner": owners[0].get("displayName") if owners and isinstance(owners[0], dict) else None,
    }


class GoogleDriveConnector(BaseConnector):
    TIMEOUT = 15.0

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        token = ((config.get("auth") or {}).get("access_token"))
        if not token:
            return False
        url = f"{_BASE}/about?fields=user"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_headers(config))
                return resp.status_code == 200
        except Exception as exc:
            logger.info("GoogleDrive test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        tables: List[Dict[str, Any]] = []
        for f in config.get("folders") or []:
            tables.append({
                "name": f.get("name") or f.get("folder_id") or "folder",
                "kind": "google_drive_folder",
                "columns": [],
                "metadata": {
                    "folder_id": f.get("folder_id") or "",
                    "q": f.get("q") or "",
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        folder_id: Optional[str] = None
        extra_q: Optional[str] = None
        page_size = 50
        fields = _DEFAULT_FIELDS

        if q.startswith("{"):
            try:
                parsed = json.loads(q)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid Google Drive query JSON: {exc}") from exc
            folder_id = parsed.get("folder_id")
            extra_q = parsed.get("q")
            page_size = int(parsed.get("page_size") or 50)
            fields = parsed.get("fields") or _DEFAULT_FIELDS
        elif q:
            folder_id = q

        q_clauses: List[str] = []
        if folder_id:
            q_clauses.append(f"'{folder_id}' in parents")
        if extra_q:
            q_clauses.append(extra_q)
        q_param = " and ".join(q_clauses) if q_clauses else None

        params: Dict[str, Any] = {
            "pageSize": max(1, min(1000, page_size)),
            "fields": fields,
        }
        if q_param:
            params["q"] = q_param

        url = f"{_BASE}/files"
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.get(url, headers=_headers(config), params=params)
            resp.raise_for_status()
            data = resp.json()

        files = data.get("files") if isinstance(data, dict) else None
        if not isinstance(files, list):
            return []
        return [_file_to_row(f) for f in files]

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows_by_folder: Dict[str, int] = {}
        for f in config.get("folders") or []:
            try:
                rows = await self.execute_query(
                    config,
                    json.dumps({
                        "folder_id": f.get("folder_id"),
                        "q": f.get("q"),
                        "page_size": 50,
                    }),
                )
                rows_by_folder[f.get("name") or f.get("folder_id") or "folder"] = len(rows)
            except Exception as exc:
                logger.warning("GoogleDrive sync %s failed: %s", f, exc)
                rows_by_folder[f.get("name") or "folder"] = 0
        return {"success": True, "rows_by_folder": rows_by_folder}
