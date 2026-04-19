"""Glossary term model — business vocabulary for the context layer.

A glossary term is a short definition of a domain concept (e.g. "GMV",
"Churn", "MAU") scoped to a Space / Crew. Terms are projected into
``context_documents`` with kind=``glossary`` by the context-event
emitter so retrieval can cite them alongside connections and strategy.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    term = Column(String(255), nullable=False)
    definition = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)

    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    owner_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("space_id", "crew_id", "term", name="uq_glossary_scope_term"),
    )
