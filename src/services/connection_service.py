"""Connection service."""

import time
from datetime import datetime, time, timedelta, timezone
from typing import List, Optional
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.http_client import AIServiceHTTPClient
from src.config.settings import get_settings
from src.connectors.registry import get_connector
from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.user import User
from src.repositories.connection import ConnectionMetadataRepository, ConnectionRepository
from src.repositories.space import SpaceRepository
from src.schemas.connection import (
    ConnectionCreate,
    ConnectionMetadataResponse,
    ConnectionResponse,
    ConnectionStatusResponse,
    ConnectionSyncResponse,
    ConnectionTestResponse,
    ConnectionUpdate,
    ConnectionValidateResponse,
    TableMetadataSchema,
)

logger = structlog.get_logger(__name__)


class ConnectionService:
    """Connection service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize connection service.

        Args:
            db: Database session
        """
        self.db = db
        self.connection_repo = ConnectionRepository(db)
        self.metadata_repo = ConnectionMetadataRepository(db)
        self.space_repo = SpaceRepository(db)
        self.ai_client = AIServiceHTTPClient()

    async def _calculate_next_sync(self, frequency: str, last_sync: Optional[datetime]) -> Optional[datetime]:
        """
        Calculate next sync time based on frequency.
        
        Args:
            frequency: Sync frequency alias (1h, 6h, daily_00, etc.)
            last_sync: Last successful sync time
            
        Returns:
            Optional[datetime]: Next predicted sync time
        """
        if not frequency or frequency == "manual":
            return None
            
        base_time = last_sync or datetime.now(timezone.utc)
        
        if frequency == "1h":
            return base_time + timedelta(hours=1)
        elif frequency == "6h":
            return base_time + timedelta(hours=6)
        elif frequency == "12h":
            return base_time + timedelta(hours=12)
        elif frequency == "daily_00":
            # Next day at 00:00 UTC
            next_day = base_time.date() + timedelta(days=1)
            return datetime.combine(next_day, time(0, 0), tzinfo=timezone.utc)
        elif frequency == "daily_02":
            # Next day at 02:00 UTC
            next_day = base_time.date() + timedelta(days=1)
            return datetime.combine(next_day, time(2, 0), tzinfo=timezone.utc)
        elif "*/" in frequency:
            # Simple handling for cron strings from connector definitions
            # Default to 6 hours for any cron-like string for now
            return base_time + timedelta(hours=6)
            
        return base_time + timedelta(hours=1)

    async def list_connections(
        self,
        user: User,
        status: Optional[str] = None,
        connector_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[ConnectionResponse]:
        """
        List connections.

        Args:
            user: Current user
            status: Optional status filter
            connector_id: Optional connector filter
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[ConnectionResponse]: List of connections
        """
        filters = {}
        if status:
            filters["status"] = status
        if connector_id:
            filters["connector_id"] = connector_id

        connections = await self.connection_repo.get_by_user(
            user.id, skip=skip, limit=limit, filters=filters
        )
        return [ConnectionResponse.model_validate(c) for c in connections]

    async def get_connection(self, connection_id: UUID, user: User) -> ConnectionResponse:
        """
        Get connection by ID.

        Args:
            connection_id: Connection ID
            user: Current user

        Returns:
            ConnectionResponse: Connection data

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
        """
        connection = await self.connection_repo.get_by_id_with_metadata(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        # Check access (only owner for now)
        if connection.created_by != user.id:
            raise ForbiddenError("Access denied to this connection")

        return ConnectionResponse.model_validate(connection)

    async def create_connection(
        self, user: User, connection_data: ConnectionCreate
    ) -> ConnectionResponse:
        """
        Create a new connection and automatically sync metadata.

        Args:
            user: Current user
            connection_data: Connection creation data

        Returns:
            ConnectionResponse: Created connection (possibly already synced)

        Raises:
            BadRequestError: If connector_id is invalid
        """
        # Validate connector exists
        try:
            get_connector(connection_data.connector_id)
        except Exception:
            raise BadRequestError(f"Invalid connector_id: {connection_data.connector_id}")

        # TODO: Encrypt config before storing
        # Calculate initial next sync
        next_sync = await self._calculate_next_sync(connection_data.sync_frequency, None)

        connection = await self.connection_repo.create(
            name=connection_data.name,
            connector_id=connection_data.connector_id,
            description=connection_data.description,
            config=connection_data.config,
            sync_frequency=connection_data.sync_frequency,
            next_sync=next_sync,
            status="inactive",
            created_by=user.id,
        )

        await self.db.commit()
        await self.db.refresh(connection)

        # Automatically sync metadata after creating the connection.
        # If sync fails, we keep the connection created and just return it as-is.
        try:
            await self.sync_connection(connection.id, user)
            # Reload connection to include updated status/last_sync fields
            connection = await self.connection_repo.get_by_id(connection.id) or connection
        except Exception:
            # Swallow sync errors here; detailed error handling happens inside sync_connection
            pass

        return ConnectionResponse.model_validate(connection)

    async def update_connection(
        self, connection_id: UUID, user: User, connection_data: ConnectionUpdate
    ) -> ConnectionResponse:
        """
        Update connection.

        Args:
            connection_id: Connection ID
            user: Current user
            connection_data: Connection update data

        Returns:
            ConnectionResponse: Updated connection

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
        """
        connection = await self.connection_repo.get_by_id(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        if connection.created_by != user.id:
            raise ForbiddenError("Access denied to this connection")

        update_data = connection_data.model_dump(exclude_unset=True)
        
        # If sync_frequency is updated, recalculate next_sync
        if "sync_frequency" in update_data:
            update_data["next_sync"] = await self._calculate_next_sync(
                update_data["sync_frequency"], connection.last_sync
            )
            
        # TODO: Encrypt config if provided
        connection = await self.connection_repo.update(connection_id, **update_data)
        await self.db.commit()
        await self.db.refresh(connection)

        return ConnectionResponse.model_validate(connection)

    async def delete_connection(self, connection_id: UUID, user: User) -> None:
        """
        Delete connection.

        Args:
            connection_id: Connection ID
            user: Current user

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
        """
        connection = await self.connection_repo.get_by_id(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        settings = get_settings()

        # In development, allow any user to delete any connection
        # In production, only admin or owner can delete
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            f"🔴 [DELETE SERVICE] Checking permissions: connection_id={connection_id}, user_id={user.id}, environment={settings.ENVIRONMENT}, is_development={settings.is_development}"
        )

        if settings.is_development:
            # Development mode: allow any authenticated user to delete
            logger.info(
                f"🔴 [DELETE SERVICE] Development mode: Allowing user {user.id} to delete connection {connection_id} (created by {connection.created_by})"
            )
        else:
            # Production mode: only admin or owner can delete
            logger.info(
                f"🔴 [DELETE SERVICE] Production mode: Checking if user {user.id} is admin or owner"
            )
            if user.role != "admin" and connection.created_by != user.id:
                logger.warning(
                    f"🔴 [DELETE SERVICE] Access denied: user {user.id} is not admin and not owner (created_by={connection.created_by})"
                )
                raise ForbiddenError("Access denied to this connection")

        logger.info(f"🔴 [DELETE SERVICE] Deleting connection {connection_id} from database...")
        await self.connection_repo.delete(connection_id)
        await self.db.commit()
        logger.info(f"🔴 [DELETE SERVICE] Connection {connection_id} deleted successfully")

    async def test_connection(self, connection_id: UUID, user: User) -> ConnectionTestResponse:
        """
        Test connection.

        Args:
            connection_id: Connection ID
            user: Current user

        Returns:
            ConnectionTestResponse: Test result

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
        """
        connection = await self.connection_repo.get_by_id(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        if connection.created_by != user.id:
            raise ForbiddenError("Access denied to this connection")

        try:
            connector = get_connector(connection.connector_id)
            start_time = time.time()
            success = await connector.test_connection(connection.config)
            latency = int((time.time() - start_time) * 1000)

            if success:
                # Update status
                await self.connection_repo.update(connection_id, status="active", error=None)
                await self.db.commit()
                return ConnectionTestResponse(
                    success=True, message="Connection successful", latency=latency
                )
            else:
                await self.connection_repo.update(
                    connection_id,
                    status="error",
                    error={
                        "message": "Connection test failed",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
                await self.db.commit()
                return ConnectionTestResponse(
                    success=False, message="Connection test failed", latency=latency
                )
        except Exception as e:
            await self.connection_repo.update(
                connection_id,
                status="error",
                error={"message": str(e), "timestamp": datetime.now(timezone.utc).isoformat()},
            )
            await self.db.commit()
            return ConnectionTestResponse(success=False, message=f"Error: {str(e)}")

    async def sync_connection(self, connection_id: UUID, user: User) -> ConnectionSyncResponse:
        """
        Sync connection metadata.

        Args:
            connection_id: Connection ID
            user: Current user

        Returns:
            ConnectionSyncResponse: Sync result

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
        """
        connection = await self.connection_repo.get_by_id(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        if connection.created_by != user.id:
            raise ForbiddenError("Access denied to this connection")

        try:
            connector = get_connector(connection.connector_id)
            metadata = await connector.get_metadata(connection.config)

            # Update or create metadata
            existing_metadata = await self.metadata_repo.get_by_connection_id(connection_id)
            if existing_metadata:
                await self.metadata_repo.update(
                    existing_metadata.id,
                    tables=metadata.get("tables", []),
                    schemas=metadata.get("schemas", []),
                    last_metadata_update=datetime.now(timezone.utc),
                )
            else:
                await self.metadata_repo.create(
                    connection_id=connection_id,
                    tables=metadata.get("tables", []),
                    schemas=metadata.get("schemas", []),
                    last_metadata_update=datetime.now(timezone.utc),
                )

            # Update connection
            now = datetime.now(timezone.utc)
            next_sync = await self._calculate_next_sync(connection.sync_frequency, now)
            await self.connection_repo.update(
                connection_id,
                last_sync=now,
                next_sync=next_sync,
                last_metadata_update=now,
                status="active",
                error=None,
            )
            await self.db.commit()

            # === Notify AI Service for embedding generation ===
            try:
                # Get all spaces linked to this connection
                spaces = await self.space_repo.get_spaces_by_connection_id(connection_id)

                logger.info(
                    "notifying_ai_service_for_connection_sync",
                    connection_id=str(connection_id),
                    space_count=len(spaces),
                )

                # Notify AI service for each space
                for space in spaces:
                    try:
                        await self.ai_client.discover_connection(
                            connection_id=connection_id, space_id=space.id, run_in_background=True
                        )
                        logger.info(
                            "ai_service_notified",
                            connection_id=str(connection_id),
                            space_id=str(space.id),
                        )
                    except Exception as space_error:
                        # Log but don't propagate - fire-and-forget per space
                        logger.warning(
                            "ai_service_notification_failed_for_space",
                            connection_id=str(connection_id),
                            space_id=str(space.id),
                            error=str(space_error),
                        )

            except Exception as e:
                # Log but don't propagate - fire-and-forget
                logger.error(
                    "ai_service_notification_failed",
                    connection_id=str(connection_id),
                    error=str(e),
                    exc_info=True,
                )

            return ConnectionSyncResponse(
                success=True, last_sync=now, message="Sync completed successfully"
            )
        except Exception as e:
            await self.connection_repo.update(
                connection_id,
                status="error",
                error={"message": str(e), "timestamp": datetime.now(timezone.utc).isoformat()},
            )
            await self.db.commit()
            return ConnectionSyncResponse(success=False, message=f"Sync failed: {str(e)}")

    async def get_metadata(self, connection_id: UUID, user: User) -> ConnectionMetadataResponse:
        """
        Get connection metadata.

        Args:
            connection_id: Connection ID
            user: Current user

        Returns:
            ConnectionMetadataResponse: Metadata

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
        """
        connection = await self.connection_repo.get_by_id(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        if connection.created_by != user.id:
            raise ForbiddenError("Access denied to this connection")

        metadata = await self.metadata_repo.get_by_connection_id(connection_id)
        if not metadata:
            return ConnectionMetadataResponse(tables=[], schemas=[])

        tables = [
            (
                TableMetadataSchema(**table)
                if isinstance(table, dict)
                else TableMetadataSchema.model_validate(table)
            )
            for table in (metadata.tables or [])
        ]

        return ConnectionMetadataResponse(
            tables=tables,
            schemas=metadata.schemas or [],
            last_metadata_update=metadata.last_metadata_update,
        )

    async def update_metadata(
        self, connection_id: UUID, user: User, metadata_update: dict
    ) -> ConnectionMetadataResponse:
        """
        Update connection metadata (e.g., column tags, descriptions).

        Args:
            connection_id: Connection ID
            user: Current user
            metadata_update: Partial metadata to update

        Returns:
            ConnectionMetadataResponse: Updated metadata

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
        """
        connection = await self.connection_repo.get_by_id(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        if connection.created_by != user.id:
            raise ForbiddenError("Access denied to this connection")

        # Get existing metadata
        existing_metadata = await self.metadata_repo.get_by_connection_id(connection_id)
        if not existing_metadata:
            raise NotFoundError("Connection metadata not found")

        # Merge the update with existing metadata
        update_data = {}
        if "tables" in metadata_update:
            update_data["tables"] = metadata_update["tables"]
        if "schemas" in metadata_update:
            update_data["schemas"] = metadata_update["schemas"]
        
        # Update last_metadata_update timestamp
        update_data["last_metadata_update"] = datetime.now(timezone.utc)

        # Update metadata
        await self.metadata_repo.update(existing_metadata.id, **update_data)
        await self.db.commit()

        # Return updated metadata
        return await self.get_metadata(connection_id, user)

    async def get_tables(self, connection_id: UUID, user: User) -> List[TableMetadataSchema]:
        """
        Get connection tables.

        Args:
            connection_id: Connection ID
            user: Current user

        Returns:
            List[TableMetadataSchema]: List of tables

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
        """
        metadata_response = await self.get_metadata(connection_id, user)
        return metadata_response.tables

    async def get_schemas(self, connection_id: UUID, user: User) -> List[str]:
        """
        Get connection schemas.

        Args:
            connection_id: Connection ID
            user: Current user

        Returns:
            List[str]: List of schemas

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
        """
        metadata_response = await self.get_metadata(connection_id, user)
        return metadata_response.schemas

    async def get_status(self, connection_id: UUID, user: User) -> ConnectionStatusResponse:
        """
        Get connection status.

        Args:
            connection_id: Connection ID
            user: Current user

        Returns:
            ConnectionStatusResponse: Status

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
        """
        connection = await self.connection_repo.get_by_id(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        if connection.created_by != user.id:
            raise ForbiddenError("Access denied to this connection")

        return ConnectionStatusResponse(
            status=connection.status,
            last_sync=connection.last_sync,
            next_sync=connection.next_sync,
            error=connection.error,
            is_healthy=connection.status == "active" and connection.error is None,
        )

    async def validate_connection(
        self, connection_id: UUID, user: User
    ) -> ConnectionValidateResponse:
        """
        Validate connection configuration.

        Args:
            connection_id: Connection ID
            user: Current user

        Returns:
            ConnectionValidateResponse: Validation result

        Raises:
            NotFoundError: If connection not found
            ForbiddenError: If user doesn't have access
        """
        connection = await self.connection_repo.get_by_id(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        if connection.created_by != user.id:
            raise ForbiddenError("Access denied to this connection")

        errors = []
        if not connection.config:
            errors.append("Configuration is missing")
        if not connection.connector_id:
            errors.append("Connector ID is missing")

        try:
            _ = get_connector(connection.connector_id)
        except Exception as e:
            errors.append(f"Invalid connector: {str(e)}")

        if errors:
            return ConnectionValidateResponse(
                valid=False, message="Validation failed", errors=errors
            )

        return ConnectionValidateResponse(valid=True, message="Connection is valid")
