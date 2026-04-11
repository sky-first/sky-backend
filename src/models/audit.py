"""Audit event model — append-only with hash chain."""

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.types import JSON

from src.config.database import Base

# SQLite (used in test fixtures) has no INET or JSONB types, so the schema
# compiler errors out at test collection time. Give each a SQLite-specific
# variant that falls back to a compatible type. Production (PostgreSQL) still
# uses the native type — zero migration, zero performance change.
_INET_OR_STRING = INET().with_variant(String(45), "sqlite")
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")

# SQLite only treats a primary-key column as the auto-incrementing ROWID alias
# when the declared type is literally `INTEGER`. `BIGINT PRIMARY KEY` becomes a
# normal NOT NULL column with no autogen, which is exactly what blew up the
# unit-test matrix: every INSERT into audit_events failed with
# `NOT NULL constraint failed: audit_events.id`, the session rolled back, and
# the rate-limit middleware then deadlocked the asyncio loop on a poisoned
# connection. Variant swap keeps BIGINT on PostgreSQL, INTEGER on SQLite.
_BIGINT_OR_INT_PK = BigInteger().with_variant(Integer(), "sqlite")


class AuditEvent(Base):
    """Immutable audit log entry. INSERT only — UPDATE and DELETE blocked by DB triggers."""

    __tablename__ = "audit_events"

    id = Column(_BIGINT_OR_INT_PK, primary_key=True, autoincrement=True)
    # CURRENT_TIMESTAMP is SQL standard and works on both PostgreSQL and SQLite.
    # now() is PostgreSQL-specific and breaks the sqlite test fixture.
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

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
