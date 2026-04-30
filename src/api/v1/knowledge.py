"""Knowledge Library API — /api/v1/knowledge."""

from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.azure.blob_helper import save_local_blob
from src.core.scope_guard import assert_not_personal_scope
from src.models.user import User
from src.schemas.knowledge import (
    ConfirmUploadRequest,
    KnowledgeFileListResponse,
    KnowledgeFileResponse,
    MentionSearchItem,
    PreviewUrlResponse,
    QuotaResponse,
    UploadUrlRequest,
    UploadUrlResponse,
)
from src.services.knowledge_service import KnowledgeService
from src.services.quota_service import QuotaService

router = APIRouter()


def _svc(db: AsyncSession) -> KnowledgeService:
    return KnowledgeService(db)


# ── Upload flow ────────────────────────────────────────────────────────────────

@router.post("/upload-url", response_model=UploadUrlResponse)
async def request_upload_url(
    body: UploadUrlRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UploadUrlResponse:
    """Pre-flight: validate quota, create DB record, return signed upload URL."""
    # Personal context is read-only — uploads must target a Space/Crew.
    assert_not_personal_scope(body.scope)
    return await _svc(db).request_upload_url(
        user=current_user,
        filename=body.filename,
        mime_type=body.mime_type,
        size_bytes=body.size_bytes,
        scope=body.scope,
        scope_id=body.scope_id,
    )


@router.post("/{file_id}/confirm", response_model=KnowledgeFileResponse)
async def confirm_upload(
    file_id: UUID,
    body: ConfirmUploadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeFileResponse:
    """Called after the browser PUT to Azure. Enqueues Celery processing."""
    return await _svc(db).confirm_upload(
        user=current_user,
        file_id=file_id,
        sha256_hash=body.sha256_hash,
    )


# ── Local dev upload endpoint (replaces Azure SAS PUT in dev) ─────────────────
# These endpoints are ONLY active when AZURE_STORAGE_ACCOUNT_NAME is unset.
# In production they return 404 because Azure SAS URLs are used instead.

from src.azure.blob_helper import _USE_LOCAL  # re-import flag for guard


def _assert_local_mode() -> None:
    if not _USE_LOCAL:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")


@router.put("/local-upload/{blob_path:path}")
async def local_upload(
    blob_path: str,
    request: Request,
) -> Response:
    """Dev-only: receive raw bytes and store locally (mimics Azure SAS PUT)."""
    _assert_local_mode()
    data = await request.body()
    save_local_blob(blob_path, data)
    return Response(status_code=201)


@router.get("/local-download/{blob_path:path}")
async def local_download(blob_path: str) -> Response:
    """Dev-only: serve local blob for preview."""
    _assert_local_mode()
    from src.azure.blob_helper import _local_path
    p = _local_path(blob_path)
    if not p.exists():
        from src.core.exceptions import NotFoundError
        raise NotFoundError("Blob not found.")
    return Response(content=p.read_bytes(), media_type="application/octet-stream")


# ── Read ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=KnowledgeFileListResponse)
async def list_files(
    scope: str = Query(..., description="personal | crew | space"),
    scope_id: Optional[UUID] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeFileListResponse:
    return await _svc(db).list_files(
        user=current_user,
        scope=scope,
        scope_id=scope_id,
        skip=skip,
        limit=limit,
    )


@router.get("/quota", response_model=QuotaResponse)
async def get_quota(
    scope: str = Query(...),
    scope_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> QuotaResponse:
    effective_scope_id = scope_id if scope != "personal" else current_user.id
    return await QuotaService(db).get_quota(scope, effective_scope_id)


@router.get("/mention-search", response_model=list[MentionSearchItem])
async def mention_search(
    q: str = Query(..., min_length=1),
    scope: str = Query(...),
    scope_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[MentionSearchItem]:
    return await _svc(db).mention_search(
        user=current_user,
        query=q,
        scope=scope,
        scope_id=scope_id,
    )


@router.get("/{file_id}", response_model=KnowledgeFileResponse)
async def get_file(
    file_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeFileResponse:
    return await _svc(db).get_file(user=current_user, file_id=file_id)


@router.get("/{file_id}/preview", response_model=PreviewUrlResponse)
async def get_preview_url(
    file_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PreviewUrlResponse:
    return await _svc(db).get_preview_url(user=current_user, file_id=file_id)


# ── Mutate ────────────────────────────────────────────────────────────────────

@router.delete("/{file_id}", status_code=204)
async def delete_file(
    file_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await _svc(db).delete_file(user=current_user, file_id=file_id)


@router.post("/{file_id}/reprocess", response_model=KnowledgeFileResponse)
async def reprocess_file(
    file_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeFileResponse:
    return await _svc(db).reprocess_file(user=current_user, file_id=file_id)


@router.post("/{file_id}/approve", response_model=KnowledgeFileResponse)
async def approve_file(
    file_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeFileResponse:
    """Commander approves a navigator-uploaded file and triggers processing."""
    return await _svc(db).approve_upload(user=current_user, file_id=file_id)
