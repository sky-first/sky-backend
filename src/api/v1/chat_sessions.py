"""Chat-session HTTP endpoints.

Two router groupings (mounted separately in router.py):

  /pages/{page_id}/chat-sessions     — collection scoped to a page
  /chat-sessions/{session_id}        — operations on a single session

A session is the "Chat 1 / Chat 2 / …" container the user switches between
in the chatbox header. The page's canvas (widgets/dashboard) is shared across
all of a page's sessions.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.user import User
from src.schemas.chat_session import (
    ChatSessionCreate,
    ChatSessionListResponse,
    ChatSessionResponse,
    ChatSessionUpdate,
)
from src.schemas.common import ErrorResponse
from src.services.chat_session_service import ChatSessionService
from src.services.page_service import PageService


# ─── Page-scoped collection (/pages/{page_id}/chat-sessions) ──────────────

page_router = APIRouter()


@page_router.get(
    "/{page_id}/chat-sessions",
    response_model=ChatSessionListResponse,
    summary="List chat sessions on a page (switcher order)",
    responses={401: {"model": ErrorResponse}},
)
async def list_chat_sessions(
    page_id: UUID,
    include_archived: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatSessionListResponse:
    # Option B — a chat session is page content. Gate on real page access
    # (owner / page member / crew member / space member) before listing.
    await PageService(db).get_page(page_id, current_user)
    service = ChatSessionService(db)
    items = await service.list_for_page(
        page_id=page_id, user=current_user, include_archived=include_archived
    )
    # Guarantee at least one session exists so the switcher is never empty.
    if not items:
        await service.ensure_default_session(page_id=page_id, user=current_user)
        items = await service.list_for_page(page_id=page_id, user=current_user)
    return ChatSessionListResponse(
        items=[ChatSessionResponse.model_validate(i) for i in items]
    )


@page_router.post(
    "/{page_id}/chat-sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open a new chat session on a page ('+')",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def create_chat_session(
    page_id: UUID,
    payload: ChatSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatSessionResponse:
    # Option B — gate on real page access before opening a session on it.
    await PageService(db).get_page(page_id, current_user)
    service = ChatSessionService(db)
    session = await service.create(page_id=page_id, user=current_user, payload=payload)
    return ChatSessionResponse.model_validate(session)


# ─── Single-session endpoints (/chat-sessions/{id}) ───────────────────────

router = APIRouter()


@router.patch(
    "/{session_id}",
    response_model=ChatSessionResponse,
    summary="Rename a chat session",
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def update_chat_session(
    session_id: UUID,
    payload: ChatSessionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatSessionResponse:
    service = ChatSessionService(db)
    try:
        session = await service.update(session_id, current_user, payload)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    return ChatSessionResponse.model_validate(session)


@router.post(
    "/{session_id}/archive",
    response_model=ChatSessionResponse,
    summary="Archive a chat session (hides it from the switcher; threads kept)",
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def archive_chat_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatSessionResponse:
    service = ChatSessionService(db)
    try:
        session = await service.archive(session_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
    return ChatSessionResponse.model_validate(session)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a chat session and its threads (creator only; can't delete the last chat)",
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def delete_chat_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    service = ChatSessionService(db)
    try:
        await service.delete(session_id, current_user)
    except NotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ForbiddenError as err:
        raise HTTPException(status_code=403, detail=str(err))
