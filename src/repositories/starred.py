"""Starred item repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.starred import StarredItem
from src.repositories.base import BaseRepository


class StarredItemRepository(BaseRepository[StarredItem]):
    """Starred item repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, StarredItem)

    async def get_by_user_and_item(
        self, user_id: UUID, item_id: UUID, item_type: str
    ) -> Optional[StarredItem]:
        """
        Get starred item by user, item ID and type.

        Args:
            user_id: User ID
            item_id: Item ID (page, space, or crew ID)
            item_type: Item type (page, space, or crew)

        Returns:
            Optional[StarredItem]: Starred item or None
        """
        result = await self.db.execute(
            select(StarredItem).where(
                StarredItem.user_id == user_id,
                StarredItem.item_id == item_id,
                StarredItem.item_type == item_type,
                StarredItem.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user(
        self, user_id: UUID, item_type: Optional[str] = None
    ) -> List[StarredItem]:
        """
        Get all starred items for a user.

        Args:
            user_id: User ID
            item_type: Optional filter by item type (page, space, or crew)

        Returns:
            List[StarredItem]: List of starred items
        """
        query = select(StarredItem).where(
            StarredItem.user_id == user_id,
            StarredItem.deleted_at.is_(None),
        )

        if item_type:
            query = query.where(StarredItem.item_type == item_type)

        query = query.order_by(StarredItem.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create_starred_item(
        self, user_id: UUID, item_id: UUID, item_type: str
    ) -> StarredItem:
        """
        Create a new starred item.

        Args:
            user_id: User ID
            item_id: Item ID (page, space, or crew ID)
            item_type: Item type (page, space, or crew)

        Returns:
            StarredItem: Created starred item

        Raises:
            ValueError: If a non-deleted starred item already exists
        """
        # Check if a non-deleted starred item already exists
        existing = await self.get_by_user_and_item(user_id, item_id, item_type)
        if existing:
            raise ValueError(
                f"Item {item_id} of type {item_type} is already starred by user {user_id}"
            )

        starred_item = StarredItem(
            user_id=user_id,
            item_id=item_id,
            item_type=item_type,
        )
        self.db.add(starred_item)
        await self.db.flush()
        await self.db.refresh(starred_item)
        return starred_item
