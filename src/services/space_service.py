"""Space service."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.crew import Crew
from src.models.space import SpaceConnection
from src.models.user import User
from src.repositories.connection import ConnectionMetadataRepository, ConnectionRepository
from src.repositories.space import SpaceMemberRepository, SpaceRepository, SpaceTableRepository
from src.schemas.space import (
    SpaceCreate,
    SpaceMemberCreate,
    SpaceMemberResponse,
    SpaceResponse,
    SpaceTableCreate,
    SpaceUpdate,
)


class SpaceService:
    """Space service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize space service.

        Args:
            db: Database session
        """
        self.db = db
        self.space_repo = SpaceRepository(db)
        self.connection_repo = ConnectionRepository(db)
        self.member_repo = SpaceMemberRepository(db)
        self.metadata_repo = ConnectionMetadataRepository(db)
        self.table_repo = SpaceTableRepository(db)

    async def list_spaces(self, user: User, skip: int = 0, limit: int = 100) -> List[SpaceResponse]:
        """
        List spaces.

        Args:
            user: Current user
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[SpaceResponse]: List of spaces
        """
        import logging

        logger = logging.getLogger(__name__)

        try:
            spaces = await self.space_repo.get_by_user(user.id, skip=skip, limit=limit)
            result = []
            for space in spaces:
                try:
                    # Normalize color field - ensure it's either None or a valid hex color
                    normalized_color = None
                    if space.color:
                        # Check if it's a valid hex color
                        if (
                            isinstance(space.color, str)
                            and space.color.startswith("#")
                            and len(space.color) == 7
                        ):
                            try:
                                int(space.color[1:], 16)  # Validate hex
                                normalized_color = space.color
                            except ValueError:
                                # Invalid hex, set to None
                                normalized_color = None
                        # If it's not a valid hex format, set to None

                    # Create response using model_validate with from_attributes
                    # Temporarily set color to normalized value
                    original_color = space.color
                    space.color = normalized_color
                    try:
                        response = SpaceResponse.model_validate(space)
                        result.append(response)
                    finally:
                        # Restore original color value
                        space.color = original_color
                except Exception as e:
                    logger.error(f"Error validating space {space.id}: {str(e)}", exc_info=True)
                    # Try with color as None if validation fails
                    try:
                        original_color = space.color
                        space.color = None
                        try:
                            response = SpaceResponse.model_validate(space)
                            result.append(response)
                        finally:
                            space.color = original_color
                    except Exception as e2:
                        logger.error(
                            f"Error validating space {space.id} with color=None: {str(e2)}",
                            exc_info=True,
                        )
                        # Skip this space if it still fails
                        continue
            return result
        except Exception as e:
            logger.error(f"Error listing spaces for user {user.id}: {str(e)}", exc_info=True)
            raise

    async def get_space(self, space_id: UUID, user: User) -> SpaceResponse:
        """
        Get space by ID.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            SpaceResponse: Space data

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        # Check access (only owner for now)
        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        return SpaceResponse.model_validate(space)

    async def create_space(self, user: User, space_data: SpaceCreate) -> SpaceResponse:
        """
        Create a new space.

        Args:
            user: Current user
            space_data: Space creation data

        Returns:
            SpaceResponse: Created space
        """
        space = await self.space_repo.create(
            name=space_data.name,
            description=space_data.description,
            color=space_data.color,
            icon=space_data.icon,
            created_by=user.id,
        )

        await self.db.commit()
        await self.db.refresh(space)

        return SpaceResponse.model_validate(space)

    async def update_space(
        self, space_id: UUID, user: User, space_data: SpaceUpdate
    ) -> SpaceResponse:
        """
        Update space.

        Args:
            space_id: Space ID
            user: Current user
            space_data: Space update data

        Returns:
            SpaceResponse: Updated space

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        update_data = space_data.model_dump(exclude_unset=True)
        space = await self.space_repo.update(space_id, **update_data)
        await self.db.commit()
        await self.db.refresh(space)

        return SpaceResponse.model_validate(space)

    async def delete_space(self, space_id: UUID, user: User) -> None:
        """
        Delete space.

        Args:
            space_id: Space ID
            user: Current user

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        import logging

        from src.config.settings import get_settings

        logger = logging.getLogger(__name__)

        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        settings = get_settings()

        # In development, allow any user to delete any space
        # In production, only admin or owner can delete
        if settings.is_development:
            # Development mode: allow any authenticated user to delete
            logger.info(
                f"🔴 [DELETE SPACE SERVICE] Development mode: Allowing user {user.id} to delete space {space_id} (created by {space.created_by})"
            )
        else:
            # Production mode: only admin or owner can delete
            if user.role != "admin" and space.created_by != user.id:
                raise ForbiddenError("Access denied to this space")

        await self.space_repo.delete(space_id)
        await self.db.commit()
        logger.info(f"🔴 [DELETE SPACE SERVICE] Space {space_id} deleted successfully")

    async def get_space_crews(self, space_id: UUID, user: User) -> List[Crew]:
        """
        Get crews for a space.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            List[Crew]: List of crews

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        crews = await self.space_repo.get_space_crews(space_id)
        return crews

    async def get_space_connections(self, space_id: UUID, user: User) -> List[SpaceConnection]:
        """
        Get connections for a space.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            List[SpaceConnection]: List of space connections

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        connections = await self.space_repo.get_space_connections(space_id)
        return connections

    async def add_space_connection(
        self, space_id: UUID, connection_id: UUID, user: User
    ) -> SpaceConnection:
        """
        Add a connection to a space.

        Args:
            space_id: Space ID
            connection_id: Connection ID
            user: Current user

        Returns:
            SpaceConnection: The created association

        Raises:
            NotFoundError: If space or connection not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        connection = await self.connection_repo.get_by_id(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        # Check if already exists
        existing = await self.space_repo.get_space_connection(space_id, connection_id)
        if existing:
            return existing

        # Create association using the repository's helper or manually
        space_connection = SpaceConnection(space_id=space_id, connection_id=connection_id)
        self.db.add(space_connection)
        await self.db.commit()
        await self.db.refresh(space_connection)

        return space_connection

    async def remove_space_connection(self, space_id: UUID, connection_id: UUID, user: User) -> None:
        """
        Remove a connection from a space.

        Args:
            space_id: Space ID
            connection_id: Connection ID
            user: Current user

        Raises:
            NotFoundError: If space or association not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        association = await self.space_repo.get_space_connection(space_id, connection_id)
        if not association:
            raise NotFoundError("Connection not linked to this space")

        await self.db.delete(association)
        await self.db.commit()

    async def get_space_members(self, space_id: UUID, user: User) -> List[SpaceMemberResponse]:
        """
        Get all members of a space.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            List[SpaceMemberResponse]: List of members

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        members = await self.member_repo.get_space_members(space_id)
        # Refresh user objects to ensure they're loaded
        for member in members:
            await self.db.refresh(member, ["user"])
        return [SpaceMemberResponse.model_validate(m) for m in members]

    async def add_space_member(
        self, space_id: UUID, user: User, member_data: SpaceMemberCreate
    ) -> SpaceMemberResponse:
        """
        Add member to space.

        Args:
            space_id: Space ID
            user: Current user
            member_data: Member data

        Returns:
            SpaceMemberResponse: Created member

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
            BadRequestError: If member already exists
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        # Check if member already exists
        existing = await self.member_repo.get_by_space_and_user(space_id, member_data.user_id)
        if existing:
            raise BadRequestError("User is already a member of this space")

        # Create new member
        member = await self.member_repo.create(
            space_id=space_id,
            user_id=member_data.user_id,
        )

        await self.db.commit()
        await self.db.refresh(member, ["user"])

        return SpaceMemberResponse.model_validate(member)

    async def remove_space_member(self, space_id: UUID, user_id: UUID, current_user: User) -> None:
        """
        Remove member from space.

        Args:
            space_id: Space ID
            user_id: User ID to remove
            current_user: Current user

        Raises:
            NotFoundError: If space or member not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != current_user.id:
            raise ForbiddenError("Access denied to this space")

        # Check if member exists
        member = await self.member_repo.get_by_space_and_user(space_id, user_id)
        if not member:
            raise NotFoundError("Member not found")

        # Don't allow removing the space creator
        if space.created_by == user_id:
            raise ForbiddenError("Cannot remove space creator")

        await self.member_repo.delete(member.id)
        await self.db.commit()

    async def get_space_tables(self, space_id: UUID, user: User) -> List[dict]:
        """
        Get all tables from connections in a space.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            List[dict]: List of tables with connection info
                Format: [
                    {
                        "connection_id": str,
                        "connection_name": str,
                        "table_name": str,
                        "schema": str | None,
                        "row_count": int | None
                    },
                    ...
                ]

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        # Get space connections
        space_connections = await self.space_repo.get_space_connections(space_id)
        
        # Get explicitly selected tables
        selected_tables_entities = await self.table_repo.get_space_tables(space_id)
        selected_tables_map = {
            (str(t.connection_id), t.table_name, t.schema_name): True 
            for t in selected_tables_entities
        }

        # Get tables from each connection
        tables = []
        for space_conn in space_connections:
            connection = await self.connection_repo.get_by_id(space_conn.connection_id)
            if not connection:
                continue

            metadata = await self.metadata_repo.get_by_connection_id(space_conn.connection_id)
            if not metadata or not metadata.tables:
                continue

            # Extract table information
            for table_data in metadata.tables:
                if isinstance(table_data, dict):
                    t_name = table_data.get("name", "")
                    t_schema = table_data.get("schema")
                    is_selected = (str(space_conn.connection_id), t_name, t_schema) in selected_tables_map
                    
                    tables.append(
                        {
                            "connection_id": str(space_conn.connection_id),
                            "connection_name": connection.name,
                            "connection_type": getattr(connection, "connector_id", None),
                            "table_name": t_name,
                            "schema": t_schema,
                            "row_count": table_data.get("row_count"),
                            "selected": is_selected
                        }
                    )
                else:
                    # If it's already a TableMetadata object
                    t_name = getattr(table_data, "name", "")
                    t_schema = getattr(table_data, "schema", None)
                    is_selected = (str(space_conn.connection_id), t_name, t_schema) in selected_tables_map

                    tables.append(
                        {
                            "connection_id": str(space_conn.connection_id),
                            "connection_name": connection.name,
                            "connection_type": getattr(connection, "connector_id", None),
                            "table_name": t_name,
                            "schema": t_schema,
                            "row_count": getattr(table_data, "row_count", None),
                            "selected": is_selected
                        }
                    )

        return tables

    async def add_space_table(
        self, space_id: UUID, table_data: SpaceTableCreate, user: User
    ) -> dict:
        """
        Add a specific table to a space.
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        # Check if already exists
        existing = await self.table_repo.get_space_table(
            space_id, table_data.connection_id, table_data.table_name, table_data.schema_name
        )
        if existing:
            return {"message": "Table already linked", "id": str(existing.id)}

        # Create association
        from src.models.space import SpaceTable

        space_table = SpaceTable(
            space_id=space_id,
            connection_id=table_data.connection_id,
            table_name=table_data.table_name,
            schema_name=table_data.schema_name,
        )
        self.db.add(space_table)
        await self.db.commit()
        await self.db.refresh(space_table)

        return {"message": "Table linked successfully", "id": str(space_table.id)}

    async def remove_space_table(
        self, space_id: UUID, connection_id: UUID, table_name: str, schema_name: Optional[str], user: User
    ) -> None:
        """
        Remove a specific table from a space.
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        association = await self.table_repo.get_space_table(
            space_id, connection_id, table_name, schema_name
        )
        if not association:
            raise NotFoundError("Table association not found")

        await self.db.delete(association)
        await self.db.commit()
