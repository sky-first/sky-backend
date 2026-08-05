"""Device model — the push-notification registry (BE-06).

One row per (user, push_token). A mobile client registers its push token
on login/foreground and unregisters on logout; the dispatcher fans a
push out to every live device a user owns. Tenancy is by database (each
customer has its own DB), so ``tenant_id`` is kept for spec fidelity and
auditing but is not the isolation boundary — the DB is.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class Device(Base):
    """A registered push target for one user on one device."""

    __tablename__ = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Kept for spec fidelity / auditing. Isolation is by database (one DB
    # per tenant), so this is not the boundary that keeps tenant A's
    # pushes away from tenant B — being in a different DB is.
    tenant_id = Column(UUID(as_uuid=True), nullable=True)

    platform = Column(String(10), nullable=False)  # 'ios' | 'android'
    push_token = Column(String(512), nullable=False)
    # How to reach the token: 'expo' (ExponentPushToken), 'apns', or 'fcm'.
    provider = Column(String(10), nullable=False, default="expo")

    last_seen_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user = relationship("User", backref="devices")

    __table_args__ = (
        UniqueConstraint("user_id", "push_token", name="uq_device_user_token"),
        CheckConstraint("platform IN ('ios','android')", name="ck_device_platform"),
        Index("idx_devices_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<Device(id={self.id}, user_id={self.user_id}, platform={self.platform})>"
