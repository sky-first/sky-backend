"""BeatConsumption — append-only log of every billable AI event.

Beats are the unified usage currency: 1 beat == cost of one
gpt-4o-mini call (the cheapest LLM tier). See
``src/config/plan_quotas.py::KIND_COSTS`` for the table that maps
each event ``kind`` (chat, suggest_title, agent_l1, …) to its beat
cost.

The schema is intentionally simple and append-only:
  • Each row records ONE event.
  • Aggregates (per user / per tenant / per period) are computed
    on-demand by ``BeatsService.usage_window`` summing across a
    rolling time window. No reset cron, works for any plan period.
  • ``source_id`` lets us join back to the originating row
    (ai_query.id, agent_run.id, suggestion.id) when we need to drill
    into a specific bill line.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from src.config.database import Base


class BeatConsumption(Base):
    __tablename__ = "beat_consumption"

    id = Column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    user_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # tenant_id stays nullable until the multi-tenant model lands —
    # the query path falls back to "everyone is in the single Sky
    # tenant" when None. Keep the FK target unwired here (no
    # tenants table yet) so this migration ships without depending
    # on the tenant model.
    tenant_id = Column(
        PG_UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    kind = Column(String(32), nullable=False)
    source_id = Column(PG_UUID(as_uuid=True), nullable=True)
    beats = Column(Numeric(8, 2), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index(
            "idx_beat_consumption_user_time",
            "user_id",
            text("created_at DESC"),
        ),
        Index(
            "idx_beat_consumption_tenant_time",
            "tenant_id",
            text("created_at DESC"),
        ),
        Index("idx_beat_consumption_kind", "kind"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<BeatConsumption user={self.user_id} kind={self.kind} "
            f"beats={self.beats} at={self.created_at}>"
        )
