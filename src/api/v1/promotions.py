"""Knowledge promotion endpoints — Phase 4.

  POST   /api/v1/metrics/{id}/promote        — enqueue a promotion
  POST   /api/v1/promotion-requests/{id}/approve
  POST   /api/v1/promotion-requests/{id}/reject
  GET    /api/v1/promotion-requests/{id}     — request + items + conflicts
  POST   /api/v1/knowledge-conflicts/{id}/resolve
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.promotion import KnowledgeConflict, PromotionRequest
from src.models.user import User
from src.services.promotion_service import PromotionService

metric_router = APIRouter()
request_router = APIRouter()
conflict_router = APIRouter()


class PromoteRequest(BaseModel):
    target_scope: str
    target_scope_id: Optional[UUID] = None
    note: Optional[str] = None


class ConflictResponse(BaseModel):
    id: UUID
    proposed_entity_id: UUID
    canonical_entity_id: UUID
    similarity: float
    reason: Optional[str]
    decision: Optional[str]


class PromotionResponse(BaseModel):
    id: UUID
    requester_user_id: Optional[UUID]
    target_scope: str
    target_scope_id: Optional[UUID]
    status: str
    note: Optional[str]
    conflicts: List[ConflictResponse] = []


def _conflict(c: KnowledgeConflict) -> ConflictResponse:
    return ConflictResponse(
        id=c.id,
        proposed_entity_id=c.proposed_entity_id,
        canonical_entity_id=c.canonical_entity_id,
        similarity=float(c.similarity),
        reason=c.reason,
        decision=c.decision,
    )


def _request(r: PromotionRequest, conflicts: List[KnowledgeConflict] = ()) -> PromotionResponse:
    return PromotionResponse(
        id=r.id,
        requester_user_id=r.requester_user_id,
        target_scope=r.target_scope,
        target_scope_id=r.target_scope_id,
        status=r.status,
        note=r.note,
        conflicts=[_conflict(c) for c in conflicts],
    )


@metric_router.post(
    "/{metric_id}/promote",
    response_model=PromotionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def promote_metric(
    metric_id: UUID,
    body: PromoteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = PromotionService(db)
    request, conflicts = await service.enqueue(
        requester=current_user,
        metric_id=metric_id,
        target_scope=body.target_scope,
        target_scope_id=body.target_scope_id,
        note=body.note,
    )
    await db.commit()
    return _request(request, conflicts)


@request_router.get("/{request_id}", response_model=PromotionResponse)
async def get_promotion_request(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = PromotionService(db)
    req = await service._load(request_id)
    rows = await db.execute(
        select(KnowledgeConflict).where(KnowledgeConflict.request_id == request_id)
    )
    conflicts = list(rows.scalars().all())
    return _request(req, conflicts)


@request_router.post("/{request_id}/approve", response_model=PromotionResponse)
async def approve_promotion(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = PromotionService(db)
    req = await service.approve(approver=current_user, request_id=request_id)
    await db.commit()
    return _request(req)


@request_router.post("/{request_id}/reject", response_model=PromotionResponse)
async def reject_promotion(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = PromotionService(db)
    req = await service.reject(approver=current_user, request_id=request_id)
    await db.commit()
    return _request(req)


class ResolveRequest(BaseModel):
    decision: str  # keep_canonical | replace_canonical | merge_alias


@conflict_router.post("/{conflict_id}/resolve", response_model=ConflictResponse)
async def resolve_conflict(
    conflict_id: UUID,
    body: ResolveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = PromotionService(db)
    c = await service.resolve_conflict(
        owner=current_user, conflict_id=conflict_id, decision=body.decision
    )
    await db.commit()
    return _conflict(c)
