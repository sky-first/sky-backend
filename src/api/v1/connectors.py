"""Connector registry endpoints."""

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.schemas.connector import ConnectorResponse
from src.services.connector_service import ConnectorService

router = APIRouter()


@router.get(
    "",
    response_model=List[ConnectorResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="List connectors",
    description="Get list of all available connectors",
)
async def list_connectors(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[ConnectorResponse]:
    """
    List all available connectors.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[ConnectorResponse]: List of connectors
    """
    connector_service = ConnectorService(db)
    return connector_service.get_connectors()


@router.get(
    "/{connector_id}",
    response_model=ConnectorResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Get connector",
    description="Get connector details by ID",
)
async def get_connector(
    connector_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConnectorResponse:
    """
    Get connector by ID.

    Args:
        connector_id: Connector ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectorResponse: Connector data
    """
    connector_service = ConnectorService(db)
    return connector_service.get_connector(connector_id)


@router.get(
    "/categories",
    response_model=List[str],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get connector categories",
    description="Get list of all connector categories",
)
async def get_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[str]:
    """
    Get connector categories.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[str]: List of categories
    """
    connector_service = ConnectorService(db)
    return connector_service.get_categories()

