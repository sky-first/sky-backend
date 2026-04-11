"""Audit event model — append-only with hash chain."""

from sqlalchemy import BigInteger, Column, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.types import JSON

from src.config.database import Base

# SQLite (used in test fixtures) has no INET or JSONB types, so the schema
# compiler errors out at test collection time. Give each a SQLite-specific
# variant that falls back to a compatible type. Production (PostgreSQL) still
# uses the native type — zero migration, zero performance change.
_INET_OR_STRING = INET().with_variant(String(45), "sqlite")
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


class AuditEvent(Base):
    """Immutable audit log entry. INSERT only — UPDATE and DELETE blocked by DB triggers."""

    __tablename__ = "audit_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    # Who
    actor_kind = Column(String(50), nullable=False)  # user, api_token, service_principal, sky_support, system
    actor_id = Column(UUID(as_uuid=True), nullable=True)
    actor_email = Column(String(255), nullable=True)

    # What
    action = Column(String(100), nullable=False)  # permission key e.g. "connections.read"
    resource_kind = Column(String(50), nullable=True)  # connection, page, crew, space, ...
    resource_id = Column(String(255), nullable=True)

    # Decision
    decision = Column(String(10), nullable=False)  # "allow" or "deny"
    decision_reason = Column(Text, nullable=True)

    # Request context
    request_id = Column(UUID(as_uuid=True), nullable=True)
    ip = Column(_INET_OR_STRING, nullable=True)
    user_agent = Column(Text, nullable=True)

    # Sky Support context
    sky_session_id = Column(UUID(as_uuid=True), nullable=True)
    sky_ticket_id = Column(String(100), nullable=True)

    # Extra
    extra_data = Column("metadata", _JSONB_OR_JSON, nullable=True)

    # Hash chain for tamper detection
    prev_hash = Column(String(64), nullable=True)
    this_hash = Column(String(64), nullable=False)

    def __repr__(self) -> str:
        return f"<AuditEvent(id={self.id}, action={self.action}, decision={self.decision})>"
