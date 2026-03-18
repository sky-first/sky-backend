"""File upload schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FileUploadResponse(BaseModel):
    """File upload response schema."""

    file_id: UUID
    url: str
    type: str  # mime_type
    size: int  # bytes
    filename: str
    original_name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CSVUploadResponse(BaseModel):
    """CSV upload response schema."""

    file_id: UUID
    data: List[Dict[str, Any]] = Field(description="Parsed CSV data")
    columns: List[str] = Field(description="Column names")
    preview: List[Dict[str, Any]] = Field(description="First 10 rows")
    url: str
    type: str
    size: int
    created_at: datetime


class ExcelUploadResponse(BaseModel):
    """Excel upload response schema."""

    file_id: UUID
    data: Dict[str, List[Dict[str, Any]]] = Field(
        description="Parsed Excel data by sheet name"
    )
    sheets: List[str] = Field(description="Sheet names")
    columns: Dict[str, List[str]] = Field(description="Column names by sheet")
    preview: Dict[str, List[Dict[str, Any]]] = Field(
        description="First 10 rows by sheet"
    )
    url: str
    type: str
    size: int
    created_at: datetime


class FileResponse(BaseModel):
    """File response schema."""

    id: UUID
    filename: str
    original_name: str
    mime_type: str
    size: int
    url: str
    storage: str
    widget_id: Optional[UUID] = None
    parsed_data: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
