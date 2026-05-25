"""Salesforce connector.

Real implementation, but with a deliberate scope limit: this PR takes
pre-issued access tokens (`config.auth.access_token` + `instance_url`).
The full OAuth 2.0 authorization-code + refresh-token flow is a
separate concern (needs a UI-level redirect + secret storage) and ships
in a follow-up — we wire the transport + data path first so agents can
already pull data from Salesforce once a token is provisioned.

Config:

    {
        "instance_url": "https://<tenant>.my.salesforce.com",  # required
        "auth": {
            "type": "bearer",
            "access_token": "00D...!AQ...",         # required
            "refresh_token": "5Aep...",             # optional (next PR)
            "client_id": "...",                     # optional (next PR)
            "client_secret": "...",                 # optional (next PR)
        },
        "api_version": "v60.0",                     # optional, default below
        "objects": [                                 # optional — "tables"
            {"name": "Accounts", "object_type": "Account"},
            {"name": "Opportunities", "object_type": "Opportunity"}
        ]
    }

execute_query:
  - string starting with SELECT (case-insensitive) → treated as SOQL
  - JSON {"soql": "SELECT ..."}
  - plain object_type string → auto-generates `SELECT Id, Name FROM {object_type} LIMIT 100`
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_API_VERSION = "v60.0"


def _headers(config: Dict[str, Any]) -> Dict[str, str]:
    auth = config.get("auth") or {}
    token = auth.get("access_token") or auth.get("token")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _api_base(config: Dict[str, Any]) -> str:
    instance = (config.get("instance_url") or "").rstrip("/")
    version = config.get("api_version") or _DEFAULT_API_VERSION
    return f"{instance}/services/data/{version}"


class SalesforceConnector(BaseConnector):
    """Treats Salesforce sObjects as tabular rows via SOQL."""

    TIMEOUT = 15.0

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        if not config.get("instance_url") or not ((config.get("auth") or {}).get("access_token")):
            return False
        # GET /services/data/{v}/ — lists available resources. Cheap,
        # 200 confirms token + instance are wired correctly.
        url = f"{_api_base(config)}/"
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(url, headers=_headers(config))
                return resp.status_code == 200
        except Exception as exc:
            logger.info("Salesforce test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        tables: List[Dict[str, Any]] = []
        # User-declared objects first — predictable + no API call.
        for obj in config.get("objects") or []:
            tables.append({
                "name": obj.get("name") or obj.get("object_type") or "sobject",
                "kind": "salesforce_sobject",
                "columns": [],
                "metadata": {
                    "object_type": obj.get("object_type") or "Account",
                    "type": "sobject",
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        if not config.get("instance_url"):
            raise ValueError("Salesforce connector requires instance_url")
        q = (query or "").strip()
        soql: str

        if q.startswith("{"):
            try:
                parsed = json.loads(q)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid Salesforce query JSON: {exc}") from exc
            soql = parsed.get("soql") or parsed.get("query") or ""
            if not soql:
                raise ValueError("Salesforce query JSON must include 'soql'")
        elif q.upper().startswith("SELECT "):
            soql = q
        elif q:
            # Syntactic sugar: "Account" -> "SELECT Id, Name FROM Account LIMIT 100".
            soql = f"SELECT Id, Name FROM {q} LIMIT 100"
        else:
            raise ValueError("Salesforce execute_query requires SOQL or an object name")

        url = f"{_api_base(config)}/query"
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.get(url, headers=_headers(config), params={"q": soql})
            resp.raise_for_status()
            data = resp.json()

        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list):
            return []
        out: List[Dict[str, Any]] = []
        for rec in records:
            # Strip Salesforce's `attributes` noise.
            clean = {k: v for k, v in rec.items() if k != "attributes"}
            out.append(clean)
        return out

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows_by_object: Dict[str, int] = {}
        for obj in config.get("objects") or []:
            try:
                rows = await self.execute_query(
                    config, obj.get("object_type") or "Account"
                )
                rows_by_object[obj.get("name") or obj.get("object_type") or "sobject"] = len(rows)
            except Exception as exc:
                logger.warning("Salesforce sync %s failed: %s", obj, exc)
                rows_by_object[obj.get("name") or "sobject"] = 0
        return {"success": True, "rows_by_object": rows_by_object}
