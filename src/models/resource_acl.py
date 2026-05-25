"""resource_acl model — explicit per-resource sharing.

Companion to the new Authorization resolver. Lets a resource (connection,
dashboard, agent, knowledge file, …) carry explicit grants that override
the Space-default level for specific principals.

Resolution rule (effective level for `(user, resource)`):

  effective_level = max(
      space_member_level(user, resource.space)         # default per Space
      explicit_user_grant(user, resource)              # this row
      explicit_space_grant(any space the user is in)   # this row, principal_type='space'
      tenant_default_grant(resource)                   # this row, principal_type='tenant'
  )

A `tenant` grant has `principal_id IS NULL` — it applies to every user
in the tenant. A `space` grant applies to every member of that Space at
their existing membership level capped to the grant's level.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


class ResourceAcl(Base):
    __tablename__ = "resource_acl"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_type = Column(String(32), nullable=False)
    resource_id = Column(UUID(as_uuid=True), nullable=False)
    principal_type = Column(String(16), nullable=False)
    principal_id = Column(UUID(as_uuid=True), nullable=True)
    level = Column(String(16), nullable=False)
    granted_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    granted_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "resource_type IN ('connection','dashboard','agent','knowledge_file','space','widget','page')",
            name="ck_resource_acl_resource_type",
        ),
        CheckConstraint(
            "principal_type IN ('user','space','tenant')",
            name="ck_resource_acl_principal_type",
        ),
        CheckConstraint(
            "level IN ('viewer','editor','owner')",
            name="ck_resource_acl_level",
        ),
        CheckConstraint(
            "(principal_type = 'tenant' AND principal_id IS NULL) "
            "OR (principal_type IN ('user','space') AND principal_id IS NOT NULL)",
            name="ck_resource_acl_principal_consistency",
        ),
        Index("ix_resource_acl_resource", "resource_type", "resource_id"),
        Index("ix_resource_acl_principal", "principal_type", "principal_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ResourceAcl({self.resource_type}/{self.resource_id} → "
            f"{self.principal_type}/{self.principal_id} = {self.level})>"
        )
