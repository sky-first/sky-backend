"""User schemas."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    """Base user schema."""

    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    avatar: Optional[str] = None
    # Este padrão fica **solto** de propósito: o `UserBase` alimenta o
    # `UserResponse`, e apertar a leitura não fecha porta nenhuma — só faz a
    # API rebentar a serializar linhas que existem. Foi o que aconteceu:
    # apertei aqui e o `PageMemberResponse`, que embute um `UserResponse`,
    # deixou de conseguir devolver membros de página.
    #
    # Quem escreve é que é apertado: `UserCreate`, `UserUpdate`,
    # `UserPermissionsUpdate` e `UserInviteRequest` abaixo, e sobretudo o
    # `validar_atribuicao_de_papel` no serviço, que é o portão a sério.
    role: str = Field(default="member", pattern="^(super_admin|admin|member|user|owner|billing_admin|compliance_auditor|service_account)$")


class UserCreate(UserBase):
    """User creation schema."""

    password: str = Field(..., min_length=8, max_length=100)
    # Criar é escrever: aqui os nomes legados não entram.
    role: str = Field(default="member", pattern="^(super_admin|admin|member|billing_admin|compliance_auditor|service_account)$")


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
    role: Optional[str] = Field(None, pattern="^(super_admin|admin|member|billing_admin|compliance_auditor|service_account)$")
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
    """User response schema.

    ``role`` inherits the loose pattern on ``UserBase`` which accepts
    the legacy ``user`` / ``owner`` strings in addition to the
    canonical ``super_admin | admin | member`` taxonomy. The DB
    migration ``rename_role_20260603`` normalised production rows,
    but test fixtures and historical session tokens still ship the
    legacy values — and a stricter regex here would 500 every
    serialise. Clean taxonomy is enforced at the inbound
    ``InviteGenerateRequest`` boundary (``^(admin|member)$``) and by
    ``is_tenant_admin()`` which returns False for ``user`` / ``owner``,
    so the loose pattern here cannot grant tenant-level privileges.
    """

    id: UUID
    email_verified: bool
    email_verified_at: Optional[datetime] = None
    # Se o email de acesso chegou a sair.
    #
    # `None` quando a resposta não vem de um convite (a maioria das leituras).
    # `False` quer dizer: a pessoa TEM acesso, mas não foi avisada — quem
    # convidou tem de lho dizer por outro meio. Até aqui a falha de envio era
    # escrita no log e a API respondia sucesso na mesma, o que dava o pior dos
    # cenários: o administrador via "convidado", o convidado nunca recebia
    # nada, e ninguém percebia porquê.
    access_email_sent: Optional[bool] = None
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

    Three terminal states a password login can reach:

    1. **Normal session** — ``access_token`` + ``refresh_token`` + ``user``
       populated. User logged in successfully.
    2. **MFA challenge** — ``require_mfa=true`` + ``mfa_challenge_token``.
       Account already has TOTP enrolled; FE prompts for the 6-digit
       code and POSTs to /auth/login/mfa.
    3. **Force enrolment** — ``force_enrollment=true`` +
       ``mfa_enrollment_token`` + ``mfa_enrollment_secret`` +
       ``mfa_enrollment_qrcode_b64``. The account is configured with
       password auth but has never enrolled MFA. We require enrolment
       on this first successful password verification so the cliente
       cannot dismiss it and keep logging in without a second factor.
       FE shows the QR + secret, asks for the first 6-digit code, then
       POSTs to /auth/login/mfa-finalize to persist the secret AND
       receive the session tokens in the same response.

    SSO callbacks never set the MFA fields — IdP-side 2FA already
    covers that path and forcing on top would be user-hostile.
    """

    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int = 0
    user: Optional[UserResponse] = None

    # MFA second-step challenge (account already has TOTP enrolled).
    require_mfa: bool = False
    mfa_challenge_token: Optional[str] = None
    mfa_expires_in: Optional[int] = None

    # Force MFA enrolment (account has password auth but never enrolled).
    # Mandatory for the cliente without SSO — design decision Lucas
    # 2026-05-31: every password-authenticated user must have MFA.
    force_enrollment: bool = False
    mfa_enrollment_token: Optional[str] = None
    mfa_enrollment_secret: Optional[str] = None
    mfa_enrollment_qrcode_b64: Optional[str] = None
    mfa_enrollment_issuer: Optional[str] = None


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


class MFAFinalizeEnrollmentRequest(BaseModel):
    """Body for POST /auth/login/mfa-finalize — first login of a
    password-authenticated account.

    The FE collected the enrolment token + 6-digit code from the user
    after they scanned the QR code returned by /auth/login. The BE
    verifies the code, persists the secret + recovery codes, and only
    then mints the session tokens. The response is a full
    LoginResponse so the FE can drop the user straight into the
    dashboard once they confirm they've stored the recovery codes.
    """

    enrollment_token: str = Field(
        ..., description="Short-lived enrolment token from /auth/login"
    )
    code: str = Field(..., min_length=6, max_length=6, description="6-digit TOTP code")


class MFAFinalizeEnrollmentResponse(BaseModel):
    """Response of /auth/login/mfa-finalize.

    Same shape as a normal LoginResponse PLUS the freshly-minted
    recovery codes. The codes appear here EXACTLY ONCE; the FE must
    surface them to the user (copy + download .txt) and warn that
    they cannot be retrieved again.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
    recovery_codes: List[str] = Field(
        ..., description="Plaintext recovery codes — shown exactly once"
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

    role: str = Field(..., pattern="^(super_admin|admin|member|billing_admin|compliance_auditor|service_account)$")


class UserInviteRequest(BaseModel):
    """User invite request schema."""

    workspace_id: Optional[UUID] = None
    role: Optional[str] = Field(None, pattern="^(super_admin|admin|member|billing_admin|compliance_auditor|service_account)$")


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
    # Tenant role the invitee gets after accepting. ``super_admin`` is
    # intentionally absent — that role is reserved for the tenant
    # founder and is granted on tenant creation, not via invite. The
    # legacy ``user`` alias was normalised to ``member`` by the
    # ``rename_role_20260603`` migration, so the canonical taxonomy is
    # now ``admin | member`` for invites.
    role: str = Field(
        default="member",
        pattern=r"^(admin|member)$",
        description="Tenant role for the invited user (admin or member).",
    )


class InviteGenerateResponse(BaseModel):
    """Invite generation response schema."""

    token: str
    email: str
    expires_at: str
    # False when the invitation email could not be delivered (e.g. the AWS
    # SES sandbox rejects recipients that are not verified identities). The
    # invite row + token are still created; the client surfaces a warning so
    # the operator knows the email did not go out. Defaults True for mock
    # mode and any caller that doesn't set it.
    email_sent: bool = True
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
