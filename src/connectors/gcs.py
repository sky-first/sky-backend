"""Google Cloud Storage connector.

Treats a GCS account as a tabular data source by surfacing buckets and
blobs (objects). Mirrors the S3 connector's read-only stance — exposes
metadata (name, size, content_type, updated, md5_hash, storage_class)
so agents can monitor a prefix the same way they monitor a database
table or a CRM list.

Auth — Service Account JSON (the same shape used by the BigQuery
connector). For convenience we also accept the JSON parsed as a dict.
Config:

    {
        "project_id": "my-project",                    # optional —
                                                       # service account
                                                       # already implies it
        "service_account_json": "{...}" | {...},       # required
        "objects": [
            {"name": "ingest", "object_type": "objects",
             "bucket": "sky-ingest", "prefix": "2026/04/"},
            {"name": "buckets", "object_type": "buckets"}
        ]
    }

execute_query forms accepted:
  - empty string                → defaults to ``buckets``
  - bare object name (``buckets``, ``objects``)
  - JSON ``{"object_type":"objects","bucket":"X","prefix":"Y","limit":100}``

Required IAM roles (read-only):
  - ``roles/storage.objectViewer`` — for ``objects``
  - ``roles/storage.bucketLister``  — for ``buckets``

Read-only — does NOT upload, copy, or delete blobs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 1000  # GCS list_blobs server cap is 1000 per page.


def _import_gcs():
    """Lazy import — keeps registry import clean if the dep is missing."""
    try:
        from google.cloud import storage  # type: ignore
        from google.oauth2 import service_account  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "google-cloud-storage is required for the GCS connector. "
            "Install it with 'pip install google-cloud-storage'."
        ) from exc
    return storage, service_account


def _build_client(config: Dict[str, Any]):
    storage, service_account = _import_gcs()

    sa_raw = config.get("service_account_json") or (config.get("auth") or {}).get("service_account_json")
    credentials = None
    project_id = config.get("project_id")

    if sa_raw:
        sa_info = json.loads(sa_raw) if isinstance(sa_raw, str) else sa_raw
        if not isinstance(sa_info, dict):
            raise ValueError("service_account_json must be a JSON string or dict")
        credentials = service_account.Credentials.from_service_account_info(sa_info)
        project_id = project_id or sa_info.get("project_id")

    return storage.Client(project=project_id, credentials=credentials)


def _bucket_to_row(b: Any) -> Dict[str, Any]:
    """Flatten a google.cloud.storage.Bucket into a flat row."""
    return {
        "name": getattr(b, "name", None),
        "location": getattr(b, "location", None),
        "storage_class": getattr(b, "storage_class", None),
        "created": getattr(b, "time_created", None).isoformat()
            if getattr(b, "time_created", None) else None,
    }


def _blob_to_row(blob: Any, bucket: Optional[str] = None) -> Dict[str, Any]:
    return {
        "bucket": bucket or getattr(blob, "bucket", None) and blob.bucket.name,
        "name": getattr(blob, "name", None),
        "size": getattr(blob, "size", None),
        "content_type": getattr(blob, "content_type", None),
        "updated": getattr(blob, "updated", None).isoformat()
            if getattr(blob, "updated", None) else None,
        "md5_hash": getattr(blob, "md5_hash", None),
        "storage_class": getattr(blob, "storage_class", None),
    }


class GCSConnector(BaseConnector):
    """Google Cloud Storage as a read-only tabular source."""

    TIMEOUT = 15.0

    async def _run(self, fn, *args, **kwargs):
        """google-cloud-storage is synchronous; bridge through a thread.

        Same call pattern as the S3 connector — avoids pulling in
        google-cloud-storage's async fork (gcsfs) just for an
        infrequent connector call.
        """
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """``list_buckets(max_results=1)`` is the cheapest "is this SA good?" call.

        Validates the credentials + project combination in one round
        trip without depending on a specific bucket existing.
        """
        try:
            client = _build_client(config)
            await self._run(lambda: list(client.list_buckets(max_results=1)))
            return True
        except Exception as exc:
            logger.info("GCS test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        tables: List[Dict[str, Any]] = []
        for obj in config.get("objects") or []:
            object_type = obj.get("object_type") or "buckets"
            tables.append({
                "name": obj.get("name") or object_type,
                "kind": "gcs_object",
                "columns": _columns_for(object_type),
                "metadata": {
                    "object_type": object_type,
                    "bucket": obj.get("bucket"),
                    "prefix": obj.get("prefix") or "",
                },
            })
        return {"tables": tables, "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        q = (query or "").strip()

        object_type: str = "buckets"
        bucket: Optional[str] = None
        prefix: str = ""
        limit: int = _DEFAULT_LIMIT

        if q.startswith("{"):
            try:
                parsed = json.loads(q)
                object_type = parsed.get("object_type") or parsed.get("type") or "buckets"
                bucket = parsed.get("bucket")
                prefix = parsed.get("prefix") or ""
                limit = int(parsed.get("limit") or _DEFAULT_LIMIT)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid GCS query JSON: {exc}") from exc
        elif q:
            object_type = q

        # GCS list endpoints cap page size at 1000 server-side.
        limit = max(1, min(1000, limit))
        client = _build_client(config)

        if object_type == "buckets":
            buckets = await self._run(lambda: list(client.list_buckets(max_results=limit)))
            return [_bucket_to_row(b) for b in buckets]

        if object_type == "objects":
            if not bucket:
                raise ValueError(
                    "GCS 'objects' object_type requires 'bucket' "
                    "(e.g. {\"object_type\":\"objects\",\"bucket\":\"my-bucket\"})."
                )
            kwargs: Dict[str, Any] = {"max_results": limit}
            if prefix:
                kwargs["prefix"] = prefix
            blobs = await self._run(lambda: list(client.list_blobs(bucket, **kwargs)))
            return [_blob_to_row(b, bucket=bucket) for b in blobs]

        raise ValueError(f"Unknown GCS object_type: {object_type!r}")

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows_by_object: Dict[str, int] = {}
        for obj in config.get("objects") or []:
            label = obj.get("name") or obj.get("object_type") or "object"
            try:
                payload: Dict[str, Any] = {
                    "object_type": obj.get("object_type") or "buckets",
                    "limit": int(obj.get("limit") or _DEFAULT_LIMIT),
                }
                if obj.get("bucket"):
                    payload["bucket"] = obj["bucket"]
                if obj.get("prefix"):
                    payload["prefix"] = obj["prefix"]
                rows = await self.execute_query(config, json.dumps(payload))
                rows_by_object[label] = len(rows)
            except Exception as exc:
                logger.warning("GCS sync %s failed: %s", label, exc)
                rows_by_object[label] = 0
        return {"success": True, "rows_by_object": rows_by_object}


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


_COLUMN_DEFS: Dict[str, List[Dict[str, str]]] = {
    "buckets": [
        {"name": "name"}, {"name": "location"},
        {"name": "storage_class"}, {"name": "created"},
    ],
    "objects": [
        {"name": "bucket"}, {"name": "name"}, {"name": "size"},
        {"name": "content_type"}, {"name": "updated"},
        {"name": "md5_hash"}, {"name": "storage_class"},
    ],
}


def _columns_for(object_type: str) -> List[Dict[str, str]]:
    return list(_COLUMN_DEFS.get(object_type, []))
