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
    role: str = Field(default="user", pattern="^(owner|admin|user|member|billing_admin|compliance_auditor|service_account)$")


class UserCreate(UserBase):
    """User creation schema."""

    password: str = Field(..., min_length=8, max_length=100)


class RegisterRequest(BaseModel):
    """User registration request schema."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    token: Optional[str] = Field(None, description="Invitation token (optional)")


class UserUpdate(BaseModel):
    """User update schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    avatar: Optional[str] = None
    role: Optional[str] = Field(None, pattern="^(owner|admin|user|member|billing_admin|compliance_auditor|service_account)$")
    email_verified: Optional[bool] = None
    onboarding_step: Optional[int] = None
    onboarding_version: Optional[int] = None
    has_completed_onboarding: Optional[bool] = None
    selected_domain: Optional[str] = None
    preferences: Optional[dict] = None
    ai_tone: Optional[str] = None
    ai_style: Optional[str] = None
    ai_context: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|away|offline)$")


class OnboardingUpdate(BaseModel):
    """Onboarding update schema."""

    step: Optional[int] = None
    version: Optional[int] = None


class ExploreDemoDataResponse(BaseModel):
    """Response from POST /me/onboarding/explore-demo-data.

    Returned when an SSO user opts into the "explore with sample data"
    flow on first login. The FE switches the active workspace to the
    returned ``space_id`` so the user immediately sees the seeded
    Connections, Glossary, Metrics, and Agents.
    """

    space_id: str
    space_name: str
    is_new: bool  # False on a re-run that found a pre-existing demo space
    seeded: dict  # {"glossary": int, "metrics": int, "relationships": int}
    agents_added: int
    connections_added: int


class DemoDataStatusResponse(BaseModel):
    """Response from GET /me/onboarding/explore-demo-data.

    Used by the FE banner inside the Demo Sky workspace to show
    "you have N metrics + M glossary terms here, [Remove sample data]".
    """

    has_demo_space: bool
    space_id: Optional[str] = None
    space_name: Optional[str] = None
    metrics_count: int = 0
    glossary_count: int = 0
    connections_count: int = 0


class DemoDataRemovedResponse(BaseModel):
    """Response from DELETE /me/onboarding/explore-demo-data.

    Idempotent: ``removed=False`` means there was nothing to remove.
    """

    removed: bool
    space_id: Optional[str] = None
    deleted: dict = Field(default_factory=dict)


class UserResponse(UserBase):
    """User response schema."""

    id: UUID
    email_verified: bool
    email_verified_at: Optional[datetime] = None
    onboarding_step: Optional[int] = 0
    onboarding_version: int = 0
    needs_onboarding: bool = False
    has_completed_onboarding: bool
    selected_domain: Optional[str] = None
    preferences: dict = Field(default_factory=dict)
    last_login_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None
    status: str = "offline"
    # Public demo flags — exposed so the FE can render the demo TTL
    # countdown badge ("5 days left") and the demo welcome banner.
    # Without these fields, the FE never knows the user is a demo
    # guest and falls back to the regular paid-plan experience.
    is_demo: bool = False
    demo_expires_at: Optional[datetime] = None
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

    role: str = Field(..., pattern="^(owner|admin|user|member|billing_admin|compliance_auditor|service_account)$")


class UserInviteRequest(BaseModel):
    """User invite request schema."""

    workspace_id: Optional[UUID] = None
    role: Optional[str] = Field(None, pattern="^(owner|admin|user|member|billing_admin|compliance_auditor|service_account)$")


# Invite System Schemas


class InviteValidateRequest(BaseModel):
    """Invite validation request schema."""

    token: str = Field(..., description="Invite token to validate")


class InviteValidateResponse(BaseModel):
    """Invite validation response schema."""

    valid: bool
    email: Optional[str] = None
    expires_at: Optional[str] = None
    invited_by_name: Optional[str] = None
    name: Optional[str] = None
    message: Optional[str] = None


class InviteLoginRequest(BaseModel):
    """Invite login request schema."""

    token: str = Field(..., description="Invite token")
    password: str = Field(..., min_length=8, max_length=100, description="User password")


class InviteGenerateRequest(BaseModel):
    """Invite generation request schema."""

    email: EmailStr = Field(..., description="Email of user to invite")
    expires_days: int = Field(default=7, ge=1, le=30, description="Days until invite expires")
    name: Optional[str] = Field(
        None, min_length=1, max_length=255, description="Optional name for invited user"
    )


class InviteGenerateResponse(BaseModel):
    """Invite generation response schema."""

    token: str
    email: str
    expires_at: str
    message: str


class SessionResponse(BaseModel):
    """Session response schema."""

    id: str
    created_at: datetime
    expires_at: datetime
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    is_current: bool = False


class ChangePasswordRequest(BaseModel):
    """Change password request schema."""

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=100)
