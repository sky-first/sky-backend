"""Space service."""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import BackgroundTasks
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
from src.ai.http_client import AIServiceHTTPClient

logger = logging.getLogger(__name__)


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
        self.ai_client = AIServiceHTTPClient()

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
        try:
            spaces_data = await self.space_repo.get_by_user_with_stats(user.id, skip=skip, limit=limit)
            result = []
            for space_data in spaces_data:
                try:
                    result.append(SpaceResponse.model_validate(space_data))
                except Exception as e:
                    logger.error(
                        f"Error validating space {space_data.get('id')}: {str(e)}",
                        exc_info=True,
                    )
                    try:
                        space_data["color"] = None
                        result.append(SpaceResponse.model_validate(space_data))
                    except Exception as e2:
                        logger.error(
                            f"Error validating space {space_data.get('id')} with color=None: {str(e2)}",
                            exc_info=True,
                        )
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
        if space.created_by != user.id and user.role not in ("admin", "owner"):
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

        # Auto-add creator as the first member of the space.
        # Without this, the creator does not show up in the members list
        # nor in the collaborative presence pill (see DO2025-collaborative-mode).
        await self.member_repo.create(
            space_id=space.id,
            user_id=user.id,
        )

        # Auto-create a service principal for this space (C3 in master plan).
        # Collaborative agents created on space-scoped pages run as this
        # identity so they survive the creator leaving the org.
        from src.models.service_principal import ServicePrincipal

        sp = ServicePrincipal(
            space_id=space.id,
            name=f"sa-space-{str(space.id)[:8]}",
        )
        self.db.add(sp)

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

        if space.created_by != user.id and user.role not in ("admin", "owner"):
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
            if user.role not in ("admin", "owner") and space.created_by != user.id:
                raise ForbiddenError("Access denied to this space")

        # C6: end every agent scoped to this space before cascade-deleting.
        # The agents rows are kept (audit), but moved to status='ended' so
        # the worker / beat never schedules them again.
        from sqlalchemy import update as sa_update

        from src.models.agent import Agent

        await self.db.execute(
            sa_update(Agent)
            .where(
                Agent.scope == "space",
                Agent.scope_id == str(space_id),
                Agent.status != "ended",
            )
            .values(status="ended")
        )

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

        is_creator = space.created_by == user.id
        is_member = await self.member_repo.get_by_space_and_user(space_id, user.id) is not None
        if not is_creator and not is_member:
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

        if space.created_by != user.id and user.role not in ("admin", "owner"):
            raise ForbiddenError("Access denied to this space")

        connections = await self.space_repo.get_space_connections(space_id)
        return connections

    async def add_space_connection(
        self, space_id: UUID, connection_id: UUID, user: User, background_tasks: BackgroundTasks
    ) -> SpaceConnection:
        """
        Add a connection to a space.

        Args:
            space_id: Space ID
            connection_id: Connection ID
            user: Current user
            background_tasks: FastAPI BackgroundTasks object

        Returns:
            SpaceConnection: The created association

        Raises:
            NotFoundError: If space or connection not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id and user.role not in ("admin", "owner"):
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

        # Trigger AI discovery for the connection in the background using BackgroundTasks abstraction
        background_tasks.add_task(
            self._trigger_ai_discovery,
            connection_id=str(connection_id),
            space_id=str(space_id),
        )

        return space_connection

    async def _trigger_ai_discovery(self, connection_id: str, space_id: str) -> None:
        """Helper to trigger AI discovery with proper error handling for BackgroundTasks."""
        try:
            await self.ai_client.discover_connection(
                connection_id=connection_id,
                space_id=space_id,
                run_in_background=True,
            )
        except Exception as e:
            logger.error(
                f"Background task failed: Auto-discovery for space {space_id} and connection {connection_id} failed: {str(e)}"
            )

    async def remove_space_connection(
        self, space_id: UUID, connection_id: UUID, user: User
    ) -> None:
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

        if space.created_by != user.id and user.role not in ("admin", "owner"):
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

        if space.created_by != user.id and user.role not in ("admin", "owner"):
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

        if space.created_by != user.id and user.role not in ("admin", "owner"):
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

        # Notify the new member they've been added to the space
        try:
            from src.schemas.notification import NotificationCreate
            from src.services.notification_service import NotificationService

            notif_svc = NotificationService(self.db)
            await notif_svc.create(
                NotificationCreate(
                    user_id=member_data.user_id,
                    type="space_member_added",
                    title=f"You were added to space '{space.name}'",
                    description=f"{user.name or user.email} added you to this space",
                    entity_type="space",
                    entity_id=str(space_id),
                    deep_link=f"/dashboard?space={space_id}",
                )
            )
        except Exception:
            pass  # Non-fatal

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

    async def get_space_tables(
        self, space_id: UUID, user: User, only_selected: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get all tables from connections in a space.

        Args:
            space_id: Space ID
            user: Current user
            only_selected: If True, only return tables that were explicitly linked to the space.

        Returns:
            List[Dict[str, Any]]: List of tables with connection info
        """
        # Get space connections
        space_connections = await self.space_repo.get_space_connections(space_id)

        # Get explicitly selected tables, building a lookup set that covers
        # both the canonical (conn_id, bare_name, schema) tuple AND the legacy
        # format where the full "schema.table" name was stored as table_name.
        selected_tables_entities = await self.table_repo.get_space_tables(space_id)
        selected_tables_set: set = set()
        for t in selected_tables_entities:
            conn_str = str(t.connection_id)
            # Canonical key: (conn_id, bare_table_name, schema_name)
            selected_tables_set.add((conn_str, t.table_name, t.schema_name))
            # Legacy: if someone previously stored "schema.table" as table_name,
            # add a split variant so it can still match against metadata tuples
            if "." in t.table_name:
                parts = t.table_name.split(".", 1)
                selected_tables_set.add((conn_str, parts[1], parts[0]))
                # Also allow matching when schema is None in metadata
                selected_tables_set.add((conn_str, parts[1], None))

        # Get tables from each connection
        tables = []
        for space_conn in space_connections:
            connection = space_conn.connection
            metadata = await self.metadata_repo.get_by_connection_id(space_conn.connection_id)
            if not metadata or not metadata.tables:
                continue

            # Extract table information
            for table_data in metadata.tables:
                t_name = None
                t_schema = None

                if isinstance(table_data, dict):
                    t_name = table_data.get("name")
                    t_schema = table_data.get("schema")
                else:
                    # If it's already a TableMetadata object
                    t_name = getattr(table_data, "name", None)
                    t_schema = getattr(table_data, "schema", None)

                if t_name:
                    conn_str = str(space_conn.connection_id)
                    is_selected = (conn_str, t_name, t_schema) in selected_tables_set or (
                        conn_str,
                        t_name,
                        None,
                    ) in selected_tables_set

                    if only_selected and not is_selected:
                        continue

                    tables.append(
                        {
                            "id": f"{space_conn.connection_id}-{t_name}",
                            "connection_id": str(space_conn.connection_id),
                            "connection_name": connection.name,
                            "connection_type": getattr(connection, "connector_id", None),
                            "table_name": t_name,
                            "name": t_name,
                            "schema": t_schema,
                            "schema_name": t_schema,
                            "row_count": (
                                table_data.get("row_count")
                                if isinstance(table_data, dict)
                                else getattr(table_data, "row_count", None)
                            ),
                            "selected": is_selected,
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

        # Owners and admins can link tables to any space; creators can
        # link tables to their own. The endpoint already RBAC-checks
        # `spaces.members.manage` — this guard is defence-in-depth for
        # internal callers that bypass the route.
        if space.created_by != user.id and user.role not in ("admin", "owner"):
            raise ForbiddenError("Access denied to this space")

        # Verify the connection exists — if not, fail fast with a 404
        # instead of letting the FK blow up inside commit() and surface
        # as an opaque 500.
        connection = await self.connection_repo.get_by_id(table_data.connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        # Check if already exists
        existing = await self.table_repo.get_space_table(
            space_id,
            table_data.connection_id,
            table_data.table_name,
            table_data.schema_name,
        )
        if existing:
            return {"message": "Table already linked", "id": str(existing.id)}

        # Create association
        from sqlalchemy.exc import IntegrityError

        from src.models.space import SpaceTable

        space_table = SpaceTable(
            space_id=space_id,
            connection_id=table_data.connection_id,
            table_name=table_data.table_name,
            schema_name=table_data.schema_name,
        )
        self.db.add(space_table)
        try:
            await self.db.commit()
            await self.db.refresh(space_table)
        except IntegrityError as e:
            # Race condition (concurrent link) or unique-constraint hit —
            # roll back and treat as an idempotent success. Logging the
            # actual error here keeps the 500 off the wire so the user
            # sees the correct linked state.
            await self.db.rollback()
            logger.warning(
                "add_space_table integrity error (treated as already linked): %s",
                str(e),
            )
            existing = await self.table_repo.get_space_table(
                space_id,
                table_data.connection_id,
                table_data.table_name,
                table_data.schema_name,
            )
            if existing:
                return {"message": "Table already linked", "id": str(existing.id)}
            raise BadRequestError("Could not link table — integrity check failed")
        except Exception as e:
            # Any other DB error: roll back and surface a clean 400 with
            # the exception type so the frontend stops showing a generic
            # 500 that reverts the optimistic Link state.
            await self.db.rollback()
            logger.exception("add_space_table failed")
            raise BadRequestError(f"Could not link table: {type(e).__name__}")

        return {"message": "Table linked successfully", "id": str(space_table.id)}

    async def remove_space_table(
        self,
        space_id: UUID,
        connection_id: UUID,
        table_name: str,
        schema_name: Optional[str],
        user: User,
    ) -> None:
        """
        Remove a specific table from a space.
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id and user.role not in ("admin", "owner"):
            raise ForbiddenError("Access denied to this space")

        association = await self.table_repo.get_space_table(
            space_id, connection_id, table_name, schema_name
        )
        if not association:
            raise NotFoundError("Table association not found")

        await self.db.delete(association)
        await self.db.commit()

    async def set_space_table_hidden_columns(
        self,
        space_id: UUID,
        connection_id: UUID,
        table_name: str,
        schema_name: Optional[str],
        hidden_columns: list[str],
        user: User,
    ) -> None:
        """Replace the hidden_columns list for a space-linked table.

        `hidden_columns` is a whitelist-inverse: every column in the
        list is filtered out of retrieval / render for this Space only.
        The RBAC gate at the endpoint layer (`connections.edit`) is the
        authoritative permission check; the ownership guard below is a
        defence-in-depth against rogue internal callers that bypass the
        route handler.
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")
        if space.created_by != user.id and user.role not in ("admin", "owner"):
            raise ForbiddenError("Access denied to this space")

        association = await self.table_repo.get_space_table(
            space_id, connection_id, table_name, schema_name
        )
        if not association:
            raise NotFoundError("Table association not found — link the table first")

        # Deduplicate + strip while preserving UI order.
        seen: set[str] = set()
        cleaned: list[str] = []
        for col in hidden_columns:
            key = col.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(key)
        association.hidden_columns = cleaned
        await self.db.commit()

    async def get_space_stats(self, space_id: UUID, user: User) -> dict:
        """
        Get statistics for a space.
        """
        from src.repositories.ai import AIQueryRepository

        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        # Get space connections
        space_connections = await self.space_repo.get_space_connections(space_id)
        connection_ids = [sc.connection_id for sc in space_connections]

        # Get stats from AI Repository
        ai_repo = AIQueryRepository(self.db)
        total_queries = await ai_repo.count_queries_by_connection_ids(connection_ids)
        active_users = await ai_repo.get_active_users_by_connection_ids(connection_ids)

        # Aggregated metrics from connections
        total_usage_bytes = 0
        avg_compliance = 0
        conn_count = 0

        for sc in space_connections:
            conn = await self.connection_repo.get_by_id(sc.connection_id)
            if conn and conn.metrics:
                m = conn.metrics
                if isinstance(m, dict):
                    total_usage_bytes += m.get("usage_bytes", 0)
                    if "compliance_score" in m:
                        avg_compliance += m["compliance_score"]
                        conn_count += 1

        compliance = (avg_compliance / conn_count) if conn_count > 0 else 0

        # Formatting helpers
        def format_bytes(b):
            if b <= 0:
                return "0B"
            import math

            size_name = ("B", "KB", "MB", "GB", "TB")
            i = int(math.floor(math.log(b, 1024)))
            p = math.pow(1024, i)
            s = round(b / p, 1)
            return f"{s}{size_name[i]}"

        def format_number(n):
            if n >= 1000:
                return f"{round(n / 1000, 1)}k"
            return str(n)

        # Return in a format that matches the expected schema
        return {
            "total_queries": {
                "value": format_number(total_queries),
                "change": "+0%",
                "trend": "neutral",
            },
            "active_users": {
                "value": str(active_users),
                "change": "+0%",
                "trend": "neutral",
            },
            "data_usage": {
                "value": format_bytes(total_usage_bytes),
                "change": "+0%",
                "trend": "neutral",
            },
            "compliance_score": {
                "value": f"{int(compliance)}%",
                "change": "+0%",
                "trend": "neutral",
            },
            "activity_feed": [],  # TODO: Implement activity feed
        }
