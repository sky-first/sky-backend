"""Conversation service — business logic + RBAC for chat threads.

Visibility rules enforced here (mirrored in the repository's SQL filter so
the DB query is tight and the service layer is the single place where the
policy lives as code):

  - Personal conversation   → only the creator can see / mutate it.
  - Space-scoped            → every space member can see. Only the creator
                              can mutate (rename / archive / delete). For now.
                              Admin-level moderation is a Phase 4 concern.
  - Crew-scoped             → every crew member can see. Only the creator
                              can mutate. Same rationale.

The page the conversation is on is expected to be accessible to the user
(pages already have their own RBAC). If someone creates a conversation on a
page they can't see, the page-level check will reject it before we get here.
"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.core.exceptions import ForbiddenError, NotFoundError
from src.core.permissions import is_tenant_admin
from src.models.conversation import Conversation
from src.models.crew import CrewMember
from src.models.space import SpaceMember
from src.models.user import User
from src.repositories.conversation import ConversationRepository
from src.schemas.conversation import (
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
)

try:
    # PR4 broadcast helper — see message_service for the import dance.
    from src.api.v1.chat_ws import broadcast_event_nowait
except Exception:  # pragma: no cover
    def broadcast_event_nowait(*args, **kwargs):
        return None


class ConversationService:
    """Business logic for conversations."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ConversationRepository(db)

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

    async def _can_view(self, conv: Conversation, user: User) -> bool:
        # Tenant-level admins see everything (matches the existing admin
        # bypass used by spaces / crews). This is intentional: Phase 1
        # does not introduce a separate "conversation admin" role.
        if is_tenant_admin(user):
            return True
        # Creator always sees their own conversations.
        if conv.created_by == user.id:
            return True
        # Scope-based visibility
        if conv.space_id is not None:
            return conv.space_id in await self._user_space_ids(user.id)
        if conv.crew_id is not None:
            return conv.crew_id in await self._user_crew_ids(user.id)
        # Personal conversation from another user
        return False

    def _can_mutate(self, conv: Conversation, user: User) -> bool:
        # Only the creator (or tenant-level admin) can rename / archive /
        # delete. Member visibility does NOT grant mutation rights.
        return is_tenant_admin(user) or conv.created_by == user.id

    # ─── CRUD ────────────────────────────────────────────────────────────

    async def create(
        self, *, page_id: UUID, user: User, payload: ConversationCreate
    ) -> Conversation:
        space_id = payload.space_id
        crew_id = payload.crew_id
        # Inherit the page's collaborative scope when the caller didn't
        # pin one. A conversation created on a crew/space page IS the
        # shared room's chat — it must be visible to every crew/space
        # member, not a personal thread only its author can see. This
        # makes scoping correct regardless of what the client sends.
        if space_id is None and crew_id is None:
            from src.repositories.page import PageRepository

            page = await PageRepository(self.db).get_by_id(page_id)
            if page is not None:
                space_id = page.space_id
                crew_id = page.crew_id
        conv = await self.repo.create(
            page_id=page_id,
            created_by=user.id,
            space_id=space_id,
            crew_id=crew_id,
        )
        await self.db.commit()
        await self.db.refresh(conv)
        # Tell every peer on the page a new thread exists so it shows up
        # live in their chat list — without this they'd only learn about
        # it on the next poll / page navigation.
        broadcast_event_nowait(
            str(page_id),
            "conversation.created",
            ConversationResponse.model_validate(conv).model_dump(mode="json"),
        )
        return conv

    async def get(self, conversation_id: UUID, user: User) -> Conversation:
        conv = await self.repo.get_by_id(conversation_id)
        if not conv:
            raise NotFoundError("Conversation not found")
        if not await self._can_view(conv, user):
            # Return 404 instead of 403 so existence isn't leaked to
            # unauthorised callers.
            raise NotFoundError("Conversation not found")
        return conv

    async def list_for_page(
        self,
        *,
        page_id: UUID,
        user: User,
        include_archived: bool = False,
        limit: int = 20,
        cursor: Optional[datetime] = None,
    ) -> List[Conversation]:
        space_ids = await self._user_space_ids(user.id)
        crew_ids = await self._user_crew_ids(user.id)
        return await self.repo.list_for_page(
            page_id=page_id,
            user_id=user.id,
            user_space_ids=space_ids,
            user_crew_ids=crew_ids,
            include_archived=include_archived,
            limit=limit,
            cursor=cursor,
        )

    async def update(
        self, conversation_id: UUID, user: User, payload: ConversationUpdate
    ) -> Conversation:
        conv = await self.repo.get_by_id(conversation_id)
        if not conv:
            raise NotFoundError("Conversation not found")
        if not await self._can_view(conv, user):
            raise NotFoundError("Conversation not found")
        if not self._can_mutate(conv, user):
            raise ForbiddenError("Only the conversation creator can rename it")

        fields = payload.model_dump(exclude_unset=True, exclude_none=True)
        if fields:
            conv = await self.repo.update(conversation_id, **fields)
            assert conv is not None
        await self.db.commit()
        await self.db.refresh(conv)
        return conv

    async def archive(self, conversation_id: UUID, user: User) -> Conversation:
        conv = await self.repo.get_by_id(conversation_id)
        if not conv:
            raise NotFoundError("Conversation not found")
        if not await self._can_view(conv, user):
            raise NotFoundError("Conversation not found")
        if not self._can_mutate(conv, user):
            raise ForbiddenError("Only the conversation creator can archive it")

        conv = await self.repo.archive(conversation_id)
        assert conv is not None
        await self.db.commit()
        await self.db.refresh(conv)
        return conv

    async def unarchive(self, conversation_id: UUID, user: User) -> Conversation:
        conv = await self.repo.get_by_id(conversation_id)
        if not conv:
            raise NotFoundError("Conversation not found")
        if not await self._can_view(conv, user):
            raise NotFoundError("Conversation not found")
        if not self._can_mutate(conv, user):
            raise ForbiddenError("Only the conversation creator can unarchive it")

        conv = await self.repo.unarchive(conversation_id)
        assert conv is not None
        await self.db.commit()
        await self.db.refresh(conv)
        return conv

    async def delete(self, conversation_id: UUID, user: User) -> None:
        conv = await self.repo.get_by_id(conversation_id)
        if not conv:
            raise NotFoundError("Conversation not found")
        if not await self._can_view(conv, user):
            raise NotFoundError("Conversation not found")
        if not self._can_mutate(conv, user):
            raise ForbiddenError("Only the conversation creator can delete it")

        await self.repo.delete(conversation_id)
        await self.db.commit()

    # ─── Pin / Resolve (chat-threads-master-plan PR1) ───────────────────

    async def pin_message(
        self, conversation_id: UUID, message_id: UUID, user: User
    ) -> Conversation:
        conv = await self.repo.get_by_id(conversation_id)
        if not conv:
            raise NotFoundError("Conversation not found")
        if not await self._can_view(conv, user):
            raise NotFoundError("Conversation not found")
        if not self._can_mutate(conv, user):
            raise ForbiddenError(
                "Only the conversation owner can pin a message"
            )

        # Validate the message belongs to this conversation; otherwise
        # an attacker could pin a message from a thread they don't own.
        from src.models.conversation import Message  # avoid circular import

        msg = await self.db.get(Message, message_id)
        if msg is None or msg.conversation_id != conversation_id:
            raise NotFoundError("Message not found in this conversation")

        conv.pinned_message_id = message_id
        conv.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(conv)
        broadcast_event_nowait(
            str(conv.page_id),
            "conversation.pinned",
            ConversationResponse.model_validate(conv).model_dump(mode="json"),
        )
        return conv

    async def unpin(self, conversation_id: UUID, user: User) -> Conversation:
        conv = await self.repo.get_by_id(conversation_id)
        if not conv:
            raise NotFoundError("Conversation not found")
        if not await self._can_view(conv, user):
            raise NotFoundError("Conversation not found")
        if not self._can_mutate(conv, user):
            raise ForbiddenError(
                "Only the conversation owner can unpin a message"
            )

        conv.pinned_message_id = None
        conv.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(conv)
        broadcast_event_nowait(
            str(conv.page_id),
            "conversation.pinned",
            ConversationResponse.model_validate(conv).model_dump(mode="json"),
        )
        return conv

    async def resolve(
        self, conversation_id: UUID, user: User
    ) -> Conversation:
        conv = await self.repo.get_by_id(conversation_id)
        if not conv:
            raise NotFoundError("Conversation not found")
        if not await self._can_view(conv, user):
            raise NotFoundError("Conversation not found")
        # Resolve is allowed for owner OR page-editors (mirrors the
        # chat-threads permission matrix). For PR1 we approximate
        # "page editor" with _can_mutate; a future PR will read the
        # pages.edit gate from the RBAC catalog.
        if not self._can_mutate(conv, user):
            raise ForbiddenError(
                "Only the conversation owner can resolve the thread"
            )

        conv.resolved_at = datetime.utcnow()
        conv.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(conv)
        broadcast_event_nowait(
            str(conv.page_id),
            "conversation.resolved",
            ConversationResponse.model_validate(conv).model_dump(mode="json"),
        )
        return conv

    async def unresolve(
        self, conversation_id: UUID, user: User
    ) -> Conversation:
        conv = await self.repo.get_by_id(conversation_id)
        if not conv:
            raise NotFoundError("Conversation not found")
        if not await self._can_view(conv, user):
            raise NotFoundError("Conversation not found")
        if not self._can_mutate(conv, user):
            raise ForbiddenError(
                "Only the conversation owner can re-open the thread"
            )

        conv.resolved_at = None
        conv.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(conv)
        broadcast_event_nowait(
            str(conv.page_id),
            "conversation.resolved",
            ConversationResponse.model_validate(conv).model_dump(mode="json"),
        )
        return conv

    # ─── Ownership transfer (chat-threads master plan PR6) ────────────────
    async def transfer_ownership(
        self,
        conversation_id: UUID,
        new_owner_id: UUID,
        user: User,
    ) -> Conversation:
        """Reassign a thread's creator to another user.

        Authorised callers: the current owner, or any platform admin.
        (Space admin / editor RBAC is enforced by the FE for now; the
        BE accepts platform admin as the override path until the
        per-space role check is wired through here.)
        """
        conv = await self.repo.get_by_id(conversation_id)
        if not conv:
            raise NotFoundError("Conversation not found")
        if not await self._can_view(conv, user):
            raise NotFoundError("Conversation not found")
        is_owner = conv.created_by == user.id
        is_admin = is_tenant_admin(user)
        if not (is_owner or is_admin):
            raise ForbiddenError(
                "Only the conversation owner or a platform admin can "
                "transfer ownership"
            )

        previous_owner = conv.created_by
        if previous_owner == new_owner_id:
            return conv

        conv.created_by = new_owner_id
        conv.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(conv)
        try:
            from src.services.audit_service import AuditService
            await AuditService(self.db).log_event(
                actor_kind="user",
                actor_id=user.id,
                action="conversation.ownership_transferred",
                resource_kind="conversation",
                resource_id=str(conv.id),
                decision="allow",
                metadata={
                    "previous_owner_id": str(previous_owner) if previous_owner else None,
                    "new_owner_id": str(new_owner_id),
                    "page_id": str(conv.page_id),
                },
            )
        except Exception:
            # Audit failures must not block the user-facing transfer.
            pass
        broadcast_event_nowait(
            str(conv.page_id),
            "conversation.ownership_transferred",
            ConversationResponse.model_validate(conv).model_dump(mode="json"),
        )
        return conv
