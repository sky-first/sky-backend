"""Connection endpoints."""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import ForbiddenError
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
from src.schemas.connection import _URL_CONFIG_KEYS_BY_CONNECTOR
from src.security.filesystem_paths import UnsafePathError, validate_sqlite_path
from src.security.url_allowlist import UnsafeURLError, validate_outbound_url
from src.services.connection_service import ConnectionService
from src.services.rbac_service import RBACService


def _reject_unsafe_paths_or_400(connector_id: str, config: Optional[Dict[str, Any]]) -> None:
    """Edge-guard for local-filesystem misconfigs (path traversal).
    Red-team finding CR-003 (2026-04-23)."""
    from fastapi import HTTPException
    if connector_id != "sqlite":
        return
    for key in ("database_path", "path"):
        val = (config or {}).get(key)
        if val is None:
            continue
        try:
            validate_sqlite_path(str(val))
        except UnsafePathError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key}: {exc}",
            )


def _reject_unsafe_urls_or_400(connector_id: str, config: Optional[Dict[str, Any]]) -> None:
    """Edge-guard for SSRF-style misconfigs. Red-team CR-002 (2026-04-23):
    the REST connector accepted IMDS / private / non-HTTP URLs and would
    then fetch them with server creds. We refuse at create/update time.
    """
    from fastapi import HTTPException
    keys = _URL_CONFIG_KEYS_BY_CONNECTOR.get(connector_id or "", ())
    if not keys or not config:
        return
    for key in keys:
        val = config.get(key)
        if val is None:
            continue
        try:
            validate_outbound_url(str(val))
        except UnsafeURLError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key}: {exc}",
            )

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
    await RBACService(db).assert_permission(current_user, "connections.view")
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
        current_user, "connections.view", connection_id=connection_id
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
    # Demo guests use a shared, pre-provisioned synthetic dataset —
    # they cannot create new Connections (would tunnel into real BYO
    # databases at the visitor's expense, and the cleanup cron would
    # leave orphan rows after TTL expiry).
    if getattr(current_user, "is_demo", False):
        raise ForbiddenError(
            "Demo guests cannot create connections. Sign up for a "
            "workspace to wire your own data sources."
        )
    rbac = RBACService(db)
    # Belt-and-suspenders: assert BOTH connections.create and connections.edit.
    # Pre-A1 the catalog only differentiated edit, but Lucas's spec
    # (2026-04-29 demo review) draws a sharper line — only owner/admin
    # mint a Connection, editors/viewers are read-only even when
    # linked to a Space. Asserting both keys means a future role tweak
    # that flips one but forgets the other still denies.
    await rbac.assert_permission(current_user, "connections.create")
    await rbac.assert_permission(current_user, "connections.edit")

    _reject_unsafe_urls_or_400(connection_data.connector_id, connection_data.config)
    _reject_unsafe_paths_or_400(connection_data.connector_id, connection_data.config)

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
        # Demo guests are admins of their own demo Space (so they can
        # do every other Space-management action), but the 5 demo
        # Connections themselves are SHARED across every visitor —
        # one guest deleting one would break the dataset for the
        # entire public demo. Hard-deny the action up front, before
        # the standard mutation guard, so a curious visitor can't
        # take down the demo for everyone else.
        if getattr(current_user, "is_demo", False):
            raise ForbiddenError(
                "Demo guests cannot delete connections. The synthetic "
                "dataset is shared across every visitor."
            )
        rbac = RBACService(db)
        await rbac.assert_permission(current_user, "connections.edit", connection_id=connection_id)

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
    # Demo guests cannot mutate the shared synthetic Connections.
    # Same reasoning as the DELETE handler above — see comment there.
    if getattr(current_user, "is_demo", False):
        raise ForbiddenError(
            "Demo guests cannot edit connections. The synthetic "
            "dataset is shared across every visitor."
        )
    rbac = RBACService(db)
    await rbac.assert_permission(current_user, "connections.edit", connection_id=connection_id)

    # Update may switch the config URL — re-validate before the service
    # touches anything. We look up the connector_id from the existing
    # row since ConnectionUpdate.connector_id is optional by design.
    connection_service = ConnectionService(db)
    if connection_data.config is not None:
        existing = await connection_service.get_connection(connection_id, current_user)
        _reject_unsafe_urls_or_400(existing.connector_id, connection_data.config)
        _reject_unsafe_paths_or_400(existing.connector_id, connection_data.config)
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

    SECURITY (Lucas's 2026-05-05 audit): without an explicit RBAC
    check here an attacker could enumerate connection UUIDs and
    trigger credential probes against arbitrary tenants' databases.
    Gate on ``connections.test`` for the specific connection.

    Args:
        connection_id: Connection ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectionTestResponse: Test result
    """
    await RBACService(db).assert_permission(
        current_user, "connections.test", connection_id=connection_id
    )
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

    SECURITY: gate on ``connections.sync`` so tenant-foreign callers
    can't trigger schema discovery / metadata refresh against arbitrary
    connection IDs (audit 2026-05-05).

    Args:
        connection_id: Connection ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectionSyncResponse: Sync result
    """
    await RBACService(db).assert_permission(
        current_user, "connections.sync", connection_id=connection_id
    )
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
        current_user, "connections.view", connection_id=connection_id
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

    SECURITY: gate on ``connections.edit``. The endpoint accepts an
    unbounded ``Dict[str, Any]`` and forwards it to the service —
    without a permission check, any authenticated caller could mutate
    metadata on connections owned by other tenants (audit 2026-05-05).

    Args:
        connection_id: Connection ID
        metadata_update: Partial metadata update
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectionMetadataResponse: Updated connection metadata
    """
    await RBACService(db).assert_permission(
        current_user, "connections.edit", connection_id=connection_id
    )
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
        current_user, "connections.view", connection_id=connection_id
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
        current_user, "connections.view", connection_id=connection_id
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
        current_user, "connections.view", connection_id=connection_id
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
        current_user, "connections.view", connection_id=connection_id
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

    SECURITY: gate on ``connections.view`` so this endpoint can't be
    abused for IDOR reconnaissance (audit 2026-05-05).

    Args:
        connection_id: Connection ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        ConnectionValidateResponse: Validation result
    """
    await RBACService(db).assert_permission(
        current_user, "connections.view", connection_id=connection_id
    )
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
        current_user, "connections.view", connection_id=connection_id
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
    # SECURITY: explicit RBAC gate. The previous code relied on
    # ``get_connection`` raising 403/404 internally — fragile if a
    # future refactor changes that contract (audit 2026-05-05).
    await RBACService(db).assert_permission(
        current_user, "connections.sync", connection_id=connection_id
    )
    connection_service = ConnectionService(db)
    await connection_service.get_connection(connection_id, current_user)

    # For this project, "AI catalog refresh" is equivalent to syncing connection metadata from the connector
    # into the backend `connection_metadata` table.
    # We ignore run_in_background for now and perform the sync inline (frontend already shows loading).
    sync = await connection_service.sync_connection(connection_id, current_user)

    # Robust discovery (2026-06-19): sync_connection notifies the AI engine
    # with run_in_background=True (fire-and-forget). Under load that background
    # discover can silently fail to generate the table embeddings, leaving the
    # AI /query path with "No metadata found — execute table discovery first"
    # for a freshly-linked connection. This endpoint is an explicit operator
    # "refresh catalog" action (the FE already shows a loading state and it is
    # NOT the hot query path), so force a SYNCHRONOUS discover for THIS space.
    # That makes "link a connection to a space → it is immediately queryable"
    # hold reliably, instead of best-effort. Never fatal: a failure here still
    # returns the synced metadata, and the AI side can be re-discovered.
    try:
        await connection_service.ai_client.discover_connection(
            connection_id=str(connection_id),
            space_id=UUID(space_id),
            run_in_background=False,
        )
    except Exception as _discover_err:  # pragma: no cover — best-effort hardening
        _logger.warning(
            "synchronous AI discover after catalog refresh failed for "
            "connection=%s space=%s: %s",
            connection_id,
            space_id,
            _discover_err,
        )

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
        current_user, "connections.view", connection_id=connection_id
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
