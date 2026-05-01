"""Permission service."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.crew import CrewMember
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
        from src.repositories.space import SpaceTableRepository

        self.space_table_repo = SpaceTableRepository(db)

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
        self,
        connection_id: UUID,
        user: User,
        permission_data: ConnectionPermissionCreate,
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
            connection_id,
            permission_data.space_id,
            permission_data.crew_id,
            permission_data.user_id,
        )
        if existing:
            raise BadRequestError(
                "Permission already exists for this connection, target (space/crew/user) already assigned"
            )

        permission = await self.permission_repo.create(
            connection_id=connection_id,
            space_id=permission_data.space_id,
            crew_id=permission_data.crew_id,
            user_id=permission_data.user_id,
            access_level=permission_data.access_level,
            table_access=permission_data.table_access,
        )

        # Commit permission first
        await self.db.commit()
        await self.db.refresh(permission)

        # If permission is for a space, automatically create SpaceConnection
        # so tables are available when viewing the space
        if permission_data.space_id:
            try:
                # 1. Sync SpaceConnection
                existing_connections = await self.space_repo.get_space_connections(
                    permission_data.space_id
                )
                connection_exists = any(
                    str(sc.connection_id) == str(connection_id) for sc in existing_connections
                )

                if not connection_exists:
                    from src.models.space import SpaceConnection

                    space_connection = SpaceConnection(
                        space_id=permission_data.space_id, connection_id=connection_id
                    )
                    self.db.add(space_connection)
                    await self.db.commit()

                # 2. Sync SpaceTable if tables are specified
                if permission_data.table_access:
                    await self._sync_space_tables(
                        permission_data.space_id,
                        connection_id,
                        permission_data.table_access,
                    )

            except Exception as e:
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Failed to sync space associations for space {permission_data.space_id} and connection {connection_id}: {e}",
                    exc_info=True,
                )
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

        # If space_id exists and table_access was updated, sync SpaceTable
        if permission.space_id and "table_access" in update_data:
            await self._sync_space_tables(
                permission.space_id,
                permission.connection_id,
                update_data["table_access"],
            )

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

        # If this was a space permission, we might want to clean up SpaceTable entries
        # so they don't linger without permission
        if permission.space_id:
            await self._sync_space_tables(permission.space_id, permission.connection_id, [])

        await self.permission_repo.delete(permission_id)
        await self.db.commit()

    async def _sync_space_tables(
        self, space_id: UUID, connection_id: UUID, table_access: Optional[List[str]]
    ) -> None:
        """
        Sync SpaceTable entries for a space and connection.

        Table names in table_access may arrive as "schema.tablename" (e.g. "public.orders")
        or as bare table names (e.g. "orders").  We normalise them into (table_name, schema_name)
        pairs so the stored values match what get_space_tables looks up from connection metadata.
        """
        if not space_id:
            return

        # Parse each entry into (table_name, schema_name) tuples
        def _parse(entry: str):
            parts = entry.split(".", 1)
            if len(parts) == 2:
                return parts[1], parts[0]  # (table_name, schema_name)
            return parts[0], None  # (table_name, None)

        # Get existing SpaceTable entries for this space and connection
        existing_tables = await self.space_table_repo.get_space_tables(space_id)
        # Key by (table_name, schema_name) so we handle schema-qualified names correctly
        existing_conn_map = {
            (t.table_name, t.schema_name): t
            for t in existing_tables
            if t.connection_id == connection_id
        }

        # Tables that SHOULD be there (parsed into tuples)
        target_tuples = {_parse(t) for t in (table_access or [])}

        # Tables to add
        for t_name, s_name in target_tuples:
            if (t_name, s_name) not in existing_conn_map:
                create_kwargs: dict = {
                    "space_id": space_id,
                    "connection_id": connection_id,
                    "table_name": t_name,
                }
                if s_name is not None:
                    create_kwargs["schema_name"] = s_name
                await self.space_table_repo.create(**create_kwargs)

        # Tables to remove
        for (t_name, s_name), t_obj in existing_conn_map.items():
            if (t_name, s_name) not in target_tuples:
                await self.space_table_repo.delete(t_obj.id)

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
            allowed=False,
            reason="User does not have permission to access this connection",
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
            permission_data.connection_id,
            permission_data.table_name,
            permission_data.member_id,
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
        self,
        permission_id: UUID,
        user: User,
        permission_data: TableMemberPermissionUpdate,
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
            ForbiddenError: If user doesn't have permission (admin or owner)
        """
        # Owner is the platform's super-admin (Wave 1 of platform-roles)
        # and bypasses every check on the FE; the BE was checking only
        # 'admin' which locked owners out. Both must pass.
        if user.role not in ("admin", "owner"):
            raise ForbiddenError("Only admins or the workspace owner can view role permissions")

        role_permissions = await self.role_permission_repo.get_all()
        return [RolePermissionResponse.model_validate(rp) for rp in role_permissions]

    async def update_role_permission(
        self, role: str, user: User, permission_data: RolePermissionUpdate
    ) -> RolePermissionResponse:
        """
        Update role permission.

        Args:
            role: Role name (owner, editor, viewer)
            user: Current user
            permission_data: Permission update data

        Returns:
            RolePermissionResponse: Updated role permission

        Raises:
            ForbiddenError: If user doesn't have permission (admin only)
            BadRequestError: If role is invalid
        """
        # Only admins or owner can update role permissions (owner is
        # the platform super-admin per Wave 1 of platform-roles).
        if user.role not in ("admin", "owner"):
            raise ForbiddenError("Only admins or the workspace owner can update role permissions")

        # Lucas's 2026-04-30 review: Member is the platform-level role
        # for everyday employees and MUST be editable in the matrix.
        # Guest was retired (canonicalised to viewer on the BE).
        # Owner / Admin still bypass on the runtime read path
        # (rbac_service:697) so flipping their toggles is a no-op,
        # but the toggle has to land somewhere to persist; we accept
        # them here so the FE matrix renders the same row count it
        # already shows.
        valid_roles = ["owner", "admin", "member", "editor", "viewer"]
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

    async def get_authorized_tables(
        self,
        user_id: UUID,
        connection_id: UUID,
        space_id: Optional[UUID] = None,
        crew_ids: Optional[List[UUID]] = None,
    ) -> List[str]:
        """
        Get authorized tables for a user in a specific context.

        Args:
            user_id: User ID
            connection_id: Connection ID
            space_id: Optional Space ID
            crew_ids: Optional list of Crew IDs

        Returns:
            List[str]: List of authorized table names
        """
        from typing import Set

        connection = await self.connection_repo.get_by_id_with_metadata(connection_id)
        if not connection:
            return []

        # Helper to get all tables from metadata
        def get_all_tables() -> List[str]:
            metadata = connection.connection_metadata
            if metadata and metadata.tables:
                return [t.get("name") for t in metadata.tables if t.get("name")]
            return []

        # 1. Ownership: Still return all tables if owner AND No Context (Personal Management)
        # If in Space or Crew context, enforce strict filtering (Fail-Closed).
        if connection.created_by == user_id and not space_id and not crew_ids:
            return get_all_tables()

        authorized_tables: Set[str] = set()
        is_restricted_by_space = False

        # 2. Space Permissions & Table Linkage
        if space_id:
            perm = await self.permission_repo.get_by_connection_and_space(
                connection_id, space_id, None
            )

            # Check explicit SpaceTable associations
            space_tables = await self.space_table_repo.get_space_tables(space_id)
            linked_tables = {t.table_name for t in space_tables if t.connection_id == connection_id}

            if perm:
                if perm.access_level == "full":
                    # Full access at space level usually bypasses specific table checks
                    # unless we want SpaceTable to be the absolute filter.
                    # For now, full access wins.
                    return get_all_tables()
                elif perm.table_access:
                    authorized_tables.update(perm.table_access)
                    is_restricted_by_space = True

            if linked_tables:
                # If the user has linked specific tables to this space, use them.
                # If authorized_tables already had some from 'perm', they merge.
                authorized_tables.update(linked_tables)
                is_restricted_by_space = True

        # 3. Crew Permissions
        if crew_ids:
            for crew_id in crew_ids:
                perm = await self.permission_repo.get_by_connection_and_space(
                    connection_id, None, crew_id
                )
                if perm:
                    if perm.access_level == "full":
                        return get_all_tables()  # Full access at crew level
                    elif perm.table_access:
                        authorized_tables.update(perm.table_access)
                        is_restricted_by_space = True

        # 4. Individual User Connection Permissions
        user_conn_perm = await self.permission_repo.get_by_connection_and_space(
            connection_id, None, None, user_id
        )
        if user_conn_perm:
            if user_conn_perm.access_level == "full":
                return get_all_tables()
            elif user_conn_perm.table_access:
                authorized_tables.update(user_conn_perm.table_access)
                is_restricted_by_space = (
                    True  # Treat user restriction similarly for inheritance logic
                )

        # 5. Granular Table Member Permissions (if any)
        # Note: These usually come from crew member context, but kept for legacy/bridge support
        query = select(CrewMember.id).where(CrewMember.user_id == user_id)
        res = await self.db.execute(query)
        member_ids = [r[0] for r in res.all()]

        member_perms = []
        if member_ids:
            # We filter by member_id and connection_id
            for m_id in member_ids:
                perms = await self.table_member_permission_repo.get_by_member(m_id)
                for p in perms:
                    if p.connection_id == connection_id and p.has_access:
                        authorized_tables.add(p.table_name)
                        member_perms.append(p)

        # Final check: if we are in a space/crew context and NO tables are authorized yet,
        # but the user is NOT the owner and DOES NOT have member perms, they should have nothing.
        if (
            (space_id or crew_ids)
            and not authorized_tables
            and not is_restricted_by_space
            and not member_perms
        ):
            # If no permissions are explicitly defined for the space/crew, does it inherit ownership?
            # No, ownership was checked at step 1.
            # Does it inherit "all tables"? Usually not in a collaborative context unless public.
            # For now, return empty if no matches found in collaborative context.
            return []

        # Final safety filter: ensure everything in authorized_tables is a non-None string
        final_list = [t for t in authorized_tables if t and isinstance(t, str)]
        return sorted(list(set(final_list)))
