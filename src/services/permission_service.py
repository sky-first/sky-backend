"""Permission service."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.crew import CrewMember
from src.models.space import SpaceConnection
from src.models.user import User
from src.repositories.connection import ConnectionRepository
from src.repositories.crew import CrewMemberRepository, CrewRepository
from src.repositories.permission import (
    PermissionRepository,
    RolePermissionRepository,
    TableMemberPermissionRepository,
)
from src.repositories.space import SpaceRepository
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
        self.table_member_permission_repo = TableMemberPermissionRepository(db)
        self.role_permission_repo = RolePermissionRepository(db)
        self.crew_repo = CrewRepository(db)
        self.crew_member_repo = CrewMemberRepository(db)
        self.space_repo = SpaceRepository(db)

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

        # Commit permission first
        await self.db.commit()
        await self.db.refresh(permission)

        # If permission is for a space, automatically create SpaceConnection
        # so tables are available when viewing the space
        # Do this after committing the permission to avoid rollback
        if permission_data.space_id:
            try:
                # Check if SpaceConnection already exists
                existing_connections = await self.space_repo.get_space_connections(
                    permission_data.space_id
                )
                connection_exists = any(
                    str(sc.connection_id) == str(connection_id) for sc in existing_connections
                )

                if not connection_exists:
                    # Create SpaceConnection to associate connection with space
                    space_connection = SpaceConnection(
                        space_id=permission_data.space_id, connection_id=connection_id
                    )
                    self.db.add(space_connection)
                    await self.db.commit()

            except Exception as e:
                # Log error but don't fail the permission creation
                # The permission is more important than the connection association
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Failed to create SpaceConnection for space {permission_data.space_id} and connection {connection_id}: {e}",
                    exc_info=True,
                )
                # Rollback the SpaceConnection creation but keep the permission
                await self.db.rollback()

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

    async def get_space_permissions(self, space_id: UUID, user: User) -> List[PermissionResponse]:
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

    async def get_crew_permissions(self, crew_id: UUID, user: User) -> List[PermissionResponse]:
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

    async def get_table_member_permissions(
        self, connection_id: UUID, table_name: str, user: User
    ) -> List[TableMemberPermissionResponse]:
        """
        Get table member permissions.

        Args:
            connection_id: Connection ID
            table_name: Table name
            user: Current user

        Returns:
            List[TableMemberPermissionResponse]: List of permissions

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
        """
        connection = await self.connection_repo.get_by_id(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        if connection.created_by != user.id:
            raise ForbiddenError("Access denied to this connection")

        permissions = await self.table_member_permission_repo.get_by_table(
            connection_id, table_name
        )

        # Convert to response format safely
        result = []
        for p in permissions:
            try:
                result.append(
                    TableMemberPermissionResponse.model_validate(
                        {
                            "id": p.id,
                            "connection_id": p.connection_id,
                            "table_name": p.table_name,
                            "crew_id": p.crew_id,
                            "member_id": p.member_id,
                            "has_access": p.has_access,
                            "created_at": p.created_at,
                            "updated_at": p.updated_at,
                        }
                    )
                )
            except Exception as e:
                import logging

                logger = logging.getLogger(__name__)
                logger.error(f"Error validating permission {p.id}: {e}")
                logger.error(
                    f"Permission data: id={p.id}, connection_id={p.connection_id}, table_name={p.table_name}, crew_id={p.crew_id}, member_id={p.member_id}, has_access={p.has_access}"
                )
                # Skip invalid permissions instead of failing completely
                continue

        return result

    async def create_table_member_permission(
        self, user: User, permission_data: TableMemberPermissionCreate
    ) -> TableMemberPermissionResponse:
        """
        Create table member permission.

        Args:
            user: Current user
            permission_data: Permission data

        Returns:
            TableMemberPermissionResponse: Created permission

        Raises:
            NotFoundError: If connection, crew, or member not found
            ForbiddenError: If user doesn't have access
            BadRequestError: If permission already exists
        """
        connection = await self.connection_repo.get_by_id(permission_data.connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        if connection.created_by != user.id:
            raise ForbiddenError("Access denied to this connection")

        crew = await self.crew_repo.get_by_id(permission_data.crew_id)
        if not crew:
            raise NotFoundError("Crew not found")

        member = await self.crew_member_repo.get_by_id(permission_data.member_id)
        if not member:
            raise NotFoundError("Crew member not found")

        if member.crew_id != permission_data.crew_id:
            raise BadRequestError("Member does not belong to the specified crew")

        # Check if permission already exists
        existing = await self.table_member_permission_repo.get_by_connection_table_member(
            permission_data.connection_id, permission_data.table_name, permission_data.member_id
        )
        if existing:
            raise BadRequestError("Permission already exists for this table and member")

        permission = await self.table_member_permission_repo.create(
            connection_id=permission_data.connection_id,
            table_name=permission_data.table_name,
            crew_id=permission_data.crew_id,
            member_id=permission_data.member_id,
            has_access=permission_data.has_access,
        )

        await self.db.commit()
        await self.db.refresh(permission)

        return TableMemberPermissionResponse.model_validate(permission)

    async def update_table_member_permission(
        self, permission_id: UUID, user: User, permission_data: TableMemberPermissionUpdate
    ) -> TableMemberPermissionResponse:
        """
        Update table member permission.

        Args:
            permission_id: Permission ID
            user: Current user
            permission_data: Permission update data

        Returns:
            TableMemberPermissionResponse: Updated permission

        Raises:
            NotFoundError: If permission not found
            ForbiddenError: If user doesn't have access
        """
        permission = await self.table_member_permission_repo.get_by_id(permission_id)
        if not permission:
            raise NotFoundError("Permission not found")

        # Check if user owns the connection
        connection = await self.connection_repo.get_by_id(permission.connection_id)
        if not connection or connection.created_by != user.id:
            raise ForbiddenError("Access denied to this permission")

        update_data = permission_data.model_dump(exclude_unset=True)
        permission = await self.table_member_permission_repo.update(permission_id, **update_data)
        await self.db.commit()
        await self.db.refresh(permission)

        return TableMemberPermissionResponse.model_validate(permission)

    async def delete_table_member_permission(self, permission_id: UUID, user: User) -> None:
        """
        Delete table member permission.

        Args:
            permission_id: Permission ID
            user: Current user

        Raises:
            NotFoundError: If permission not found
            ForbiddenError: If user doesn't have access
        """
        permission = await self.table_member_permission_repo.get_by_id(permission_id)
        if not permission:
            raise NotFoundError("Permission not found")

        # Check if user owns the connection
        connection = await self.connection_repo.get_by_id(permission.connection_id)
        if not connection or connection.created_by != user.id:
            raise ForbiddenError("Access denied to this permission")

        await self.table_member_permission_repo.delete(permission_id)
        await self.db.commit()

    async def get_all_role_permissions(self, user: User) -> List[RolePermissionResponse]:
        """
        Get all role permissions.

        Args:
            user: Current user

        Returns:
            List[RolePermissionResponse]: List of all role permissions

        Raises:
            ForbiddenError: If user doesn't have permission (admin only)
        """
        # Only admins can view role permissions
        if user.role != "admin":
            raise ForbiddenError("Only admins can view role permissions")

        role_permissions = await self.role_permission_repo.get_all()
        return [RolePermissionResponse.model_validate(rp) for rp in role_permissions]

    async def update_role_permission(
        self, role: str, user: User, permission_data: RolePermissionUpdate
    ) -> RolePermissionResponse:
        """
        Update role permission.

        Args:
            role: Role name (commander, navigator, explorer, guest)
            user: Current user
            permission_data: Permission update data

        Returns:
            RolePermissionResponse: Updated role permission

        Raises:
            ForbiddenError: If user doesn't have permission (admin only)
            BadRequestError: If role is invalid
        """
        # Only admins can update role permissions
        if user.role != "admin":
            raise ForbiddenError("Only admins can update role permissions")

        valid_roles = ["commander", "navigator", "explorer", "guest"]
        if role not in valid_roles:
            raise BadRequestError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")

        # Get existing role permission or create new one
        role_permission = await self.role_permission_repo.get_by_role(role)

        if role_permission:
            # Update existing
            role_permission.permissions = permission_data.permissions
            await self.db.commit()
            await self.db.refresh(role_permission)
        else:
            # Create new
            role_permission = await self.role_permission_repo.create(
                role=role, permissions=permission_data.permissions
            )
            await self.db.commit()
            await self.db.refresh(role_permission)

        return RolePermissionResponse.model_validate(role_permission)
