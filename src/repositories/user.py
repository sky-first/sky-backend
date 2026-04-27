"""User repository."""

from datetime import timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.user import User
from src.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """User repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, User)

    async def get_by_email(self, email: str) -> Optional[User]:
        """
        Get user by email.

        Args:
            email: User email

        Returns:
            Optional[User]: User or None
        """
        result = await self.db.execute(
            select(User).where(User.email == email, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_email_including_deleted(self, email: str) -> Optional[User]:
        """
        Get user by email — INCLUDING soft-deleted rows.

        Used by the SSO callback flow to detect a returning user whose
        account was previously deleted, so we can restore the existing
        row (clear deleted_at) instead of failing on the unique-email
        index when create_user_from_auth0 attempts an INSERT. Without
        this, a deleted user is permanently locked out of SSO re-login
        even though their identity provider still authenticates them.

        Callers MUST be careful not to leak the soft-deleted state to
        unprivileged code paths — the returned User has deleted_at set
        and should be either restored (set to None) or rejected
        explicitly. Do NOT use this from generic read paths.
        """
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_email_with_tokens(self, email: str) -> Optional[User]:
        """
        Get user by email with refresh tokens loaded.

        Args:
            email: User email

        Returns:
            Optional[User]: User or None
        """
        result = await self.db.execute(
            select(User)
            .where(User.email == email, User.deleted_at.is_(None))
            .options(selectinload(User.refresh_tokens))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, id: UUID) -> Optional[User]:
        """
        Get user by ID (excluding deleted).

        Args:
            id: User ID

        Returns:
            Optional[User]: User or None
        """
        result = await self.db.execute(select(User).where(User.id == id, User.deleted_at.is_(None)))
        return result.scalar_one_or_none()

    async def update_last_active_atomic(self, user_id: UUID, cooldown_seconds: int = 60) -> None:
        """
        Atomically update last_active_at using a conditional SQL WHERE clause.

        This avoids the Python-level read → check → write race condition by
        pushing the time-check into the database engine itself. Postgres will
        only lock the row when the condition is true, preventing lock storms
        when many parallel requests arrive for the same user_id.

        Args:
            user_id: User ID to update.
            cooldown_seconds: Minimum seconds between updates (default 60).
        """
        now = func.now()
        threshold = func.now() - timedelta(seconds=cooldown_seconds)

        stmt = (
            update(User)
            .where(User.id == user_id)
            .where(User.deleted_at.is_(None))
            .where(
                or_(
                    User.last_active_at.is_(None),
                    User.last_active_at < threshold,
                )
            )
            .values(last_active_at=now, status="active", updated_at=now)
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def get_by_auth0_id(self, auth0_id: str) -> Optional[User]:
        """
        Get user by Auth0 ID.

        Args:
            auth0_id: Auth0 user ID

        Returns:
            Optional[User]: User or None
        """
        result = await self.db.execute(
            select(User).where(User.auth0_id == auth0_id, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_auth_provider_id(self, provider_id: str, provider: str) -> Optional[User]:
        """
        Get user by auth provider ID.

        Args:
            provider_id: Provider-specific user ID
            provider: Provider name (google, azure, okta)

        Returns:
            Optional[User]: User or None
        """
        result = await self.db.execute(
            select(User).where(
                User.auth_provider_id == provider_id,
                User.auth_provider == provider,
                User.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_all(self, skip: int = 0, limit: int = 100) -> List[User]:
        """
        Get all users (excluding deleted).

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            List[User]: List of users
        """
        result = await self.db.execute(
            select(User)
            .where(User.deleted_at.is_(None))
            .order_by(User.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())
