"""Change-request HTTP endpoints (chat-threads-master-plan PR3).

Two router groupings:

  /change-requests                     — create / accept / dismiss
  /widgets/{widget_id}/change-requests — list per widget (powers the
                                         orange "X pending changes" pill)
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.user import User
from src.schemas.change_request import (
    ChangeRequestCreate,
    ChangeRequestListResponse,
    ChangeRequestResponse,
)
from src.schemas.common import ErrorResponse
from src.services.change_request_service import ChangeRequestService


router = APIRouter()


@router.post(
    "",
    response_model=ChangeRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open a change request linking a comment to a widget",
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def create_change_request(
    payload: ChangeRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChangeRequestResponse:
    service = ChangeRequestService(db)
    try:
        cr = await service.create(current_user, payload)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    return ChangeRequestResponse.model_validate(cr)


@router.post(
    "/{change_request_id}/accept",
    response_model=ChangeRequestResponse,
    summary="Widget owner accepts the request (Ask AI re-fire happens FE-side)",
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def accept_change_request(
    change_request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChangeRequestResponse:
    service = ChangeRequestService(db)
    try:
        cr = await service.accept(change_request_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except BadRequestError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return ChangeRequestResponse.model_validate(cr)


@router.post(
    "/{change_request_id}/dismiss",
    response_model=ChangeRequestResponse,
    summary="Widget owner closes the request without action",
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def dismiss_change_request(
    change_request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChangeRequestResponse:
    service = ChangeRequestService(db)
    try:
        cr = await service.dismiss(change_request_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except BadRequestError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return ChangeRequestResponse.model_validate(cr)


# ─── /widgets/{widget_id}/change-requests ─────────────────────────────────


widget_router = APIRouter()


@widget_router.get(
    "/{widget_id}/change-requests",
    response_model=ChangeRequestListResponse,
    summary="List change requests on a widget (powers the orange pill)",
    responses={404: {"model": ErrorResponse}},
)
async def list_change_requests_for_widget(
    widget_id: UUID,
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="pending|accepted|dismissed — defaults to all",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChangeRequestListResponse:
    service = ChangeRequestService(db)
    try:
        items = await service.list_for_widget(
            widget_id, current_user, status_filter=status_filter,
        )
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except BadRequestError as err:
        raise HTTPException(status_code=400, detail=str(err))
    pending_count = sum(1 for cr in items if cr.status == "pending")
    return ChangeRequestListResponse(
        items=[ChangeRequestResponse.model_validate(cr) for cr in items],
        pending_count=pending_count,
    )
