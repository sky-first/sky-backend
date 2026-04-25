"""Ticket model — customer-raised support tickets.

Distinct from ``support_sessions`` (operator JIT access). A ticket is
raised by the customer when something goes wrong (chat error, agent
failure, suspected bug, security concern). Visible internally to space
admins / workspace owner. Owner can escalate to Sky team review.
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.types import JSON

from src.config.database import Base

_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


class TicketCategory(str, Enum):
    CHAT_ERROR = "chat_error"
    AGENT_ERROR = "agent_error"
    BUG = "bug"
    FEATURE_REQUEST = "feature_request"
    SECURITY = "security"
    OTHER = "other"


class TicketSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TicketStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    ESCALATED = "escalated"


class TicketEventKind(str, Enum):
    CREATED = "created"
    COMMENTED = "commented"
    STATUS_CHANGED = "status_changed"
    ASSIGNED = "assigned"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    REOPENED = "reopened"


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    reporter_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=False, default="")
    category = Column(String(32), nullable=False, default="other")
    severity = Column(String(16), nullable=False, default="medium")
    status = Column(String(16), nullable=False, default="open", index=True)

    assigned_to_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Escalation — when admin/owner pushes to Sky team review.
    escalated_at = Column(DateTime(timezone=True), nullable=True)
    escalated_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    external_ref = Column(String(64), nullable=True)

    # Free-form context the FE attaches (chat trace_id, query_id, page,
    # widget, agent run, browser/UA, etc.). Capped at ~16 KiB by the
    # service layer to avoid log/DB bloat.
    context = Column("context_jsonb", _JSONB_OR_JSON, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "category in ('chat_error','agent_error','bug','feature_request','security','other')",
            name="ck_tickets_category",
        ),
        CheckConstraint(
            "severity in ('low','medium','high','critical')",
            name="ck_tickets_severity",
        ),
        CheckConstraint(
            "status in ('open','in_progress','resolved','closed','escalated')",
            name="ck_tickets_status",
        ),
        Index("ix_tickets_reporter", "reporter_user_id"),
        Index("ix_tickets_space", "space_id"),
        Index("ix_tickets_status_created", "status", "created_at"),
    )


class TicketEvent(Base):
    __tablename__ = "ticket_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind = Column(String(32), nullable=False)
    payload = Column("payload_jsonb", _JSONB_OR_JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind in ('created','commented','status_changed','assigned',"
            "'escalated','resolved','reopened')",
            name="ck_ticket_events_kind",
        ),
        Index("ix_ticket_events_ticket_created", "ticket_id", "created_at"),
    )
