"""Sync worker for data connections."""

import logging

from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def sync_connection(self, connection_id: str):
    """
    Sync data connection.

    Args:
        connection_id: Connection ID

    Returns:
        dict: Sync result
    """
    try:
        # TODO: Implement sync logic
        logger.info(f"Syncing connection {connection_id}")
        return {"status": "success", "connection_id": connection_id}
    except Exception as exc:
        logger.error(f"Sync failed for connection {connection_id}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)


@celery_app.task
def sync_connection_metadata(connection_id: str):
    """
    Sync connection metadata.

    Args:
        connection_id: Connection ID

    Returns:
        dict: Sync result
    """
    import asyncio
    from src.config.database import AsyncSessionLocal
    from src.repositories.connection import ConnectionRepository, ConnectionMetadataRepository
    from src.services.connector_service import ConnectorService
    from src.utils.encryption import decrypt_dict
    from src.config.settings import settings
    from uuid import UUID

    async def _sync():
        async with AsyncSessionLocal() as db:
            connection_repo = ConnectionRepository(db)
            metadata_repo = ConnectionMetadataRepository(db)
            ConnectorService(db)

            # 1. Get connection and decrypted config
            connection = await connection_repo.get_by_id(UUID(connection_id))
            if not connection:
                logger.error(f"Connection {connection_id} not found")
                return {"status": "error", "message": "Connection not found"}

            config = decrypt_dict(connection.config, settings.ENCRYPTION_KEY)

            # 2. Extract metadata from source
            # We need to instantiate the specific connector based on connection.connector_id
            # For now, we'll manually check, but ideally this should be a factory in ConnectorService
            if connection.connector_id == 'postgresql':
                from src.connectors.postgresql import PostgreSQLConnector
                connector = PostgreSQLConnector()
                try:
                    source_metadata = await connector.get_metadata(config)
                except Exception as e:
                    logger.error(f"Failed to extract metadata from source: {e}")
                    return {"status": "error", "message": str(e)}
            else:
                # Fallback/TODO for other connectors
                logger.warning(f"Metadata sync not implemented for {connection.connector_id}")
                return {"status": "skipped", "message": "Connector not supported"}

            # 3. Get existing metadata to preserve custom fields (health, tags, usage)
            existing_metadata = await metadata_repo.get_by_connection_id(connection.id)
            existing_tables_map = {}
            if existing_metadata and existing_metadata.tables:
                for table in existing_metadata.tables:
                    # Key by schema.name or just name
                    key = f"{table.get('schema')}.{table.get('name')}" if table.get('schema') else table.get('name')
                    existing_tables_map[key] = table

            # 4. Merge metadata
            merged_tables = []
            for table in source_metadata.get("tables", []):
                key = f"{table.get('schema')}.{table.get('name')}" if table.get('schema') else table.get('name')
                existing_table = existing_tables_map.get(key)

                if existing_table:
                    # Preserve existing fields
                    table["health"] = existing_table.get("health", "Healthy")
                    table["usage_score"] = existing_table.get("usage_score", 0)
                    table["tags"] = existing_table.get("tags", [])
                    # Update last_updated if row count changed significantly?
                    # For now just keep it simple
                else:
                    # New table defaults
                    table["health"] = "Healthy"
                    table["usage_score"] = 0
                    table["tags"] = []

                merged_tables.append(table)

            # 5. Save metadata
            if existing_metadata:
                await metadata_repo.update(
                    existing_metadata.id,
                    tables=merged_tables,
                    schemas=source_metadata.get("schemas", [])
                )
            else:
                await metadata_repo.create(
                    connection_id=connection.id,
                    tables=merged_tables,
                    schemas=source_metadata.get("schemas", [])
                )

            logger.info(f"Syncing connection metadata {connection_id} complete")
            return {"status": "success", "connection_id": connection_id}

    # Run async function in sync celery task
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(_sync())
