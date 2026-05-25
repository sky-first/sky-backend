"""Amazon S3 connector.

Treats an S3 account as a tabular data source by surfacing buckets and
objects. The connector itself does not download object bodies — it
exposes metadata (key, size, last_modified, storage_class, etag) so
agents can monitor a prefix the same way they monitor a database table
or a CRM list.

Auth — IAM access key pair (the same pair you'd put in ``~/.aws``).
Config:

    {
        "region_name": "us-east-1",                    # default
        "endpoint_url": "https://s3.amazonaws.com",    # optional — set for
                                                       # MinIO / R2 / etc.
        "auth": {
            "type": "aws_keys",
            "aws_access_key_id": "AKIA...",
            "aws_secret_access_key": "..."
        },
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

Required IAM actions (read-only):
  - ``s3:ListAllMyBuckets`` — for ``buckets``
  - ``s3:ListBucket``       — for ``objects``
  - ``s3:GetBucketLocation``— for ``test_connection`` head_bucket fallback

The connector is read-only — it does NOT upload, copy or delete
objects.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_REGION = "us-east-1"
_DEFAULT_LIMIT = 1000  # boto3 cap per ListObjectsV2 page


def _build_client(config: Dict[str, Any]):
    """Construct a boto3 S3 client from the connector config.

    Imported lazily so the connector module loads cleanly even on
    deploys where boto3 is missing (e.g. minimal worker images). The
    error surface is then the user's first method call, not an import
    failure at registry time.
    """
    import boto3  # noqa: WPS433  (intentional lazy import)
    from botocore.config import Config as _BotoCfg

    auth = config.get("auth") or {}
    return boto3.client(
        "s3",
        aws_access_key_id=auth.get("aws_access_key_id") or auth.get("access_key_id"),
        aws_secret_access_key=auth.get("aws_secret_access_key") or auth.get("secret_access_key"),
        region_name=config.get("region_name") or auth.get("region_name") or _DEFAULT_REGION,
        endpoint_url=config.get("endpoint_url"),
        config=_BotoCfg(retries={"max_attempts": 2, "mode": "standard"}),
    )


def _bucket_to_row(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": b.get("Name"),
        "creation_date": b.get("CreationDate").isoformat() if b.get("CreationDate") else None,
    }


def _object_to_row(o: Dict[str, Any], bucket: Optional[str] = None) -> Dict[str, Any]:
    return {
        "bucket": bucket,
        "key": o.get("Key"),
        "size": o.get("Size"),
        "last_modified": o.get("LastModified").isoformat() if o.get("LastModified") else None,
        "storage_class": o.get("StorageClass"),
        "etag": (o.get("ETag") or "").strip('"'),
    }


class S3Connector(BaseConnector):
    """Amazon S3 as a read-only tabular source.

    Auth: IAM access key pair (passed via config — never read from
    ``~/.aws`` to keep multi-tenant isolation explicit).
    """

    TIMEOUT = 15.0

    async def _run(self, fn, *args, **kwargs):
        """boto3 is synchronous; bounce blocking calls through a thread.

        We use ``asyncio.to_thread`` rather than aioboto3 to keep the
        dependency footprint small — the connector path is low-volume
        compared to the FastAPI request hot path, so the thread cost
        is invisible.
        """
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """``list_buckets`` is the cheapest "is this key good?" call.

        ``head_bucket`` would be more specific but requires a bucket
        name; ``list_buckets`` always works for a valid IAM principal
        with ``s3:ListAllMyBuckets``.
        """
        try:
            client = _build_client(config)
            await self._run(client.list_buckets)
            return True
        except Exception as exc:
            logger.info("S3 test_connection failed: %s", exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        tables: List[Dict[str, Any]] = []
        for obj in config.get("objects") or []:
            object_type = obj.get("object_type") or "buckets"
            tables.append({
                "name": obj.get("name") or object_type,
                "kind": "s3_object",
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
        cursor: Optional[str] = None

        if q.startswith("{"):
            try:
                parsed = json.loads(q)
                object_type = parsed.get("object_type") or parsed.get("type") or "buckets"
                bucket = parsed.get("bucket")
                prefix = parsed.get("prefix") or ""
                limit = int(parsed.get("limit") or _DEFAULT_LIMIT)
                cursor = parsed.get("cursor")
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid S3 query JSON: {exc}") from exc
        elif q:
            object_type = q

        # ListObjectsV2 caps MaxKeys at 1000 server-side.
        limit = max(1, min(1000, limit))
        client = _build_client(config)

        if object_type == "buckets":
            data = await self._run(client.list_buckets)
            return [_bucket_to_row(b) for b in (data.get("Buckets") or [])]

        if object_type == "objects":
            if not bucket:
                raise ValueError(
                    "S3 'objects' object_type requires 'bucket' "
                    "(e.g. {\"object_type\":\"objects\",\"bucket\":\"my-bucket\"})."
                )
            kwargs: Dict[str, Any] = {"Bucket": bucket, "MaxKeys": limit}
            if prefix:
                kwargs["Prefix"] = prefix
            if cursor:
                kwargs["ContinuationToken"] = cursor
            data = await self._run(lambda: client.list_objects_v2(**kwargs))
            return [_object_to_row(o, bucket=bucket) for o in (data.get("Contents") or [])]

        raise ValueError(f"Unknown S3 object_type: {object_type!r}")

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
                logger.warning("S3 sync %s failed: %s", label, exc)
                rows_by_object[label] = 0
        return {"success": True, "rows_by_object": rows_by_object}


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


_COLUMN_DEFS: Dict[str, List[Dict[str, str]]] = {
    "buckets": [
        {"name": "name"}, {"name": "creation_date"},
    ],
    "objects": [
        {"name": "bucket"}, {"name": "key"}, {"name": "size"},
        {"name": "last_modified"}, {"name": "storage_class"}, {"name": "etag"},
    ],
}


def _columns_for(object_type: str) -> List[Dict[str, str]]:
    return list(_COLUMN_DEFS.get(object_type, []))
