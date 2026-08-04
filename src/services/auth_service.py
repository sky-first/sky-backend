"""Authentication service."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from src.config.settings import settings
from src.core.device_tenant import carry_tenant_claims, tenant_claims_for_context
from src.core.exceptions import BadRequestError, UnauthorizedError
from src.core.permissions import is_tenant_admin
from src.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    refresh_ttl_days,
    verify_password,
    verify_token,
)
from src.core.tenant_context import current_tenant, reset_current_tenant, set_current_tenant
from src.models.user import RefreshToken, User
from src.repositories.user import UserRepository
from src.schemas.user import (
    LoginResponse,
    RefreshTokenResponse,
    RegisterRequest,
    UserCreate,
    UserResponse,
)
from src.services.onboarding_service import ensure_default_page_and_space


def user_to_response_dict(user: User) -> dict:
    """
    Convert User model to dictionary for UserResponse validation.

    Args:
        user: User model instance

    Returns:
        dict: Dictionary with converted fields
    """
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar": user.avatar,
        "role": user.role,
        "is_demo": user.is_demo,
        "demo_expires_at": user.demo_expires_at,
        "email_verified": user.email_verified,
        "email_verified_at": user.email_verified_at,
        "onboarding_step": user.onboarding_step or 0,
        "onboarding_version": user.onboarding_version or 0,
        "needs_onboarding": (
            is_tenant_admin(user)
            and (user.onboarding_version or 0) < settings.ADMIN_ONBOARDING_VERSION
        ),
        "has_completed_onboarding": user.has_completed_onboarding,
        "selected_domain": user.selected_domain,
        "preferences": user.preferences or {},
        "last_login_at": user.last_login_at,
        "last_active_at": user.last_active_at,
        "status": user.status or "offline",
        # Sky-platform fields — passed through so SSO callback /
        # password login responses don't strip the operator flag and
        # internal role. Without this, the FE user-store hydrates
        # without ``is_sky_operator`` and the platform profile dropdown
        # silently hides the Console shortcut for engineers.
        "is_sky_operator": bool(getattr(user, "is_sky_operator", False)),
        "sky_role": getattr(user, "sky_role", None),
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


async def perform_onboarding_task(user_id: UUID):
    """Background task to ensure default page and space for a user."""
    from src.config.database import AsyncSessionLocal
    from src.repositories.user import UserRepository
    from src.services.onboarding_service import ensure_default_page_and_space

    async with AsyncSessionLocal() as db:
        user_repo = UserRepository(db)
        user = await user_repo.get_by_id(user_id)
        if user:
            await ensure_default_page_and_space(db, user)


class AuthenticationService:
    """Authentication service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize authentication service.

        Args:
            db: Database session
        """
        self.db = db
        self.user_repo = UserRepository(db)

    async def register(
        self, user_data: UserCreate, background_tasks: Optional[BackgroundTasks] = None
    ) -> UserResponse:
        """
        Register a new user.

        Args:
            user_data: User creation data

        Returns:
            UserResponse: Created user

        Raises:
            BadRequestError: If email already exists
        """
        # Check if user already exists
        existing_user = await self.user_repo.get_by_email(user_data.email)
        if existing_user:
            raise BadRequestError("User with this email already exists")

        # Create user
        user = await self.user_repo.create(
            email=user_data.email,
            password_hash=get_password_hash(user_data.password),
            name=user_data.name,
            avatar=user_data.avatar,
            role=user_data.role,
        )

        await self.db.commit()
        await self.db.refresh(user)
        # Note: redundant refresh removed due to expire_on_commit=False

        # Ensure default page/space for new users
        if user.id:
            if background_tasks:
                background_tasks.add_task(perform_onboarding_task, UUID(str(user.id)))
            else:
                await ensure_default_page_and_space(self.db, user)

        # Ingest the user into the RAG so agents + chat can answer
        # questions like "who is on my team?" or "who reported that
        # finding?". Personal scope (owner_user_id = self) so the
        # user's profile only shows up in their own retrieval unless
        # they end up as a member of shared scopes.
        try:
            from src.ai.http_client import AIServiceHTTPClient

            ai_client = AIServiceHTTPClient()
            await ai_client.ingest_knowledge_graph(
                {
                    "id": str(user.id),
                    "entity_type": "user",
                    "name": user.name,
                    "description": f"Platform user — {user.role}" if user.role else "Platform user",
                    "space_id": None,
                    "crew_id": None,
                    "owner_user_id": str(user.id),
                    "entity_details": {
                        "email": user.email,
                        "role": user.role,
                    },
                }
            )
        except Exception as exc:
            logger.warning(f"AI ingest failed for user {user.id}: {exc}")

        user_response_data = user_to_response_dict(user)
        return UserResponse.model_validate(user_response_data)

    async def register_with_tokens(
        self,
        register_data: RegisterRequest,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> LoginResponse:
        """
        Register a new user and return tokens (auto-login after registration).

        Args:
            register_data: Registration data

        Returns:
            LoginResponse: Access token, refresh token, and user data

        Raises:
            BadRequestError: If email already exists
        """
        # Derive name from email if not provided
        name = register_data.name
        if not name:
            # Extract name from email (part before @)
            email_part = register_data.email.split("@")[0]
            # Capitalize first letter and replace dots/underscores with spaces
            name = email_part.replace(".", " ").replace("_", " ").title()

        # Create UserCreate from RegisterRequest
        user_data = UserCreate(
            email=register_data.email,
            password=register_data.password,
            name=name,
            role="user",  # Default role for self-registration
        )

        # Register user (this will check for existing email and create user)
        user_response = await self.register(user_data, background_tasks=background_tasks)

        # Get the created user from database
        user = await self.user_repo.get_by_email(register_data.email)
        if not user:
            raise BadRequestError("Failed to create user")

        # Create tokens (same logic as login)
        token_data = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            # BE-01: stamp the resolved tenant so device clients carry a
            # signed, immutable tenant claim. No-op in single-tenant mode.
            **tenant_claims_for_context(current_tenant()),
        }
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        # Save refresh token (set to 100 years in the future - effectively infinite)
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )
        refresh_token_model = RefreshToken(
            user_id=user.id,
            token=refresh_token,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
            # BE-05 — a fresh login opens a new token family (login lineage).
            family_id=uuid4(),
        )
        self.db.add(refresh_token_model)
        await self.db.commit()

        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            user=user_response,
        )

    async def login(
        self,
        email: str,
        password: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> LoginResponse:
        """
        Authenticate user and return tokens (hybrid: traditional, SSO, or invite).

        Args:
            email: User email
            password: User password

        Returns:
            LoginResponse: Access token, refresh token, and user data

        Raises:
            UnauthorizedError: If credentials are invalid
        """
        # Get user
        user = await self.user_repo.get_by_email(email)
        if not user:
            raise UnauthorizedError("Invalid email or password")

        # Check authentication type
        auth_type = self._detect_auth_type(user)

        # Validate based on auth type
        if auth_type == "sso":
            # SSO users should not login with password
            raise UnauthorizedError(
                "This account uses SSO authentication. Please use your SSO provider to login."
            )
        elif auth_type == "invite":
            # Invite users can login with password, but must complete registration first
            if user.invite_token:
                raise UnauthorizedError(
                    "Please complete your registration using the invite token first."
                )

        # Verify password (for traditional and completed invite users)
        if not user.password_hash or not verify_password(password, user.password_hash):
            raise UnauthorizedError("Invalid email or password")

        # Phase 3 — MFA gate. When the user has TOTP enabled we stop
        # short of issuing real tokens and hand back a short-lived
        # challenge token instead. The caller redeems it at
        # /auth/login/mfa with the 6-digit code (or a recovery code)
        # and only then receives access + refresh. last_login_at is
        # bumped only after the second factor succeeds — otherwise an
        # attacker with the password could ping it indefinitely and
        # mask the fact that they don't have the device.
        if getattr(user, "mfa_enabled", False):
            from src.services.mfa_service import (
                MFA_CHALLENGE_TTL_MINUTES,
                issue_mfa_challenge_token,
            )

            # Commit nothing — no DB state changes for an MFA-required
            # account at this stage. (Refresh tokens are only created
            # after the second factor in ``complete_mfa_login``.)
            challenge_token = issue_mfa_challenge_token(user)
            return LoginResponse(
                require_mfa=True,
                mfa_challenge_token=challenge_token,
                mfa_expires_in=MFA_CHALLENGE_TTL_MINUTES * 60,
            )

        # Force MFA enrolment on first password login (Lucas decision
        # 2026-05-31). A password-authenticated account without MFA is
        # the threat we want to close: phished credentials would walk
        # straight in. SSO-only users skip this because the IdP already
        # enforces 2FA. We bake the candidate secret into the enrolment
        # token so a half-done enrolment doesn't leave a DB row behind
        # — only the finalize-step writes anything.
        from src.services.mfa_service import (
            MFA_ENROLLMENT_TTL_MINUTES,
            MFAService,
            issue_mfa_enrollment_token,
        )

        mfa = MFAService(self.db)
        # Issuer is the bare brand for now; per-tenant labelling can
        # be wired once the resolver lands in this code path.
        challenge = await mfa.generate_enrollment(user)
        enrollment_token = issue_mfa_enrollment_token(user, challenge.secret)
        return LoginResponse(
            force_enrollment=True,
            mfa_enrollment_token=enrollment_token,
            mfa_enrollment_secret=challenge.secret,
            mfa_enrollment_qrcode_b64=challenge.qrcode_png_b64,
            mfa_enrollment_issuer="SkyFirst",
            mfa_expires_in=MFA_ENROLLMENT_TTL_MINUTES * 60,
        )

    async def _issue_session(
        self,
        user: User,
        *,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
        client_type: Optional[str] = None,
    ) -> LoginResponse:
        """Mint access+refresh tokens for an authenticated user.

        Shared between the no-MFA login path and ``complete_mfa_login``
        so the post-auth side-effects (last_login_at, onboarding
        bootstrap, refresh-token row) are guaranteed to be identical
        regardless of whether a second factor was involved.

        ``client_type='mobile'`` gives the refresh token the longer mobile
        TTL (BE-05) and stamps a ``ctyp`` claim so rotations keep it.
        """
        # Update last login
        user.last_login_at = datetime.now(timezone.utc)

        # Ensure default page/space exists (fallback for legacy users)
        if user.id:
            if background_tasks:
                background_tasks.add_task(perform_onboarding_task, UUID(str(user.id)))
            else:
                await ensure_default_page_and_space(self.db, user)

        # Create tokens
        tenant_claims = tenant_claims_for_context(current_tenant())
        token_data = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            # BE-01: stamp the resolved tenant so device clients carry a
            # signed, immutable tenant claim. No-op in single-tenant mode.
            **tenant_claims,
        }

        # Registar a pertença. `TenantMembershipService.grant` dizia na
        # docstring "called on every successful login" mas ninguém o
        # chamava — a tabela nunca era preenchida, portanto o portão de
        # dispositivo (que verifica pertença a cada pedido) recusava
        # todos os utilizadores móveis com 403. O portão falhava fechado,
        # que é o lado certo para falhar, mas falhava.
        #
        # Aqui é o sítio certo: o login é o único momento em que sabemos
        # ao mesmo tempo quem é a pessoa e a que cliente se autenticou
        # com sucesso. Idempotente — não cria linhas repetidas.
        if tenant_claims.get("tid"):
            from src.services.tenant_membership_service import TenantMembershipService

            await TenantMembershipService.upsert(
                self.db,
                user_id=user.id,
                tenant_id=tenant_claims["tid"],
                role=user.role or "member",
            )

        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data, client_type=client_type)

        # BE-05 — refresh row TTL matches the JWT exp (mobile gets the long one).
        expires_at = datetime.now(timezone.utc) + timedelta(days=refresh_ttl_days(client_type))
        refresh_token_model = RefreshToken(
            user_id=user.id,
            token=refresh_token,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
            # BE-05 — a fresh login opens a new token family (login lineage).
            family_id=uuid4(),
        )
        self.db.add(refresh_token_model)

        # Flush to avoid greenlet issues when accessing attributes in sync function later
        await self.db.commit()
        await self.db.refresh(user)

        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            user=UserResponse.model_validate(user_to_response_dict(user)),
        )

    async def issue_session_for_tenant(
        self,
        user: User,
        tenant_ctx,
        *,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> LoginResponse:
        """Re-issue a session scoped to ``tenant_ctx`` — the BE-01 workspace
        switch (``POST /auth/select-workspace``).

        Switching tenants is always an *explicit* re-issue, never a side
        effect of refreshing. We set the tenant contextvar so
        ``_issue_session`` stamps the correct ``tid``/``tslug`` into the new
        tokens, then restore it — reusing every standard post-auth side
        effect (refresh-token row, last_login_at) unchanged. The caller is
        responsible for verifying the user's membership of ``tenant_ctx``
        *before* calling this.
        """
        token = set_current_tenant(tenant_ctx)
        try:
            return await self._issue_session(user, user_agent=user_agent, ip_address=ip_address)
        finally:
            reset_current_tenant(token)

    async def complete_mfa_login(
        self,
        *,
        challenge_token: str,
        code: str,
        is_recovery_code: bool = False,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
        client_type: Optional[str] = None,
    ) -> LoginResponse:
        """Redeem an MFA challenge token + second factor for real tokens.

        Phase 3 of the auth roadmap. The challenge token was issued
        by ``login`` after a successful password check; it embeds the
        ``sub`` (user id) and expires after 5 minutes. We re-load the
        user here so a concurrent ``disable_mfa`` (e.g. via admin
        impersonation) takes effect immediately — if the user no
        longer has MFA enabled by the time the second-factor lands,
        we still issue tokens (no second factor is required).
        """
        from src.services.mfa_service import MFAService, verify_mfa_challenge_token

        try:
            user_id_str = verify_mfa_challenge_token(challenge_token)
        except ValueError:
            raise UnauthorizedError("Invalid or expired MFA challenge")

        try:
            user_id = UUID(user_id_str)
        except (TypeError, ValueError):
            raise UnauthorizedError("Invalid MFA challenge payload")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise UnauthorizedError("User not found")

        # If MFA has been disabled in the meantime, accept the
        # challenge as proof of password and skip the second factor.
        if getattr(user, "mfa_enabled", False):
            mfa = MFAService(self.db)
            ok = False
            if is_recovery_code:
                ok = await mfa.consume_recovery_code(user, code)
            else:
                ok = await mfa.verify_login_code(user, code)
            if not ok:
                raise UnauthorizedError("Invalid MFA code")

        return await self._issue_session(
            user,
            user_agent=user_agent,
            ip_address=ip_address,
            background_tasks=background_tasks,
            client_type=client_type,
        )

    async def finalize_mfa_enrollment(
        self,
        *,
        enrollment_token: str,
        code: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
        client_type: Optional[str] = None,
    ):
        """Close the forced first-login MFA enrolment + mint tokens.

        Path:
          1. Verify the enrolment token, recover (user_id, secret).
          2. Verify the user's 6-digit code matches the secret.
          3. Persist the secret + bcrypt-hashed recovery codes.
          4. Mint the access + refresh pair (same shape as a normal
             login) and return the recovery codes ONCE in the body.

        Refuses with a 409 if MFA is already enabled on the account —
        protects against an attacker replaying a stale enrolment token
        after the legitimate owner has finished onboarding.
        """
        from fastapi import HTTPException
        from fastapi import status as http_status

        from src.schemas.user import MFAFinalizeEnrollmentResponse, UserResponse
        from src.services.mfa_service import MFAService, verify_mfa_enrollment_token

        try:
            user_id_str, secret = verify_mfa_enrollment_token(enrollment_token)
        except ValueError:
            raise UnauthorizedError("Invalid or expired enrolment token")

        try:
            user_id = UUID(user_id_str)
        except (TypeError, ValueError):
            raise UnauthorizedError("Invalid enrolment token payload")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise UnauthorizedError("User not found")

        mfa = MFAService(self.db)
        try:
            result = await mfa.persist_enrollment(user, secret=secret, code=code)
        except ValueError as exc:
            if str(exc) == "mfa_already_enabled":
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail="MFA is already enabled on this account",
                )
            raise UnauthorizedError("Invalid code")

        # Mint the session tokens via the same pipeline that the
        # password-without-MFA path used pre-Phase 3. Returns
        # LoginResponse; we unpack into the enrolment-specific shape
        # that also surfaces the freshly minted recovery codes.
        session = await self._issue_session(
            user,
            user_agent=user_agent,
            ip_address=ip_address,
            background_tasks=background_tasks,
            client_type=client_type,
        )
        return MFAFinalizeEnrollmentResponse(
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            token_type=session.token_type,
            expires_in=session.expires_in,
            user=session.user,
            recovery_codes=result.recovery_codes,
        )

    def _detect_auth_type(self, user: User) -> str:
        """
        Detect authentication type for a user.

        Args:
            user: User model

        Returns:
            str: Authentication type (traditional, sso, invite)
        """
        # Check if user has SSO provider
        if user.auth_provider and user.auth_provider != "local":
            return "sso"

        # Check if user has active invite
        if user.invite_token and user.invite_expires_at:
            if user.invite_expires_at > datetime.now(timezone.utc):
                return "invite"

        # Default to traditional
        return "traditional"

    async def refresh_access_token(self, refresh_token: str) -> RefreshTokenResponse:
        """
        Refresh access token using refresh token.

        Args:
            refresh_token: Refresh token

        Returns:
            RefreshTokenResponse: New access and refresh tokens

        Raises:
            UnauthorizedError: If refresh token is invalid
        """
        # Verify refresh token
        try:
            payload = verify_token(refresh_token, token_type="refresh")
        except Exception:
            raise UnauthorizedError("Invalid refresh token")

        # BE-05 (T-05.8) — a refresh token is bound to its tenant. If the
        # request resolves to a different tenant than the token's signed tid,
        # reject: a tenant-A token must never refresh against tenant B. No-op
        # in single-tenant mode (no tid on either side).
        token_tid = payload.get("tid")
        ctx_tid = tenant_claims_for_context(current_tenant()).get("tid")
        if token_tid and ctx_tid and str(token_tid) != str(ctx_tid):
            raise UnauthorizedError("Refresh token tenant mismatch")

        user_id = UUID(payload.get("sub"))
        if not user_id:
            raise UnauthorizedError("Invalid token payload")

        # BE-05 — look the token up WITHOUT the revoked/expired filter so we
        # can tell three cases apart: unknown (forged), already-rotated (reuse
        # = theft), or genuinely active. The old code collapsed all three into
        # one 401, so a stolen token that had already been rotated could be
        # replayed and nobody would notice.
        #
        # TODO(BE-09): TOCTOU on concurrent refresh. Two simultaneous refreshes
        # with the same token can both read it as active before either revokes,
        # so the loser trips the reuse detector and nukes a healthy family by
        # mistake. Harden with a row lock (SELECT ... FOR UPDATE) + a short
        # grace window, plus a concurrency test. Accepted for now (BE-05).
        from sqlalchemy import select

        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token == refresh_token)
        )
        token_model = result.scalar_one_or_none()

        if token_model is None:
            # A token we never issued (or already pruned) — nothing to nuke.
            raise UnauthorizedError("Invalid refresh token")

        if token_model.revoked_at is not None:
            # 🚨 A revoked token is being reused. Treat it as compromise:
            # revoke the whole family and blocklist the user's access tokens.
            await self._revoke_token_family(token_model)
            raise UnauthorizedError("Refresh token reuse detected")

        # Normalise tz: SQLite hands back naive datetimes, Postgres aware ones.
        expires_at = token_model.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise UnauthorizedError("Invalid or expired refresh token")

        # Get user
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise UnauthorizedError("User not found")

        # Revoke old token (rotation)
        token_model.revoked_at = datetime.now(timezone.utc)

        # Create new tokens
        # BE-01: a refresh must PRESERVE the tenant — switching workspace is
        # an explicit /auth/select-workspace re-issue, never a side effect of
        # refreshing. We carry the tid/tslug forward from the incoming token.
        token_data = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            **carry_tenant_claims(payload),
        }
        # BE-05 — carry the client type forward so a mobile session keeps its
        # long refresh TTL across every rotation, not just the first one.
        client_type = payload.get("ctyp")
        new_access_token = create_access_token(token_data)
        new_refresh_token = create_refresh_token(token_data, client_type=client_type)

        expires_at = datetime.now(timezone.utc) + timedelta(days=refresh_ttl_days(client_type))
        new_token_model = RefreshToken(
            user_id=user.id,
            token=new_refresh_token,
            expires_at=expires_at,
            # BE-05 — the rotated token stays in the same family as its parent
            # (``or id`` covers legacy rows backfilled to their own id).
            family_id=token_model.family_id or token_model.id,
        )
        self.db.add(new_token_model)
        await self.db.commit()

        return RefreshTokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_in=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        )

    async def _revoke_token_family(self, token_model: RefreshToken) -> None:
        """BE-05 — a revoked refresh token was replayed: treat it as theft.

        Revoke every still-live token in the same family (the login lineage)
        so neither attacker nor victim can rotate it again, then bump the
        user's access-token blocklist so any outstanding access token minted
        from this login dies within seconds (Option A). Other devices keep
        their own families and simply re-refresh silently.
        """
        from sqlalchemy import or_, update

        family = token_model.family_id or token_model.id
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(RefreshToken)
            .where(
                or_(
                    RefreshToken.family_id == family,
                    RefreshToken.id == family,  # legacy row: family == own id
                ),
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await self.db.commit()
        logger.warning(
            "BE-05: refresh-token reuse detected — revoked family %s for user %s",
            family,
            token_model.user_id,
        )
        # Best-effort: kill outstanding access tokens for this user. A Redis
        # hiccup must never swallow the reuse signal — the family is already dead.
        try:
            from src.core.token_blocklist import revoke_user_tokens

            await revoke_user_tokens(
                str(token_model.user_id), issued_before_epoch=int(now.timestamp())
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "BE-05 reuse: access-token blocklist bump failed for user %s: %s",
                token_model.user_id,
                exc,
            )

    async def logout(self, refresh_token: str) -> None:
        """
        Logout user by revoking refresh token and marking them offline.

        Args:
            refresh_token: Refresh token to revoke
        """
        from sqlalchemy import select, update

        # Revoke the token
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.token == refresh_token)
            .values(revoked_at=datetime.now(timezone.utc))
        )

        # Mark the user offline so presence reflects the logout
        result = await self.db.execute(
            select(RefreshToken.user_id).where(RefreshToken.token == refresh_token)
        )
        user_id = result.scalar_one_or_none()
        if user_id:
            await self.db.execute(update(User).where(User.id == user_id).values(status="offline"))

        await self.db.commit()

    async def revoke_all_tokens(self, user_id: UUID) -> None:
        """
        Revoke all refresh tokens for a user.

        Args:
            user_id: User ID
        """
        from sqlalchemy import update

        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await self.db.commit()

    async def revoke_device_session(self, *, session_id: UUID, user_id: UUID) -> bool:
        """BE-05 (T-05.7) — surgically revoke ONE device's session.

        Revokes the whole family of the refresh token identified by
        ``session_id`` (so that device's rotated tokens all die) but touches
        no other family and does NOT bump the user-level access blocklist —
        so the user's *other* devices keep working. This is the "sign out
        this device" primitive behind ``DELETE /auth/sessions/{id}``, distinct
        from ``logout`` (current device) and ``revoke_all_tokens`` (all).

        Returns True if a matching, still-live session was found.
        """
        from sqlalchemy import or_, select, update

        row = (
            await self.db.execute(
                select(RefreshToken).where(
                    RefreshToken.id == session_id,
                    RefreshToken.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return False

        family = row.family_id or row.id
        result = await self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                or_(RefreshToken.family_id == family, RefreshToken.id == family),
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await self.db.commit()
        return result.rowcount > 0

    async def get_current_user(self, user_id: UUID) -> UserResponse:
        """
        Get current user by ID.

        Args:
            user_id: User ID

        Returns:
            UserResponse: User data

        Raises:
            UnauthorizedError: If user not found
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise UnauthorizedError("User not found")

        return UserResponse.model_validate(user_to_response_dict(user))

    async def get_active_sessions(self, user_id: UUID) -> list[dict]:
        """
        Get active sessions for a user.

        Args:
            user_id: User ID

        Returns:
            list[dict]: List of active sessions
        """
        from sqlalchemy import select

        result = await self.db.execute(
            select(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > datetime.now(timezone.utc),
            )
            .order_by(RefreshToken.created_at.desc())
        )
        tokens = result.scalars().all()

        return [
            {
                "id": str(token.id),
                "created_at": token.created_at,
                "expires_at": token.expires_at,
                "user_agent": token.user_agent,
                "ip_address": token.ip_address,
                "is_current": False,  # Client can determine this by comparing tokens
            }
            for token in tokens
        ]

    async def change_password(
        self, user_id: UUID, current_password: str, new_password: str
    ) -> None:
        """
        Change user password.

        Args:
            user_id: User ID
            current_password: Current password
            new_password: New password

        Raises:
            UnauthorizedError: If current password is incorrect
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise UnauthorizedError("User not found")

        if not user.password_hash or not verify_password(current_password, user.password_hash):
            raise UnauthorizedError("Invalid current password")

        user.password_hash = get_password_hash(new_password)
        await self.db.commit()
