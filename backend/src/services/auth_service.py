"""Authentication service."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

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
from src.schemas.user import LoginResponse, RefreshTokenResponse, UserCreate, UserResponse


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
        "email_verified": user.email_verified,
        "email_verified_at": user.email_verified_at,
        "onboarding_step": int(user.onboarding_step) if user.onboarding_step and str(user.onboarding_step).isdigit() else 0,
        "has_completed_onboarding": user.has_completed_onboarding,
        "selected_domain": user.selected_domain,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


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

    async def register(self, user_data: UserCreate) -> UserResponse:
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
        await self.db.refresh(user)  # Refresh to ensure all fields are loaded

        return UserResponse.model_validate(user_to_response_dict(user))

    async def login(self, email: str, password: str) -> LoginResponse:
        """
        Authenticate user and return tokens.

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

        # Verify password
        if not verify_password(password, user.password_hash):
            raise UnauthorizedError("Invalid email or password")

        # Update last login
        user.last_login_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(user)  # Refresh to ensure all fields are loaded

        # Create tokens
        token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        # Save refresh token
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
        refresh_token_model = RefreshToken(
            user_id=user.id,
            token=refresh_token,
            expires_at=expires_at,
        )
        self.db.add(refresh_token_model)
        await self.db.commit()

        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserResponse.model_validate(user_to_response_dict(user)),
        )

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

        # Save new refresh token
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
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
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def logout(self, refresh_token: str) -> None:
        """
        Logout user by revoking refresh token.

        Args:
            refresh_token: Refresh token to revoke
        """
        from sqlalchemy import select, update

        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.token == refresh_token)
            .values(revoked_at=datetime.now(timezone.utc))
        )
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

