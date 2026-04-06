"""Starred item service."""

from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import BadRequestError
from src.models.user import User
from src.repositories.starred import StarredItemRepository


class StarredItemService:
    """Starred item service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize starred item service.

        Args:
            db: Database session
        """
        self.db = db
        self.starred_repo = StarredItemRepository(db)

    async def star_item(self, user: User, item_id: UUID, item_type: str) -> None:
        """
        Star an item (page, space, or crew).

        Args:
            user: Current user
            item_id: Item ID to star
            item_type: Item type (page, space, or crew)

        Raises:
            BadRequestError: If item is already starred or invalid item type
        """
        # Validate item type
        if item_type not in ["page", "space", "crew"]:
            raise BadRequestError(f"Invalid item type: {item_type}")

        # Check if already starred
        existing = await self.starred_repo.get_by_user_and_item(user.id, item_id, item_type)
        if existing:
            # Already starred, do nothing (idempotent)
            return

        # Create starred item
        await self.starred_repo.create_starred_item(user.id, item_id, item_type)
        await self.db.commit()

    async def unstar_item(self, user: User, item_id: UUID, item_type: str) -> None:
        """
        Unstar an item (page, space, or crew).

        Args:
            user: Current user
            item_id: Item ID to unstar
            item_type: Item type (page, space, or crew)

        Raises:
            NotFoundError: If item is not starred
        """
        # Validate item type
        if item_type not in ["page", "space", "crew"]:
            raise BadRequestError(f"Invalid item type: {item_type}")

        # Find starred item
        starred_item = await self.starred_repo.get_by_user_and_item(user.id, item_id, item_type)
        if not starred_item:
            # Not starred, do nothing (idempotent)
            return

        # Soft delete
        await self.starred_repo.delete(starred_item.id)
        await self.db.commit()

    async def get_user_starred_items(self, user: User, item_type: str = None) -> List[dict]:
        """
        Get all starred items for a user.

        Args:
            user: Current user
            item_type: Optional filter by item type (page, space, or crew)

        Returns:
            List[dict]: List of starred items with item_id and item_type
        """
        starred_items = await self.starred_repo.get_by_user(user.id, item_type)
        return [
            {
                "item_id": str(item.item_id),
                "item_type": item.item_type,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in starred_items
        ]

    async def is_item_starred(self, user: User, item_id: UUID, item_type: str) -> bool:
        """
        Check if an item is starred by the user.

        Args:
            user: Current user
            item_id: Item ID to check
            item_type: Item type (page, space, or crew)

        Returns:
            bool: True if item is starred, False otherwise
        """
        starred_item = await self.starred_repo.get_by_user_and_item(user.id, item_id, item_type)
        return starred_item is not None
