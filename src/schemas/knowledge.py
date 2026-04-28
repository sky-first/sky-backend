"""Knowledge Library — Pydantic request/response schemas."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Enums as literals ──────────────────────────────────────────────────────────

KnowledgeScope = str  # "personal" | "crew" | "space"
FileStatus = str      # "pending" | "processing" | "ready" | "error"


# ── Requests ───────────────────────────────────────────────────────────────────

class UploadUrlRequest(BaseModel):
    filename: str
    mime_type: str
    size_bytes: int = Field(gt=0)
    scope: KnowledgeScope
    scope_id: Optional[UUID] = None  # required for crew/space, null for personal


class ConfirmUploadRequest(BaseModel):
    sha256_hash: Optional[str] = None


# ── Responses ─────────────────────────────────────────────────────────────────

class UploadUrlResponse(BaseModel):
    file_id: UUID
    upload_url: str      # SAS URL (Azure) or local endpoint
    expires_at: datetime


class KnowledgeFileResponse(BaseModel):
    id: UUID
    original_name: str
    mime_type: str
    size_bytes: int
    scope: str
    scope_id: Optional[UUID]
    status: FileStatus
    processing_error: Optional[str]
    chunks_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeFileListResponse(BaseModel):
    items: List[KnowledgeFileResponse]
    total: int
    skip: int
    limit: int


class QuotaResponse(BaseModel):
    scope: str
    scope_id: Optional[UUID]
    bytes_used: int
    files_count: int
    bytes_limit: int
    files_limit: int
    percent_used: float


class MentionSearchItem(BaseModel):
    id: UUID
    original_name: str
    mime_type: str
    scope: str

    model_config = {"from_attributes": True}


class PreviewUrlResponse(BaseModel):
    url: str
    expires_at: datetime
