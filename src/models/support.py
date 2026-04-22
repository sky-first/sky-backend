"""SQLAlchemy models for Sky Support JIT.

Mirror the `support_settings` and `support_sessions` tables created by
migration `add_support_settings_20260410`. The live app only issues raw
SQL against these tables (see src/api/v1/support.py), but having the
models means test fixtures that call ``Base.metadata.create_all`` on an
in-memory SQLite see the schema too — without them the support
endpoints raise OperationalError "no such table" under tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from src.config.database import Base


class SupportSettings(Base):
    __tablename__ = "support_settings"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    access_enabled = Column(Boolean, nullable=False, default=True)
    require_ticket_id = Column(Boolean, nullable=False, default=False)
    # allowed_modes is ARRAY(String) in Postgres; JSON works for SQLite too.
    allowed_modes = Column(JSON, nullable=False, default=lambda: ["read_only", "read_write_no_data"])
    auto_revoke_after_minutes = Column(Integer, nullable=False, default=240)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SupportSession(Base):
    __tablename__ = "support_sessions"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operator_id = Column(PG_UUID(as_uuid=True), nullable=False)
    ticket_id = Column(String(100), nullable=True)
    mode = Column(String(50), nullable=False)
    justification = Column(Text, nullable=True)
    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by = Column(PG_UUID(as_uuid=True), nullable=True)
