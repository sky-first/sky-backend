"""Enterprise Graph Models."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import JSON

from src.config.database import Base


class EnterpriseGraphNode(Base):
    """Enterprise Graph Node representation."""

    __tablename__ = "enterprise_graph_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False)
    type = Column(String(100), nullable=False)
    properties = Column(JSON, nullable=True, default=dict)
    
    # Audit info
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
        onupdate=datetime.utcnow,
    )


class EnterpriseGraphEdge(Base):
    """Enterprise Graph Edge representation."""

    __tablename__ = "enterprise_graph_edges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(UUID(as_uuid=True), ForeignKey("enterprise_graph_nodes.id", ondelete="CASCADE"), nullable=False)
    target = Column(UUID(as_uuid=True), ForeignKey("enterprise_graph_nodes.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(50), nullable=False)
    type = Column(String(100), nullable=False)
    properties = Column(JSON, nullable=True, default=dict)

    # Audit info
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
        onupdate=datetime.utcnow,
    )

    # Note: Source and Target relationships are implicit via ForeignKey
