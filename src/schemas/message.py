"""Message schemas — request/response shapes for messages inside a conversation."""

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MessageCreate(BaseModel):
    """Payload to append a message to a conversation.

    Callers can only create messages with role='user'. Assistant / system
    messages are produced internally (by the AI service callback in Phase 2,
    or by the agent runtime). The validator below rejects anything else.

    ``kind`` further qualifies the message inside the collaborative-thread
    semantics (chat-threads-master-plan PR1):
      - question → owner asks AI (fires a build job)
      - comment  → non-owner discussion; AI doesn't reply directly
    ``ai_response`` and ``system`` are server-produced and rejected if a
    client tries to set them.
    """

    role: str = Field(default="user", pattern="^(user|assistant|system)$")
    kind: Optional[str] = Field(default=None, pattern="^(question|comment)$")
    content: str = Field(..., min_length=1, max_length=100_000)
    query_id: Optional[UUID] = None
    cost_tokens: Optional[int] = Field(None, ge=0)
    cost_usd: Optional[Decimal] = Field(None, ge=0)
    parent_message_id: Optional[UUID] = None


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    kind: Optional[str] = None
    content: str
    # Author of the message. ``user_id`` is the writer's user id (NULL for
    # assistant/system messages); ``author_name`` is their display name,
    # resolved server-side so collaborators always see the REAL author
    # instead of their own name in a shared (space/crew) chat. Both are
    # None for AI/system messages and for legacy rows with no author.
    user_id: Optional[UUID] = None
    author_name: Optional[str] = None
    query_id: Optional[UUID]
    cost_tokens: Optional[int]
    cost_usd: Optional[Decimal]
    # BE-04 (Sky Mobile) — how the message was created. 'voice' turns render a
    # mic glyph in the transcript; ``duration_ms`` is set for spoken turns.
    origin: str = "text"
    duration_ms: Optional[int] = None
    created_at: datetime
    pinned_widget_id: Optional[UUID]
    parent_message_id: Optional[UUID] = None
    incorporated_in_message_id: Optional[UUID] = None
    # O achado que esta mensagem apresenta (respostas de agente). O cliente usa
    # isto para desenhar o cartao com grafico em vez de um paragrafo de texto.
    finding_id: Optional[UUID] = None
    # Slack-style reactions: {"emoji": ["user_id", …]}. Empty dict
    # when no one reacted. FE derives counts and "did I react?" from
    # this shape.
    reactions: Dict[str, List[str]] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class ReactionToggleRequest(BaseModel):
    """Toggle a single emoji reaction on a message for the current user.

    The endpoint adds the user to the emoji's list if absent, removes
    them if present. Idempotent on the resulting state — useful for
    optimistic UI that may retry.
    """

    emoji: str = Field(..., min_length=1, max_length=16)


class MessageListResponse(BaseModel):
    items: List[MessageResponse]
    # Messages paginate by created_at ascending (oldest first) so the
    # frontend can render them in thread order without reversing.
    next_cursor: Optional[datetime] = None


class PinRequest(BaseModel):
    """Materialise a widget pinned to this message."""

    page_id: UUID
    title: Optional[str] = Field(None, max_length=255)
    widget_type: str = Field(default="insight", max_length=50)
    position: Optional[dict] = None  # {x, y}
    size: Optional[dict] = None  # {width, height}


class ForkRequest(BaseModel):
    """Branch a conversation from a specific message."""

    from_message_id: UUID


class AskAIBundleRequest(BaseModel):
    """Owner fires Ask-AI with bundled comments (chat-threads PR2).

    The FE sends the question text + (optionally) the AI's answer text;
    server inserts both as messages, stamps any pending comments as
    incorporated into the new ai_response, and returns the bundle.

    For wave 1 the AI text is computed by the existing AI pipeline on
    the FE side and shipped here for persistence. PR4 will move the
    AI call server-side and broadcast over WebSocket.
    """

    question: str = Field(..., min_length=1, max_length=100_000)
    ai_answer: str = Field(..., min_length=1, max_length=200_000)
    query_id: Optional[UUID] = None
    tier: Optional[str] = None
    duration_ms: Optional[int] = Field(None, ge=0)
    cost_tokens: Optional[int] = Field(None, ge=0)
    cost_usd: Optional[Decimal] = Field(None, ge=0)


class AskAIBundleResponse(BaseModel):
    question: MessageResponse
    ai_response: MessageResponse
    incorporated_message_ids: List[UUID]


class BundledPromptResponse(BaseModel):
    """Preview the prompt that *would* be sent to the LLM if the owner
    hit Ask AI right now. Used by the FE chip "X comments will be
    included" — the owner can see exactly what the LLM will receive."""

    prompt: str
    incorporated_count: int
