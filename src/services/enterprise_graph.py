from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.enterprise_graph import EnterpriseGraphRepository
from src.schemas.enterprise_graph import (
    EnterpriseGraphDataResponse,
    EnterpriseGraphEdgeCreate,
    EnterpriseGraphEdgeResponse,
    EnterpriseGraphEdgeUpdate,
    EnterpriseGraphNodeCreate,
    EnterpriseGraphNodeResponse,
    EnterpriseGraphNodeUpdate,
)


class EnterpriseGraphService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = EnterpriseGraphRepository(session)

    async def get_graph_data(self) -> EnterpriseGraphDataResponse:
        nodes = await self.repository.get_all_nodes()
        edges = await self.repository.get_all_edges()
        
        return EnterpriseGraphDataResponse(
            nodes=nodes,
            edges=edges,
        )

    async def create_node(self, schema: EnterpriseGraphNodeCreate) -> EnterpriseGraphNodeResponse:
        node = await self.repository.create_node(schema)
        await self.session.commit()
        await self.session.refresh(node)
        return node

    async def update_node(
        self, node_id: UUID, schema: EnterpriseGraphNodeUpdate
    ) -> EnterpriseGraphNodeResponse:
        node = await self.repository.get_node_by_id(node_id)
        if not node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Node not found"
            )
            
        node = await self.repository.update_node(node, schema)
        await self.session.commit()
        await self.session.refresh(node)
        return node

    async def delete_node(self, node_id: UUID) -> None:
        node = await self.repository.get_node_by_id(node_id)
        if not node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Node not found"
            )
            
        await self.repository.delete_node(node)
        await self.session.commit()

    async def create_edge(self, schema: EnterpriseGraphEdgeCreate) -> EnterpriseGraphEdgeResponse:
        # Validate that source and target nodes exist
        source_node = await self.repository.get_node_by_id(schema.source)
        if not source_node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Source node {schema.source} not found"
            )
            
        target_node = await self.repository.get_node_by_id(schema.target)
        if not target_node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Target node {schema.target} not found"
            )
            
        edge = await self.repository.create_edge(schema)
        await self.session.commit()
        await self.session.refresh(edge)
        return edge

    async def update_edge(
        self, edge_id: UUID, schema: EnterpriseGraphEdgeUpdate
    ) -> EnterpriseGraphEdgeResponse:
        edge = await self.repository.get_edge_by_id(edge_id)
        if not edge:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Edge not found"
            )
            
        edge = await self.repository.update_edge(edge, schema)
        await self.session.commit()
        await self.session.refresh(edge)
        return edge

    async def delete_edge(self, edge_id: UUID) -> None:
        edge = await self.repository.get_edge_by_id(edge_id)
        if not edge:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Edge not found"
            )
            
        await self.repository.delete_edge(edge)
        await self.session.commit()
