"""Enterprise Relationship management service."""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.enterprise_relationship import EnterpriseRelationship
from src.models.user import User
from src.repositories.enterprise_relationship import EnterpriseRelationshipRepository
from src.schemas.enterprise_relationship import EnterpriseRelationshipCreate

logger = logging.getLogger(__name__)


class EnterpriseRelationshipService:
    """Enterprise Relationship management service."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.relationship_repo = EnterpriseRelationshipRepository(db)

    async def list_relationships(self, user: User) -> list[EnterpriseRelationship]:
        """List all relationships for a user."""
        return await self.relationship_repo.get_by_user(user.id)

    async def create_relationship(
        self, data: EnterpriseRelationshipCreate, user: User
    ) -> EnterpriseRelationship:
        """Create a new relationship."""
        # Convert sources to dict for JSON storage
        sources_data = [s.model_dump() for s in data.sources]

        relationship = await self.relationship_repo.create(
            name=data.name,
            description=data.description,
            sources=sources_data,
            target_id=data.target_id,
            target_type=data.target_type,
            target_details=data.target_details,
            relationship_type=data.relationship_type,
            created_by=user.id,
        )
        await self.db.commit()
        await self.db.refresh(relationship)

        # Notify AI Service for Knowledge Graph ingestion
        try:
            from src.ai.http_client import AIServiceHTTPClient

            ai_client = AIServiceHTTPClient()

            # The table is strictly per-user (user_enterprise_relationships)
            # so the embedding belongs to the creator. owner_user_id lets the
            # RAG filter return only this user's relationships in Personal
            # mode; space_id/crew_id stay NULL.
            payload = {
                "id": str(relationship.id),
                "entity_type": "enterprise_graph_node",
                "name": relationship.name,
                "description": relationship.description,
                "sources": sources_data,
                "target_id": str(relationship.target_id),
                "target_type": relationship.target_type,
                "target_details": relationship.target_details,
                "relationship_type": relationship.relationship_type,
                "space_id": None,
                "crew_id": None,
                "owner_user_id": str(relationship.created_by),
            }
            await ai_client.ingest_knowledge_graph(payload)
        except Exception as e:
            logger.error(f"Failed to trigger AI ingestion for relationship {relationship.id}: {e}")

        return relationship

    async def update_relationship(
        self, relationship_id: UUID, data: EnterpriseRelationshipCreate, user: User
    ) -> EnterpriseRelationship:
        """Update an existing relationship."""
        relationship = await self.relationship_repo.get_by_id(relationship_id)
        if not relationship:
            raise NotFoundError("Relationship not found")

        if relationship.created_by != user.id:
            raise ForbiddenError("You don't have permission to update this relationship")

        sources_data = [s.model_dump() for s in data.sources]

        updated_relationship = await self.relationship_repo.update(
            relationship_id,
            name=data.name,
            description=data.description,
            sources=sources_data,
            target_id=data.target_id,
            target_type=data.target_type,
            target_details=data.target_details,
            relationship_type=data.relationship_type,
        )
        await self.db.commit()
        if updated_relationship:
            await self.db.refresh(updated_relationship)

            # Notify AI Service for Knowledge Graph ingestion (Update)
            try:
                from src.ai.http_client import AIServiceHTTPClient

                ai_client = AIServiceHTTPClient()

                payload = {
                    "id": str(updated_relationship.id),
                    "entity_type": "enterprise_graph_node",
                    "name": updated_relationship.name,
                    "description": updated_relationship.description,
                    "sources": sources_data,
                    "target_id": str(updated_relationship.target_id),
                    "target_type": updated_relationship.target_type,
                    "target_details": updated_relationship.target_details,
                    "relationship_type": updated_relationship.relationship_type,
                    "space_id": None,
                    "crew_id": None,
                    "owner_user_id": str(updated_relationship.created_by),
                }
                await ai_client.ingest_knowledge_graph(payload)
            except Exception as e:
                logger.error(
                    f"Failed to trigger AI ingestion for updated relationship {updated_relationship.id}: {e}"
                )

        return updated_relationship

    async def delete_relationship(self, relationship_id: UUID, user: User) -> None:
        """Delete a relationship."""
        relationship = await self.relationship_repo.get_by_id(relationship_id)
        if not relationship:
            raise NotFoundError("Relationship not found")

        if relationship.created_by != user.id:
            raise ForbiddenError("You don't have permission to delete this relationship")

        await self.relationship_repo.delete(relationship_id)
        await self.db.commit()
