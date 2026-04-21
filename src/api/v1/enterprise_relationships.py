"""Enterprise Relationship endpoints."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.enterprise_relationship import (
    EnterpriseRelationshipCreate,
    EnterpriseRelationshipResponse,
)
from src.services.enterprise_relationship_service import EnterpriseRelationshipService
from src.services.rbac_service import RBACService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "",
    response_model=list[EnterpriseRelationshipResponse],
    status_code=status.HTTP_200_OK,
    summary="List enterprise relationships",
)
async def list_relationships(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[EnterpriseRelationshipResponse]:
    """List all relationships for the current user."""
    if current_user.role not in ("admin", "owner"):
        from src.core.exceptions import ForbiddenError
        raise ForbiddenError("Admin role required.")
    await RBACService(db).assert_permission(current_user, "connections.view")
    service = EnterpriseRelationshipService(db)
    return await service.list_relationships(current_user)


@router.post(
    "",
    response_model=EnterpriseRelationshipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create enterprise relationship",
)
async def create_relationship(
    data: EnterpriseRelationshipCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> EnterpriseRelationshipResponse:
    """Create a new relationship."""
    if current_user.role not in ("admin", "owner"):
        from src.core.exceptions import ForbiddenError
        raise ForbiddenError("Admin role required.")
    await RBACService(db).assert_permission(current_user, "connections.edit")
    try:
        service = EnterpriseRelationshipService(db)
        return await service.create_relationship(data, current_user)
    except Exception as e:
        logger.error(f"Error creating relationship: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create relationship: {str(e)}",
        )


@router.put(
    "/{relationship_id}",
    response_model=EnterpriseRelationshipResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update enterprise relationship",
)
async def update_relationship(
    relationship_id: UUID,
    data: EnterpriseRelationshipCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> EnterpriseRelationshipResponse:
    """Update a relationship."""
    if current_user.role not in ("admin", "owner"):
        from src.core.exceptions import ForbiddenError
        raise ForbiddenError("Admin role required.")
    await RBACService(db).assert_permission(current_user, "connections.edit")
    try:
        service = EnterpriseRelationshipService(db)
        return await service.update_relationship(relationship_id, data, current_user)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating relationship: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update relationship: {str(e)}",
        )


@router.delete(
    "/{relationship_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete enterprise relationship",
)
async def delete_relationship(
    relationship_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """Delete a relationship."""
    if current_user.role not in ("admin", "owner"):
        from src.core.exceptions import ForbiddenError
        raise ForbiddenError("Admin role required.")
    await RBACService(db).assert_permission(current_user, "connections.edit")
    try:
        service = EnterpriseRelationshipService(db)
        await service.delete_relationship(relationship_id, current_user)
        return SuccessResponse(message="Relationship deleted successfully")
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting relationship: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete relationship: {str(e)}",
        )
