"""Dataset management endpoints."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
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


@router.get(
    "",
    response_model=List[Dict[str, Any]],
    status_code=status.HTTP_200_OK,
    summary="List datasets",
    description="Get list of available datasets (tables and files) across all pages",
)
async def list_datasets(
    connection_id: Optional[str] = Query(None),
    page_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """
    List all available datasets.

    For now, returns an empty list as a placeholder to satisfy frontend requirements.
    Future implementations can aggregate tables from connections and uploaded files.

    Args:
        connection_id: Optional connection filter
        page_id: Optional page filter
        skip: Pagination offset
        limit: Pagination limit
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[Dict[str, Any]]: List of dataset objects
    """
    # This endpoint is currently a placeholder to prevent frontend 404 errors
    return []
