"""Per-user review/pin state for insight findings (BE-02, Sky Mobile).

A finding (``agent_findings`` row) is shared content, but "I reviewed this" and
"I pinned this" are **per-user** signals — two people looking at the same feed
keep their own state. This table holds exactly that: one row per (user,
finding) that the user has ever reviewed or pinned. Absence of a row means
neither.

Kept separate from ``AgentFinding`` on purpose: the finding is produced by the
engine and is immutable content; the review/pin state is user interaction and
must not race with or bloat the finding row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


class InsightState(Base):
    __tablename__ = "insight_state"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    finding_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_findings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL = not reviewed / not pinned. A timestamp = when the user did it.
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    pinned_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "finding_id", name="uq_insight_state_user_finding"),
        Index("idx_insight_state_user", "user_id"),
    )
