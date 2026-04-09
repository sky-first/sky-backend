"""Connection endpoints."""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.repositories.crew import CrewMemberRepository
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.connection import (
    ConnectionCreate,
    ConnectionMetadataResponse,
    ConnectionMetrics,
    ConnectionResponse,
    ConnectionStatusResponse,
    ConnectionSyncResponse,
    ConnectionTestResponse,
    ConnectionUpdate,
    ConnectionValidateResponse,
    TableMetadataSchema,
)
from src.services.connection_service import ConnectionService
from src.services.rbac_service import RBACService

router = APIRouter()

_logger = logging.getLogger(__name__)
_logger.info("🔴 [CONNECTIONS ROUTER] Module loaded, DELETE endpoint will be registered")


async def _resolve_user_crew_ids(db: AsyncSession, user_id: UUID, space_id: UUID) -> List[str]:
    """
    Resolve crew_ids for the current user in a given space.
    Mirrors the logic used by AIService.process_query to keep permissions consistent.
    """
    repo = CrewMemberRepository(db)
    crew_ids = await repo.get_crew_ids_by_user_and_space(user_id=user_id, space_id=space_id)
    return [str(cid) for cid in crew_ids]


@router.get(
    "",
    response_model=List[ConnectionResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="List connections",
    description="Get list of data connections",
)
async def list_connections(
    status: Optional[str] = Query(None, description="Filter by status (active, inactive, error)"),
    connector_id: Optional[str] = Query(None, description="Filter by connector type"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[ConnectionResponse]:
    """
    List connections.

    Args:
        status: Optional status filter
        connector_id: Optional connector filter
        skip: Number of records to skip
        limit: Maximum number of records to return
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[ConnectionResponse]: List of connections
    """
    # Phase 0 RBAC: gate the read at the route, not just at the service-layer
    # `created_by` filter (closes SIGN_OFF_TRACKER X.18 cross-space leak risk).
    await RBACService(db).assert_permission(current_user, "viewConnections")
    connection_service = ConnectionService(db)
    return await connection_service.list_connections(
        current_user, status=status, connector_id=connector_id, skip=skip, limit=limit
    )


@router.get(
    "/{connection_id}",
    response_model=ConnectionResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get connection",
    description="Get connection by ID",
)
async def get_connection(
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConnectionResponse:
    """
    Get connection by ID.

    Args:
        connection_id: Connection ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectionResponse: Connection data
    """
    await RBACService(db).assert_permission(
        current_user, "viewConnections", connection_id=connection_id
    )
    connection_service = ConnectionService(db)
    return await connection_service.get_connection(connection_id, current_user)


@router.post(
    "",
    response_model=ConnectionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Create connection",
    description="Create a new data connection",
)
async def create_connection(
    connection_data: ConnectionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConnectionResponse:
    """
    Create a new connection.

    Args:
        connection_data: Connection creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectionResponse: Created connection
    """
    rbac = RBACService(db)
    await rbac.assert_permission(current_user, "manageConnections")

    connection_service = ConnectionService(db)
    return await connection_service.create_connection(current_user, connection_data)


@router.delete(
    "/{connection_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete connection",
    description="Delete connection",
)
async def delete_connection(
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete connection.

    Args:
        connection_id: Connection ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    import logging

    logger = logging.getLogger(__name__)
    logger.info(
        f"🔴 [DELETE API] Delete connection endpoint called: connection_id={connection_id}, user_id={current_user.id}"
    )

    try:
        rbac = RBACService(db)
        await rbac.assert_permission(current_user, "manageConnections", connection_id=connection_id)

        connection_service = ConnectionService(db)
        await connection_service.delete_connection(connection_id, current_user)
        logger.info(
            f"🔴 [DELETE API] Connection {connection_id} deleted successfully by user {current_user.id}"
        )
        return SuccessResponse(message="Connection deleted successfully")
    except Exception as e:
        logger.error(
            f"🔴 [DELETE API] Error deleting connection {connection_id}: {str(e)}",
            exc_info=True,
        )
        raise


@router.put(
    "/{connection_id}",
    response_model=ConnectionResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update connection",
    description="Update connection information",
)
async def update_connection(
    connection_id: UUID,
    connection_data: ConnectionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConnectionResponse:
    """
    Update connection.

    Args:
        connection_id: Connection ID
        connection_data: Connection update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectionResponse: Updated connection
    """
    rbac = RBACService(db)
    await rbac.assert_permission(current_user, "connections.edit", connection_id=connection_id)

    connection_service = ConnectionService(db)
    return await connection_service.update_connection(connection_id, current_user, connection_data)


@router.post(
    "/{connection_id}/test",
    response_model=ConnectionTestResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Test connection",
    description="Test data connection",
)
async def test_connection(
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConnectionTestResponse:
    """
    Test connection.

    Args:
        connection_id: Connection ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectionTestResponse: Test result
    """
    connection_service = ConnectionService(db)
    return await connection_service.test_connection(connection_id, current_user)


@router.post(
    "/{connection_id}/sync",
    response_model=ConnectionSyncResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Sync connection",
    description="Force sync connection metadata",
)
async def sync_connection(
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConnectionSyncResponse:
    """
    Sync connection metadata.

    Args:
        connection_id: Connection ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectionSyncResponse: Sync result
    """
    connection_service = ConnectionService(db)
    return await connection_service.sync_connection(connection_id, current_user)


@router.get(
    "/{connection_id}/metadata",
    response_model=ConnectionMetadataResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get connection metadata",
    description="Get connection metadata (tables, schemas, etc)",
)
async def get_connection_metadata(
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConnectionMetadataResponse:
    """
    Get connection metadata.

    Args:
        connection_id: Connection ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectionMetadataResponse: Connection metadata
    """
    await RBACService(db).assert_permission(
        current_user, "viewConnections", connection_id=connection_id
    )
    connection_service = ConnectionService(db)
    return await connection_service.get_metadata(connection_id, current_user)


@router.put(
    "/{connection_id}/metadata",
    response_model=ConnectionMetadataResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update connection metadata",
    description="Update connection metadata (e.g., column tags, descriptions)",
)
async def update_connection_metadata(
    connection_id: UUID,
    metadata_update: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConnectionMetadataResponse:
    """
    Update connection metadata.

    Args:
        connection_id: Connection ID
        metadata_update: Partial metadata update
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectionMetadataResponse: Updated connection metadata
    """
    connection_service = ConnectionService(db)
    return await connection_service.update_metadata(connection_id, current_user, metadata_update)


@router.get(
    "/{connection_id}/tables",
    response_model=List[TableMetadataSchema],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get connection tables",
    description="Get list of tables in connection",
)
async def get_connection_tables(
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Get connection tables.

    Args:
        connection_id: Connection ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[TableMetadataSchema]: List of tables
    """
    await RBACService(db).assert_permission(
        current_user, "viewConnections", connection_id=connection_id
    )
    connection_service = ConnectionService(db)
    tables = await connection_service.get_tables(connection_id, current_user)
    return tables


@router.get(
    "/{connection_id}/schemas",
    response_model=List[str],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get connection schemas",
    description="Get list of schemas in connection",
)
async def get_connection_schemas(
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[str]:
    """
    Get connection schemas.

    Args:
        connection_id: Connection ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[str]: List of schemas
    """
    await RBACService(db).assert_permission(
        current_user, "viewConnections", connection_id=connection_id
    )
    connection_service = ConnectionService(db)
    return await connection_service.get_schemas(connection_id, current_user)


@router.get(
    "/{connection_id}/status",
    response_model=ConnectionStatusResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get connection status",
    description="Get connection status information",
)
async def get_connection_status(
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConnectionStatusResponse:
    """
    Get connection status.

    Args:
        connection_id: Connection ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectionStatusResponse: Connection status
    """
    await RBACService(db).assert_permission(
        current_user, "viewConnections", connection_id=connection_id
    )
    connection_service = ConnectionService(db)
    return await connection_service.get_status(connection_id, current_user)


@router.get(
    "/{connection_id}/metrics",
    response_model=ConnectionMetrics,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get connection metrics",
    description="Get aggregated usage metrics for a connection (queries, latency, uptime, active users)",
)
async def get_connection_metrics(
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConnectionMetrics:
    """
    Get connection metrics.

    Calculates real metrics from sync_logs and ai_queries tables.
    Returns zeros for metrics that haven't been recorded yet.
    """
    await RBACService(db).assert_permission(
        current_user, "viewConnections", connection_id=connection_id
    )
    connection_service = ConnectionService(db)
    return await connection_service.get_metrics(connection_id, current_user)


@router.post(
    "/{connection_id}/validate",
    response_model=ConnectionValidateResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Validate connection",
    description="Validate connection configuration",
)
async def validate_connection(
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConnectionValidateResponse:
    """
    Validate connection configuration.

    Args:
        connection_id: Connection ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectionValidateResponse: Validation result
    """
    connection_service = ConnectionService(db)
    return await connection_service.validate_connection(connection_id, current_user)


@router.get(
    "/{connection_id}/ai/catalog/status",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get AI catalog status",
    description="Proxy to AI Engine metadata-status for this connection",
)
async def get_ai_catalog_status(
    connection_id: UUID,
    space_id: str = Query(..., description="Space ID used by AI Engine"),
    ttl_seconds: Optional[int] = Query(
        None, ge=0, description="Override TTL (seconds) for AI metadata freshness check"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    # Ensure user has access to this connection
    await RBACService(db).assert_permission(
        current_user, "viewConnections", connection_id=connection_id
    )
    connection_service = ConnectionService(db)
    await connection_service.get_connection(connection_id, current_user)

    # Backend is the source-of-truth for metadata in `connection_metadata`.
    # Keep this endpoint stable for the frontend by returning a small status payload.
    metadata = await connection_service.metadata_repo.get_by_connection_id(
        connection_id
    )  # type: ignore[attr-defined]
    has_tables = bool(metadata and getattr(metadata, "tables", None))
    return {
        "connection_id": str(connection_id),
        "space_id": space_id,
        "has_tables": has_tables,
        "table_count": len(getattr(metadata, "tables", []) or []) if metadata else 0,
        "last_metadata_update": (
            metadata.last_metadata_update.isoformat()
            if metadata and metadata.last_metadata_update
            else None
        ),
        "ttl_seconds": ttl_seconds,
        "source": "backend_connection_metadata",
    }


@router.post(
    "/{connection_id}/ai/catalog/refresh",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Refresh AI catalog",
    description="Proxy to AI Engine discover for this connection",
)
async def refresh_ai_catalog(
    connection_id: UUID,
    space_id: str = Query(..., description="Space ID used by AI Engine"),
    run_in_background: bool = Query(
        True, description="If true, triggers discovery in background on AI Engine"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    # Ensure user has access to this connection
    connection_service = ConnectionService(db)
    await connection_service.get_connection(connection_id, current_user)

    # For this project, "AI catalog refresh" is equivalent to syncing connection metadata from the connector
    # into the backend `connection_metadata` table.
    # We ignore run_in_background for now and perform the sync inline (frontend already shows loading).
    sync = await connection_service.sync_connection(connection_id, current_user)
    metadata = await connection_service.metadata_repo.get_by_connection_id(
        connection_id
    )  # type: ignore[attr-defined]
    return {
        "success": bool(getattr(sync, "success", True)),
        "message": getattr(sync, "message", "Sync completed"),
        "connection_id": str(connection_id),
        "space_id": space_id,
        "has_tables": bool(metadata and getattr(metadata, "tables", None)),
        "table_count": len(getattr(metadata, "tables", []) or []) if metadata else 0,
        "last_metadata_update": (
            metadata.last_metadata_update.isoformat()
            if metadata and metadata.last_metadata_update
            else None
        ),
        "source": "backend_connection_metadata",
    }


@router.get(
    "/{connection_id}/ai/catalog/tables",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="List AI catalog tables",
    description="Proxy to AI Engine tables catalog for this connection",
)
async def list_ai_catalog_tables(
    connection_id: UUID,
    space_id: str = Query(..., description="Space ID used by AI Engine"),
    is_personal: bool = Query(
        False,
        description="If true, AI Engine returns tables across all crews the user belongs to (personal mode)",
    ),
    crew_ids: Optional[List[str]] = Query(
        None,
        description="Optional explicit crew_ids filter. If omitted, backend resolves crews from membership.",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    # Ensure user has access to this connection
    await RBACService(db).assert_permission(
        current_user, "viewConnections", connection_id=connection_id
    )
    connection_service = ConnectionService(db)
    await connection_service.get_connection(connection_id, current_user)

    resolved_crew_ids = crew_ids
    if resolved_crew_ids is None and not is_personal:
        # In collaborative mode, default to user's crews in this space.
        from uuid import UUID as UUIDType

        resolved_crew_ids = await _resolve_user_crew_ids(
            db=db,
            user_id=current_user.id,
            space_id=UUIDType(space_id),
        )

    metadata = await connection_service.metadata_repo.get_by_connection_id(
        connection_id
    )  # type: ignore[attr-defined]
    return {
        "connection_id": str(connection_id),
        "space_id": space_id,
        "tables": metadata.tables if metadata and getattr(metadata, "tables", None) else [],
        "total_tables": len(getattr(metadata, "tables", []) or []) if metadata else 0,
        "source": "backend_connection_metadata",
        "note": "Crew-level filtering is enforced by backend permissions when querying; catalog listing is best-effort.",
    }
