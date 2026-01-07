"""User repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
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
        result = await self.db.execute(
            select(User).where(User.id == id, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_auth0_id(self, auth0_id: str) -> Optional[User]:
        """
        Get user by Auth0 ID.

        Args:
            auth0_id: Auth0 user ID

        Returns:
            Optional[User]: User or None
        """
        result = await self.db.execute(
            select(User).where(
                User.auth0_id == auth0_id,
                User.deleted_at.is_(None)
            )
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
                User.deleted_at.is_(None)
            )
        )
        return result.scalar_one_or_none()

    async def get_all(
        self, skip: int = 0, limit: int = 100
    ) -> List[User]:
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

