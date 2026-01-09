"""Dataset repositories."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.dataset import UserDataset
from src.repositories.base import BaseRepository


class UserDatasetRepository(BaseRepository[UserDataset]):
    """User dataset repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, UserDataset)

    async def get_by_user_and_dataset(
        self, user_id: UUID, dataset_id: str
    ) -> Optional[UserDataset]:
        """
        Get user dataset exclusion by user and dataset ID.

        Args:
            user_id: User ID
            dataset_id: Dataset ID (table name or file_id)

        Returns:
            Optional[UserDataset]: User dataset exclusion if found
        """
        result = await self.db.execute(
            select(UserDataset).where(
                UserDataset.user_id == user_id, UserDataset.dataset_id == dataset_id
            )
        )
        return result.scalar_one_or_none()

    async def get_excluded_datasets(self, user_id: UUID) -> list[str]:
        """
        Get list of excluded dataset IDs for a user.

        Args:
            user_id: User ID

        Returns:
            list[str]: List of excluded dataset IDs
        """
        result = await self.db.execute(
            select(UserDataset.dataset_id).where(UserDataset.user_id == user_id)
        )
        return [row[0] for row in result.all()]
