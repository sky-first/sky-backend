"""Base repository with common CRUD operations."""

from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Base repository with common CRUD operations."""

    def __init__(self, db: AsyncSession, model: Type[ModelType]):
        """
        Initialize repository.

        Args:
            db: Database session
            model: SQLAlchemy model class
        """
        self.db = db
        self.model = model

    async def get_by_id(self, id: UUID) -> Optional[ModelType]:
        """
        Get entity by ID.

        Args:
            id: Entity ID

        Returns:
            Optional[ModelType]: Entity or None
        """
        result = await self.db.execute(
            select(self.model).where(cast(Any, self.model).id == id)
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[Dict[str, Any]] = None,
        order_by: Optional[str] = None,
    ) -> List[ModelType]:
        """
        Get all entities with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            filters: Optional filters (dict of column: value)
            order_by: Optional column name to order by

        Returns:
            List[ModelType]: List of entities
        """
        query = select(self.model)

        # Apply filters
        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.where(getattr(self.model, key) == value)

        # Apply ordering
        if order_by and hasattr(self.model, order_by):
            query = query.order_by(getattr(self.model, order_by))

        # Apply pagination
        query = query.offset(skip).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """
        Count entities.

        Args:
            filters: Optional filters

        Returns:
            int: Count of entities
        """
        from sqlalchemy import func

        query = select(func.count()).select_from(self.model)

        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.where(getattr(self.model, key) == value)

        result = await self.db.execute(query)
        return result.scalar() or 0

    async def create(self, **kwargs) -> ModelType:
        """
        Create new entity.

        Args:
            **kwargs: Entity attributes

        Returns:
            ModelType: Created entity
        """
        # Set created_at, updated_at, and other timestamp fields if not provided and model has these fields
        # This is needed for SQLite which doesn't support server_default=func.now()
        from datetime import datetime, timezone

        # Use naive utcnow to match existing pattern and avoid asyncpg aware/naive mismatch
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Ensure ALL datetime objects in kwargs are naive
        for key, value in kwargs.items():
            if isinstance(value, datetime) and value.tzinfo is not None:
                kwargs[key] = value.replace(tzinfo=None)

        if hasattr(self.model, "created_at") and "created_at" not in kwargs:
            kwargs["created_at"] = now
        if hasattr(self.model, "updated_at") and "updated_at" not in kwargs:
            kwargs["updated_at"] = now
        if hasattr(self.model, "joined_at") and "joined_at" not in kwargs:
            kwargs["joined_at"] = now
        if hasattr(self.model, "date") and "date" not in kwargs:
            kwargs["date"] = now
        if hasattr(self.model, "started_at") and "started_at" not in kwargs:
            kwargs["started_at"] = now
        if hasattr(self.model, "timestamp") and "timestamp" not in kwargs:
            kwargs["timestamp"] = now
        if (
            hasattr(self.model, "last_metadata_update")
            and "last_metadata_update" not in kwargs
        ):
            # Only set if it's required (not nullable)
            # Check if column is nullable by inspecting the model
            col = getattr(self.model, "last_metadata_update", None)
            if col and not col.nullable:
                kwargs["last_metadata_update"] = now

        entity = self.model(**kwargs)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update(self, id: UUID, **kwargs) -> Optional[ModelType]:
        """
        Update entity.

        Args:
            id: Entity ID
            **kwargs: Attributes to update

        Returns:
            Optional[ModelType]: Updated entity or None
        """
        # Remove None values
        kwargs = {k: v for k, v in kwargs.items() if v is not None}

        if not kwargs:
            return await self.get_by_id(id)

        await self.db.execute(
            update(self.model).where(cast(Any, self.model).id == id).values(**kwargs)
        )
        await self.db.flush()
        return await self.get_by_id(id)

    async def delete(self, id: UUID) -> bool:
        """
        Delete entity (soft delete if deleted_at exists).

        Args:
            id: Entity ID

        Returns:
            bool: True if deleted
        """
        entity = await self.get_by_id(id)
        if not entity:
            return False

        # Soft delete if deleted_at column exists
        if hasattr(self.model, "deleted_at"):
            from sqlalchemy import func

            await self.db.execute(
                update(self.model)
                .where(cast(Any, self.model).id == id)
                .values(deleted_at=func.now())
            )
        else:
            await self.db.delete(entity)

        await self.db.flush()
        return True

    async def exists(self, id: UUID) -> bool:
        """
        Check if entity exists.

        Args:
            id: Entity ID

        Returns:
            bool: True if exists
        """
        entity = await self.get_by_id(id)
        return entity is not None
