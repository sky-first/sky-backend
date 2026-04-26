"""Glossary term model — business vocabulary for the context layer.

A glossary term is a short definition of a domain concept (e.g. "GMV",
"Churn", "MAU"). Knowledge refactor Phase 5 added the 4-scope columns
(``scope`` / ``scope_id`` / ``slug``) and an ``aliases`` array so the
suggest engine and the conflict detector can look up terms by any of
their names. The legacy ``space_id`` / ``crew_id`` columns stay so
existing callers don't break — service code prefers ``scope`` when
both are populated.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.types import JSON

from src.config.database import Base


# SQLite has no native JSONB or array — fall back to JSON for both.
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    term = Column(String(255), nullable=False)
    definition = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)

    # ─── Phase 5 — 4-scope hierarchy ──────────────────────────────────
    # Nullable so legacy rows that only set space_id/crew_id keep
    # working. The Phase 5 service always populates these for new rows.
    scope = Column(String(20), nullable=True, index=True)
    scope_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    slug = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="active", server_default="active")

    aliases = Column(_JSONB_OR_JSON, nullable=False, default=list, server_default="[]")
    related_metric_ids = Column(
        _JSONB_OR_JSON, nullable=False, default=list, server_default="[]"
    )
    related_source_ids = Column(
        _JSONB_OR_JSON, nullable=False, default=list, server_default="[]"
    )

    certified_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    certified_at = Column(DateTime(timezone=True), nullable=True)

    # ─── legacy scope columns (kept for backward compat) ──────────────
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

    created_by_user_id = Column(
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
