"""ChatSession service — business logic + RBAC for page chat sessions.

A session is the "Chat 1 / Chat 2 / …" container the user switches between.
Visibility and mutation rules mirror ``ConversationService`` exactly, so a
session on a shared space/crew page is seen by every member and the
provenance chip on a widget ("from Chat 3") resolves for the whole team.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select

from src.core.exceptions import ForbiddenError, NotFoundError
from src.core.permissions import is_tenant_admin
from src.models.chat_session import ChatSession
from src.models.crew import CrewMember
from src.models.space import SpaceMember
from src.models.user import User
from src.repositories.chat_session import ChatSessionRepository
from src.schemas.chat_session import (
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionUpdate,
)

try:  # PR4 broadcast helper — same import dance as conversation_service.
    from src.api.v1.chat_ws import broadcast_event_nowait
except Exception:  # pragma: no cover

    def broadcast_event_nowait(*args, **kwargs):
        return None


class ChatSessionService:
    def __init__(self, db):
        self.db = db
        self.repo = ChatSessionRepository(db)

    # ─── Membership helpers ──────────────────────────────────────────────

    async def _user_space_ids(self, user_id: UUID) -> List[UUID]:
        result = await self.db.execute(
            select(SpaceMember.space_id).where(SpaceMember.user_id == user_id)
        )
        return [row[0] for row in result.all()]

    async def _user_crew_ids(self, user_id: UUID) -> List[UUID]:
        result = await self.db.execute(
            select(CrewMember.crew_id).where(CrewMember.user_id == user_id)
        )
        return [row[0] for row in result.all()]

    async def _can_view(self, session: ChatSession, user: User) -> bool:
        if is_tenant_admin(user):
            return True
        if session.created_by == user.id:
            return True
        if session.space_id is not None:
            return session.space_id in await self._user_space_ids(user.id)
        if session.crew_id is not None:
            return session.crew_id in await self._user_crew_ids(user.id)
        return False

    def _can_mutate(self, session: ChatSession, user: User) -> bool:
        # Any member may create a session; renaming/archiving an existing one
        # is restricted to its creator or a tenant admin (mirrors threads).
        return is_tenant_admin(user) or session.created_by == user.id

    # ─── Reads ───────────────────────────────────────────────────────────

    async def list_for_page(
        self, *, page_id: UUID, user: User, include_archived: bool = False
    ) -> List[ChatSession]:
        return await self.repo.list_for_page(
            page_id=page_id,
            user_id=user.id,
            user_space_ids=await self._user_space_ids(user.id),
            user_crew_ids=await self._user_crew_ids(user.id),
            include_archived=include_archived,
        )

    async def ensure_default_session(self, *, page_id: UUID, user: User) -> ChatSession:
        """Return the page's default (first) session, creating "Chat 1" if the
        page has none yet. Used by the conversation create path so every
        thread lands in a session even when the client didn't pin one.
        """
        existing = await self.list_for_page(page_id=page_id, user=user)
        if existing:
            return existing[0]
        return await self.create(
            page_id=page_id, user=user, payload=ChatSessionCreate(title="Chat 1")
        )

    # ─── Mutations ───────────────────────────────────────────────────────

    async def create(
        self, *, page_id: UUID, user: User, payload: ChatSessionCreate
    ) -> ChatSession:
        space_id = payload.space_id
        crew_id = payload.crew_id
        # Inherit the page's collaborative scope so the session is shared with
        # every member of the room (never a personal-only chat on a team page).
        if space_id is None and crew_id is None:
            from src.repositories.page import PageRepository

            page = await PageRepository(self.db).get_by_id(page_id)
            if page is not None:
                space_id = page.space_id
                crew_id = page.crew_id

        # Monotonic position/number so "Chat N" titles never collide after a
        # delete (count-based numbering reused freed numbers → two "Chat 3").
        position = await self.repo.max_position_for_page(page_id) + 1
        title = payload.title or f"Chat {position + 1}"
        session = await self.repo.create(
            page_id=page_id,
            created_by=user.id,
            space_id=space_id,
            crew_id=crew_id,
            title=title,
            position=position,
        )
        await self.db.commit()
        await self.db.refresh(session)
        broadcast_event_nowait(
            str(page_id),
            "chat_session.created",
            ChatSessionResponse.model_validate(session).model_dump(mode="json"),
        )
        return session

    async def get(self, session_id: UUID, user: User) -> ChatSession:
        session = await self.repo.get_by_id(session_id)
        if not session or not await self._can_view(session, user):
            raise NotFoundError("Chat session not found")
        return session

    async def update(
        self, session_id: UUID, user: User, payload: ChatSessionUpdate
    ) -> ChatSession:
        session = await self.get(session_id, user)
        if not self._can_mutate(session, user):
            raise ForbiddenError("Only the chat creator can rename it")
        fields = payload.model_dump(exclude_unset=True, exclude_none=True)
        if fields:
            session = await self.repo.update(session_id, **fields)
            assert session is not None
        await self.db.commit()
        await self.db.refresh(session)
        broadcast_event_nowait(
            str(session.page_id),
            "chat_session.updated",
            ChatSessionResponse.model_validate(session).model_dump(mode="json"),
        )
        return session

    async def archive(self, session_id: UUID, user: User) -> ChatSession:
        session = await self.get(session_id, user)
        if not self._can_mutate(session, user):
            raise ForbiddenError("Only the chat creator can archive it")
        from datetime import datetime, timezone

        session = await self.repo.update(
            session_id, archived_at=datetime.now(timezone.utc)
        )
        assert session is not None
        await self.db.commit()
        await self.db.refresh(session)
        broadcast_event_nowait(
            str(session.page_id),
            "chat_session.archived",
            ChatSessionResponse.model_validate(session).model_dump(mode="json"),
        )
        return session

    async def delete(self, session_id: UUID, user: User) -> None:
        """Hard-delete a chat session AND its threads.

        Guard rails:
          - Only the creator (or a tenant admin) can delete (``_can_mutate``).
          - A page must always keep at least one chat — deleting the last
            remaining (visible) session is refused so the chatbox never lands
            on an empty void.

        The session's conversations are deleted; their messages cascade at the
        DB level (``Message.conversation_id ON DELETE CASCADE``). Widgets that
        pinned one of those messages keep their reference nulled (SET NULL),
        same as a single-conversation delete.
        """
        session = await self.get(session_id, user)
        if not self._can_mutate(session, user):
            raise ForbiddenError("Only the chat creator can delete it")
        page_id = session.page_id
        visible = await self.list_for_page(page_id=page_id, user=user)
        if len([s for s in visible if s.id != session_id]) == 0:
            raise ForbiddenError(
                "A page must keep at least one chat — create another chat "
                "before deleting this one."
            )
        from sqlalchemy import delete as sa_delete

        from src.models.conversation import Conversation

        await self.db.execute(
            sa_delete(Conversation).where(Conversation.session_id == session_id)
        )
        await self.repo.delete(session_id)
        await self.db.commit()
        broadcast_event_nowait(
            str(page_id),
            "chat_session.deleted",
            {"id": str(session_id), "page_id": str(page_id)},
        )

    async def _ensure_session_id(
        self, *, page_id: UUID, user: User, session_id: Optional[UUID]
    ) -> UUID:
        """Resolve the session a new conversation belongs to. Honour a pinned
        id when it's a real, viewable session on the page; otherwise fall back
        to the page's default session.
        """
        if session_id is not None:
            session = await self.repo.get_by_id(session_id)
            if (
                session is not None
                and session.page_id == page_id
                and await self._can_view(session, user)
            ):
                return session.id
        return (await self.ensure_default_session(page_id=page_id, user=user)).id
