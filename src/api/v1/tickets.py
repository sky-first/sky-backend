"""Ticket endpoints — customer-raised support tickets."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.ticket import (
    TicketCommentRequest,
    TicketCreateRequest,
    TicketDetailResponse,
    TicketEscalateRequest,
    TicketEventResponse,
    TicketListResponse,
    TicketResponse,
    TicketUpdateRequest,
)
from src.services.ticket_service import TicketService

router = APIRouter()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=TicketResponse,
    summary="Open a new support ticket",
)
async def create_ticket(
    payload: TicketCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TicketResponse:
    return await TicketService(db).create(user=current_user, payload=payload)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=TicketListResponse,
    summary="List tickets visible to the caller",
)
async def list_tickets(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TicketListResponse:
    return await TicketService(db).list(
        user=current_user, status=status_filter, skip=skip, limit=limit,
    )


@router.get(
    "/{ticket_id}",
    status_code=status.HTTP_200_OK,
    response_model=TicketDetailResponse,
    summary="Get ticket detail + timeline",
)
async def get_ticket(
    ticket_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TicketDetailResponse:
    return await TicketService(db).get(user=current_user, ticket_id=ticket_id)


@router.patch(
    "/{ticket_id}",
    status_code=status.HTTP_200_OK,
    response_model=TicketResponse,
    summary="Update ticket (admin / owner only)",
)
async def update_ticket(
    ticket_id: UUID,
    payload: TicketUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TicketResponse:
    return await TicketService(db).update(
        user=current_user, ticket_id=ticket_id, payload=payload,
    )


@router.post(
    "/{ticket_id}/comments",
    status_code=status.HTTP_201_CREATED,
    response_model=TicketEventResponse,
    summary="Add a comment to a ticket",
)
async def comment_on_ticket(
    ticket_id: UUID,
    payload: TicketCommentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TicketEventResponse:
    return await TicketService(db).comment(
        user=current_user, ticket_id=ticket_id, payload=payload,
    )


@router.post(
    "/{ticket_id}/escalate",
    status_code=status.HTTP_200_OK,
    response_model=TicketResponse,
    summary="Escalate a ticket to Sky team review (admin / owner only)",
)
async def escalate_ticket(
    ticket_id: UUID,
    payload: TicketEscalateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TicketResponse:
    return await TicketService(db).escalate(
        user=current_user, ticket_id=ticket_id, payload=payload,
    )


@router.post(
    "/{ticket_id}/reopen",
    status_code=status.HTTP_200_OK,
    response_model=TicketResponse,
    summary="Reopen a resolved or closed ticket",
)
async def reopen_ticket(
    ticket_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TicketResponse:
    return await TicketService(db).reopen(
        user=current_user, ticket_id=ticket_id,
    )
