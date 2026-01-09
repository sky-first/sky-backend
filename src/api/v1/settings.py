"""Settings endpoints."""

from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.settings import (
    APIKeyCreate,
    APIKeyResponse,
    CrewsSettingsResponse,
    DataCatalogSettingsResponse,
    IntegrationCreate,
    IntegrationResponse,
    IntegrationUpdate,
    PermissionsSettingsResponse,
    SettingsResponse,
    SettingsUpdate,
    SpacesSettingsResponse,
    UsersSettingsResponse,
)
from src.services.settings_service import SettingsService

router = APIRouter()


@router.get(
    "",
    response_model=SettingsResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get settings",
    description="Get user settings",
)
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SettingsResponse:
    """
    Get user settings.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        SettingsResponse: User settings
    """
    settings_service = SettingsService(db)
    return await settings_service.get_settings(current_user)


@router.put(
    "",
    response_model=SettingsResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Update settings",
    description="Update user settings",
)
async def update_settings(
    settings_data: SettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SettingsResponse:
    """
    Update user settings.

    Args:
        settings_data: Settings update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        SettingsResponse: Updated settings
    """
    settings_service = SettingsService(db)
    return await settings_service.update_settings(current_user, settings_data)


@router.get(
    "/data-catalog",
    response_model=DataCatalogSettingsResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get data catalog settings",
    description="Get data catalog configuration settings",
)
async def get_data_catalog_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DataCatalogSettingsResponse:
    """
    Get data catalog settings.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        DataCatalogSettingsResponse: Data catalog settings
    """
    settings_service = SettingsService(db)
    return await settings_service.get_data_catalog_settings(current_user)


@router.get(
    "/spaces",
    response_model=SpacesSettingsResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get spaces settings",
    description="Get spaces configuration settings",
)
async def get_spaces_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SpacesSettingsResponse:
    """
    Get spaces settings.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        SpacesSettingsResponse: Spaces settings
    """
    settings_service = SettingsService(db)
    return await settings_service.get_spaces_settings(current_user)


@router.get(
    "/crews",
    response_model=CrewsSettingsResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get crews settings",
    description="Get crews configuration settings",
)
async def get_crews_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CrewsSettingsResponse:
    """
    Get crews settings.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        CrewsSettingsResponse: Crews settings
    """
    settings_service = SettingsService(db)
    return await settings_service.get_crews_settings(current_user)


@router.get(
    "/users",
    response_model=UsersSettingsResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get users settings",
    description="Get users configuration settings (Admin only)",
)
async def get_users_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UsersSettingsResponse:
    """
    Get users settings.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        UsersSettingsResponse: Users settings
    """
    settings_service = SettingsService(db)
    return await settings_service.get_users_settings(current_user)


@router.get(
    "/permissions",
    response_model=PermissionsSettingsResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get permissions settings",
    description="Get permissions configuration settings (Admin only)",
)
async def get_permissions_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PermissionsSettingsResponse:
    """
    Get permissions settings.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        PermissionsSettingsResponse: Permissions settings
    """
    settings_service = SettingsService(db)
    return await settings_service.get_permissions_settings(current_user)


@router.get(
    "/api-keys",
    response_model=List[APIKeyResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get API keys",
    description="Get list of user API keys",
)
async def get_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[APIKeyResponse]:
    """
    Get user API keys.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[APIKeyResponse]: List of API keys
    """
    settings_service = SettingsService(db)
    return await settings_service.get_api_keys(current_user)


@router.post(
    "/api-keys",
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Create API key",
    description="Create a new API key (key is only shown once)",
)
async def create_api_key(
    api_key_data: APIKeyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Create API key.

    Args:
        api_key_data: API key creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Dict[str, Any]: API key with plain key (only shown once)
    """
    settings_service = SettingsService(db)
    return await settings_service.create_api_key(current_user, api_key_data)


@router.delete(
    "/api-keys/{api_key_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete API key",
    description="Delete an API key",
)
async def delete_api_key(
    api_key_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete API key.

    Args:
        api_key_id: API key ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    settings_service = SettingsService(db)
    await settings_service.delete_api_key(api_key_id, current_user)
    return SuccessResponse(message="API key deleted successfully")


@router.get(
    "/integrations",
    response_model=List[IntegrationResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get integrations",
    description="Get list of user integrations",
)
async def get_integrations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[IntegrationResponse]:
    """
    Get user integrations.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[IntegrationResponse]: List of integrations
    """
    settings_service = SettingsService(db)
    return await settings_service.get_integrations(current_user)


@router.post(
    "/integrations",
    response_model=IntegrationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Create integration",
    description="Create a new integration",
)
async def create_integration(
    integration_data: IntegrationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> IntegrationResponse:
    """
    Create integration.

    Args:
        integration_data: Integration creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        IntegrationResponse: Created integration
    """
    settings_service = SettingsService(db)
    return await settings_service.create_integration(current_user, integration_data)


@router.put(
    "/integrations/{integration_id}",
    response_model=IntegrationResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update integration",
    description="Update an integration",
)
async def update_integration(
    integration_id: UUID,
    integration_data: IntegrationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> IntegrationResponse:
    """
    Update integration.

    Args:
        integration_id: Integration ID
        integration_data: Integration update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        IntegrationResponse: Updated integration
    """
    settings_service = SettingsService(db)
    return await settings_service.update_integration(integration_id, current_user, integration_data)


@router.delete(
    "/integrations/{integration_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete integration",
    description="Delete an integration",
)
async def delete_integration(
    integration_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete integration.

    Args:
        integration_id: Integration ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    settings_service = SettingsService(db)
    await settings_service.delete_integration(integration_id, current_user)
    return SuccessResponse(message="Integration deleted successfully")
