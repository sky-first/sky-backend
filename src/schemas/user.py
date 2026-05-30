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
    # Sky-team operator flag. Exposed so the platform profile dropdown
    # can show the "Console" entry only for engineers — keeping the
    # operator surface invisible to customer users on the same UI.
    is_sky_operator: bool = False
    # Sky-platform internal role (ceo / admin / support / read_only),
    # null for customer users. Independent from ``role`` above, which
    # is the tenant-side role. The Console UI displays this; the
    # platform never reads it.
    sky_role: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    """Login request schema."""

    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Login response schema.

    When MFA is enabled on the account, the first POST /auth/login
    returns ``require_mfa=true`` + a short-lived ``mfa_challenge_token``
    and leaves ``access_token`` / ``refresh_token`` / ``user`` empty.
    The caller then POSTs the challenge token + the 6-digit code to
    /auth/login/mfa to obtain the real tokens. This keeps the
    ``LoginResponse`` shape stable for FE callers that never enable
    MFA — they continue to see ``require_mfa`` absent or false and the
    populated token+user fields, identical to the pre-Phase-3 shape.
    """

    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int = 0
    user: Optional[UserResponse] = None

    require_mfa: bool = False
    mfa_challenge_token: Optional[str] = None
    mfa_expires_in: Optional[int] = None


class MFALoginRequest(BaseModel):
    """Body for POST /auth/login/mfa — Phase 3.

    The challenge token authorises the attempt (it embeds the user id
    and is short-lived). ``code`` is either a 6-digit TOTP or a
    recovery code; the boolean tells the service which path to take.
    """

    challenge_token: str = Field(..., description="Short-lived MFA challenge token from /auth/login")
    code: str = Field(..., min_length=1, max_length=64)
    is_recovery_code: bool = Field(
        default=False,
        description="True when ``code`` is a recovery code; otherwise a 6-digit TOTP",
    )


# ── MFA enrolment / management ────────────────────────────────────────


class MFAEnrollStartResponse(BaseModel):
    """Response to POST /auth/mfa/enroll/start (Phase 3).

    The ``secret`` field is the plaintext base32 TOTP seed — the
    enrolling user needs it to either scan the QR or type it into
    their authenticator manually. The BE does NOT persist anything
    until /auth/mfa/enroll/verify succeeds; until then the FE owns
    the secret in component state.
    """

    secret: str
    otpauth_url: str
    qrcode_png_b64: str
    issuer: str


class MFAEnrollVerifyRequest(BaseModel):
    """Body for POST /auth/mfa/enroll/verify."""

    secret: str = Field(..., description="Echo back of the secret from /enroll/start")
    code: str = Field(..., min_length=6, max_length=6, description="6-digit TOTP code")


class MFAEnrollVerifyResponse(BaseModel):
    """Response to /auth/mfa/enroll/verify.

    ``recovery_codes`` are returned plaintext exactly once. The FE
    must surface them clearly (copy + download .txt) — they are the
    only way back into the account if the user loses their device.
    """

    enabled: bool
    recovery_codes: list[str]
    enrolled_at: datetime


class MFARotateRecoveryCodesResponse(BaseModel):
    """Response to POST /auth/mfa/recovery-codes/rotate."""

    recovery_codes: list[str]


class MFAStatusResponse(BaseModel):
    """Response to GET /auth/mfa/status (settings → Security)."""

    enabled: bool
    enrolled_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


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
