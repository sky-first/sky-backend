"""Connection schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConnectionBase(BaseModel):
    """Base connection schema."""

    name: str = Field(..., min_length=1, max_length=255)
    connector_id: str = Field(..., description="Connector type (postgresql, mysql, mongodb, etc)")
    description: Optional[str] = None
    sync_frequency: Optional[str] = Field(None, description="Cron expression for sync frequency")


class ConnectionCreate(ConnectionBase):
    """Connection creation schema."""

    config: Dict[str, Any] = Field(..., description="Connection configuration (credentials, etc)")


class ConnectionUpdate(BaseModel):
    """Connection update schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    sync_frequency: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|inactive|error)$")


class ConnectionResponse(ConnectionBase):
    """Connection response schema."""

    id: UUID
    status: str
    last_sync: Optional[datetime] = None
    next_sync: Optional[datetime] = None
    last_metadata_update: Optional[datetime] = None
    error: Optional[Dict[str, Any]] = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConnectionTestResponse(BaseModel):
    """Connection test response schema."""

    success: bool
    message: str
    latency: Optional[int] = Field(None, description="Latency in milliseconds")


class ConnectionSyncResponse(BaseModel):
    """Connection sync response schema."""

    success: bool
    last_sync: Optional[datetime] = None
    next_sync: Optional[datetime] = None
    message: Optional[str] = None


class ColumnMetadataSchema(BaseModel):
    """Column metadata schema."""

    name: str
    type: str
    nullable: bool = True
    description: Optional[str] = None


class TableMetadataSchema(BaseModel):
    """Table metadata schema."""

    name: str
    schema_name: Optional[str] = Field(None, alias="schema", description="Database schema name")
    row_count: Optional[int] = None
    columns: Optional[List[ColumnMetadataSchema]] = None
    last_updated: Optional[datetime] = None

    model_config = ConfigDict(populate_by_name=True)


class ConnectionMetadataResponse(BaseModel):
    """Connection metadata response schema."""

    tables: List[TableMetadataSchema] = []
    schemas: List[str] = []
    last_metadata_update: Optional[datetime] = None


class ConnectionStatusResponse(BaseModel):
    """Connection status response schema."""

    status: str
    last_sync: Optional[datetime] = None
    next_sync: Optional[datetime] = None
    error: Optional[Dict[str, Any]] = None
    is_healthy: bool


class ConnectionValidateResponse(BaseModel):
    """Connection validation response schema."""

    valid: bool
    message: str
    errors: Optional[List[str]] = None
