"""User schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    """Base user schema."""

    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    avatar: Optional[str] = None
    role: str = Field(default="user", pattern="^(admin|user|viewer)$")


class UserCreate(UserBase):
    """User creation schema."""

    password: str = Field(..., min_length=8, max_length=100)


class UserUpdate(BaseModel):
    """User update schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    avatar: Optional[str] = None
    role: Optional[str] = Field(None, pattern="^(admin|user|viewer)$")
    email_verified: Optional[bool] = None
    onboarding_step: Optional[int] = None
    has_completed_onboarding: Optional[bool] = None
    selected_domain: Optional[str] = None


class UserResponse(UserBase):
    """User response schema."""

    id: UUID
    email_verified: bool
    email_verified_at: Optional[datetime] = None
    onboarding_step: int
    has_completed_onboarding: bool
    selected_domain: Optional[str] = None
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    """Login request schema."""

    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Login response schema."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    """Refresh token request schema."""

    refresh_token: str


class RefreshTokenResponse(BaseModel):
    """Refresh token response schema."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class ForgotPasswordRequest(BaseModel):
    """Forgot password request schema."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Reset password request schema."""

    token: str
    new_password: str = Field(..., min_length=8, max_length=100)


class VerifyEmailRequest(BaseModel):
    """Verify email request schema."""

    token: str


class UserPermissionsResponse(BaseModel):
    """User permissions response schema."""

    permissions: dict
    role: str


class UserPermissionsUpdate(BaseModel):
    """User permissions update schema."""

    role: str = Field(..., pattern="^(admin|user|viewer)$")


class UserInviteRequest(BaseModel):
    """User invite request schema."""

    workspace_id: Optional[UUID] = None
    role: Optional[str] = Field(None, pattern="^(admin|user|viewer)$")

