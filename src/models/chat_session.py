"""ChatSession model — a named chat container ("Chat 1", "Chat 2", …) on a page.

A page owns a shared canvas (widgets/dashboard) AND one or more chat sessions.
Each session groups its own conversations/threads so the timeline stays clean
even over months of use — the user clicks "+" to open a fresh session and can
switch between them without leaving the page or touching the canvas.

Sessions are SHARED at the page/space/crew level (same visibility model as
``Conversation``): in a collaborative space every member sees the same
Chat 1 / Chat 2 / … so a widget's "from Chat 3" provenance chip resolves for
everyone. Personal pages have a single-member scope, so sharing is a no-op
there.
"""

import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


class ChatSession(Base):
    """A named chat container scoped to a page (and optionally a space/crew)."""

    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Collaborative scope — inherited from the page on create. Drives the
    # same space/crew visibility rules ``Conversation`` uses, so every
    # member of the room sees the same set of chats.
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(String(500), nullable=True)
    # Ordering within the page so the switcher renders "Chat 1, 2, 3…" in a
    # stable order independent of created_at clock skew across peers.
    position = Column(Integer, nullable=False, server_default=text("0"))
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    # Soft-archive (Phase 1 does not hard-delete sessions — archiving hides
    # the chat from the default switcher while keeping its threads intact).
    archived_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ChatSession(id={self.id}, page_id={self.page_id}, title={self.title})>"
