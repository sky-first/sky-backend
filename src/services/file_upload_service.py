"""File upload service."""

import csv
import io
import secrets
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.core.exceptions import BadRequestError, NotFoundError
from src.models.user import User
from src.repositories.file import FileUploadRepository
from src.schemas.file import (
    CSVUploadResponse,
    ExcelUploadResponse,
    FileResponse,
    FileUploadResponse,
)


class FileUploadService:
    """File upload service."""

    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    ALLOWED_CSV_TYPES = ["text/csv", "application/csv", "text/plain"]
    ALLOWED_EXCEL_TYPES = [
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ]
    ALLOWED_PDF_TYPES = ["application/pdf"]

    def __init__(self, db: AsyncSession):
        """
        Initialize file upload service.

        Args:
            db: Database session
        """
        self.db = db
        self.file_repo = FileUploadRepository(db)
        self.storage_type = settings.STORAGE_TYPE
        self.upload_dir = Path("uploads")

    def _validate_file_size(self, size: int) -> None:
        """
        Validate file size.

        Args:
            size: File size in bytes

        Raises:
            BadRequestError: If file is too large
        """
        if size > self.MAX_FILE_SIZE:
            raise BadRequestError(
                f"File size exceeds maximum allowed size of {self.MAX_FILE_SIZE / (1024 * 1024)}MB"
            )

    def _validate_file_type(self, mime_type: str, allowed_types: List[str]) -> None:
        """
        Validate file type.

        Args:
            mime_type: File MIME type
            allowed_types: List of allowed MIME types

        Raises:
            BadRequestError: If file type is not allowed
        """
        if mime_type not in allowed_types:
            raise BadRequestError(
                f"File type {mime_type} is not allowed. Allowed types: {', '.join(allowed_types)}"
            )

    async def _save_file(self, file: UploadFile, user_id: UUID) -> tuple[str, str]:
        """
        Save file to storage.

        Args:
            file: Uploaded file
            user_id: User ID

        Returns:
            tuple[str, str]: (filename, url)
        """
        # Generate unique filename
        file_extension = Path(file.filename).suffix if file.filename else ""
        unique_filename = f"{secrets.token_urlsafe(16)}{file_extension}"

        if self.storage_type == "local":
            # Create upload directory if it doesn't exist
            user_dir = self.upload_dir / str(user_id)
            user_dir.mkdir(parents=True, exist_ok=True)

            file_path = user_dir / unique_filename

            # Save file
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)

            # Generate URL (in production, this would be a proper URL)
            url = f"/uploads/{user_id}/{unique_filename}"
        else:
            # TODO: Implement S3/GCS storage
            raise BadRequestError("S3/GCS storage not implemented yet")

        return unique_filename, url

    async def upload_file(
        self, user: User, file: UploadFile, widget_id: Optional[UUID] = None
    ) -> FileUploadResponse:
        """
        Upload a generic file.

        Args:
            user: Current user
            file: Uploaded file
            widget_id: Optional widget ID

        Returns:
            FileUploadResponse: Upload response
        """
        # Validate file size
        file_content = await file.read()
        file_size = len(file_content)
        self._validate_file_size(file_size)

        # Reset file pointer
        await file.seek(0)

        # Save file
        filename, url = await self._save_file(file, user.id)

        # Create file record
        file_upload = await self.file_repo.create(
            user_id=user.id,
            filename=filename,
            original_name=file.filename or "unknown",
            mime_type=file.content_type or "application/octet-stream",
            size=file_size,
            url=url,
            storage=self.storage_type,
            widget_id=widget_id,
        )

        await self.db.commit()
        await self.db.refresh(file_upload)

        return FileUploadResponse(
            file_id=file_upload.id,
            url=url,
            type=file_upload.mime_type,
            size=file_upload.size,
            filename=file_upload.filename,
            original_name=file_upload.original_name,
            created_at=file_upload.created_at,
        )

    async def upload_csv(self, user: User, file: UploadFile) -> CSVUploadResponse:
        """
        Upload and parse CSV file.

        Args:
            user: Current user
            file: Uploaded CSV file

        Returns:
            CSVUploadResponse: CSV upload response with parsed data
        """
        # Validate file size
        file_content = await file.read()
        file_size = len(file_content)
        self._validate_file_size(file_size)

        # Validate file type
        mime_type = file.content_type or "text/csv"
        self._validate_file_type(mime_type, self.ALLOWED_CSV_TYPES)

        # Parse CSV
        await file.seek(0)
        content = await file.read()
        text_content = content.decode("utf-8")
        csv_reader = csv.DictReader(io.StringIO(text_content))

        rows = list(csv_reader)
        columns = list(rows[0].keys()) if rows else []
        preview = rows[:10]

        # Save file
        await file.seek(0)
        filename, url = await self._save_file(file, user.id)

        # Create file record with parsed data
        file_upload = await self.file_repo.create(
            user_id=user.id,
            filename=filename,
            original_name=file.filename or "unknown.csv",
            mime_type=mime_type,
            size=file_size,
            url=url,
            storage=self.storage_type,
            parsed_data={"rows": rows, "columns": columns},
        )

        await self.db.commit()
        await self.db.refresh(file_upload)

        return CSVUploadResponse(
            file_id=file_upload.id,
            data=rows,
            columns=columns,
            preview=preview,
            url=url,
            type=mime_type,
            size=file_size,
            created_at=file_upload.created_at,
        )

    async def upload_excel(self, user: User, file: UploadFile) -> ExcelUploadResponse:
        """
        Upload and parse Excel file.

        Args:
            user: Current user
            file: Uploaded Excel file

        Returns:
            ExcelUploadResponse: Excel upload response with parsed data
        """
        try:
            import pandas as pd
        except ImportError:
            raise BadRequestError("pandas library is required for Excel upload")

        # Validate file size
        file_content = await file.read()
        file_size = len(file_content)
        self._validate_file_size(file_size)

        # Validate file type
        mime_type = file.content_type or "application/vnd.ms-excel"
        self._validate_file_type(mime_type, self.ALLOWED_EXCEL_TYPES)

        # Parse Excel
        await file.seek(0)
        excel_file = io.BytesIO(await file.read())

        try:
            df_dict = pd.read_excel(excel_file, sheet_name=None)  # Read all sheets
        except Exception as e:
            raise BadRequestError(f"Failed to parse Excel file: {str(e)}")

        # Convert to dict format
        data = {}
        columns = {}
        preview = {}
        sheets = list(df_dict.keys())

        for sheet_name, df in df_dict.items():
            data[sheet_name] = df.to_dict("records")
            columns[sheet_name] = list(df.columns)
            preview[sheet_name] = df.head(10).to_dict("records")

        # Save file
        await file.seek(0)
        filename, url = await self._save_file(file, user.id)

        # Create file record with parsed data
        file_upload = await self.file_repo.create(
            user_id=user.id,
            filename=filename,
            original_name=file.filename or "unknown.xlsx",
            mime_type=mime_type,
            size=file_size,
            url=url,
            storage=self.storage_type,
            parsed_data={"sheets": data, "columns": columns},
        )

        await self.db.commit()
        await self.db.refresh(file_upload)

        return ExcelUploadResponse(
            file_id=file_upload.id,
            data=data,
            sheets=sheets,
            columns=columns,
            preview=preview,
            url=url,
            type=mime_type,
            size=file_size,
            created_at=file_upload.created_at,
        )

    async def upload_image(
        self, user: User, file: UploadFile, widget_id: Optional[UUID] = None
    ) -> FileUploadResponse:
        """
        Upload an image file.

        Args:
            user: Current user
            file: Uploaded image file
            widget_id: Optional widget ID

        Returns:
            FileUploadResponse: Image upload response
        """
        # Validate file size
        file_content = await file.read()
        file_size = len(file_content)
        self._validate_file_size(file_size)

        # Validate file type
        mime_type = file.content_type or "image/jpeg"
        self._validate_file_type(mime_type, self.ALLOWED_IMAGE_TYPES)

        # Save file
        await file.seek(0)
        filename, url = await self._save_file(file, user.id)

        # Create file record
        file_upload = await self.file_repo.create(
            user_id=user.id,
            filename=filename,
            original_name=file.filename or "unknown.jpg",
            mime_type=mime_type,
            size=file_size,
            url=url,
            storage=self.storage_type,
            widget_id=widget_id,
        )

        await self.db.commit()
        await self.db.refresh(file_upload)

        return FileUploadResponse(
            file_id=file_upload.id,
            url=url,
            type=mime_type,
            size=file_size,
            filename=file_upload.filename,
            original_name=file_upload.original_name,
            created_at=file_upload.created_at,
        )

    async def upload_pdf(
        self, user: User, file: UploadFile, widget_id: Optional[UUID] = None
    ) -> FileUploadResponse:
        """
        Upload a PDF file.

        Args:
            user: Current user
            file: Uploaded PDF file
            widget_id: Optional widget ID

        Returns:
            FileUploadResponse: PDF upload response
        """
        # Validate file size
        file_content = await file.read()
        file_size = len(file_content)
        self._validate_file_size(file_size)

        # Validate file type
        mime_type = file.content_type or "application/pdf"
        self._validate_file_type(mime_type, self.ALLOWED_PDF_TYPES)

        # Save file
        await file.seek(0)
        filename, url = await self._save_file(file, user.id)

        # Create file record
        file_upload = await self.file_repo.create(
            user_id=user.id,
            filename=filename,
            original_name=file.filename or "unknown.pdf",
            mime_type=mime_type,
            size=file_size,
            url=url,
            storage=self.storage_type,
            widget_id=widget_id,
        )

        await self.db.commit()
        await self.db.refresh(file_upload)

        return FileUploadResponse(
            file_id=file_upload.id,
            url=url,
            type=mime_type,
            size=file_size,
            filename=file_upload.filename,
            original_name=file_upload.original_name,
            created_at=file_upload.created_at,
        )

    async def get_file(self, file_id: UUID, user: User) -> FileResponse:
        """
        Get file by ID.

        Args:
            file_id: File ID
            user: Current user

        Returns:
            FileResponse: File data

        Raises:
            NotFoundError: If file not found
            ForbiddenError: If user doesn't own the file
        """
        file_upload = await self.file_repo.get_by_id(file_id)
        if not file_upload:
            raise NotFoundError("File not found")

        if file_upload.user_id != user.id:
            from src.core.exceptions import ForbiddenError

            raise ForbiddenError("You do not have permission to access this file")

        return FileResponse.model_validate(file_upload)

    async def delete_file(self, file_id: UUID, user: User) -> None:
        """
        Delete file.

        Args:
            file_id: File ID
            user: Current user

        Raises:
            NotFoundError: If file not found
            ForbiddenError: If user doesn't own the file
        """
        file_upload = await self.file_repo.get_by_id(file_id)
        if not file_upload:
            raise NotFoundError("File not found")

        if file_upload.user_id != user.id:
            from src.core.exceptions import ForbiddenError

            raise ForbiddenError("You do not have permission to delete this file")

        # Delete physical file if local storage
        if file_upload.storage == "local":
            file_path = (
                self.upload_dir / str(file_upload.user_id) / file_upload.filename
            )
            if file_path.exists():
                file_path.unlink()

        # Delete database record
        await self.file_repo.delete(file_id)
        await self.db.commit()
