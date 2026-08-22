"""Unified mobile Insights feed endpoints (BE-02, Sky Mobile).

    GET  /api/v1/insights?filter=&cursor=&limit=   — paginated, scoped feed
    GET  /api/v1/insights/{id}                      — detail (+ series, tiles)
    POST /api/v1/insights/{id}/review { reviewed }  — per-user, idempotent
    POST /api/v1/insights/{id}/pin    { pinned }    — per-user, idempotent

Auth is the standard user dependency (a missing token → 401). Findings outside
the caller's content plane are invisible in the feed and return **404** on
detail/mutation — never a 403 that would leak their existence.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.schemas.insight_feed import (
    INSIGHT_FILTERS,
    InsightDetail,
    InsightFeedResponse,
    PinRequest,
    ReviewRequest,
)
from src.services.insight_feed_service import InsightFeedService, InvalidCursor

router = APIRouter()


@router.get(
    "",
    response_model=InsightFeedResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Paginated Insights feed",
    description=(
        "Findings the caller can see (agent + scan), newest first, keyset "
        "cursor. Filters: all | latest | featured | risk | opportunity."
    ),
)
async def list_insights(
    filter: str = Query("all"),
    cursor: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    space_id: Optional[UUID] = Query(
        None,
        description=(
            "Restringe o feed a um projeto. Sem ele, devolve tudo o que quem "
            "chama alcança — que era o comportamento anterior e continua a ser "
            "o de quem não o manda."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> InsightFeedResponse:
    if filter not in INSIGHT_FILTERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"filter must be one of {', '.join(INSIGHT_FILTERS)}",
        )
    try:
        return await InsightFeedService(db).list(
            current_user.id, filter, cursor, limit, space_id
        )
    except InvalidCursor:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed cursor")


@router.get(
    "/{finding_id}",
    response_model=InsightDetail,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Insight detail",
)
async def get_insight(
    finding_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> InsightDetail:
    detail = await InsightFeedService(db).detail(current_user.id, finding_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insight not found")
    return detail


@router.post(
    "/{finding_id}/review",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Mark an insight reviewed (per-user, idempotent)",
)
async def review_insight(
    finding_id: str,
    body: ReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    ok = await InsightFeedService(db).set_reviewed(current_user.id, finding_id, body.reviewed)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insight not found")
    await db.commit()
    return {"id": finding_id, "reviewed": body.reviewed}


@router.post(
    "/{finding_id}/pin",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Pin an insight (per-user, idempotent)",
)
async def pin_insight(
    finding_id: str,
    body: PinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    ok = await InsightFeedService(db).set_pinned(current_user.id, finding_id, body.pinned)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insight not found")
    await db.commit()
    return {"id": finding_id, "pinned": body.pinned}
