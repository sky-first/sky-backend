"""Per-user permission grants — Knowledge refactor Phase 3.

Used to delegate Owner-default permissions (e.g. ``knowledge.certify``)
to specific users without making them tenant Owner. Avoids the cliff
of "either you're Owner, or you can't certify Org metrics" — Lucas's
explicit Phase 0 ratification: the CEO might be Owner but the CFO
should run governance.

Schema mirrors KNOWLEDGE_REFACTOR.md §6:

    id, user_id, permission, granted_by_user_id, granted_at, revoked_at

Soft-revoke via ``revoked_at`` so we have a forensic trail of who had
what when.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


# Permission keys delegable through this table. Keep stable — they are
# stored as strings in the DB and auditing pipelines pin against them.
PERMISSION_KNOWLEDGE_CERTIFY = "knowledge.certify"

GRANTABLE_PERMISSIONS = (
    PERMISSION_KNOWLEDGE_CERTIFY,
)


class UserPermissionGrant(Base):
    """A live grant of a delegable permission to a specific user."""

    __tablename__ = "user_permission_grants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission = Column(String(100), nullable=False)

    granted_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    granted_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # A user can have many historical grants of the same permission
        # (granted, revoked, granted again). The "live grant" check has
        # to be (user_id, permission, revoked_at IS NULL) — that filter
        # lives in the service layer because partial unique indexes
        # don't round-trip on SQLite. The plain unique constraint here
        # keeps the DB sane without requiring partial indexes.
        Index(
            "ix_user_permission_grants_user_permission",
            "user_id",
            "permission",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        suffix = "live" if self.revoked_at is None else "revoked"
        return (
            f"<UserPermissionGrant(user={self.user_id}, "
            f"permission={self.permission}, {suffix})>"
        )
