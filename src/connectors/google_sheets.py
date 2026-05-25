"""Google Sheets connector — "arquivos online" per Bug 5.

Reads a sheet's values via the Google Sheets v4 API. Auth is a
pre-issued OAuth access token (same posture as the Salesforce
connector — full OAuth flow ships separately).

Config:

    {
        "auth": {
            "type": "bearer",
            "access_token": "ya29.a0Ae...",
        },
        "spreadsheet_id": "1Abc…",                   # optional default
        "sheets": [                                   # optional "tables"
            {"name": "orders", "spreadsheet_id": "1Abc", "range": "Orders!A1:Z"},
            {"name": "leads",  "spreadsheet_id": "2Def", "range": "Leads!A1:Z"}
        ]
    }

execute_query:
  - plain string treated as "<spreadsheet_id>!<range>" or just "<range>"
    (uses config.spreadsheet_id)
  - JSON {"spreadsheet_id": "...", "range": "..."}
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


def _headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    token = auth.get("access_token") or auth.get("token")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _values_to_rows(values: List[List[Any]]) -> List[Dict[str, Any]]:
    """First row = headers; each subsequent row is a dict keyed by them.
    When rows are shorter than headers, missing cells become empty strings.
    """
    if not values:
        return []
    headers = [str(h) for h in (values[0] or [])]
    rows: List[Dict[str, Any]] = []
    for raw in values[1:]:
        row: Dict[str, Any] = {}
        for i, h in enumerate(headers):
            row[h] = raw[i] if i < len(raw) else ""
        rows.append(row)
    return rows


class GoogleSheetsConnector(BaseConnector):
    TIMEOUT = 15.0

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        auth = config.get("auth") or {}
        if not auth.get("access_token"):
            return False
        sid = config.get("spreadsheet_id")
        if not sid:
            # No sheet provided — probe the token against the Drive
            # "about" endpoint instead (needs drive.readonly scope).
            url = "https://www.googleapis.com/drive/v3/about?fields=user"
            try:
                async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                    resp = await client.get(url, headers=_headers(config))
                    return resp.status_code == 200
            except Exception as exc:
                logger.info("GoogleSheets probe failed: %s", exc)
                return False
        url = f"{_SHEETS_BASE}/{sid}"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_headers(config))
                return resp.status_code == 200
        except Exception as exc:
            logger.info("GoogleSheets test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        tables: List[Dict[str, Any]] = []
        for sheet in config.get("sheets") or []:
            tables.append({
                "name": sheet.get("name") or sheet.get("range") or "sheet",
                "kind": "google_sheets_range",
                "columns": [],
                "metadata": {
                    "spreadsheet_id": sheet.get("spreadsheet_id") or config.get("spreadsheet_id") or "",
                    "range": sheet.get("range") or "",
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        default_sid = config.get("spreadsheet_id")
        q = (query or "").strip()

        spreadsheet_id = default_sid
        cell_range: str = ""

        if q.startswith("{"):
            try:
                parsed = json.loads(q)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid Google Sheets query JSON: {exc}") from exc
            spreadsheet_id = parsed.get("spreadsheet_id") or default_sid
            cell_range = parsed.get("range") or ""
        elif "!" in q:
            # "<spreadsheet_id>!<range>" — a caller-specified override.
            sheet_part, sep, r = q.partition("!")
            if sep and r and sheet_part:
                # Heuristic: if sheet_part looks like a Google sheet id
                # (no space, 40+ chars) use it; otherwise it's a tab
                # name within the default sheet.
                if len(sheet_part) > 30 and " " not in sheet_part:
                    spreadsheet_id = sheet_part
                    cell_range = r
                else:
                    cell_range = q
        elif q:
            cell_range = q

        if not spreadsheet_id:
            raise ValueError("Google Sheets connector requires spreadsheet_id")
        if not cell_range:
            raise ValueError("Google Sheets execute_query requires a cell range")

        url = f"{_SHEETS_BASE}/{spreadsheet_id}/values/{cell_range}"
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.get(url, headers=_headers(config))
            resp.raise_for_status()
            data = resp.json()

        values = data.get("values") or []
        return _values_to_rows(values)

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows_by_sheet: Dict[str, int] = {}
        for sheet in config.get("sheets") or []:
            try:
                rows = await self.execute_query(
                    config,
                    json.dumps({
                        "spreadsheet_id": sheet.get("spreadsheet_id") or config.get("spreadsheet_id"),
                        "range": sheet.get("range") or "",
                    }),
                )
                rows_by_sheet[sheet.get("name") or "sheet"] = len(rows)
            except Exception as exc:
                logger.warning("GoogleSheets sync %s failed: %s", sheet, exc)
                rows_by_sheet[sheet.get("name") or "sheet"] = 0
        return {"success": True, "rows_by_sheet": rows_by_sheet}
