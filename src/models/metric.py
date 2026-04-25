"""Metric model — Knowledge refactor Phase 2.

A Metric is the unified "measurable thing with a formula" that replaces
the old Pillar / Goal / OKR / KeyResult / Initiative / Risk / Cycle /
Assumption ladder. The folded-in entities map onto attributes of a
single row:

  * Pillar              → ``tags`` (JSONB array of strings)
  * OKR / KeyResult     → ``target_value`` + ``target_date``
  * Risk                → ``threshold_warning`` + ``threshold_critical``
  * Initiative / Cycle  → modelled as Metric ``status`` transitions

Scope follows the 4-level hierarchy from KNOWLEDGE_REFACTOR.md:

    personal  → owner_user only sees it
    crew      → all crew members see it
    space     → all members of the space see it
    org       → everyone in the tenant sees it (Owner-certified)

See sky-security/docs/KNOWLEDGE_REFACTOR.md §2 + §6 for the full plan;
the equivalent contract tests live in
``src/tests/knowledge/test_knowledge_*``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.types import JSON

from src.config.database import Base

# SQLite has no native JSONB — fall back to JSON in tests so the column
# round-trips identically across both dialects.
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


METRIC_SCOPES = ("personal", "crew", "space", "org")
METRIC_STATUSES = ("draft", "active", "deprecated")
METRIC_LANGUAGES = ("sql", "describe")


class Metric(Base):
    """Unified measurable concept — formula, target, threshold, tags."""

    __tablename__ = "metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Scope ----------------------------------------------------------------
    # ``scope_id`` is NULL for ``scope='org'``. For everything else it
    # points to the user/crew/space that owns the row. We don't FK it
    # here because the target table varies — the application enforces
    # the (scope, scope_id) invariant in the service layer.
    scope = Column(String(20), nullable=False)
    scope_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="draft")

    # Formula --------------------------------------------------------------
    # ``formula_text`` is the resolved SQL. ``formula_description`` is
    # the original natural-language prompt when the user authored the
    # metric in Describe mode. ``formula_language`` distinguishes the
    # two so the UI can offer the right editor.
    formula_text = Column(Text, nullable=True)
    formula_description = Column(Text, nullable=True)
    formula_language = Column(String(20), nullable=False, default="sql")

    # Source binding -------------------------------------------------------
    # FKs ``data_connections`` today; will follow the ``data_source``
    # rename in Phase 1c. ``ON DELETE SET NULL`` keeps the metric
    # discoverable even after the source is unhooked.
    source_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_table = Column(String(255), nullable=True)
    source_column = Column(String(255), nullable=True)

    # Semantic attributes --------------------------------------------------
    aggregation = Column(String(30), nullable=True)
    unit = Column(String(30), nullable=True)
    time_grain = Column(String(20), nullable=True)

    # Folded-in entities ---------------------------------------------------
    target_value = Column(Numeric, nullable=True)
    target_date = Column(Date, nullable=True)
    threshold_warning = Column(Numeric, nullable=True)
    threshold_critical = Column(Numeric, nullable=True)
    tags = Column(_JSONB_OR_JSON, nullable=False, default=list)

    # Provenance + audit ---------------------------------------------------
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
    updated_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    certified_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    certified_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Soft-delete-aware uniqueness is enforced in the service layer
        # because SQLite (used in tests) doesn't support partial indexes
        # the same way Postgres does. The plain UNIQUE here keeps the
        # invariant for live rows, and the service layer skips the
        # collision check on rows where ``deleted_at IS NOT NULL``.
        UniqueConstraint("scope", "scope_id", "slug", name="uq_metrics_scope_slug"),
        Index("ix_metrics_scope_scope_id", "scope", "scope_id"),
        Index("ix_metrics_status", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        return f"<Metric(id={self.id}, name={self.name}, scope={self.scope})>"
