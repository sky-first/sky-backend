"""Authentication endpoints."""

import re
from typing import List, Optional
from urllib.parse import urlencode
from uuid import UUID

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import (  # get_current_user usado em outros endpoints
    enforce_device_tenant,
    get_current_user,
    get_db_session,
)
from src.api.middleware.tenant_resolver import _load_tenant_by_id
from src.config.auth0 import auth0_settings
from src.core.exceptions import BadRequestError, ForbiddenError
from src.models.tenant import (
    DEFAULT_AUTH_METHODS,
    PLATFORM_FALLBACK_AUTH_METHODS,
    Tenant,
)
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.permission import EffectivePermissionsResponse
from src.schemas.user import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    InviteGenerateRequest,
    InviteGenerateResponse,
    InviteLoginRequest,
    InviteValidateRequest,
    InviteValidateResponse,
    LoginRequest,
    LoginResponse,
    MFAFinalizeEnrollmentRequest,
    MFAFinalizeEnrollmentResponse,
    MFALoginRequest,
    RefreshTokenRequest,
    RefreshTokenResponse,
    RegisterRequest,
    ResetPasswordRequest,
    SessionResponse,
    UserResponse,
    VerifyEmailRequest,
)
from src.services.auth0_service import Auth0Service
from src.services.auth_service import AuthenticationService, user_to_response_dict
from src.services.invite_service import InviteService, request_base_url
from src.services.password_reset_service import PasswordResetService
from src.services.rbac_service import RBACService
from src.services.tenant_membership_service import TenantMembershipService

router = APIRouter()


# ── Per-tenant auth methods helpers ───────────────────────────────────
# Subdomain shape: ``workspace-<slug>[-stg].<domain>``. The slug is the
# only thing we trust from the host header, and the regex below has to
# match the one in ``src/api/middleware/tenant_resolver.py`` so the two
# paths agree on which slug to look up.
# Accept these subdomain patterns so the same regex covers every host
# the onboard-client workflow can mint (kept in sync with
# tenant_resolver.py's ``_SUBDOMAIN_RE``):
#
#   workspace-<slug>.skyfirstlabs.com       (production explicit prefix)
#   workspace-<slug>-stg.skyfirstlabs.com   (staging explicit prefix)
#   api-<slug>.skyfirstlabs.com             (production API subdomain)
#   api-<slug>-stg.skyfirstlabs.com         (staging API subdomain)
#   <slug>-stg.skyfirstlabs.com             (legacy bare slug, staging)
#
# A bare host with neither a ``workspace-``/``api-`` prefix nor a
# ``-stg`` suffix (``demo.``, ``api.``, the base) is NOT a tenant.
# ``sky-stg.skyfirstlabs.com`` (the platform default) never matches in
# practice — the workflow's reserved-name list rejects ``sky``.
_AUTH_SUBDOMAIN_RE = re.compile(
    r"^(?:(?:workspace|api)-([a-z0-9-]{2,50}?)(?:-stg)?|([a-z0-9-]{2,50}?)-stg)\."
)


class AuthMethodsResponse(BaseModel):
    """Public shape returned by ``GET /auth/methods``.

    Drives what the ``/login`` page renders. The frontend mounts this
    on entry so a tenant that allows only password sees an
    email/password form, and one that allows only Google sees the
    ``Continue with Google`` button.

    ``show_demo`` is independent of the four auth methods. It controls
    whether the public "Try the live demo" link appears below the
    sign-in box. The Sky landing keeps it on by default so prospects
    can try the product; a tenant created via the Console starts with
    it off (the operator opts back in by ticking the checkbox).
    """

    password: bool = False
    google: bool = True
    azure: bool = False
    okta: bool = False
    show_demo: bool = True
    tenant_slug: Optional[str] = None
    # Só o caminho por email o põe a ``False``: quer dizer "este domínio não
    # está registado em nenhum workspace". A app precisa de distinguir isso
    # dos métodos por omissão, senão mostrava "Continuar com Google" a quem
    # escreveu um email que não pertence a cliente nenhum — e o botão levava
    # a um SSO que nunca ia deixar entrar. No caminho por host mantém-se
    # ``True``, que preserva a resposta que o frontend web já recebia.
    domain_known: bool = True


from src.core.sso_state import SSOStateError, issue_state, verify_state


def _slug_from_request(request: Request) -> Optional[str]:
    host_header = request.headers.get("host")
    if host_header:
        host = host_header.split(":", 1)[0].lower()
        m = _AUTH_SUBDOMAIN_RE.match(host)
        if m:
            # Group 1 = prefixed (workspace-/api-), group 2 = bare -stg form.
            return m.group(1) or m.group(2)
    # Device clients have no sub-domain — honour the explicit X-Tenant-Slug
    # override (same header the tenant resolver already accepts), so mobile can
    # reach a workspace's auth methods (e.g. password-enabled) on a bare host.
    header_slug = request.headers.get("x-tenant-slug")
    return header_slug.strip().lower() if header_slug else None


def _methods_from_tenant(tenant: Tenant) -> AuthMethodsResponse:
    """Métodos de autenticação de um cliente já resolvido.

    Existe porque o caminho por domínio resolve o cliente a partir do
    email, sem passar pelo middleware — portanto não há
    ``request.state.tenant_context`` nem slug no host para
    ``_auth_methods_for_request`` seguir.
    """
    methods = dict(tenant.auth_methods or {}) or dict(DEFAULT_AUTH_METHODS)
    flags = dict(tenant.feature_flags or {})
    return AuthMethodsResponse(
        password=bool(methods.get("password", False)),
        google=bool(methods.get("google", False)),
        azure=bool(methods.get("azure", False)),
        okta=bool(methods.get("okta", False)),
        show_demo=bool(flags.get("demo_enabled", False)),
        tenant_slug=tenant.slug,
    )


async def _tenant_from_email_domain(request: Request, email: str):
    """Descobre o cliente pelo domínio do email — o caminho do mobile.

    Na web o cliente vem do sub-domínio. Uma app móvel fala com um host
    só, portanto sem isto o backend não sabe em que base de dados
    procurar quem está a tentar entrar: os utilizadores vivem em bases
    separadas por cliente.

    É o mesmo mecanismo do Microsoft Entra ID (*home realm discovery*):
    o domínio identifica a organização, e cada organização pode ter
    vários domínios registados.

    Devolve ``None`` quando já há sub-domínio ou header — nesse caso o
    caminho normal já resolveu o cliente e não há nada a descobrir — e
    também quando o domínio não está registado. Quem chama trata os dois
    silêncios da mesma maneira.

    A consulta corre contra a base de **registo**, não contra a do
    cliente: tem de responder antes de sabermos qual é o cliente.
    """
    if _slug_from_request(request):
        return None  # web ou console — o cliente já está resolvido

    from src.config.database import AsyncSessionLocal
    from src.services.tenant_domain_service import TenantDomainService

    # A lookup failure (registry unreachable, schema missing) is treated the
    # same as "domain not registered": return None so login falls through to
    # the normal path instead of 500-ing. Matches the service's silent-None
    # design — the caller never distinguishes the reasons anyway.
    try:
        async with AsyncSessionLocal() as registry:
            return await TenantDomainService.resolve_by_email(registry, email)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("tenant_domain_lookup_failed", exc_info=True)
        return None


async def _auth_methods_for_request(request: Request, db: AsyncSession) -> AuthMethodsResponse:
    """Resolve the tenant for the request and return its auth methods.

    Resolution order:

    1. ``request.state.tenant_context`` populated by the tenant
       resolver middleware (Model B path — the resolver already
       looked up ``tenant_registry`` against the platform DB and
       attached ``auth_methods`` + ``feature_flags`` to the context).
       Cheapest path, no extra DB round-trip.
    2. Legacy alias ``request.state.tenant`` — kept for safety so
       callers that pre-date the middleware rename don't crash.
    3. Slug parsed from the ``Host`` header → DB lookup. Used by
       requests that escape the middleware (some health probes /
       internal paths skip it on purpose).
    4. Nothing resolvable → fall back to ``PLATFORM_FALLBACK_AUTH_METHODS``
       (só Google): sem cliente resolvido quem está a responder é a
       plataforma, e a equipa da Sky entra por SSO e mais nada.
    """
    methods: Optional[dict] = None
    feature_flags: Optional[dict] = None
    slug: Optional[str] = None

    ctx = (
        getattr(request.state, "tenant_context", None) or getattr(request.state, "tenant", None)
        if hasattr(request, "state")
        else None
    )
    if ctx is not None and not getattr(ctx, "is_default", False):
        ctx_slug = getattr(ctx, "slug", None)
        ctx_methods = getattr(ctx, "auth_methods", None)
        if ctx_slug:
            slug = ctx_slug
        if ctx_methods:
            methods = dict(ctx_methods)
        ctx_ff = getattr(ctx, "feature_flags", None)
        if ctx_ff:
            feature_flags = dict(ctx_ff)

    if methods is None:
        slug = slug or _slug_from_request(request)
        if slug:
            row = (
                await db.execute(
                    select(Tenant.auth_methods, Tenant.feature_flags).where(Tenant.slug == slug)
                )
            ).one_or_none()
            if row is not None:
                methods = dict(row[0]) if row[0] else None
                feature_flags = dict(row[1]) if row[1] else None

    if not methods:
        # Sem cliente resolvido é a plataforma que está a responder, não
        # um cliente por configurar. Ver o comentário na constante.
        methods = dict(PLATFORM_FALLBACK_AUTH_METHODS)

    # Demo link policy:
    # * No tenant resolved (bare Sky landing) → demo on by default.
    # * Tenant resolved → off unless ``feature_flags.demo_enabled`` is true.
    # Tenants opt back in via the "Show demo link" checkbox in the
    # Console create-tenant form.
    if slug is None:
        show_demo = True
    else:
        show_demo = bool((feature_flags or {}).get("demo_enabled", False))

    return AuthMethodsResponse(
        password=bool(methods.get("password", False)),
        google=bool(methods.get("google", False)),
        azure=bool(methods.get("azure", False)),
        okta=bool(methods.get("okta", False)),
        show_demo=show_demo,
        tenant_slug=slug,
    )


@router.post(
    "/register",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="User registration",
    description="Register a new user and return access and refresh tokens",
)
async def register(
    register_data: RegisterRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """Self-registration is disabled. Access is granted via SSO or admin invite."""
    raise ForbiddenError(
        "Self-registration is disabled. Please sign in with your company account via SSO."
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="User login",
    description="Authenticate user and return access and refresh tokens",
)
async def login(
    login_data: LoginRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """Email + password login, gated per tenant.

    A tenant with ``auth_methods.password == false`` (the production
    default) rejects with 403 just like before. Starter tenants
    that need a quick way to onboard users without setting up SSO can
    flip the flag in the Internal Console; the handler then runs the
    standard credential check.
    """
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None

    # Caminho móvel: sem sub-domínio, o cliente sai do domínio do email.
    # Sem isto o `db` injectado aponta para a base por omissão, onde o
    # utilizador da GBT simplesmente não existe.
    domain_tenant = await _tenant_from_email_domain(request, login_data.email)

    if domain_tenant is not None:
        from src.api.middleware.tenant_resolver import _row_to_context
        from src.config.tenant_connection_manager import tenant_connection_manager
        from src.core.tenant_context import reset_current_tenant, set_current_tenant

        ctx = _row_to_context(domain_tenant)
        request.state.tenant_context = ctx
        # O contextvar, não só o request.state: é de `current_tenant()`
        # que `tenant_claims_for_context` tira o `tid` que vai assinado
        # no token. Sem isto o login por domínio devolvia um token sem
        # claim de cliente — e o portão de dispositivo recusava-o a
        # seguir com 400, um bug que só aparece no segundo pedido.
        token_ctx = set_current_tenant(ctx)

        session = tenant_connection_manager.session_for(ctx)
        try:
            methods = _methods_from_tenant(domain_tenant)
            if not methods.password:
                raise ForbiddenError(
                    "Password login is disabled for this workspace. "
                    "Please sign in with your company SSO."
                )
            result = await AuthenticationService(session).login(
                email=login_data.email,
                password=login_data.password,
                user_agent=user_agent,
                ip_address=ip_address,
                background_tasks=background_tasks,
            )
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise
        finally:
            reset_current_tenant(token_ctx)
            await session.close()

    methods = await _auth_methods_for_request(request, db)
    if not methods.password:
        raise ForbiddenError(
            "Password login is disabled for this workspace. "
            "Please sign in with your company SSO."
        )

    auth_service = AuthenticationService(db)
    return await auth_service.login(
        email=login_data.email,
        password=login_data.password,
        user_agent=user_agent,
        ip_address=ip_address,
        background_tasks=background_tasks,
    )


@router.post(
    "/login/mfa",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Complete MFA login",
    description=(
        "Redeems a short-lived MFA challenge token (issued by "
        "/auth/login when ``require_mfa`` is true) plus a 6-digit "
        "TOTP code (or a single-use recovery code) for the real "
        "access + refresh pair."
    ),
)
async def login_mfa(
    body: MFALoginRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    auth_service = AuthenticationService(db)
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None
    # BE-05 — a device that sends `X-Client-Type: mobile` gets the long
    # refresh TTL; anything else keeps the web default.
    client_type = request.headers.get("x-client-type")
    return await auth_service.complete_mfa_login(
        challenge_token=body.challenge_token,
        code=body.code,
        is_recovery_code=body.is_recovery_code,
        user_agent=user_agent,
        ip_address=ip_address,
        background_tasks=background_tasks,
        client_type=client_type,
    )


@router.post(
    "/login/mfa-finalize",
    response_model=MFAFinalizeEnrollmentResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Finalise first-time MFA enrolment + complete login",
    description=(
        "Closes the forced-enrolment loop: takes the enrolment token "
        "issued by /auth/login (when ``force_enrollment`` was true) "
        "plus the user's first 6-digit TOTP code, persists the secret "
        "and the bcrypt-hashed recovery codes, and mints the session "
        "tokens in the same response. The recovery codes are returned "
        "EXACTLY ONCE — the FE must surface them to the user and warn "
        "they cannot be retrieved again."
    ),
)
async def login_mfa_finalize(
    body: MFAFinalizeEnrollmentRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
) -> MFAFinalizeEnrollmentResponse:
    auth_service = AuthenticationService(db)
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None
    client_type = request.headers.get("x-client-type")  # BE-05 — mobile TTL
    return await auth_service.finalize_mfa_enrollment(
        enrollment_token=body.enrollment_token,
        code=body.code,
        user_agent=user_agent,
        ip_address=ip_address,
        background_tasks=background_tasks,
        client_type=client_type,
    )


@router.get(
    "/methods",
    response_model=AuthMethodsResponse,
    summary="Authentication methods enabled for this workspace",
    description=(
        "Returns the auth methods enabled for a workspace. Without "
        "``email``, resolves the workspace from the Host header — the web "
        "login page mounts it that way. With ``email``, resolves from the "
        "domain of the address (home-realm discovery), which is how the "
        "mobile app finds the workspace: it talks to a single host and has "
        "no sub-domain to go by."
    ),
)
async def get_auth_methods(
    request: Request,
    email: Optional[str] = Query(
        None,
        description="Work email. The domain identifies the workspace.",
    ),
    db: AsyncSession = Depends(get_db_session),
) -> AuthMethodsResponse:
    # O caminho por email existe para o login em dois passos da app: primeiro
    # o email, e só depois o que esse workspace aceita — password, SSO, ou
    # ambos. É o que permite activar o SSO de um cliente novo e ele entrar na
    # app da loja no mesmo dia, sem publicar versão nenhuma.
    #
    # Isto expõe publicamente que um domínio está registado. É o mesmo que a
    # Microsoft e a Google fazem no home-realm discovery, e é inevitável: sem
    # o dizer, não há como oferecer o botão certo. Não revela utilizadores,
    # só a existência do workspace.
    if email:
        tenant = await _tenant_from_email_domain(request, email)
        if tenant is not None:
            return _methods_from_tenant(tenant)
        # Domínio desconhecido. Devolve os métodos por omissão mas assinala
        # que ninguém o reclama, para a app poder dizê-lo em vez de mostrar
        # um botão que não leva a lado nenhum.
        fallback = await _auth_methods_for_request(request, db)
        fallback.domain_known = False
        fallback.tenant_slug = None
        return fallback

    return await _auth_methods_for_request(request, db)


@router.post(
    "/logout",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="User logout",
    description="Logout user by revoking refresh token",
)
async def logout(
    refresh_token_data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Logout endpoint.

    Revokes the caller's refresh token AND all outstanding access
    tokens for the same user. The access-token invalidation uses a
    "revoke tokens issued before now" marker stored in Redis and
    checked by the auth middleware — the old access token keeps its
    JWT shape but stops being accepted immediately.

    Red-team HI (2026-04-23): before this change, a stolen access
    token kept working until its JWT exp (15 min) regardless of
    logout.
    """
    import time

    from jose import jwt as _jwt

    auth_service = AuthenticationService(db)
    await auth_service.logout(refresh_token_data.refresh_token)

    # Decode the refresh to get `sub` (user id) so we can revoke all
    # the access tokens for the SAME user. We only need the sub
    # claim; signature was checked inside auth_service.logout above.
    try:
        claims = _jwt.get_unverified_claims(refresh_token_data.refresh_token)
        user_id = claims.get("sub")
    except Exception:
        user_id = None

    if user_id:
        from src.core.token_blocklist import revoke_user_tokens

        await revoke_user_tokens(user_id, issued_before_epoch=int(time.time()))

    return SuccessResponse(message="Logged out successfully")


@router.post(
    "/refresh",
    response_model=RefreshTokenResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Refresh access token",
    description="Get new access token using refresh token",
)
async def refresh_token(
    refresh_token_data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db_session),
) -> RefreshTokenResponse:
    """
    Refresh token endpoint.

    Args:
        refresh_token_data: Refresh token
        db: Database session

    Returns:
        RefreshTokenResponse: New access and refresh tokens
    """
    auth_service = AuthenticationService(db)
    return await auth_service.refresh_access_token(refresh_token_data.refresh_token)


# ── BE-01 · Mobile workspace switcher ──────────────────────────────────────
# Device clients carry no sub-domain, so the tenant travels as a signed
# ``tid`` claim. These endpoints let a user who belongs to more than one
# tenant list them and switch — always via an explicit token re-issue.


class WorkspaceSummary(BaseModel):
    tenant_id: str
    slug: str
    name: str
    role: str


class WorkspacesResponse(BaseModel):
    workspaces: List[WorkspaceSummary]


class SelectWorkspaceRequest(BaseModel):
    tenant_id: str


@router.get(
    "/me/workspaces",
    response_model=WorkspacesResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="List the workspaces the current user may act as",
    description=(
        "Every tenant the authenticated user is a member of, with their "
        "role — the source for the mobile workspace switcher."
    ),
)
async def list_my_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspacesResponse:
    memberships = await TenantMembershipService.list_for_user(db, current_user.id)
    if not memberships:
        return WorkspacesResponse(workspaces=[])

    rows = (
        (await db.execute(select(Tenant).where(Tenant.id.in_([m.tenant_id for m in memberships]))))
        .scalars()
        .all()
    )
    tenants_by_id = {str(t.id): t for t in rows}

    workspaces: List[WorkspaceSummary] = []
    for membership in memberships:
        tenant = tenants_by_id.get(str(membership.tenant_id))
        if tenant is None:
            continue  # membership to a tenant that no longer exists — skip
        workspaces.append(
            WorkspaceSummary(
                tenant_id=str(membership.tenant_id),
                slug=tenant.slug,
                name=tenant.display_name,
                role=membership.role,
            )
        )
    return WorkspacesResponse(workspaces=workspaces)


@router.post(
    "/select-workspace",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
    summary="Switch the active workspace and re-issue tokens",
    description=(
        "Explicitly re-issues an access+refresh pair scoped to another tenant "
        "the user belongs to. Switching is never a side effect of refreshing."
    ),
)
async def select_workspace(
    body: SelectWorkspaceRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    # Authorization: a valid session is not enough — the user must be a
    # current member of the target tenant (re-checked live).
    if not await TenantMembershipService.is_member(db, current_user.id, body.tenant_id):
        raise ForbiddenError("You are not a member of that workspace.")

    ctx = await _load_tenant_by_id(body.tenant_id)
    if ctx is None:
        raise BadRequestError("Workspace not found or suspended.")

    auth_service = AuthenticationService(db)
    return await auth_service.issue_session_for_tenant(
        current_user,
        ctx,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get current user",
    description="Get authenticated user information",
)
async def get_me(
    current_user: User = Depends(get_current_user),
    _tenant: None = Depends(enforce_device_tenant),  # BE-01 device-tenant gate
) -> UserResponse:
    """
    Get current user endpoint.

    Args:
        current_user: Current authenticated user

    Returns:
        UserResponse: User data
    """
    return UserResponse.model_validate(user_to_response_dict(current_user))


@router.get(
    "/me/effective-permissions",
    response_model=EffectivePermissionsResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get effective permissions",
    description="Return effective permissions for the current user, optionally scoped by space/crew/connection.",
)
async def get_effective_permissions(
    space_id: Optional[str] = Query(None, description="Space context (optional)"),
    crew_id: Optional[str] = Query(None, description="Crew context (optional)"),
    connection_id: Optional[str] = Query(None, description="Connection context (optional)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> EffectivePermissionsResponse:
    def _to_uuid(v: Optional[str]) -> Optional[UUID]:
        if not v:
            return None
        try:
            return UUID(v)
        except Exception:
            return None

    rbac = RBACService(db)
    eff = await rbac.get_effective_permissions(
        current_user,
        space_id=_to_uuid(space_id),
        crew_id=_to_uuid(crew_id),
        connection_id=_to_uuid(connection_id),
    )
    return EffectivePermissionsResponse(
        platform_role=eff.platform_role,
        crew_role=eff.crew_role,
        permissions=eff.permissions,
    )


@router.post(
    "/forgot-password",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={403: {"model": ErrorResponse}},
    summary="Forgot password",
    description="Request password reset email",
)
async def forgot_password(
    request_data: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Forgot password endpoint.

    Gated by the same per-tenant ``methods.password`` flag as /login:
    an SSO-only workspace has no password to reset, so the request is
    refused with 403 (mirrors the login handler) before any token is
    minted.

    For tenants that allow password auth the response is ALWAYS the same
    generic success message, whether or not the email matches an account
    — this is deliberate so the endpoint cannot be used to enumerate
    which addresses have accounts. When the account does exist a reset
    token is minted, stored (1h expiry), and a reset email is sent
    best-effort (a delivery failure never changes the response).

    Args:
        request_data: Email address
        request: FastAPI request (tenant resolution + host for the link)
        db: Database session

    Returns:
        SuccessResponse: Generic success message (no account-existence leak)
    """
    methods = await _auth_methods_for_request(request, db)
    if not methods.password:
        raise ForbiddenError(
            "Password reset is disabled for this workspace. "
            "Please sign in with your company SSO."
        )

    # Build the reset link on the host the request actually arrived on —
    # the tenant's own domain — so the token resolves against the tenant
    # DB, exactly like the invite flow.
    base_url = request_base_url(request)

    reset_service = PasswordResetService(db)
    await reset_service.request_reset(email=request_data.email, base_url=base_url)

    return SuccessResponse(
        message="If an account exists for that email, we've sent password reset instructions."
    )


@router.post(
    "/reset-password",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Reset password",
    description="Reset password using reset token",
)
async def reset_password(
    request_data: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Reset password endpoint.

    Gated by the same per-tenant ``methods.password`` flag as /login.
    Validates the reset token (must exist and not be expired), sets the
    new password, and clears the token so it cannot be replayed. An
    invalid or expired token is rejected with a clean 400.

    Args:
        request_data: Reset token and new password
        request: FastAPI request (tenant resolution)
        db: Database session

    Returns:
        SuccessResponse: Success message

    Raises:
        BadRequestError: If the token is invalid or expired
        ForbiddenError: If the workspace disables password auth
    """
    methods = await _auth_methods_for_request(request, db)
    if not methods.password:
        raise ForbiddenError(
            "Password reset is disabled for this workspace. "
            "Please sign in with your company SSO."
        )

    reset_service = PasswordResetService(db)
    await reset_service.reset_password(
        token=request_data.token,
        new_password=request_data.new_password,
    )

    return SuccessResponse(message="Password has been reset successfully.")


@router.post(
    "/verify-email",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}},
    summary="Verify email",
    description="Verify user email address",
)
async def verify_email(
    request_data: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Verify email endpoint.

    Args:
        request_data: Email verification token
        db: Database session

    Returns:
        SuccessResponse: Success message

    Raises:
        BadRequestError: If token is invalid
    """
    raise ForbiddenError("Email verification is not applicable. Authentication is handled via SSO.")


@router.get(
    "/session",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get current session",
    description="Get current authenticated user session information",
)
async def get_session(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Get current session endpoint.

    Args:
        current_user: Current authenticated user

    Returns:
        UserResponse: Current user session data
    """
    return UserResponse.model_validate(user_to_response_dict(current_user))


@router.get(
    "/sessions",
    response_model=List[SessionResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get active sessions",
    description="Get list of active sessions for the current user",
)
async def get_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[SessionResponse]:
    """
    Get active sessions endpoint.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[SessionResponse]: List of active sessions
    """
    auth_service = AuthenticationService(db)
    assert current_user.id is not None
    sessions = await auth_service.get_active_sessions(UUID(str(current_user.id)))
    return [SessionResponse(**s) for s in sessions]


@router.delete(
    "/sessions",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Revoke all sessions",
    description="Revoke all sessions (except usually current one, but here all)",
)
async def revoke_all_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Revoke all sessions endpoint.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    auth_service = AuthenticationService(db)
    assert current_user.id is not None
    await auth_service.revoke_all_tokens(UUID(str(current_user.id)))
    return SuccessResponse(message="All sessions revoked successfully")


@router.delete(
    "/sessions/{session_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Revoke specific session",
    description="Revoke a specific session by ID",
)
async def revoke_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """Revoke a specific session (this device only) — BE-05 T-05.7.

    Kills the whole family of that session's refresh token, so the device's
    rotated tokens all die, while other devices keep working (no user-level
    access blocklist bump).
    """
    revoked = await AuthenticationService(db).revoke_device_session(
        session_id=session_id, user_id=UUID(str(current_user.id))
    )
    if not revoked:
        from src.core.exceptions import NotFoundError

        raise NotFoundError("Session not found or already revoked")

    return SuccessResponse(message="Session revoked successfully")


@router.post(
    "/change-password",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Change password",
    description="Change authenticated user password",
)
async def change_password(
    request_data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Change password endpoint.

    Args:
        request_data: Current and new password
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    raise ForbiddenError("Password management is disabled. Authentication is handled via SSO.")


# Invite Endpoints


@router.post(
    "/invite/validate",
    response_model=InviteValidateResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}},
    summary="Validate Invite Token",
    description="Validate an invite token and return invite information",
)
async def validate_invite(
    request_data: InviteValidateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> InviteValidateResponse:
    """
    Validate invite token endpoint.

    Args:
        request_data: Invite token to validate
        db: Database session

    Returns:
        InviteValidateResponse: Invite information if valid

    Raises:
        BadRequestError: If token is invalid or expired
    """
    invite_service = InviteService(db)
    try:
        invite_info = await invite_service.validate_invite_token(request_data.token)
        return InviteValidateResponse(
            valid=True,
            email=invite_info.get("email"),
            expires_at=invite_info.get("expires_at"),
            invited_by_name=invite_info.get("invited_by_name"),
            name=invite_info.get("name"),
            message="Invite token is valid",
        )
    except BadRequestError as e:
        return InviteValidateResponse(
            valid=False,
            message=str(e),
        )


@router.post(
    "/invite/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Login with Invite Token",
    description="Authenticate user using invite token and password",
)
async def login_with_invite(
    login_data: InviteLoginRequest,
    db: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """
    Login with invite token endpoint.

    Args:
        login_data: Invite token and password
        db: Database session

    Returns:
        LoginResponse: Access token, refresh token, and user data

    Raises:
        BadRequestError: If token is invalid or expired
        UnauthorizedError: If password is incorrect
    """
    invite_service = InviteService(db)
    login_response = await invite_service.login_with_invite(login_data.token, login_data.password)
    return LoginResponse(**login_response)


@router.post(
    "/invite/accept",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}},
    summary="Accept Invite",
    description="Accept invite, set password and login",
)
async def accept_invite_endpoint(
    login_data: InviteLoginRequest,
    db: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """
    Accept invite endpoint.

    Args:
        login_data: Invite token and new password
        db: Database session

    Returns:
        LoginResponse: Access token, refresh token, and user data

    Raises:
        BadRequestError: If token is invalid or expired
    """
    invite_service = InviteService(db)
    login_response = await invite_service.accept_invite(login_data.token, login_data.password)
    return LoginResponse(**login_response)


@router.post(
    "/invite/generate",
    response_model=InviteGenerateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Generate Invite Token",
    description="Generate an invite token for a new user (admin only)",
)
async def generate_invite(
    invite_data: InviteGenerateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> InviteGenerateResponse:
    """
    Generate invite token endpoint.

    Args:
        invite_data: Email and expiration settings
        current_user: Current authenticated user (must be admin)
        db: Database session

    Returns:
        InviteGenerateResponse: Generated invite token and information

    Raises:
        ForbiddenError: If user is not admin
        BadRequestError: If email already exists
    """
    from src.core.exceptions import ForbiddenError
    from src.core.permissions import is_tenant_admin

    # Tenant founder (super_admin) and admins can mint invites.
    if not is_tenant_admin(current_user):
        raise ForbiddenError("Only admins can generate invite tokens")

    # Build the invite link on the host the admin is actually using — the
    # tenant's own domain (e.g. gbtsolutions-stg.skyfirstlabs.com), honouring
    # the ingress-forwarded scheme. Sending the invitee to this host (rather
    # than the platform host) is what lets the token resolve to the tenant DB.
    base_url = request_base_url(request)

    invite_service = InviteService(db)
    token, email_sent = await invite_service.create_invite(
        invited_by=current_user,
        email=invite_data.email,
        expires_days=invite_data.expires_days,
        name=invite_data.name,
        role=invite_data.role,
        base_url=base_url,
    )

    # Get expiration date
    from datetime import datetime, timedelta, timezone

    expires_at = datetime.now(timezone.utc) + timedelta(days=invite_data.expires_days)

    return InviteGenerateResponse(
        token=token,
        email=invite_data.email,
        expires_at=expires_at.isoformat(),
        email_sent=email_sent,
        message=f"Invite token generated successfully. Expires in {invite_data.expires_days} days.",
    )


# SSO Endpoints


@router.get(
    "/sso/{provider}/login",
    status_code=status.HTTP_302_FOUND,
    responses={400: {"model": ErrorResponse}},
    summary="SSO Login",
    description="Redirect to SSO provider login page",
)
async def sso_login(
    provider: str,
    request: Request,
    redirect_uri: Optional[str] = Query(None, description="Redirect URI after authentication"),
    db: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    """
    SSO login endpoint - redirects to provider OAuth page.

    Args:
        provider: SSO provider (google, azure, okta)
        redirect_uri: Optional redirect URI (defaults to callback URL)
        request: FastAPI request
        db: Database session

    Returns:
        RedirectResponse: Redirect to provider OAuth page

    Raises:
        BadRequestError: If provider is not supported or not configured
    """
    if provider not in ["google", "azure", "okta"]:
        raise BadRequestError(f"Unsupported SSO provider: {provider}")

    auth0_service = Auth0Service(db)

    # Get redirect URI
    if not redirect_uri:
        # Belt-and-suspenders: the Dockerfile launches uvicorn with
        # --proxy-headers --forwarded-allow-ips='*' so request.base_url
        # already reports the real scheme. This block normalises one
        # more time in case the deploy lands without the Dockerfile
        # change (or someone runs the BE without those flags locally).
        # Google rejects http:// redirect URIs for non-localhost hosts,
        # which silently breaks SSO end-to-end — the cost of a stray
        # regex is much smaller than the cost of debugging a broken
        # login flow on staging again.
        forwarded_proto = request.headers.get("x-forwarded-proto")
        forwarded_host = request.headers.get("x-forwarded-host")
        scheme = forwarded_proto.split(",", 1)[0].strip() if forwarded_proto else request.url.scheme
        host = (
            forwarded_host.split(",", 1)[0].strip()
            if forwarded_host
            else (request.url.netloc or request.headers.get("host", ""))
        )
        # Hosted public domain → force https regardless of what the
        # ASGI app saw, because Google/Azure/Okta all refuse http://
        # callbacks for production hosts.
        if host and not host.startswith(("localhost", "127.0.0.1")):
            scheme = "https"
        if host:
            redirect_uri = f"{scheme}://{host}/api/v1/auth/sso/{provider}/callback"
        else:
            base_url = str(request.base_url)
            redirect_uri = f"{base_url.rstrip('/')}/api/v1/auth/sso/{provider}/callback"

    # Get OAuth URL based on provider
    if provider == "google":
        if not auth0_settings.is_google_enabled:
            raise BadRequestError("Google SSO is not configured")
        # State assinado e preso ao cliente que inicia o login. Era
        # `_generate_state()`, aleatorio e nunca verificado no retorno —
        # sem CSRF e sem ligacao ao cliente. Ver docs/SEGURANCA-SSO-E-
        # ISOLAMENTO-TENANT.md, achado A3.
        state = issue_state(_slug_from_request(request))
        params = {
            "client_id": auth0_settings.GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
        }
        oauth_url = f"{auth0_settings.google_authorization_url}?{urlencode(params)}"
    elif provider == "azure":
        if not auth0_settings.is_azure_enabled:
            raise BadRequestError("Azure AD SSO is not configured")
        # State assinado e preso ao cliente que inicia o login. Era
        # `_generate_state()`, aleatorio e nunca verificado no retorno —
        # sem CSRF e sem ligacao ao cliente. Ver docs/SEGURANCA-SSO-E-
        # ISOLAMENTO-TENANT.md, achado A3.
        state = issue_state(_slug_from_request(request))
        params = {
            "client_id": auth0_settings.AZURE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
        }
        oauth_url = f"{auth0_settings.azure_authorization_url}?{urlencode(params)}"
    elif provider == "okta":
        if not auth0_settings.is_okta_enabled:
            raise BadRequestError("Okta SSO is not configured")
        # State assinado e preso ao cliente que inicia o login. Era
        # `_generate_state()`, aleatorio e nunca verificado no retorno —
        # sem CSRF e sem ligacao ao cliente. Ver docs/SEGURANCA-SSO-E-
        # ISOLAMENTO-TENANT.md, achado A3.
        state = issue_state(_slug_from_request(request))
        params = {
            "client_id": auth0_settings.OKTA_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
        }
        oauth_url = f"{auth0_settings.okta_authorization_url}?{urlencode(params)}"
    else:
        raise BadRequestError(f"Unsupported provider: {provider}")

    return RedirectResponse(url=oauth_url, status_code=302)


@router.get(
    "/sso/{provider}/callback",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    summary="SSO Callback",
    description="Handle OAuth callback from SSO provider",
)
async def sso_callback(
    provider: str,
    request: Request,
    code: str = Query(..., description="Authorization code from OAuth provider"),
    state: Optional[str] = Query(None, description="State parameter from OAuth flow"),
    redirect_uri: Optional[str] = Query(None, description="Redirect URI used in authorization"),
    db: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """
    SSO callback endpoint - processes OAuth callback and returns tokens.

    Args:
        provider: SSO provider (google, azure, okta)
        code: Authorization code from OAuth provider
        state: Optional state parameter
        redirect_uri: Optional redirect URI (defaults to callback URL)
        db: Database session

    Returns:
        LoginResponse: Access token, refresh token, and user data

    Raises:
        BadRequestError: If provider is not supported, not configured, or callback fails
    """
    if provider not in ["google", "azure", "okta"]:
        raise BadRequestError(f"Unsupported SSO provider: {provider}")

    # O retorno tem de pertencer ao cliente que iniciou o login. Sem esta
    # verificacao, um `state` obtido em qualquer lado servia para entrar em
    # qualquer cliente, e o utilizador acabava criado na base em que a
    # ligacao calhasse cair. Ver docs/SEGURANCA-SSO-E-ISOLAMENTO-TENANT.md,
    # achados A1 e A3.
    #
    # Feito ANTES de instanciar o servico ou tocar na base: um retorno que
    # nao valide nao deve produzir escrita nenhuma.
    callback_tenant = _slug_from_request(request)
    try:
        verify_state(state, callback_tenant)
    except SSOStateError as exc:
        logging.getLogger(__name__).warning(
            "SSO callback recusado (provider=%s, tenant=%s): %s",
            provider,
            callback_tenant or "<plataforma>",
            exc,
        )
        raise BadRequestError("Invalid or expired SSO state")

    auth0_service = Auth0Service(db)

    # Build redirect URI from request base URL if not explicitly provided.
    # MUST match the redirect_uri sent in the /login step exactly, or the
    # provider rejects the token exchange. See the /login handler for the
    # same belt-and-suspenders normaliser — Google/Azure/Okta all reject
    # http:// callbacks for non-localhost hosts.
    if not redirect_uri:
        forwarded_proto = request.headers.get("x-forwarded-proto")
        forwarded_host = request.headers.get("x-forwarded-host")
        scheme = forwarded_proto.split(",", 1)[0].strip() if forwarded_proto else request.url.scheme
        host = (
            forwarded_host.split(",", 1)[0].strip()
            if forwarded_host
            else (request.url.netloc or request.headers.get("host", ""))
        )
        if host and not host.startswith(("localhost", "127.0.0.1")):
            scheme = "https"
        if host:
            redirect_uri = f"{scheme}://{host}/api/v1/auth/sso/{provider}/callback"
        else:
            base_url = str(request.base_url)
            redirect_uri = f"{base_url.rstrip('/')}/api/v1/auth/sso/{provider}/callback"

    # Handle callback based on provider
    if provider == "google":
        user = await auth0_service.handle_google_callback(code, redirect_uri)
    elif provider == "azure":
        user = await auth0_service.handle_azure_callback(code, redirect_uri)
    elif provider == "okta":
        user = await auth0_service.handle_okta_callback(code, redirect_uri)
    else:
        raise BadRequestError(f"Unsupported provider: {provider}")

    # Create login response
    login_response = await auth0_service.create_login_response(user)
    return LoginResponse(**login_response)
