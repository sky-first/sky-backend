"""Tenant membership registry — the central user↔tenant mapping (BE-01).

Multi-tenancy here is DB-per-tenant, so a user's identity otherwise lives
only inside a single tenant's own database. Mobile clients don't resolve
their tenant from a sub-domain — they carry a signed ``tid`` claim in the
JWT — which means the platform needs a *central* answer to two questions:

  * "which tenants may this user act as?"      → the workspace switcher
    (``GET /auth/me/workspaces`` + ``POST /auth/select-workspace``)
  * "is this user still a member of tenant X?"  → per-request authorization
    on every device call

This table lives in the platform registry DB, next to ``tenant_registry``,
and is the single source of truth for both. Off-boarding a user is a row
delete here; the device resolver re-checks membership on every request so a
stale — but validly signed — token can never resolve to a tenant the user
has already left.

Loaded by ``src.config.database.Base`` so the tests'
``Base.metadata.create_all`` picks up the table. The Postgres server-side
schema is created by the accompanying Alembic migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


class TenantMembership(Base):
    """One row per (user, tenant) the user is allowed to act as.

    ``UUID(as_uuid=True)`` round-trips through CHAR(32) on SQLite via the
    same TypeDecorator every other model uses, so the row works unchanged in
    the in-memory test database and in Postgres.
    """

    __tablename__ = "tenant_membership"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # The user's platform identity (``users.id``). Not a hard FK because the
    # ``users`` table is a per-tenant data-plane table while this registry
    # row lives in the platform DB — the coupling is by value, enforced by
    # the login/off-boarding flows, not by a cross-database constraint.
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant_registry.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Coarse role carried into the workspace list so the client can render
    # "Owner / Admin / Member" without a second call. Not the RBAC source of
    # truth (that stays per-tenant); purely descriptive here.
    role = Column(String(32), nullable=False, default="member")

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_tenant_membership_user_tenant"),
        Index("idx_tenant_membership_user", "user_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<TenantMembership user={self.user_id} tenant={self.tenant_id} " f"role={self.role}>"
        )
