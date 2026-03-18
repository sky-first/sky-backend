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
