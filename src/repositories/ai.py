"""AI repository."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.ai import AIQuery
from src.repositories.base import BaseRepository


class AIQueryRepository(BaseRepository[AIQuery]):
    """AI query repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, AIQuery)

    async def count_queries_by_connection_id(self, connection_id: UUID) -> int:
        """
        Count AI queries that used a specific connection.
        Searches within the configure_data JSON field.
        """
        conn_str = str(connection_id)
        # PostgreSQL specific query for JSONB array containment
        query = (
            select(func.count())
            .select_from(AIQuery)
            .where(
                cast(AIQuery.configure_data, JSONB)["knowledge"].contains([conn_str])
            )
        )
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def get_active_users_by_connection_id(self, connection_id: UUID) -> int:
        """
        Count unique users who queried a specific connection.
        """
        conn_str = str(connection_id)
        query = (
            select(func.count(func.distinct(AIQuery.user_id)))
            .select_from(AIQuery)
            .where(
                cast(AIQuery.configure_data, JSONB)["knowledge"].contains([conn_str])
            )
        )
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def count_queries_by_connection_ids(self, connection_ids: list[UUID]) -> int:
        """
        Count AI queries that used any of the specified connections.
        """
        if not connection_ids:
            return 0

        conn_strs = [str(cid) for cid in connection_ids]

        # PostgreSQL: ANY check for JSONB array intersection or containment
        query = (
            select(func.count())
            .select_from(AIQuery)
            .where(
                sa.or_(
                    *[
                        cast(AIQuery.configure_data, JSONB)["knowledge"].contains([c])
                        for c in conn_strs
                    ]
                )
            )
        )
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def get_active_users_by_connection_ids(
        self, connection_ids: list[UUID]
    ) -> int:
        """
        Count unique users who queried any of the specified connections.
        """
        if not connection_ids:
            return 0

        conn_strs = [str(cid) for cid in connection_ids]
        query = (
            select(func.count(func.distinct(AIQuery.user_id)))
            .select_from(AIQuery)
            .where(
                sa.or_(
                    *[
                        cast(AIQuery.configure_data, JSONB)["knowledge"].contains([c])
                        for c in conn_strs
                    ]
                )
            )
        )
        result = await self.db.execute(query)
        return result.scalar() or 0
