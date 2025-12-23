"""Connection endpoints."""

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.ai.http_client import AIServiceHTTPClient
from src.models.user import User
from src.repositories.crew import CrewMemberRepository
from src.schemas.common import ErrorResponse, SuccessResponse
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
from src.services.connection_service import ConnectionService

router = APIRouter()

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
    connection_service = ConnectionService(db)
    return await connection_service.create_connection(current_user, connection_data)


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
    connection_service = ConnectionService(db)
    return await connection_service.update_connection(connection_id, current_user, connection_data)


@router.delete(
    "/{connection_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete connection",
    description="Delete connection (soft delete)",
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
    connection_service = ConnectionService(db)
    await connection_service.delete_connection(connection_id, current_user)
    return SuccessResponse(message="Connection deleted successfully")


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
    connection_service = ConnectionService(db)
    return await connection_service.get_metadata(connection_id, current_user)


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
    connection_service = ConnectionService(db)
    return await connection_service.get_status(connection_id, current_user)


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
    connection_service = ConnectionService(db)
    await connection_service.get_connection(connection_id, current_user)

    client = AIServiceHTTPClient()
    return await client.metadata_status(
        connection_id=str(connection_id),
        space_id=space_id,
        ttl_seconds=ttl_seconds,
    )


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

    client = AIServiceHTTPClient()
    return await client.discover_connection(
        connection_id=str(connection_id),
        space_id=space_id,
        run_in_background=run_in_background,
    )


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

    client = AIServiceHTTPClient()
    return await client.list_tables(
        connection_id=str(connection_id),
        space_id=space_id,
        user_id=str(current_user.id),
        crew_ids=resolved_crew_ids,
        is_personal=is_personal,
    )

