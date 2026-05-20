"""Message HTTP endpoints — adds messages, pin, fork.

Three router groupings:

  /conversations/{conversation_id}/messages   — messages inside a thread
  /conversations/{conversation_id}/fork       — branch a thread
  /messages/{message_id}/pin                  — materialise a widget
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.schemas.conversation import ConversationResponse
from src.schemas.message import (
    ForkRequest,
    MessageCreate,
    MessageListResponse,
    MessageResponse,
    PinRequest,
)
from src.services.message_service import MessageService


# ─── /conversations/{id}/messages and /fork ───────────────────────────────

conversation_router = APIRouter()


@conversation_router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Append a user message to the conversation",
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def create_message(
    conversation_id: UUID,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> MessageResponse:
    service = MessageService(db)
    try:
        msg = await service.create(conversation_id, current_user, payload)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    return MessageResponse.model_validate(msg)


@conversation_router.get(
    "/{conversation_id}/messages",
    response_model=MessageListResponse,
    summary="List messages in thread order (oldest first)",
    responses={404: {"model": ErrorResponse}},
)
async def list_messages(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> MessageListResponse:
    service = MessageService(db)
    try:
        items = await service.list_for_conversation(
            conversation_id, current_user, limit=limit, cursor=cursor
        )
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    next_cursor = items[-1].created_at if len(items) == limit else None
    return MessageListResponse(
        items=[MessageResponse.model_validate(m) for m in items],
        next_cursor=next_cursor,
    )


@conversation_router.post(
    "/{conversation_id}/fork",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Branch a conversation from a specific message (use case A6)",
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def fork_conversation(
    conversation_id: UUID,
    payload: ForkRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConversationResponse:
    service = MessageService(db)
    try:
        child = await service.fork(conversation_id, current_user, payload)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except BadRequestError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return ConversationResponse.model_validate(child)


# ─── /messages/{id}/pin ───────────────────────────────────────────────────

router = APIRouter()


@router.post(
    "/{message_id}/pin",
    status_code=status.HTTP_201_CREATED,
    summary="Materialise a widget pinned to this message (use case A3, A7, A11)",
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def pin_message(
    message_id: UUID,
    payload: PinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    service = MessageService(db)
    try:
        widget = await service.pin_message(message_id, current_user, payload)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except BadRequestError as err:
        raise HTTPException(status_code=400, detail=str(err))
    # We return a minimal shape instead of the full WidgetResponse so this
    # endpoint has no dependency on widget-schema evolution.
    return {
        "widget_id": str(widget.id),
        "conversation_id": str(widget.conversation_id),
        "pinned_message_id": str(widget.pinned_message_id),
        "page_id": str(widget.page_id),
        "title": widget.title,
    }
