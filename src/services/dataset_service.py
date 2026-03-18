"""Dataset management service."""

import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.models.user import User
from src.repositories.dataset import UserDatasetRepository
from src.services.file_upload_service import FileUploadService

logger = logging.getLogger(__name__)


class DatasetService:
    """Dataset management service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize dataset service.

        Args:
            db: Database session
        """
        self.db = db
        self.dataset_repo = UserDatasetRepository(db)
        self.file_service = FileUploadService(db)

    async def delete_dataset(self, dataset_id: str, user: User) -> None:
        """
        Delete a dataset (table or file).

        Args:
            dataset_id: Dataset ID (can be table name or file_id prefixed with "file_")
            user: Current user

        Raises:
            NotFoundError: If dataset not found (for files)
        """
        # Check if it's a file (starts with "file_")
        if dataset_id.startswith("file_"):
            # Extract file_id from "file_{file_id}"
            file_id_str = dataset_id.replace("file_", "")
            try:
                file_id = UUID(file_id_str)
            except ValueError:
                raise NotFoundError(f"Invalid file ID: {file_id_str}")

            # Delete the file using file service
            await self.file_service.delete_file(file_id, user)

            # Also mark as excluded in user_datasets
            try:
                existing = await self.dataset_repo.get_by_user_and_dataset(
                    user.id, dataset_id
                )
                if not existing:
                    await self.dataset_repo.create(
                        user_id=user.id, dataset_id=dataset_id, dataset_type="file"
                    )
                    await self.db.commit()
            except IntegrityError:
                # Already exists, ignore
                await self.db.rollback()
                logger.debug(f"Dataset {dataset_id} already marked as excluded")
        else:
            # It's a table - just mark as excluded
            try:
                existing = await self.dataset_repo.get_by_user_and_dataset(
                    user.id, dataset_id
                )
                if not existing:
                    await self.dataset_repo.create(
                        user_id=user.id, dataset_id=dataset_id, dataset_type="table"
                    )
                    await self.db.commit()
            except IntegrityError:
                # Already exists, ignore
                await self.db.rollback()
                logger.debug(f"Dataset {dataset_id} already marked as excluded")
            except Exception as e:
                logger.error(
                    f"Error marking dataset {dataset_id} as excluded: {str(e)}",
                    exc_info=True,
                )
                await self.db.rollback()
                raise

    async def get_excluded_datasets(self, user: User) -> list[str]:
        """
        Get list of excluded dataset IDs for a user.

        Args:
            user: Current user

        Returns:
            list[str]: List of excluded dataset IDs
        """
        return await self.dataset_repo.get_excluded_datasets(user.id)
