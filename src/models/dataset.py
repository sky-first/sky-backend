"""Dataset management models."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class UserDataset(Base):
    """User dataset exclusion model - tracks which datasets (tables/files) user has excluded."""

    __tablename__ = "user_datasets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id = Column(String(255), nullable=False)  # Can be table name or file_id
    dataset_type = Column(String(50), nullable=False)  # 'table' or 'file'
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")

    # Relationships
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("user_id", "dataset_id", name="uq_user_datasets"),
        Index("idx_user_datasets_user_id", "user_id"),
        Index("idx_user_datasets_dataset_id", "dataset_id"),
    )

    def __repr__(self) -> str:
        return f"<UserDataset(id={self.id}, user_id={self.user_id}, dataset_id={self.dataset_id}, type={self.dataset_type})>"
