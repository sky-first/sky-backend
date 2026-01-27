"""Permission endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.permission import (
    ConnectionPermissionCreate,
    PermissionResponse,
    PermissionUpdate,
    PermissionValidateRequest,
    PermissionValidateResponse,
    RolePermissionResponse,
    RolePermissionUpdate,
    TableMemberPermissionCreate,
    TableMemberPermissionResponse,
    TableMemberPermissionUpdate,
)
from src.services.permission_service import PermissionService

router = APIRouter()


@router.get(
    "/connections/{connection_id}",
    response_model=List[PermissionResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get connection permissions",
    description="Get all permissions for a connection",
)
async def get_connection_permissions(
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[PermissionResponse]:
    """
    Get connection permissions.

    Args:
        connection_id: Connection ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[PermissionResponse]: List of permissions
    """
    permission_service = PermissionService(db)
    return await permission_service.get_connection_permissions(connection_id, current_user)


@router.post(
    "/connections/{connection_id}",
    response_model=PermissionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    summary="Create connection permission",
    description="Create a new permission for a connection",
)
async def create_connection_permission(
    connection_id: UUID,
    permission_data: ConnectionPermissionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PermissionResponse:
    """
    Create connection permission.

    Args:
        connection_id: Connection ID
        permission_data: Permission creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        PermissionResponse: Created permission
    """
    try:
        permission_service = PermissionService(db)
        return await permission_service.create_connection_permission(
            connection_id, current_user, permission_data
        )
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Error creating connection permission: {e}", exc_info=True)
        raise


@router.put(
    "/{permission_id}",
    response_model=PermissionResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update permission",
    description="Update permission information",
)
async def update_permission(
    permission_id: UUID,
    permission_data: PermissionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PermissionResponse:
    """
    Update permission.

    Args:
        permission_id: Permission ID
        permission_data: Permission update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        PermissionResponse: Updated permission
    """
    permission_service = PermissionService(db)
    return await permission_service.update_permission(permission_id, current_user, permission_data)


@router.delete(
    "/{permission_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete permission",
    description="Delete permission",
)
async def delete_permission(
    permission_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete permission.

    Args:
        permission_id: Permission ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    permission_service = PermissionService(db)
    await permission_service.delete_permission(permission_id, current_user)
    return SuccessResponse(message="Permission deleted successfully")


@router.get(
    "/spaces/{space_id}",
    response_model=List[PermissionResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get space permissions",
    description="Get all permissions for a space",
)
async def get_space_permissions(
    space_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[PermissionResponse]:
    """
    Get space permissions.

    Args:
        space_id: Space ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[PermissionResponse]: List of permissions
    """
    permission_service = PermissionService(db)
    return await permission_service.get_space_permissions(space_id, current_user)


@router.get(
    "/crews/{crew_id}",
    response_model=List[PermissionResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get crew permissions",
    description="Get all permissions for a crew",
)
async def get_crew_permissions(
    crew_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[PermissionResponse]:
    """
    Get crew permissions.

    Args:
        crew_id: Crew ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[PermissionResponse]: List of permissions
    """
    permission_service = PermissionService(db)
    return await permission_service.get_crew_permissions(crew_id, current_user)


@router.post(
    "/validate",
    response_model=PermissionValidateResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Validate permission",
    description="Validate if user has permission to access a connection",
)
async def validate_permission(
    validate_data: PermissionValidateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PermissionValidateResponse:
    """
    Validate permission.

    Args:
        validate_data: Validation request data
        current_user: Current authenticated user
        db: Database session

    Returns:
        PermissionValidateResponse: Validation result
    """
    permission_service = PermissionService(db)
    return await permission_service.validate_permission(current_user, validate_data)


@router.get(
    "/table-members/{connection_id}/{table_name}",
    response_model=List[TableMemberPermissionResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get table member permissions",
    description="Get all member permissions for a specific table",
)
async def get_table_member_permissions(
    connection_id: UUID,
    table_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[TableMemberPermissionResponse]:
    """
    Get table member permissions.

    Args:
        connection_id: Connection ID
        table_name: Table name
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[TableMemberPermissionResponse]: List of permissions
    """
    try:
        permission_service = PermissionService(db)
        return await permission_service.get_table_member_permissions(
            connection_id, table_name, current_user
        )
    except Exception as e:
        import logging
        import traceback

        logger = logging.getLogger(__name__)
        logger.error(f"Error getting table member permissions: {e}", exc_info=True)
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise


@router.post(
    "/table-members",
    response_model=TableMemberPermissionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    summary="Create table member permission",
    description="Create a new permission for a table and crew member",
)
async def create_table_member_permission(
    permission_data: TableMemberPermissionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TableMemberPermissionResponse:
    """
    Create table member permission.

    Args:
        permission_data: Permission creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        TableMemberPermissionResponse: Created permission
    """
    permission_service = PermissionService(db)
    return await permission_service.create_table_member_permission(current_user, permission_data)


@router.put(
    "/table-members/{permission_id}",
    response_model=TableMemberPermissionResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update table member permission",
    description="Update table member permission",
)
async def update_table_member_permission(
    permission_id: UUID,
    permission_data: TableMemberPermissionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TableMemberPermissionResponse:
    """
    Update table member permission.

    Args:
        permission_id: Permission ID
        permission_data: Permission update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        TableMemberPermissionResponse: Updated permission
    """
    permission_service = PermissionService(db)
    return await permission_service.update_table_member_permission(
        permission_id, current_user, permission_data
    )


@router.delete(
    "/table-members/{permission_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete table member permission",
    description="Delete table member permission",
)
async def delete_table_member_permission(
    permission_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete table member permission.

    Args:
        permission_id: Permission ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    permission_service = PermissionService(db)
    await permission_service.delete_table_member_permission(permission_id, current_user)
    return SuccessResponse(message="Table member permission deleted successfully")


@router.get(
    "/roles",
    response_model=List[RolePermissionResponse],
    status_code=status.HTTP_200_OK,
    responses={403: {"model": ErrorResponse}},
    summary="Get all role permissions",
    description="Get all role permissions (admin only)",
)
async def get_all_role_permissions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[RolePermissionResponse]:
    """
    Get all role permissions.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[RolePermissionResponse]: List of all role permissions
    """
    permission_service = PermissionService(db)
    return await permission_service.get_all_role_permissions(current_user)


@router.put(
    "/roles/{role}",
    response_model=RolePermissionResponse,
    status_code=status.HTTP_200_OK,
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update role permission",
    description="Update permissions for a role (admin only)",
)
async def update_role_permission(
    role: str,
    permission_data: RolePermissionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> RolePermissionResponse:
    """
    Update role permission.

    Args:
        role: Role name (commander, navigator, explorer, guest)
        permission_data: Permission update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        RolePermissionResponse: Updated role permission
    """
    permission_service = PermissionService(db)
    return await permission_service.update_role_permission(role, current_user, permission_data)
