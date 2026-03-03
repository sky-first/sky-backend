from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EnterpriseGraphNodeBase(BaseModel):
    label: str
    category: str
    type: str
    properties: Optional[Dict[str, Any]] = Field(default_factory=dict)


class EnterpriseGraphNodeCreate(EnterpriseGraphNodeBase):
    pass


class EnterpriseGraphNodeUpdate(BaseModel):
    label: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None


class EnterpriseGraphNodeResponse(EnterpriseGraphNodeBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class EnterpriseGraphEdgeBase(BaseModel):
    source: UUID
    target: UUID
    category: str
    type: str
    properties: Optional[Dict[str, Any]] = Field(default_factory=dict)


class EnterpriseGraphEdgeCreate(EnterpriseGraphEdgeBase):
    pass


class EnterpriseGraphEdgeUpdate(BaseModel):
    category: Optional[str] = None
    type: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None


class EnterpriseGraphEdgeResponse(EnterpriseGraphEdgeBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class EnterpriseGraphDataResponse(BaseModel):
    nodes: List[EnterpriseGraphNodeResponse]
    edges: List[EnterpriseGraphEdgeResponse]
