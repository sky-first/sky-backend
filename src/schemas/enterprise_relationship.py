"""Enterprise Relationship schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


class SourceEntity(BaseModel):
    id: str
    type: str
    details: Optional[Dict[str, str]] = None


class EnterpriseRelationshipBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    sources: List[SourceEntity]
    target_id: str
    target_type: str
    target_details: Optional[Dict[str, str]] = None
    relationship_type: str


class EnterpriseRelationshipCreate(EnterpriseRelationshipBase):
    pass


class EnterpriseRelationshipResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    sources: List[SourceEntity]
    target_id: str
    target_type: str
    target_details: Optional[Dict[str, str]] = None
    relationship_type: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def type(self) -> str:
        return self.relationship_type

    @computed_field
    @property
    def createdAt(self) -> str:
        return self.created_at.isoformat().replace("+00:00", "Z")

    @computed_field
    @property
    def target(self) -> Dict[str, Any]:
        target_name = "Target"
        if " → " in self.name:
            target_name = self.name.split(" → ")[-1]

        return {
            "id": self.target_id,
            "type": self.target_type,
            "name": target_name,
            "details": self.target_details,
        }
