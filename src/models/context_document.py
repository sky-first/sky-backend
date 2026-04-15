"""Context Layer — the brain.

A single table holds a vectorised, RBAC-scoped representation of every
domain entity in Sky: connections, tables, columns, business rules
(strategy items), events (signals), relationships, platform fabric
(users, crews, spaces, memberships), and outputs (pins, widgets,
conversations, messages, likes).

This is the foundation of Phase 2 of the agent master plan. See
`docs/agent-and-ai-master-plan.md` §3.6.
"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from src.config.database import Base

# SQLite has no native ARRAY / JSONB — fall back to JSON in tests so the
# metadata still creates. The production dialect (PostgreSQL) keeps the
# native types. Same pattern used by `src/models/agent.py`.
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


def _array_with_sqlite_variant(inner_type):
    return ARRAY(inner_type).with_variant(JSON(), "sqlite")


class ContextDocumentKind(str, Enum):
    # Connections
    CONNECTION = "connection"
    TABLE = "table"
    COLUMN = "column"
    # Business Rules (Strategy)
    PILLAR = "pillar"
    GOAL = "goal"
    OKR = "okr"
    INITIATIVE = "initiative"
    RISK = "risk"
    KPI = "kpi"
    GLOSSARY = "glossary"
    # Events (Signals)
    EVENT_INTERNAL = "event_internal"
    EVENT_EXTERNAL = "event_external"
    EVENT_TREND = "event_trend"
    EVENT_MACRO = "event_macro"
    # Relationships
    RELATIONSHIP = "relationship"
    # Platform fabric
    USER = "user"
    ROLE = "role"
    SPACE = "space"
    CREW = "crew"
    MEMBERSHIP = "membership"
    # Outputs & social
    PIN = "pin"
    WIDGET = "widget"
    INSIGHT = "insight"
    CONVERSATION = "conversation"
    MESSAGE = "message"
    LIKE = "like"


class ContextDocumentVisibility(str, Enum):
    PUBLIC = "public"
    SPACE = "space"
    CREW = "crew"
    USER = "user"


class ContextDocument(Base):
    __tablename__ = "context_documents"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # What this document describes
    kind = Column(String(32), nullable=False)
    source_id = Column(
        UUID(as_uuid=True),
        nullable=False,
    )
    source_table = Column(String(64), nullable=False)

    # Rendered content used for embedding and evidence display
    title = Column(String(512), nullable=False)
    body = Column(Text, nullable=False)
    meta = Column("metadata_jsonb", _JSONB_OR_JSON, nullable=False, default=dict)

    # RBAC scope — mirror of the source row's scope
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="CASCADE"),
        nullable=True,
    )
    owner_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    visibility = Column(String(16), nullable=False, default="space")

    # Content signals
    # embedding column is created in the migration directly (vector(1536) in
    # production, falls back to JSON on SQLite). The ORM exposes it as a raw
    # column with no type — code paths that touch it (ingest / retrieval) run
    # in the AI service against Postgres, never through the SQLite test bed.
    pii_flags = Column(_array_with_sqlite_variant(String), nullable=False, default=list)
    language = Column(String(8), nullable=False, default="pt")

    # Lifecycle
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    indexed_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "kind in ("
            "'connection','table','column',"
            "'pillar','goal','okr','initiative','risk','kpi','glossary',"
            "'event_internal','event_external','event_trend','event_macro',"
            "'relationship',"
            "'user','role','space','crew','membership',"
            "'pin','widget','insight','conversation','message','like'"
            ")",
            name="ck_context_documents_kind",
        ),
        CheckConstraint(
            "visibility in ('public','space','crew','user')",
            name="ck_context_documents_visibility",
        ),
        Index(
            "ix_context_documents_source",
            "source_table",
            "source_id",
            unique=True,
        ),
        Index("ix_context_documents_scope", "space_id", "crew_id", "kind"),
        Index("ix_context_documents_kind", "kind"),
        Index("ix_context_documents_alive", "deleted_at"),
    )
