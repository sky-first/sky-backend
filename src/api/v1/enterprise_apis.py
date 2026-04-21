"""Enterprise API endpoints."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.enterprise_api import (
    EnterpriseAPICreate,
    EnterpriseAPIResponse,
    EnterpriseAPIUpdate,
)
from src.services.enterprise_api_service import EnterpriseAPIService
from src.services.rbac_service import RBACService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "",
    response_model=list[EnterpriseAPIResponse],
    status_code=status.HTTP_200_OK,
    summary="List enterprise APIs",
)
async def list_apis(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """List all registered APIs for the current user."""
    if current_user.role not in ("admin", "owner"):
        from src.core.exceptions import ForbiddenError
        raise ForbiddenError("Admin role required.")
    await RBACService(db).assert_permission(current_user, "connections.view")
    try:
        service = EnterpriseAPIService(db)
        return await service.list_apis(current_user)
    except Exception as e:
        logger.error(f"Error listing APIs: {str(e)}", exc_info=True)
        raise e


@router.post(
    "",
    response_model=EnterpriseAPIResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register enterprise API",
)
async def create_api(
    data: EnterpriseAPICreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Register a new API."""
    if current_user.role not in ("admin", "owner"):
        from src.core.exceptions import ForbiddenError
        raise ForbiddenError("Admin role required.")
    await RBACService(db).assert_permission(current_user, "connections.edit")
    try:
        service = EnterpriseAPIService(db)
        return await service.create_api(current_user, data)
    except Exception as e:
        logger.error(f"Error registering API: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register API: {str(e)}",
        )


@router.get(
    "/{api_id}",
    response_model=EnterpriseAPIResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get enterprise API",
)
async def get_api(
    api_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Get API details by ID."""
    if current_user.role not in ("admin", "owner"):
        from src.core.exceptions import ForbiddenError
        raise ForbiddenError("Admin role required.")
    await RBACService(db).assert_permission(current_user, "connections.view")
    try:
        service = EnterpriseAPIService(db)
        return await service.get_api(api_id, current_user)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.put(
    "/{api_id}",
    response_model=EnterpriseAPIResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update enterprise API",
)
async def update_api(
    api_id: UUID,
    data: EnterpriseAPIUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Update API registration."""
    if current_user.role not in ("admin", "owner"):
        from src.core.exceptions import ForbiddenError
        raise ForbiddenError("Admin role required.")
    await RBACService(db).assert_permission(current_user, "connections.edit")
    try:
        service = EnterpriseAPIService(db)
        return await service.update_api(api_id, current_user, data)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating API: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update API: {str(e)}",
        )


@router.delete(
    "/{api_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete enterprise API",
)
async def delete_api(
    api_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """Delete API registration."""
    if current_user.role not in ("admin", "owner"):
        from src.core.exceptions import ForbiddenError
        raise ForbiddenError("Admin role required.")
    await RBACService(db).assert_permission(current_user, "connections.edit")
    try:
        service = EnterpriseAPIService(db)
        await service.delete_api(api_id, current_user)
        return SuccessResponse(message="API registration deleted successfully")
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting API: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete API: {str(e)}",
        )
