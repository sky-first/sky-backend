"""Permission service."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.user import User
from src.repositories.connection import ConnectionRepository
from src.repositories.permission import PermissionRepository
from src.schemas.permission import (
    ConnectionPermissionCreate,
    PermissionResponse,
    PermissionUpdate,
    PermissionValidateRequest,
    PermissionValidateResponse,
)


class PermissionService:
    """Permission service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize permission service.

        Args:
            db: Database session
        """
        self.db = db
        self.permission_repo = PermissionRepository(db)
        self.connection_repo = ConnectionRepository(db)

    async def get_connection_permissions(
        self, connection_id: UUID, user: User
    ) -> List[PermissionResponse]:
        """
        Get permissions for a connection.

        Args:
            connection_id: Connection ID
            user: Current user

        Returns:
            List[PermissionResponse]: List of permissions

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
        """
        connection = await self.connection_repo.get_by_id(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        # Check if user owns the connection
        if connection.created_by != user.id:
            raise ForbiddenError("Access denied to this connection")

        permissions = await self.permission_repo.get_by_connection_id(connection_id)
        return [PermissionResponse.model_validate(p) for p in permissions]

    async def create_connection_permission(
        self, connection_id: UUID, user: User, permission_data: ConnectionPermissionCreate
    ) -> PermissionResponse:
        """
        Create permission for a connection.

        Args:
            connection_id: Connection ID
            user: Current user
            permission_data: Permission data

        Returns:
            PermissionResponse: Created permission

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
            BadRequestError: If permission already exists
        """
        connection = await self.connection_repo.get_by_id(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        if connection.created_by != user.id:
            raise ForbiddenError("Access denied to this connection")

        # Check if permission already exists
        existing = await self.permission_repo.get_by_connection_and_space(
            connection_id, permission_data.space_id, permission_data.crew_id
        )
        if existing:
            raise BadRequestError("Permission already exists for this connection, space, and crew")

        permission = await self.permission_repo.create(
            connection_id=connection_id,
            space_id=permission_data.space_id,
            crew_id=permission_data.crew_id,
            access_level=permission_data.access_level,
            table_access=permission_data.table_access,
        )

        await self.db.commit()
        await self.db.refresh(permission)

        return PermissionResponse.model_validate(permission)

    async def update_permission(
        self, permission_id: UUID, user: User, permission_data: PermissionUpdate
    ) -> PermissionResponse:
        """
        Update permission.

        Args:
            permission_id: Permission ID
            user: Current user
            permission_data: Permission update data

        Returns:
            PermissionResponse: Updated permission

        Raises:
            NotFoundError: If permission not found
            ForbiddenError: If user doesn't have access
        """
        permission = await self.permission_repo.get_by_id(permission_id)
        if not permission:
            raise NotFoundError("Permission not found")

        # Check if user owns the connection
        connection = await self.connection_repo.get_by_id(permission.connection_id)
        if not connection or connection.created_by != user.id:
            raise ForbiddenError("Access denied to this permission")

        update_data = permission_data.model_dump(exclude_unset=True)
        permission = await self.permission_repo.update(permission_id, **update_data)
        await self.db.commit()
        await self.db.refresh(permission)

        return PermissionResponse.model_validate(permission)

    async def delete_permission(self, permission_id: UUID, user: User) -> None:
        """
        Delete permission.

        Args:
            permission_id: Permission ID
            user: Current user

        Raises:
            NotFoundError: If permission not found
            ForbiddenError: If user doesn't have access
        """
        permission = await self.permission_repo.get_by_id(permission_id)
        if not permission:
            raise NotFoundError("Permission not found")

        # Check if user owns the connection
        connection = await self.connection_repo.get_by_id(permission.connection_id)
        if not connection or connection.created_by != user.id:
            raise ForbiddenError("Access denied to this permission")

        await self.permission_repo.delete(permission_id)
        await self.db.commit()

    async def get_space_permissions(
        self, space_id: UUID, user: User
    ) -> List[PermissionResponse]:
        """
        Get permissions for a space.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            List[PermissionResponse]: List of permissions

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        # TODO: Check space access
        permissions = await self.permission_repo.get_by_space_id(space_id)
        return [PermissionResponse.model_validate(p) for p in permissions]

    async def get_crew_permissions(
        self, crew_id: UUID, user: User
    ) -> List[PermissionResponse]:
        """
        Get permissions for a crew.

        Args:
            crew_id: Crew ID
            user: Current user

        Returns:
            List[PermissionResponse]: List of permissions

        Raises:
            NotFoundError: If crew not found
            ForbiddenError: If user doesn't have access
        """
        # TODO: Check crew access
        permissions = await self.permission_repo.get_by_crew_id(crew_id)
        return [PermissionResponse.model_validate(p) for p in permissions]

    async def validate_permission(
        self, user: User, validate_data: PermissionValidateRequest
    ) -> PermissionValidateResponse:
        """
        Validate if user has permission to access a connection.

        Args:
            user: Current user
            validate_data: Validation request data

        Returns:
            PermissionValidateResponse: Validation result

        Raises:
            NotFoundError: If connection not found
        """
        connection = await self.connection_repo.get_by_id(validate_data.connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        # Check if user owns the connection
        if connection.created_by == validate_data.user_id:
            return PermissionValidateResponse(allowed=True, reason="User owns the connection")

        # Check permissions
        permissions = await self.permission_repo.get_by_connection_id(validate_data.connection_id)

        # TODO: Check if user is member of space/crew with permission
        # For now, only check ownership
        for permission in permissions:
            # If permission allows the action
            if permission.access_level == "full":
                return PermissionValidateResponse(
                    allowed=True, reason="User has full access via permission"
                )
            elif permission.access_level == "read-only" and validate_data.action == "read":
                return PermissionValidateResponse(
                    allowed=True, reason="User has read-only access via permission"
                )

        return PermissionValidateResponse(
            allowed=False, reason="User does not have permission to access this connection"
        )

