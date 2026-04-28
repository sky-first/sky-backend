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

import hashlib
import json
import uuid
from enum import Enum
from typing import Any, Mapping, Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON, TypeDecorator

from src.config.database import Base

# SQLite has no native ARRAY / JSONB — fall back to JSON in tests so the
# metadata still creates. The production dialect (PostgreSQL) keeps the
# native types. Same pattern used by `src/models/agent.py`.
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


class _UUIDJsonList(TypeDecorator):
    """JSON column that transparently stores a list of UUIDs as strings.

    Used only on SQLite — PG keeps native ``UUID[]``. The ORM layer sees
    ``list[UUID]``; on the wire we store ``list[str]``. Read-back goes
    through the ACL helpers that already coerce str→UUID, so no behaviour
    change at the application boundary.
    """

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return []
        return [str(v) if isinstance(v, uuid.UUID) else v for v in value]

    def process_result_value(self, value, dialect):
        return value or []


def _array_with_sqlite_variant(inner_type):
    # When the ARRAY contains UUIDs, the SQLite JSON fallback can't serialize
    # them natively — fall back to the UUID-aware JSON type decorator.
    is_uuid_inner = (
        isinstance(inner_type, UUID)
        or (isinstance(inner_type, type) and inner_type is UUID)
    )
    sqlite_variant = _UUIDJsonList() if is_uuid_inner else JSON()
    return ARRAY(inner_type).with_variant(sqlite_variant, "sqlite")


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
    # Multi-crew ACL — W1 of chat/agent master plan §2.3. Legacy single
    # ``crew_id`` stays for backward compat; new retrieval path uses ``crew_ids``
    # so a single embedding can be shared by multiple crews without duplicating.
    crew_ids = Column(
        _array_with_sqlite_variant(UUID(as_uuid=True)),
        nullable=False,
        default=list,
    )
    owner_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    visibility = Column(String(16), nullable=False, default="space")

    # SHA-256 of (kind, title, body, meta) — dedup key for ingest worker.
    # Not unique by itself (same content can legitimately live in two
    # spaces with different ACL); the ingest worker queries by
    # (kind, content_hash, space_id) before inserting.
    content_hash = Column(String(64), nullable=False, default="")

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
        Index("ix_context_documents_content_hash", "content_hash"),
    )

    # ------------------------------------------------------------------
    #  Content hash helpers (W1 of chat/agent master plan §2)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_content_hash(
        kind: str,
        title: str,
        body: str,
        meta: Optional[Mapping[str, Any]],
    ) -> str:
        """Deterministic SHA-256 over the content that the ingest worker
        considers "the same document". Must be stable across interpreters
        (``json.dumps(sort_keys=True)``) and across ``meta`` key insertion
        order so two equal dicts produce the same hash.

        Security note: this hashes RAW bytes — sanitization is strictly a
        render-time concern. Hashing after a naive strip would let an
        attacker poison a cached row with a visually-different body that
        collapses to the same hash.
        """
        normalized_meta: Mapping[str, Any] = meta or {}
        payload = json.dumps(
            {
                "kind": kind,
                "title": title,
                "body": body,
                "meta": normalized_meta,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _compute_and_set_content_hash(target: ContextDocument) -> None:
    """Recompute content_hash from (kind, title, body, meta). Called from
    ``before_insert`` (only if unset — backfill can pin a specific hash)
    and from ``before_update`` (always, so body edits re-key dedup)."""
    target.content_hash = ContextDocument.compute_content_hash(
        target.kind or "",
        target.title or "",
        target.body or "",
        target.meta or {},
    )


def _mirror_legacy_crew_id(target: ContextDocument) -> None:
    """If caller sets the legacy single ``crew_id`` but leaves ``crew_ids``
    empty, mirror it into the array so retrieval can uniformly query
    ``crew_ids``. Reverse (``crew_ids`` set, ``crew_id`` empty) is not
    auto-populated — single-col is deprecated for writes."""
    if target.crew_id and not target.crew_ids:
        target.crew_ids = [target.crew_id]


@event.listens_for(ContextDocument, "before_insert")
def _context_doc_before_insert(mapper, connection, target: ContextDocument) -> None:
    # Respect caller-provided hash (used by migration backfill).
    if not target.content_hash:
        _compute_and_set_content_hash(target)
    _mirror_legacy_crew_id(target)


@event.listens_for(ContextDocument, "before_update")
def _context_doc_before_update(mapper, connection, target: ContextDocument) -> None:
    # On update, the body/title/kind/meta may have changed — always
    # recompute. ``pii_flags``, ``visibility``, ACL columns and lifecycle
    # columns do NOT contribute to the hash (they're scope metadata, not
    # content). SQLAlchemy fires before_update on any mapped attr change;
    # we still recompute but the result stays the same if content didn't
    # change — property of SHA-256 determinism.
    _compute_and_set_content_hash(target)
    _mirror_legacy_crew_id(target)
