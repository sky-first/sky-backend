"""File upload repository."""

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.file import FileUpload
from src.repositories.base import BaseRepository


class FileUploadRepository(BaseRepository[FileUpload]):
    """File upload repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, FileUpload)
