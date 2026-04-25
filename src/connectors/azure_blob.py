"""Azure Blob Storage connector.

Treats an Azure Storage account as a tabular data source by surfacing
containers and blobs. Mirrors the S3/GCS connectors' read-only stance
— exposes metadata (name, size, content_type, last_modified, etag)
so agents can monitor a prefix the same way they monitor a database
table or a CRM list.

Auth — three accepted forms (in order of decreasing privilege):

  1. **Connection string** — Azure's portable credential blob, contains
     account name + key. Most common in dev/test.
  2. **Account name + key** — equivalent to connection string but split.
  3. **SAS token** — pre-signed URL fragment. Time-bounded, scope-bounded.
     Most appropriate for prod multi-tenant where the customer hands us
     a least-privilege URL.

Config:

    {
        # Form 1
        "connection_string": "DefaultEndpointsProtocol=https;...",

        # OR form 2
        "account_name": "skyingest",
        "account_key": "...",

        # OR form 3
        "account_name": "skyingest",
        "sas_token": "?sv=2024-...&se=...&sig=...",

        "objects": [
            {"name": "ingest", "object_type": "blobs",
             "container": "events", "prefix": "2026/04/"},
            {"name": "containers", "object_type": "containers"}
        ]
    }

execute_query forms accepted:
  - empty string                → defaults to ``containers``
  - bare object name (``containers``, ``blobs``)
  - JSON ``{"object_type":"blobs","container":"X","prefix":"Y","limit":100}``

Read-only — does NOT upload, copy, or delete blobs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 1000  # Azure list_blobs page cap.


def _import_azure():
    """Lazy import — keeps registry import clean if the dep is missing."""
    try:
        from azure.storage.blob import BlobServiceClient  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "azure-storage-blob is required for the Azure Blob connector. "
            "Install it with 'pip install azure-storage-blob'."
        ) from exc
    return BlobServiceClient


def _build_client(config: Dict[str, Any]):
    """Construct a BlobServiceClient from one of three accepted auth shapes."""
    BlobServiceClient = _import_azure()
    auth = config.get("auth") or {}

    conn_str = config.get("connection_string") or auth.get("connection_string")
    if conn_str:
        return BlobServiceClient.from_connection_string(conn_str)

    account_name = config.get("account_name") or auth.get("account_name")
    if not account_name:
        raise ValueError(
            "Azure Blob connector requires 'connection_string' OR "
            "'account_name' + ('account_key' or 'sas_token')."
        )

    account_url = f"https://{account_name}.blob.core.windows.net"
    sas_token = config.get("sas_token") or auth.get("sas_token")
    account_key = config.get("account_key") or auth.get("account_key")

    if sas_token:
        # SAS tokens are conventionally provided with or without the
        # leading "?"; the SDK accepts both via account_url querystring.
        token = sas_token.lstrip("?")
        return BlobServiceClient(account_url=f"{account_url}?{token}")

    if account_key:
        return BlobServiceClient(account_url=account_url, credential=account_key)

    raise ValueError(
        "Azure Blob connector requires one of: connection_string, "
        "account_key, or sas_token."
    )


def _container_to_row(c: Any) -> Dict[str, Any]:
    """Flatten an Azure ContainerProperties into a flat row."""
    last_modified = getattr(c, "last_modified", None)
    return {
        "name": getattr(c, "name", None),
        "last_modified": last_modified.isoformat() if last_modified else None,
        "etag": getattr(c, "etag", None),
        "lease_state": getattr(getattr(c, "lease", None), "state", None),
        "public_access": getattr(c, "public_access", None),
    }


def _blob_to_row(b: Any, container: Optional[str] = None) -> Dict[str, Any]:
    last_modified = getattr(b, "last_modified", None)
    return {
        "container": container,
        "name": getattr(b, "name", None),
        "size": getattr(b, "size", None),
        "content_type": getattr(getattr(b, "content_settings", None), "content_type", None),
        "last_modified": last_modified.isoformat() if last_modified else None,
        "etag": getattr(b, "etag", None),
        "blob_tier": getattr(b, "blob_tier", None),
    }


class AzureBlobConnector(BaseConnector):
    """Azure Blob Storage as a read-only tabular source."""

    TIMEOUT = 15.0

    async def _run(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """``list_containers(results_per_page=1)`` is the cheapest probe.

        Validates the credential combination resolves to a usable
        account-level token, without depending on a specific container
        existing.
        """
        try:
            client = _build_client(config)
            await self._run(
                lambda: next(iter(client.list_containers(results_per_page=1)), None)
            )
            return True
        except Exception as exc:
            logger.info("Azure Blob test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        tables: List[Dict[str, Any]] = []
        for obj in config.get("objects") or []:
            object_type = obj.get("object_type") or "containers"
            tables.append({
                "name": obj.get("name") or object_type,
                "kind": "azure_blob_object",
                "columns": _columns_for(object_type),
                "metadata": {
                    "object_type": object_type,
                    "container": obj.get("container"),
                    "prefix": obj.get("prefix") or "",
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        q = (query or "").strip()

        object_type: str = "containers"
        container: Optional[str] = None
        prefix: str = ""
        limit: int = _DEFAULT_LIMIT

        if q.startswith("{"):
            try:
                parsed = json.loads(q)
                object_type = parsed.get("object_type") or parsed.get("type") or "containers"
                container = parsed.get("container")
                prefix = parsed.get("prefix") or ""
                limit = int(parsed.get("limit") or _DEFAULT_LIMIT)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid Azure Blob query JSON: {exc}") from exc
        elif q:
            object_type = q

        # Azure list endpoints page in batches of up to 5000; we stay
        # well under to keep responses snappy in the connector path.
        limit = max(1, min(5000, limit))
        client = _build_client(config)

        if object_type == "containers":
            iterator = await self._run(
                lambda: client.list_containers(results_per_page=limit)
            )
            # results_per_page only sets the page size; we still need to
            # take exactly ``limit`` total to match S3/GCS semantics.
            taken: List[Any] = []
            for c in iterator:
                taken.append(c)
                if len(taken) >= limit:
                    break
            return [_container_to_row(c) for c in taken]

        if object_type == "blobs":
            if not container:
                raise ValueError(
                    "Azure Blob 'blobs' object_type requires 'container' "
                    "(e.g. {\"object_type\":\"blobs\",\"container\":\"my-container\"})."
                )
            container_client = await self._run(
                lambda: client.get_container_client(container)
            )
            kwargs: Dict[str, Any] = {"results_per_page": limit}
            if prefix:
                kwargs["name_starts_with"] = prefix
            iterator = await self._run(lambda: container_client.list_blobs(**kwargs))
            taken = []
            for b in iterator:
                taken.append(b)
                if len(taken) >= limit:
                    break
            return [_blob_to_row(b, container=container) for b in taken]

        raise ValueError(f"Unknown Azure Blob object_type: {object_type!r}")

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows_by_object: Dict[str, int] = {}
        for obj in config.get("objects") or []:
            label = obj.get("name") or obj.get("object_type") or "object"
            try:
                payload: Dict[str, Any] = {
                    "object_type": obj.get("object_type") or "containers",
                    "limit": int(obj.get("limit") or _DEFAULT_LIMIT),
                }
                if obj.get("container"):
                    payload["container"] = obj["container"]
                if obj.get("prefix"):
                    payload["prefix"] = obj["prefix"]
                rows = await self.execute_query(config, json.dumps(payload))
                rows_by_object[label] = len(rows)
            except Exception as exc:
                logger.warning("Azure Blob sync %s failed: %s", label, exc)
                rows_by_object[label] = 0
        return {"success": True, "rows_by_object": rows_by_object}


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


_COLUMN_DEFS: Dict[str, List[Dict[str, str]]] = {
    "containers": [
        {"name": "name"}, {"name": "last_modified"}, {"name": "etag"},
        {"name": "lease_state"}, {"name": "public_access"},
    ],
    "blobs": [
        {"name": "container"}, {"name": "name"}, {"name": "size"},
        {"name": "content_type"}, {"name": "last_modified"},
        {"name": "etag"}, {"name": "blob_tier"},
    ],
}


def _columns_for(object_type: str) -> List[Dict[str, str]]:
    return list(_COLUMN_DEFS.get(object_type, []))
