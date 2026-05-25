"""Conversation HTTP endpoints.

Two router groupings:

  /pages/{page_id}/conversations   — collection scoped to a page
  /conversations/{conversation_id} — operations on a single conversation

Mounted separately in src/api/v1/router.py so FastAPI's URL routing stays
unambiguous.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.schemas.conversation import (
    ConversationCreate,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdate,
    TransferOwnershipRequest,
)
from src.services.conversation_service import ConversationService


# ─── Page-scoped collection (/pages/{page_id}/conversations) ──────────────

page_router = APIRouter()


@page_router.post(
    "/{page_id}/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open a new conversation on a page",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def create_conversation(
    page_id: UUID,
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    service = ConversationService(db)
    conv = await service.create(page_id=page_id, user=current_user, payload=payload)
    return ConversationResponse.model_validate(conv)


@page_router.get(
    "/{page_id}/conversations",
    response_model=ConversationListResponse,
    summary="List conversations on a page (newest first)",
    responses={401: {"model": ErrorResponse}},
)
async def list_conversations(
    page_id: UUID,
    include_archived: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[datetime] = Query(
        None,
        description="Send the `next_cursor` from the previous response for pagination.",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationListResponse:
    service = ConversationService(db)
    items = await service.list_for_page(
        page_id=page_id,
        user=current_user,
        include_archived=include_archived,
        limit=limit,
        cursor=cursor,
    )
    next_cursor = items[-1].updated_at if len(items) == limit else None
    return ConversationListResponse(
        items=[ConversationResponse.model_validate(i) for i in items],
        next_cursor=next_cursor,
    )


# ─── Single-conversation endpoints (/conversations/{id}) ──────────────────

router = APIRouter()


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Get a conversation by id",
    responses={404: {"model": ErrorResponse}},
)
async def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    service = ConversationService(db)
    try:
        conv = await service.get(conversation_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    return ConversationResponse.model_validate(conv)


@router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Rename a conversation",
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    service = ConversationService(db)
    try:
        conv = await service.update(conversation_id, current_user, payload)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    return ConversationResponse.model_validate(conv)


@router.post(
    "/{conversation_id}/archive",
    response_model=ConversationResponse,
    summary="Archive a conversation (hides it from the default list)",
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def archive_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    service = ConversationService(db)
    try:
        conv = await service.archive(conversation_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    return ConversationResponse.model_validate(conv)


@router.post(
    "/{conversation_id}/unarchive",
    response_model=ConversationResponse,
    summary="Restore an archived conversation",
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def unarchive_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    service = ConversationService(db)
    try:
        conv = await service.unarchive(conversation_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    return ConversationResponse.model_validate(conv)


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hard-delete a conversation (cascade to messages; widgets keep their pinned refs as null)",
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def delete_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    service = ConversationService(db)
    try:
        await service.delete(conversation_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))


# ─── Pin / Resolve (chat-threads-master-plan PR1) ─────────────────────────


class _PinRequest(BaseModel):
    message_id: UUID


@router.post(
    "/{conversation_id}/pin",
    response_model=ConversationResponse,
    summary="Pin a message at the top of the thread (owner only)",
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def pin_conversation_message(
    conversation_id: UUID,
    payload: _PinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    service = ConversationService(db)
    try:
        conv = await service.pin_message(
            conversation_id, payload.message_id, current_user
        )
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    return ConversationResponse.model_validate(conv)


@router.delete(
    "/{conversation_id}/pin",
    response_model=ConversationResponse,
    summary="Unpin whatever message is currently pinned",
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def unpin_conversation_message(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    service = ConversationService(db)
    try:
        conv = await service.unpin(conversation_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    return ConversationResponse.model_validate(conv)


@router.post(
    "/{conversation_id}/resolve",
    response_model=ConversationResponse,
    summary="Close the thread as resolved (owner or page-editor)",
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def resolve_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    service = ConversationService(db)
    try:
        conv = await service.resolve(conversation_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    return ConversationResponse.model_validate(conv)


@router.post(
    "/{conversation_id}/unresolve",
    response_model=ConversationResponse,
    summary="Re-open a previously resolved thread",
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def unresolve_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    service = ConversationService(db)
    try:
        conv = await service.unresolve(conversation_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    return ConversationResponse.model_validate(conv)


@router.post(
    "/{conversation_id}/transfer-ownership",
    response_model=ConversationResponse,
    summary="Reassign the thread to another member (owner / platform admin)",
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def transfer_ownership(
    conversation_id: UUID,
    payload: TransferOwnershipRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    """chat-threads master plan PR6 — covers HR off-boarding flows
    and "this conversation no longer belongs to me" handoffs. The
    service records an audit event capturing the previous + new owner
    and the actor; the change is broadcast over /ws/chat so other
    page members see the new owner in real time."""
    service = ConversationService(db)
    try:
        conv = await service.transfer_ownership(
            conversation_id, payload.new_owner_id, current_user
        )
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    return ConversationResponse.model_validate(conv)
