"""Tenant plan tier — singleton row identifying which plan the tenant is on.

Single-row table (id always 1) so the read path doesn't need a tenant_id.
Mirrors the platform_branding pattern. When the app becomes truly
multi-tenant, this evolves into a per-row table keyed on tenant_id and
the singleton row migrates to whichever tenant the deployment becomes.

Default value lives in the migration (`enterprise`) — picked so the
contracted dev/staging/prod environment renders the right copy even
before an admin manually sets the tier.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


class TenantPlan(Base):
    __tablename__ = "tenant_plan"

    # Singleton: id is always 1.
    id = Column(Integer, primary_key=True, default=1)

    # One of demo / free / starter / pro / enterprise. Validated at the
    # DB layer (CheckConstraint below) so an arbitrary admin patch
    # cannot stash junk values that plan_for_user would silently
    # collapse back to "starter".
    plan_tier = Column(
        String(32),
        nullable=False,
        server_default="enterprise",
    )

    updated_by_user_id = Column(UUID(as_uuid=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "plan_tier IN ('demo','free','starter','pro','enterprise')",
            name="tenant_plan_tier_check",
        ),
    )
