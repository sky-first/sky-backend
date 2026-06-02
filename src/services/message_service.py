"""Message service — add, list, pin, fork.

RBAC for messages piggybacks on the parent conversation:
  - list / add  → anyone who can view the conversation
  - pin         → anyone who can view the conversation AND has widgets.create
  - fork        → anyone who can view the conversation; the fork is created
                  as a personal conversation owned by the caller

Pin concurrency (use case A11) is enforced by a partial unique index on
widgets.pinned_message_id: the second concurrent INSERT hits the
constraint and we return the pre-existing widget instead of raising.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.conversation import Conversation, Message
from src.models.user import User
from src.models.widget import Widget
from src.repositories.conversation import ConversationRepository
from src.repositories.message import MessageRepository
from src.schemas.message import ForkRequest, MessageCreate, MessageResponse, PinRequest
from src.services.conversation_service import ConversationService

try:
    # chat-threads PR4: broadcast new messages on the page WebSocket so
    # every connected peer renders the new comment/question/ai_response
    # without polling. Import is wrapped so circular-import or
    # not-loaded-yet doesn't crash CLI / migration code paths.
    from src.api.v1.chat_ws import broadcast_event_nowait
except Exception:  # pragma: no cover — relay is optional

    def broadcast_event_nowait(*args, **kwargs):
        return None


# Only the AI service / agent runtime should write these. Humans submit
# user messages; everything else is produced server-side.
_HUMAN_ROLE = "user"


def _display_name(user: Optional[User]) -> Optional[str]:
    """Human-friendly author label: full name, else the email local part."""
    if user is None:
        return None
    name = (getattr(user, "name", None) or "").strip()
    if name:
        return name
    email = getattr(user, "email", None)
    return email.split("@")[0] if email else None


class MessageService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = MessageRepository(db)
        self.conv_repo = ConversationRepository(db)
        self.conv_service = ConversationService(db)

    # ─── Helpers ─────────────────────────────────────────────────────────

    async def _load_viewable_conversation(self, conversation_id: UUID, user: User) -> Conversation:
        conv = await self.conv_repo.get_by_id(conversation_id)
        if not conv:
            raise NotFoundError("Conversation not found")
        if not await self.conv_service._can_view(conv, user):
            # Hide existence.
            raise NotFoundError("Conversation not found")
        return conv

    async def _attach_author_names(self, messages: List[Message]) -> None:
        """Resolve each message author's display name and attach it as the
        transient ``author_name`` attribute so MessageResponse serialises it.

        One batched query for the distinct authors in the list. AI/system
        rows (user_id NULL) and legacy rows stay None.
        """
        user_ids = {m.user_id for m in messages if m.user_id is not None}
        names: dict = {}
        if user_ids:
            rows = await self.db.execute(
                select(User.id, User.name, User.email).where(User.id.in_(user_ids))
            )
            for uid, name, email in rows.all():
                label = (name or "").strip() or (email.split("@")[0] if email else None)
                names[uid] = label
        for m in messages:
            m.author_name = names.get(m.user_id) if m.user_id else None

    # ─── Create ──────────────────────────────────────────────────────────

    async def create(self, conversation_id: UUID, user: User, payload: MessageCreate) -> Message:
        conv = await self._load_viewable_conversation(conversation_id, user)

        if payload.role != _HUMAN_ROLE:
            # Non-human roles are produced by the backend itself on behalf
            # of the AI service or an agent run. An HTTP caller cannot
            # impersonate the assistant/system.
            raise ForbiddenError("Only role='user' messages can be created via this endpoint")

        # chat-threads-master-plan PR1: derive `kind` and enforce
        # owner-gating for questions.
        #   - kind='question' (or unspecified) → fires AI; only the
        #     conversation owner (creator) may submit. Page editors
        #     and admins also pass (they can run AI on shared threads
        #     to unblock the team).
        #   - kind='comment' → any viewer may post; never fires AI.
        kind = payload.kind or "question"
        if kind == "question":
            if conv.created_by != user.id and user.role != "admin":
                # Mirror "owner gates AI re-runs in that thread" from
                # the chat-threads-master-plan. Non-owners must post
                # comments instead, which the FE renders as the "Leave
                # comment" button.
                raise ForbiddenError(
                    "Only the conversation owner can post a question; "
                    "non-owners can leave comments instead"
                )
        elif kind != "comment":
            # Should be unreachable thanks to the pattern validator on the
            # schema, but guard explicitly so the service is the canonical
            # policy gate.
            raise ForbiddenError(
                "Invalid message kind; only 'question' and 'comment' are " "accepted from clients"
            )

        msg = await self.repo.create(
            conversation_id=conv.id,
            role=payload.role,
            kind=kind,
            content=payload.content,
            user_id=user.id,
            query_id=payload.query_id,
            cost_tokens=payload.cost_tokens,
            cost_usd=payload.cost_usd,
            parent_message_id=payload.parent_message_id,
        )

        # Touch the conversation so list ordering surfaces it as recent.
        conv.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(msg)

        # The writer is the caller — stamp their display name so the
        # broadcast + HTTP response attribute the message to the real
        # author for every collaborator (not the local viewer's name).
        msg.author_name = _display_name(user)

        # PR4: broadcast to every WS subscriber on this page. Fire-and-forget
        # so the HTTP response doesn't wait on peer acks.
        broadcast_event_nowait(
            str(conv.page_id),
            "message.created",
            MessageResponse.model_validate(msg).model_dump(mode="json"),
        )

        return msg

    # ─── List ────────────────────────────────────────────────────────────

    async def list_for_conversation(
        self,
        conversation_id: UUID,
        user: User,
        *,
        limit: int = 50,
        cursor: Optional[datetime] = None,
    ) -> List[Message]:
        await self._load_viewable_conversation(conversation_id, user)
        messages = await self.repo.list_for_conversation(
            conversation_id=conversation_id, limit=limit, cursor=cursor
        )
        await self._attach_author_names(messages)
        return messages

    # ─── Ask-AI bundling (chat-threads-master-plan PR2) ─────────────────

    async def list_pending_comments(self, conversation_id: UUID, user: User) -> List[Message]:
        """Comments since the last ai_response, not yet incorporated.

        Used by the FE to preview "X comments will be included" before the
        owner fires a new question, and by the bundling code below to
        assemble the prompt.
        """
        await self._load_viewable_conversation(conversation_id, user)
        return await self.repo.list_pending_comments(conversation_id=conversation_id)

    async def ask_ai_with_bundle(
        self,
        conversation_id: UUID,
        user: User,
        question_content: str,
        ai_answer_content: str,
        *,
        query_id: Optional[UUID] = None,
        tier: Optional[str] = None,
        duration_ms: Optional[int] = None,
        cost_tokens: Optional[int] = None,
        cost_usd: Optional[Decimal] = None,
    ) -> dict:
        """Owner-gated bundle flow.

        1. Load pending comments since the last AI response.
        2. Insert the question (kind='question').
        3. Insert the AI response (kind='ai_response') with parent =
           question.id.
        4. Stamp each bundled comment's incorporated_in_message_id =
           ai_response.id so the FE renders the "incorporated in #N"
           badge.

        Returns the bundle dict {question, ai_response, incorporated:
        [comment_ids]} so the caller can ship them on the WebSocket in
        a single broadcast.

        The AI call itself is the *caller's* responsibility — this
        service stays pure-DB so it doesn't pull the AI client into the
        chat module. The caller passes the answer in. PR4 wires the
        broadcast.
        """
        conv = await self._load_viewable_conversation(conversation_id, user)
        if conv.created_by != user.id and user.role != "admin":
            raise ForbiddenError("Only the conversation owner can fire an Ask-AI bundle")

        pending = await self.repo.list_pending_comments(conversation_id=conversation_id)

        # 2. Question — authored by the owner firing the bundle.
        question = await self.repo.create(
            conversation_id=conv.id,
            role="user",
            kind="question",
            content=question_content,
            user_id=user.id,
            query_id=query_id,
        )

        # 3. AI response (kind=ai_response, role=assistant)
        ai_response = await self.repo.create(
            conversation_id=conv.id,
            role="assistant",
            kind="ai_response",
            content=ai_answer_content,
            query_id=query_id,
            tier=tier,
            duration_ms=duration_ms,
            cost_tokens=cost_tokens,
            cost_usd=cost_usd,
            parent_message_id=question.id,
        )

        # 4. Stamp incorporated comments
        if pending:
            await self.repo.mark_incorporated(
                message_ids=[c.id for c in pending],
                ai_response_id=ai_response.id,
            )

        conv.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(question)
        await self.db.refresh(ai_response)

        # Attribute the question to its author; the AI response stays
        # authorless (rendered as the assistant).
        question.author_name = _display_name(user)
        ai_response.author_name = None

        # PR4: broadcast the bundle so peers render the question/AI pair
        # immediately. We send both events (clients can render the AI
        # answer as it lands while keeping the question above it).
        page_id = str(conv.page_id)
        broadcast_event_nowait(
            page_id,
            "message.created",
            MessageResponse.model_validate(question).model_dump(mode="json"),
        )
        broadcast_event_nowait(
            page_id,
            "message.created",
            MessageResponse.model_validate(ai_response).model_dump(mode="json"),
        )

        return {
            "question": question,
            "ai_response": ai_response,
            "incorporated_message_ids": [c.id for c in pending],
        }

    @staticmethod
    def build_bundled_prompt(question_content: str, pending_comments: List[Message]) -> str:
        """Pure helper: stitches the question + pending comments into a
        single LLM-ready prompt.

        The LLM is asked to (a) skim the discussion, (b) reach a
        "consensus" reading, then (c) answer the question grounded in
        that consensus. Caller passes the resulting text to whatever
        AI client is in use; we keep the prompt assembly here so unit
        tests can lock in the format.
        """
        if not pending_comments:
            return question_content

        comments_block = "\n".join(f"- {c.content}" for c in pending_comments)
        return (
            "You are answering a follow-up question on a shared discussion. "
            "Below are the comments the team posted since your last answer. "
            "Briefly synthesise the consensus, then answer the question.\n\n"
            f"Team comments since last answer:\n{comments_block}\n\n"
            f"Question:\n{question_content}"
        )

    # ─── Pin ─────────────────────────────────────────────────────────────

    async def pin_message(self, message_id: UUID, user: User, payload: PinRequest) -> Widget:
        """Materialise a widget anchored to this message.

        A11: concurrent pins of the same message resolve to a single widget.
        The partial unique index on widgets.pinned_message_id enforces
        this. On IntegrityError we refetch and return the winning widget.
        """
        msg = await self.repo.get_by_id(message_id)
        if not msg:
            raise NotFoundError("Message not found")

        # RBAC: require view of the parent conversation.
        conv = await self._load_viewable_conversation(msg.conversation_id, user)

        # Only assistant messages produce meaningful insights. Pinning a
        # user question doesn't make sense and would just clutter the DB.
        if msg.role != "assistant":
            raise BadRequestError("Only assistant messages can be pinned")

        # Fast-path: message already pinned → return its widget.
        if msg.pinned_widget_id:
            existing = await self.db.execute(
                select(Widget).where(Widget.id == msg.pinned_widget_id)
            )
            winner = existing.scalar_one_or_none()
            if winner is not None:
                return winner

        # Create the widget. Title defaults to the first line of the
        # message content truncated to 255 chars.
        title = payload.title or msg.content.splitlines()[0][:255] if msg.content else "Insight"
        widget = Widget(
            page_id=payload.page_id,
            type=payload.widget_type,
            title=title,
            position=payload.position or {"x": 0, "y": 0},
            size=payload.size or {"width": 400, "height": 300},
            data={},
            conversation_id=conv.id,
            pinned_message_id=msg.id,
            created_by=user.id,
        )
        self.db.add(widget)
        try:
            await self.db.flush()
        except IntegrityError:
            # A concurrent request already pinned this message — fetch and
            # return the existing widget.
            await self.db.rollback()
            existing = await self.db.execute(
                select(Widget).where(Widget.pinned_message_id == msg.id)
            )
            winner = existing.scalar_one_or_none()
            if winner is None:
                # Extremely unlikely: index raised but row not visible.
                raise
            return winner

        # Back-link the message to the widget so later reads are cheap.
        msg.pinned_widget_id = widget.id
        await self.db.commit()
        await self.db.refresh(widget)
        return widget

    # ─── Fork ────────────────────────────────────────────────────────────

    async def fork(self, conversation_id: UUID, user: User, payload: ForkRequest) -> Conversation:
        """Branch a conversation: create a new thread that contains every
        message up to and including `from_message_id`, owned by the caller.

        The fork is always personal (no space / crew scope) because the
        branch carries the caller's intent — if they want to share it, they
        archive the original and reshare the branched one explicitly.
        """
        parent = await self._load_viewable_conversation(conversation_id, user)
        messages = await self.repo.list_up_to(
            conversation_id=parent.id, until_message_id=payload.from_message_id
        )
        if not messages:
            raise BadRequestError("from_message_id not in this conversation")

        child = await self.conv_repo.create(
            page_id=parent.page_id,
            created_by=user.id,
            space_id=None,
            crew_id=None,
            title=f"Branch — {parent.title or 'Conversation'}",
        )
        # Copy messages. We keep the original created_at order by bumping
        # with microsecond offsets; the exact timestamps aren't load-bearing
        # for the branched thread (the parent remains the canonical log).
        base = datetime.utcnow()
        for idx, src in enumerate(messages):
            copied = Message(
                conversation_id=child.id,
                role=src.role,
                content=src.content,
                user_id=src.user_id,
                query_id=src.query_id,
                cost_tokens=src.cost_tokens,
                cost_usd=src.cost_usd,
                created_at=base.replace(microsecond=(base.microsecond + idx) % 1_000_000),
            )
            self.db.add(copied)

        await self.db.commit()
        await self.db.refresh(child)
        return child

    async def toggle_reaction(
        self,
        conversation_id: UUID,
        message_id: UUID,
        emoji: str,
        user: User,
    ) -> Message:
        """Toggle the caller's reaction with this emoji on the message.

        Idempotent: if the user is already in the emoji's list, they
        come out; otherwise they go in. Empty lists are pruned so the
        JSONB stays compact.
        """
        # RBAC: caller must be able to see the parent conversation
        # — same gate Message.create uses.
        conv = await self.conv_repo.get_by_id(conversation_id)
        if conv is None:
            raise NotFoundError("conversation not found")
        if not await self.conv_service._can_view(conv, user):
            raise ForbiddenError("you cannot react in this conversation")

        msg = await self.db.get(Message, message_id)
        if msg is None or msg.conversation_id != conversation_id:
            raise NotFoundError("message not found in this conversation")

        # Copy-on-write so SQLAlchemy detects the change.
        reactions: dict = dict(msg.reactions or {})
        bucket = list(reactions.get(emoji, []))
        uid = str(user.id)
        if uid in bucket:
            bucket.remove(uid)
        else:
            bucket.append(uid)
        if bucket:
            reactions[emoji] = bucket
        else:
            reactions.pop(emoji, None)
        msg.reactions = reactions

        await self.db.commit()
        await self.db.refresh(msg)
        await self._attach_author_names([msg])

        # Best-effort WS broadcast so peers see the reaction update
        # in real time. The relay signature is (page_id, event_type,
        # payload) — match the existing "message.created" envelope.
        try:
            broadcast_event_nowait(
                str(conv.page_id),
                "message.reaction",
                {
                    "conversation_id": str(conv.id),
                    "message_id": str(msg.id),
                    "reactions": reactions,
                },
            )
        except Exception:  # pragma: no cover — relay is optional
            pass

        return msg
