"""Azure Blob Storage helper.

Production: uses azure-storage-blob + Managed Identity (implemented by infra colleague).
Development fallback: saves/reads from local `uploads/knowledge/` directory so the full
upload flow works without any Azure credentials.
"""

import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

from src.config.settings import settings

_USE_LOCAL = getattr(settings, "AZURE_STORAGE_ACCOUNT_NAME", "") == ""
_LOCAL_BASE = Path("uploads/knowledge")


def _local_path(blob_path: str) -> Path:
    return _LOCAL_BASE / blob_path


# ── Public interface (contract with knowledge_service.py) ─────────────────────

def generate_upload_sas_url(
    blob_path: str,
    content_type: str,
    max_size_bytes: int,
    ttl_seconds: int = 600,
) -> dict:
    """Return {url, expires_at, blob_path} for a direct PUT upload."""
    if _USE_LOCAL:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        # Local dev: the frontend will POST to our own /api/v1/knowledge/local-upload
        # endpoint instead of PUT-ing to Azure directly.
        base_url = getattr(settings, "BACKEND_BASE_URL", "http://localhost:8000")
        token = secrets.token_urlsafe(32)
        url = f"{base_url}/api/v1/knowledge/local-upload/{blob_path}?token={token}"
        return {"url": url, "expires_at": expires_at, "blob_path": blob_path}

    # ── Azure path (active when AZURE_STORAGE_ACCOUNT_NAME is set) ────────────
    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import (
            BlobSasPermissions,
            BlobServiceClient,
            generate_blob_sas,
        )

        account_name = settings.AZURE_STORAGE_ACCOUNT_NAME
        container = settings.AZURE_STORAGE_CONTAINER_RAW
        credential = DefaultAzureCredential()
        client = BlobServiceClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            credential=credential,
        )
        expiry = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=container,
            blob_name=blob_path,
            account_key=None,
            user_delegation_key=client.get_user_delegation_key(
                datetime.now(timezone.utc),
                expiry,
            ),
            permission=BlobSasPermissions(write=True, create=True),
            expiry=expiry,
            content_type=content_type,
        )
        url = f"https://{account_name}.blob.core.windows.net/{container}/{blob_path}?{sas_token}"
        return {"url": url, "expires_at": expiry, "blob_path": blob_path}
    except Exception as exc:
        raise RuntimeError(f"Azure SAS generation failed: {exc}") from exc


def generate_download_sas_url(blob_path: str, ttl_seconds: int = 300) -> str:
    """Return a read-only signed URL for file preview/download."""
    if _USE_LOCAL:
        base_url = getattr(settings, "BACKEND_BASE_URL", "http://localhost:8000")
        return f"{base_url}/api/v1/knowledge/local-download/{blob_path}"

    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas

        account_name = settings.AZURE_STORAGE_ACCOUNT_NAME
        container = settings.AZURE_STORAGE_CONTAINER_RAW
        credential = DefaultAzureCredential()
        client = BlobServiceClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            credential=credential,
        )
        expiry = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=container,
            blob_name=blob_path,
            account_key=None,
            user_delegation_key=client.get_user_delegation_key(datetime.now(timezone.utc), expiry),
            permission=BlobSasPermissions(read=True),
            expiry=expiry,
        )
        return f"https://{account_name}.blob.core.windows.net/{container}/{blob_path}?{sas_token}"
    except Exception as exc:
        raise RuntimeError(f"Azure SAS generation failed: {exc}") from exc


def delete_blob(blob_path: str) -> None:
    """Soft-delete blob (Azure 30-day retention) or remove local file."""
    if _USE_LOCAL:
        p = _local_path(blob_path)
        if p.exists():
            p.unlink()
        return

    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        account_name = settings.AZURE_STORAGE_ACCOUNT_NAME
        container = settings.AZURE_STORAGE_CONTAINER_RAW
        client = BlobServiceClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            credential=DefaultAzureCredential(),
        )
        client.get_blob_client(container=container, blob=blob_path).delete_blob(
            delete_snapshots="include"
        )
    except Exception:
        pass  # Soft delete — log but don't crash


async def download_blob_stream(blob_path: str) -> AsyncIterator[bytes]:
    """Stream blob bytes for Celery worker (avoids full in-memory load)."""
    if _USE_LOCAL:
        p = _local_path(blob_path)
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                yield chunk
        return

    from azure.identity import DefaultAzureCredential
    from azure.storage.blob.aio import BlobServiceClient as AsyncBlobServiceClient

    account_name = settings.AZURE_STORAGE_ACCOUNT_NAME
    container = settings.AZURE_STORAGE_CONTAINER_RAW
    async with AsyncBlobServiceClient(
        account_url=f"https://{account_name}.blob.core.windows.net",
        credential=DefaultAzureCredential(),
    ) as client:
        stream = await client.get_blob_client(container=container, blob=blob_path).download_blob()
        async for chunk in stream.chunks():
            yield chunk


def save_local_blob(blob_path: str, data: bytes) -> None:
    """Write bytes to local storage (used by the local-upload endpoint in dev)."""
    dest = _local_path(blob_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def make_blob_path(user_id: str, scope: str, scope_id: str, filename: str) -> str:
    """Generate a deterministic, safe blob path."""
    ext = Path(filename).suffix.lower()
    unique = uuid.uuid4().hex
    return f"{scope}/{scope_id}/{user_id}/{unique}{ext}"
