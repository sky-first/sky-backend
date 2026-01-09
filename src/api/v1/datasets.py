"""Dataset management endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import NotFoundError
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.services.dataset_service import DatasetService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.delete(
    "/{dataset_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Delete dataset",
    description="Delete a dataset (table or file). For files, deletes the file. For tables, marks as excluded.",
)
async def delete_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete dataset.

    Args:
        dataset_id: Dataset ID (table name or file_id prefixed with "file_")
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message

    Raises:
        HTTPException: If deletion fails
    """
    try:
        dataset_service = DatasetService(db)
        await dataset_service.delete_dataset(dataset_id, current_user)
        return SuccessResponse(message="Dataset deleted successfully")
    except NotFoundError as e:
        logger.warning(f"Dataset not found: {dataset_id} - {str(e)}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting dataset {dataset_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete dataset: {str(e)}",
        )


@router.get(
    "/excluded",
    response_model=list[str],
    status_code=status.HTTP_200_OK,
    summary="Get excluded datasets",
    description="Get list of excluded dataset IDs for the current user",
)
async def get_excluded_datasets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[str]:
    """
    Get excluded datasets.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        list[str]: List of excluded dataset IDs
    """
    dataset_service = DatasetService(db)
    return await dataset_service.get_excluded_datasets(current_user)
