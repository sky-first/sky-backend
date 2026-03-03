"""Enterprise Graph API router."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.user import User
from src.schemas.enterprise_graph import (
    EnterpriseGraphDataResponse,
    EnterpriseGraphEdgeCreate,
    EnterpriseGraphEdgeResponse,
    EnterpriseGraphEdgeUpdate,
    EnterpriseGraphNodeCreate,
    EnterpriseGraphNodeResponse,
    EnterpriseGraphNodeUpdate,
)
from src.services.enterprise_graph import EnterpriseGraphService

router = APIRouter()


def get_service(db: AsyncSession = Depends(get_db)) -> EnterpriseGraphService:
    return EnterpriseGraphService(db)


@router.get("", response_model=EnterpriseGraphDataResponse)
async def get_graph(
    current_user: User = Depends(get_current_user),
    service: EnterpriseGraphService = Depends(get_service),
) -> EnterpriseGraphDataResponse:
    """Get the full enterprise graph (all nodes and edges)."""
    return await service.get_graph_data()


# ── Node endpoints ──────────────────────────────────────────────────────────

@router.post("/nodes", response_model=EnterpriseGraphNodeResponse, status_code=201)
async def create_node(
    body: EnterpriseGraphNodeCreate,
    current_user: User = Depends(get_current_user),
    service: EnterpriseGraphService = Depends(get_service),
) -> EnterpriseGraphNodeResponse:
    """Create a new node in the enterprise graph."""
    return await service.create_node(body)


@router.put("/nodes/{node_id}", response_model=EnterpriseGraphNodeResponse)
async def update_node(
    node_id: UUID,
    body: EnterpriseGraphNodeUpdate,
    current_user: User = Depends(get_current_user),
    service: EnterpriseGraphService = Depends(get_service),
) -> EnterpriseGraphNodeResponse:
    """Update an existing node."""
    return await service.update_node(node_id, body)


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(
    node_id: UUID,
    current_user: User = Depends(get_current_user),
    service: EnterpriseGraphService = Depends(get_service),
) -> None:
    """Delete a node and all its connected edges."""
    await service.delete_node(node_id)


# ── Edge endpoints ──────────────────────────────────────────────────────────

@router.post("/edges", response_model=EnterpriseGraphEdgeResponse, status_code=201)
async def create_edge(
    body: EnterpriseGraphEdgeCreate,
    current_user: User = Depends(get_current_user),
    service: EnterpriseGraphService = Depends(get_service),
) -> EnterpriseGraphEdgeResponse:
    """Create a new edge between two nodes."""
    return await service.create_edge(body)


@router.put("/edges/{edge_id}", response_model=EnterpriseGraphEdgeResponse)
async def update_edge(
    edge_id: UUID,
    body: EnterpriseGraphEdgeUpdate,
    current_user: User = Depends(get_current_user),
    service: EnterpriseGraphService = Depends(get_service),
) -> EnterpriseGraphEdgeResponse:
    """Update an existing edge."""
    return await service.update_edge(edge_id, body)


@router.delete("/edges/{edge_id}", status_code=204)
async def delete_edge(
    edge_id: UUID,
    current_user: User = Depends(get_current_user),
    service: EnterpriseGraphService = Depends(get_service),
) -> None:
    """Delete an edge."""
    await service.delete_edge(edge_id)
