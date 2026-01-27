"""Starred item models."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class StarredItem(Base):
    """Starred item model."""

    __tablename__ = "starred_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), nullable=False)  # ID of the planet, space, or crew
    item_type = Column(String(50), nullable=False)  # planet, space, crew
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="starred_items")

    __table_args__ = (
        Index("idx_starred_items_user_id", "user_id", postgresql_where=deleted_at.is_(None)),
        Index(
            "idx_starred_items_item", "item_id", "item_type", postgresql_where=deleted_at.is_(None)
        ),
        # Note: Unique constraint is handled at application level to allow soft deletes
        # Multiple soft-deleted items can exist with same user_id, item_id, item_type
        # The unique constraint in the migration ensures no duplicate active starred items
    )

    def __repr__(self) -> str:
        return f"<StarredItem(id={self.id}, user_id={self.user_id}, item_id={self.item_id}, item_type={self.item_type})>"
