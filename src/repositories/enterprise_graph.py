from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.enterprise_graph import EnterpriseGraphEdge, EnterpriseGraphNode
from src.schemas.enterprise_graph import (
    EnterpriseGraphEdgeCreate,
    EnterpriseGraphEdgeUpdate,
    EnterpriseGraphNodeCreate,
    EnterpriseGraphNodeUpdate,
)


class EnterpriseGraphRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all_nodes(self) -> List[EnterpriseGraphNode]:
        result = await self.session.execute(select(EnterpriseGraphNode))
        return result.scalars().all()

    async def get_node_by_id(self, node_id: UUID) -> Optional[EnterpriseGraphNode]:
        result = await self.session.execute(
            select(EnterpriseGraphNode).where(EnterpriseGraphNode.id == node_id)
        )
        return result.scalar_one_or_none()

    async def create_node(self, schema: EnterpriseGraphNodeCreate) -> EnterpriseGraphNode:
        node = EnterpriseGraphNode(**schema.model_dump())
        self.session.add(node)
        await self.session.flush()
        return node

    async def update_node(
        self, node: EnterpriseGraphNode, schema: EnterpriseGraphNodeUpdate
    ) -> EnterpriseGraphNode:
        update_data = schema.model_dump(exclude_unset=True)
        if "properties" in update_data and update_data["properties"] is not None:
            # Merge properties
            current_props = node.properties or {}
            current_props.update(update_data["properties"])
            update_data["properties"] = current_props
        
        for key, value in update_data.items():
            setattr(node, key, value)
            
        await self.session.flush()
        return node

    async def delete_node(self, node: EnterpriseGraphNode) -> None:
        await self.session.delete(node)
        await self.session.flush()

    async def get_all_edges(self) -> List[EnterpriseGraphEdge]:
        result = await self.session.execute(select(EnterpriseGraphEdge))
        return result.scalars().all()

    async def get_edge_by_id(self, edge_id: UUID) -> Optional[EnterpriseGraphEdge]:
        result = await self.session.execute(
            select(EnterpriseGraphEdge).where(EnterpriseGraphEdge.id == edge_id)
        )
        return result.scalar_one_or_none()

    async def create_edge(self, schema: EnterpriseGraphEdgeCreate) -> EnterpriseGraphEdge:
        edge = EnterpriseGraphEdge(**schema.model_dump())
        self.session.add(edge)
        await self.session.flush()
        return edge

    async def update_edge(
        self, edge: EnterpriseGraphEdge, schema: EnterpriseGraphEdgeUpdate
    ) -> EnterpriseGraphEdge:
        update_data = schema.model_dump(exclude_unset=True)
        if "properties" in update_data and update_data["properties"] is not None:
            # Merge properties
            current_props = edge.properties or {}
            current_props.update(update_data["properties"])
            update_data["properties"] = current_props
            
        for key, value in update_data.items():
            setattr(edge, key, value)
            
        await self.session.flush()
        return edge

    async def delete_edge(self, edge: EnterpriseGraphEdge) -> None:
        await self.session.delete(edge)
        await self.session.flush()
