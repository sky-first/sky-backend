"""Promotion-flow models — Knowledge refactor Phase 4.

A promotion takes a Metric (or — Phase 5 — a GlossaryTerm) from one
scope to a wider one (Personal → Crew → Space → Org). Three tables:

    promotion_requests        — the parent envelope (status, requester,
                                 target scope)
    promotion_request_items   — primary + dependency rows. Dependencies
                                 are resolved at request-creation time
                                 (e.g. the metric's data source must
                                 also be shared at the target scope).
    knowledge_conflicts       — collision detector output. ≥75% fuzzy
                                 match on name OR alias overlap with an
                                 existing entity at the target scope
                                 generates a row here, and Owner must
                                 decide keep / replace / merge before
                                 the promotion can complete.

Status lattice: ``pending → approved`` (success), ``pending →
rejected`` (manual), ``pending → conflict_pending → approved/rejected``
when a conflict needs to be resolved first.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


PROMOTION_STATUSES = (
    "pending",
    "conflict_pending",
    "approved",
    "rejected",
)

PROMOTION_ITEM_KINDS = ("metric", "source", "glossary_term", "relationship")
PROMOTION_ITEM_ROLES = ("primary", "dependency")

CONFLICT_DECISIONS = ("keep_canonical", "replace_canonical", "merge_alias")


class PromotionRequest(Base):
    __tablename__ = "promotion_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requester_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    target_scope = Column(String(20), nullable=False)
    target_scope_id = Column(UUID(as_uuid=True), nullable=True)

    status = Column(String(30), nullable=False, default="pending")
    note = Column(String(2000), nullable=True)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_promotion_requests_status", "status"),
        Index("ix_promotion_requests_target", "target_scope", "target_scope_id"),
    )


class PromotionRequestItem(Base):
    __tablename__ = "promotion_request_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("promotion_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kind = Column(String(30), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    role = Column(String(20), nullable=False, default="dependency")

    # Snapshot of the user-facing label at request time, so the
    # approver UI can render even if the source row is renamed mid-
    # review.
    label = Column(String(255), nullable=True)


class KnowledgeConflict(Base):
    __tablename__ = "knowledge_conflicts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("promotion_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The proposed entity (the metric being promoted) and the
    # existing entity at the target scope it collides with.
    proposed_kind = Column(String(30), nullable=False, default="metric")
    proposed_entity_id = Column(UUID(as_uuid=True), nullable=False)
    canonical_kind = Column(String(30), nullable=False, default="metric")
    canonical_entity_id = Column(UUID(as_uuid=True), nullable=False)

    similarity = Column(Numeric, nullable=False)
    reason = Column(String(255), nullable=True)  # "name_match" / "alias_overlap" / …

    decision = Column(String(40), nullable=True)  # null until resolved
    decided_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
