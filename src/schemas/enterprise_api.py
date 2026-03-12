"""Enterprise API schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class APIField(BaseModel):
    name: str
    type: str


class APIEndpoint(BaseModel):
    path: str
    method: str
    description: Optional[str] = None
    fields: List[APIField]


class EnterpriseAPIBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    base_url: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    endpoints: List[APIEndpoint] = []


class EnterpriseAPICreate(EnterpriseAPIBase):
    pass


class EnterpriseAPIUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    description: Optional[str] = None
    endpoints: Optional[List[APIEndpoint]] = None


class EnterpriseAPIResponse(EnterpriseAPIBase):
    id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
