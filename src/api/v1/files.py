"""File upload and management endpoints."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.file import (
    CSVUploadResponse,
    ExcelUploadResponse,
    FileResponse,
    FileUploadResponse,
)
from src.services.file_upload_service import FileUploadService

router = APIRouter()


@router.post(
    "/upload",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Upload file",
    description="Upload a generic file",
)
async def upload_file(
    file: UploadFile = File(...),
    widget_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileUploadResponse:
    """
    Upload a generic file.

    Args:
        file: File to upload
        widget_id: Optional widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        FileUploadResponse: Upload response
    """
    file_service = FileUploadService(db)
    return await file_service.upload_file(current_user, file, widget_id)


@router.post(
    "/upload/csv",
    response_model=CSVUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Upload CSV file",
    description="Upload and parse a CSV file",
)
async def upload_csv(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CSVUploadResponse:
    """
    Upload and parse CSV file.

    Args:
        file: CSV file to upload
        current_user: Current authenticated user
        db: Database session

    Returns:
        CSVUploadResponse: CSV upload response with parsed data
    """
    file_service = FileUploadService(db)
    return await file_service.upload_csv(current_user, file)


@router.post(
    "/upload/excel",
    response_model=ExcelUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Upload Excel file",
    description="Upload and parse an Excel file",
)
async def upload_excel(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ExcelUploadResponse:
    """
    Upload and parse Excel file.

    Args:
        file: Excel file to upload
        current_user: Current authenticated user
        db: Database session

    Returns:
        ExcelUploadResponse: Excel upload response with parsed data
    """
    file_service = FileUploadService(db)
    return await file_service.upload_excel(current_user, file)


@router.post(
    "/upload/image",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Upload image file",
    description="Upload an image file",
)
async def upload_image(
    file: UploadFile = File(...),
    widget_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileUploadResponse:
    """
    Upload an image file.

    Args:
        file: Image file to upload
        widget_id: Optional widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        FileUploadResponse: Image upload response
    """
    file_service = FileUploadService(db)
    return await file_service.upload_image(current_user, file, widget_id)


@router.post(
    "/upload/pdf",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Upload PDF file",
    description="Upload a PDF file",
)
async def upload_pdf(
    file: UploadFile = File(...),
    widget_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileUploadResponse:
    """
    Upload a PDF file.

    Args:
        file: PDF file to upload
        widget_id: Optional widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        FileUploadResponse: PDF upload response
    """
    file_service = FileUploadService(db)
    return await file_service.upload_pdf(current_user, file, widget_id)


@router.get(
    "/{file_id}",
    response_model=FileResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get file",
    description="Get file information by ID",
)
async def get_file(
    file_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    """
    Get file by ID.

    Args:
        file_id: File ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        FileResponse: File data
    """
    file_service = FileUploadService(db)
    return await file_service.get_file(file_id, current_user)


@router.delete(
    "/{file_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete file",
    description="Delete a file",
)
async def delete_file(
    file_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete file.

    Args:
        file_id: File ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    file_service = FileUploadService(db)
    await file_service.delete_file(file_id, current_user)
    return SuccessResponse(message="File deleted successfully")

