"""Settings schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SettingsResponse(BaseModel):
    """Settings response schema."""

    theme: Optional[str] = None
    language: Optional[str] = None
    notifications: Optional[Dict[str, Any]] = None
    preferences: Optional[Dict[str, Any]] = None


class SettingsUpdate(BaseModel):
    """Settings update schema."""

    theme: Optional[str] = None
    language: Optional[str] = None
    notifications: Optional[Dict[str, Any]] = None
    preferences: Optional[Dict[str, Any]] = None


class DataCatalogSettingsResponse(BaseModel):
    """Data catalog settings response schema."""

    auto_sync: bool = False
    sync_interval: int = 3600  # seconds
    enabled_connectors: List[str] = Field(default_factory=list)


class SpacesSettingsResponse(BaseModel):
    """Spaces settings response schema."""

    default_role: str = "viewer"
    allow_public_spaces: bool = False
    max_spaces_per_user: Optional[int] = None


class CrewsSettingsResponse(BaseModel):
    """Crews settings response schema."""

    default_role: str = "guest"
    max_crews_per_user: Optional[int] = None
    allow_public_crews: bool = False


class UsersSettingsResponse(BaseModel):
    """Users settings response schema."""

    allow_registration: bool = True
    require_email_verification: bool = False
    default_role: str = "user"


class PermissionsSettingsResponse(BaseModel):
    """Permissions settings response schema."""

    rbac_enabled: bool = True
    default_permissions: Dict[str, List[str]] = Field(default_factory=dict)


class APIKeyBase(BaseModel):
    """Base API key schema."""

    name: str = Field(..., min_length=1, max_length=255)
    permissions: Optional[List[str]] = None
    expires_at: Optional[datetime] = None


class APIKeyCreate(APIKeyBase):
    """API key creation schema."""


class APIKeyResponse(APIKeyBase):
    """API key response schema."""

    id: UUID
    key_prefix: str
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    revoked_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class IntegrationBase(BaseModel):
    """Base integration schema."""

    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., min_length=1, max_length=100)
    config: Dict[str, Any] = Field(..., description="Integration configuration")
    enabled: bool = True


class IntegrationCreate(IntegrationBase):
    """Integration creation schema."""


class IntegrationUpdate(BaseModel):
    """Integration update schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class IntegrationResponse(IntegrationBase):
    """Integration response schema."""

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
