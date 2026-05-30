"""Authentication service."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from src.config.settings import settings
from src.core.exceptions import BadRequestError, UnauthorizedError
from src.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
    verify_token,
)
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
            user.role == "admin"
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
            await ai_client.ingest_knowledge_graph({
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
            })
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
        token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
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

        return await self._issue_session(
            user,
            user_agent=user_agent,
            ip_address=ip_address,
            background_tasks=background_tasks,
        )

    async def _issue_session(
        self,
        user: User,
        *,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> LoginResponse:
        """Mint access+refresh tokens for an authenticated user.

        Shared between the no-MFA login path and ``complete_mfa_login``
        so the post-auth side-effects (last_login_at, onboarding
        bootstrap, refresh-token row) are guaranteed to be identical
        regardless of whether a second factor was involved.
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
        token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
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

    async def complete_mfa_login(
        self,
        *,
        challenge_token: str,
        code: str,
        is_recovery_code: bool = False,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
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

        user_id = UUID(payload.get("sub"))
        if not user_id:
            raise UnauthorizedError("Invalid token payload")

        # Check if refresh token exists and is valid
        from sqlalchemy import select

        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.token == refresh_token,
                RefreshToken.expires_at > datetime.now(timezone.utc),
                RefreshToken.revoked_at.is_(None),
            )
        )
        token_model = result.scalar_one_or_none()

        if not token_model:
            raise UnauthorizedError("Invalid or expired refresh token")

        # Get user
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise UnauthorizedError("User not found")

        # Revoke old token
        token_model.revoked_at = datetime.now(timezone.utc)

        # Create new tokens
        token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
        new_access_token = create_access_token(token_data)
        new_refresh_token = create_refresh_token(token_data)

        # Save new refresh token (set to 100 years in the future - effectively infinite)
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )
        new_token_model = RefreshToken(
            user_id=user.id,
            token=new_refresh_token,
            expires_at=expires_at,
        )
        self.db.add(new_token_model)
        await self.db.commit()

        return RefreshTokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_in=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
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
