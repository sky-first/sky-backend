"""Invite service for external invite-based authentication."""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import BadRequestError, UnauthorizedError
from src.core.security import create_access_token, create_refresh_token, get_password_hash
from src.models.user import RefreshToken, User
from src.repositories.user import UserRepository
from src.services.onboarding_service import ensure_default_page_and_space

logger = logging.getLogger(__name__)


class InviteService:
    """Service for managing user invites."""

    def __init__(self, db: AsyncSession):
        """
        Initialize invite service.

        Args:
            db: Database session
        """
        self.db = db
        self.user_repo = UserRepository(db)

    def generate_invite_token(self, user_id: UUID, expires_days: int = 7) -> str:
        """
        Generate a secure invite token for a user.

        Args:
            user_id: ID of the user creating the invite
            expires_days: Number of days until token expires (default: 7)

        Returns:
            str: Generated invite token
        """
        # Generate a secure random token
        token = secrets.token_urlsafe(32)

        # Store token in database (we'll update the user who creates the invite)
        # In practice, we might want a separate invites table, but for simplicity
        # we'll use the invited_by user's invite_token field temporarily
        # Actually, we should create a new user record with the invite_token
        # But for now, we'll return the token and let the caller handle storage

        logger.info(f"✅ Generated invite token for user {user_id}, expires in {expires_days} days")
        return token

    async def create_invite(
        self,
        invited_by: User,
        email: str,
        expires_days: int = 7,
        name: Optional[str] = None,
        role: str = "member",
    ) -> str:
        """
        Create an invite for a new user.

        Args:
            invited_by: User creating the invite
            email: Email of the user to invite
            expires_days: Number of days until invite expires (default: 7)
            name: Optional name for the invited user
            role: Tenant role for the invited user (default: "member")

        Returns:
            str: Generated invite token

        Raises:
            BadRequestError: If email already exists or is invalid
        """
        # Check if user already exists
        existing_user = await self.user_repo.get_by_email(email)
        if existing_user:
            raise BadRequestError("User with this email already exists")

        # Generate invite token
        token = self.generate_invite_token(invited_by.id, expires_days)

        # Calculate expiration date
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

        # Create user record with invite token (user will complete registration later)
        # We create a "pending" user with invite_token set
        password_hash = get_password_hash(secrets.token_urlsafe(32))  # Temporary password

        user = await self.user_repo.create(
            email=email,
            password_hash=password_hash,
            name=name or email.split("@")[0],
            role=role,
            invite_token=token,
            invite_expires_at=expires_at,
            invited_by=invited_by.id,
            email_verified=False,  # Will be verified when they complete registration
        )

        await self.db.commit()
        await self.db.refresh(user)

        logger.info(f"✅ Created invite for {email}, token expires at {expires_at}")
        return token

    async def validate_invite_token(self, token: str) -> dict:
        """
        Validate an invite token and return invite information.

        Args:
            token: Invite token to validate

        Returns:
            dict: Invite information (email, expires_at, invited_by_name)

        Raises:
            BadRequestError: If token is invalid or expired
        """
        # Find user with this invite token
        from sqlalchemy import select

        result = await self.db.execute(
            select(User).where(
                User.invite_token == token,
                User.deleted_at.is_(None),
            )
        )
        user = result.scalar_one_or_none()

        if not user:
            raise BadRequestError("Invalid invite token")

        # Check if token is expired.
        # SQLite can return naive datetimes; normalize to UTC-aware before comparing.
        expires_at = user.invite_expires_at
        if expires_at is not None and getattr(expires_at, "tzinfo", None) is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at and expires_at < datetime.now(timezone.utc):
            raise BadRequestError("Invite token has expired")

        # Get inviter information
        inviter_name = "Unknown"
        if user.invited_by:
            inviter = await self.user_repo.get_by_id(user.invited_by)
            if inviter:
                inviter_name = inviter.name

        logger.debug(f"✅ Validated invite token for {user.email}")
        return {
            "email": user.email,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "invited_by_name": inviter_name,
            "name": user.name,
        }

    async def create_user_from_invite(
        self,
        token: str,
        password: str,
        name: Optional[str] = None,
    ) -> User:
        """
        Create/complete user registration from invite token.

        Args:
            token: Invite token
            password: User's chosen password
            name: Optional name (if not provided, uses existing name from invite)

        Returns:
            User: Created/updated user

        Raises:
            BadRequestError: If token is invalid, expired, or password is invalid
        """
        # Validate token first
        await self.validate_invite_token(token)

        # Find user with this invite token
        from sqlalchemy import select

        result = await self.db.execute(
            select(User).where(
                User.invite_token == token,
                User.deleted_at.is_(None),
            )
        )
        user = result.scalar_one_or_none()

        if not user:
            raise BadRequestError("Invalid invite token")

        # Update user with password and clear invite token
        user.password_hash = get_password_hash(password)
        user.invite_token = None
        user.invite_expires_at = None
        user.email_verified = True  # Invite implies email verification
        user.email_verified_at = datetime.now(timezone.utc)

        if name:
            user.name = name

        await self.db.commit()
        await self.db.refresh(user)

        # Ensure default page/space for new users
        await ensure_default_page_and_space(self.db, user)

        logger.info(f"✅ User created from invite: {user.email}")
        return user

    async def login_with_invite(self, token: str, password: str) -> dict:
        """
        Login user with invite token and password.

        Args:
            token: Invite token
            password: User's password

        Returns:
            dict: Login response with access_token, refresh_token, expires_in, and user

        Raises:
            BadRequestError: If token is invalid or expired
            UnauthorizedError: If password is incorrect
        """
        # Validate token first
        await self.validate_invite_token(token)

        # Find user with this invite token
        from sqlalchemy import select

        result = await self.db.execute(
            select(User).where(
                User.invite_token == token,
                User.deleted_at.is_(None),
            )
        )
        user = result.scalar_one_or_none()

        if not user:
            raise BadRequestError("Invalid invite token")

        # Verify password
        from src.core.security import verify_password

        if not verify_password(password, user.password_hash):
            raise UnauthorizedError("Invalid password")

        # If user hasn't completed registration (still has invite_token), complete it
        if user.invite_token:
            user.invite_token = None
            user.invite_expires_at = None
            user.email_verified = True
            user.email_verified_at = datetime.now(timezone.utc)
            await self.db.commit()

        # Update last login
        user.last_login_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(user)

        # Create tokens
        from src.schemas.user import UserResponse
        from src.services.auth_service import user_to_response_dict

        token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        # Save refresh token
        expires_at = datetime.now(timezone.utc) + timedelta(days=365 * 100)  # Effectively infinite
        refresh_token_model = RefreshToken(
            user_id=user.id,
            token=refresh_token,
            expires_at=expires_at,
        )
        self.db.add(refresh_token_model)
        await self.db.commit()

        logger.info(f"✅ User logged in with invite token: {user.email}")

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": 365 * 100 * 24 * 60 * 60,  # 100 years in seconds
            "user": UserResponse.model_validate(user_to_response_dict(user)),
        }

    async def accept_invite(self, token: str, password: str) -> dict:
        """
        Accept invite: set password and login.

        Args:
            token: Invite token
            password: New password

        Returns:
            dict: Login response

        Raises:
            BadRequestError: If token is invalid or expired
        """
        # Validate token first
        await self.validate_invite_token(token)

        # Find user with this invite token
        from sqlalchemy import select

        result = await self.db.execute(
            select(User).where(
                User.invite_token == token,
                User.deleted_at.is_(None),
            )
        )
        user = result.scalar_one_or_none()

        if not user:
            raise BadRequestError("Invalid invite token")

        # Update user
        user.password_hash = get_password_hash(password)
        user.invite_token = None
        user.invite_expires_at = None
        user.email_verified = True
        user.email_verified_at = datetime.now(timezone.utc)
        user.status = "active"
        user.last_active_at = datetime.now(timezone.utc)
        user.last_login_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(user)

        # Ensure default page/space
        await ensure_default_page_and_space(self.db, user)

        # Create tokens
        from src.schemas.user import UserResponse
        from src.services.auth_service import user_to_response_dict

        token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        # Save refresh token
        expires_at = datetime.now(timezone.utc) + timedelta(days=365 * 100)
        refresh_token_model = RefreshToken(
            user_id=user.id,
            token=refresh_token,
            expires_at=expires_at,
        )
        self.db.add(refresh_token_model)
        await self.db.commit()

        logger.info(f"✅ Invite accepted by user: {user.email}")

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": 365 * 100 * 24 * 60 * 60,
            "user": UserResponse.model_validate(user_to_response_dict(user)),
        }
