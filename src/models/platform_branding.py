"""Platform branding — owner-controlled tenant-wide visual config.

Single-row table (id always 1) so we don't need to thread a tenant_id
through the read path. The model is read by every authenticated user
on app boot and written only by the tenant Owner.
"""

import uuid

from sqlalchemy import JSON, Column, DateTime, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


class PlatformBranding(Base):
    """Tenant-wide branding config (logo, colors, font, radius).

    The row is created lazily by the service the first time the Owner
    saves changes — until then, the API returns the in-code defaults
    so a fresh deployment doesn't 404.
    """

    __tablename__ = "platform_branding"

    # Single-row table: id is always 1. Modeled as Integer rather than
    # UUID to make the upsert pattern (``INSERT ... ON CONFLICT (id) DO UPDATE``)
    # trivial and to make it visually obvious in the DB that this isn't
    # a per-row entity.
    id = Column(Integer, primary_key=True, default=1)

    # Hex color (e.g. "#1e3a5f"). Validated at the schema layer.
    primary_color = Column(String(9), nullable=False, server_default="#1e3a5f")

    # Border radius in px applied as the base of all rounded-* utilities.
    radius = Column(Integer, nullable=False, server_default="10")

    # Font family token — one of the front-end's enum values
    # ("geist" | "inter" | "dm-sans" | "plus-jakarta" | "outfit").
    font_family = Column(String(32), nullable=False, server_default="geist")

    # Logo data: either a data URL (small uploaded image) or a public
    # path. Nullable since fresh tenants have no logo. JSON-typed so we
    # can later evolve to ``{light: ..., dark: ...}`` without a migration.
    logo_url = Column(JSON, nullable=True)

    # Customer-facing product name shown in topbar + login page.
    company_name = Column(String(255), nullable=False, server_default="SkyFirstLabs")

    # Audit trail — who changed what, when. Read by no business logic
    # right now but useful for compliance reviews.
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
