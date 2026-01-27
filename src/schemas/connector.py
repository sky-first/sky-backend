"""Connector schemas."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConnectorField(BaseModel):
    """Connector field schema."""

    key: str
    label: str
    type: str  # text, password, number, url, etc.
    required: bool = False
    placeholder: Optional[str] = None
    description: Optional[str] = None
    default: Optional[Any] = None


class AuthMethod(BaseModel):
    """Auth method schema."""

    type: str  # api_key, bearer, basic, oauth, none
    label: str
    fields: List[ConnectorField] = Field(default_factory=list)
    instructions: Optional[str] = None


class ConnectorResponse(BaseModel):
    """Connector response schema."""

    id: str
    name: str
    category: str  # database, document, api, file
    description: str
    icon: Optional[str] = None
    fields: List[ConnectorField] = Field(default_factory=list)
    auth_methods: List[AuthMethod] = Field(default_factory=list)
    config_schema: Dict[str, Any] = Field(default_factory=dict)
    sync_frequency: Optional[Dict[str, Any]] = None
    metadata_schema: Optional[Dict[str, Any]] = None
