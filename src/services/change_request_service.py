"""ChangeRequest service — chat ↔ widget bridge business logic.

Lifecycle:
  - create   : any chat viewer can open a change-request on a widget
               they can see (the page-level RBAC already filters
               visibility; we re-check the message lives in a thread
               the user is allowed to participate in).
  - accept   : widget owner (or page editor) marks accepted; the FE
               re-fires Ask AI with the comment text as additional
               context.
  - dismiss  : widget owner (or page editor) closes silently.
  - list_for_widget : powers the orange "X pending changes" pill on
                      the canvas.

See chat-threads-master-plan PR3.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.core.permissions import is_tenant_admin
from src.models.change_request import ChangeRequest
from src.models.conversation import Conversation, Message
from src.models.user import User
from src.models.widget import Widget
from src.schemas.change_request import ChangeRequestCreate, ChangeRequestResponse
from src.services.conversation_service import ConversationService

try:
    # PR4 broadcast helper — fanout the new/resolved CR over /ws/chat.
    from src.api.v1.chat_ws import broadcast_event_nowait
except Exception:  # pragma: no cover
    def broadcast_event_nowait(*args, **kwargs):
        return None


_VALID_STATUSES = ("pending", "accepted", "dismissed")


class ChangeRequestService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conv_service = ConversationService(db)

    async def _get_widget(self, widget_id: UUID) -> Widget:
        w = await self.db.get(Widget, widget_id)
        if w is None:
            raise NotFoundError("Widget not found")
        return w

    async def _widget_owner_or_page_editor(self, widget: Widget, user: User) -> bool:
        # Same approximation used elsewhere in chat — tenant-level admin
        # always passes, widget creator passes. Page-edit RBAC enrichment
        # is a follow-up.
        if is_tenant_admin(user):
            return True
        return widget.created_by == user.id

    async def create(
        self, user: User, payload: ChangeRequestCreate
    ) -> ChangeRequest:
        # Make sure the conversation/message belongs to the user's
        # visible surface, and that the message is really part of the
        # referenced conversation (no cross-thread spoofing).
        conv = await self.db.get(Conversation, payload.conversation_id)
        if conv is None:
            raise NotFoundError("Conversation not found")
        if not await self.conv_service._can_view(conv, user):
            raise NotFoundError("Conversation not found")

        msg = await self.db.get(Message, payload.message_id)
        if msg is None or msg.conversation_id != payload.conversation_id:
            raise NotFoundError("Message not found in this conversation")

        await self._get_widget(payload.widget_id)

        cr = ChangeRequest(
            widget_id=payload.widget_id,
            conversation_id=payload.conversation_id,
            message_id=payload.message_id,
            requester_id=user.id,
            status="pending",
            content=payload.content,
        )
        self.db.add(cr)
        await self.db.commit()
        await self.db.refresh(cr)
        broadcast_event_nowait(
            str(conv.page_id),
            "change_request.created",
            ChangeRequestResponse.model_validate(cr).model_dump(mode="json"),
        )
        return cr

    async def list_for_widget(
        self, widget_id: UUID, user: User, *, status_filter: Optional[str] = None
    ) -> List[ChangeRequest]:
        widget = await self._get_widget(widget_id)
        # Anyone who can view the widget can see its change-requests.
        # For wave 1 we mirror "widget visibility ≈ page visibility";
        # the page-level RBAC already gates page-scoped reads.
        _ = widget  # placeholder to make the relationship explicit

        conditions = [ChangeRequest.widget_id == widget_id]
        if status_filter is not None:
            if status_filter not in _VALID_STATUSES:
                raise BadRequestError(
                    f"Invalid status filter; expected one of {_VALID_STATUSES}"
                )
            conditions.append(ChangeRequest.status == status_filter)
        stmt = (
            select(ChangeRequest)
            .where(*conditions)
            .order_by(ChangeRequest.created_at.asc(), ChangeRequest.id.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_pending_for_widget(self, widget_id: UUID) -> int:
        stmt = (
            select(ChangeRequest)
            .where(
                ChangeRequest.widget_id == widget_id,
                ChangeRequest.status == "pending",
            )
        )
        result = await self.db.execute(stmt)
        return len(result.scalars().all())

    async def accept(self, change_request_id: UUID, user: User) -> ChangeRequest:
        cr = await self.db.get(ChangeRequest, change_request_id)
        if cr is None:
            raise NotFoundError("Change request not found")
        if cr.status != "pending":
            raise BadRequestError(
                f"Cannot accept a change request in '{cr.status}' state"
            )

        widget = await self._get_widget(cr.widget_id)
        if not await self._widget_owner_or_page_editor(widget, user):
            raise ForbiddenError(
                "Only the widget owner can accept a change request"
            )

        cr.status = "accepted"
        cr.resolved_at = datetime.utcnow()
        cr.resolved_by = user.id
        await self.db.commit()
        await self.db.refresh(cr)
        # Lookup the page_id via the conversation so we know which
        # WS channel to fan out on.
        conv = await self.db.get(Conversation, cr.conversation_id)
        if conv is not None:
            broadcast_event_nowait(
                str(conv.page_id),
                "change_request.resolved",
                ChangeRequestResponse.model_validate(cr).model_dump(mode="json"),
            )
        return cr

    async def dismiss(self, change_request_id: UUID, user: User) -> ChangeRequest:
        cr = await self.db.get(ChangeRequest, change_request_id)
        if cr is None:
            raise NotFoundError("Change request not found")
        if cr.status != "pending":
            raise BadRequestError(
                f"Cannot dismiss a change request in '{cr.status}' state"
            )

        widget = await self._get_widget(cr.widget_id)
        if not await self._widget_owner_or_page_editor(widget, user):
            raise ForbiddenError(
                "Only the widget owner can dismiss a change request"
            )

        cr.status = "dismissed"
        cr.resolved_at = datetime.utcnow()
        cr.resolved_by = user.id
        await self.db.commit()
        await self.db.refresh(cr)
        # Lookup the page_id via the conversation so we know which
        # WS channel to fan out on.
        conv = await self.db.get(Conversation, cr.conversation_id)
        if conv is not None:
            broadcast_event_nowait(
                str(conv.page_id),
                "change_request.resolved",
                ChangeRequestResponse.model_validate(cr).model_dump(mode="json"),
            )
        return cr
