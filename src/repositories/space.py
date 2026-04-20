"""Space repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.connection import DataConnection
from src.models.crew import Crew
from src.models.space import Space, SpaceConnection, SpaceMember, SpaceTable
from src.repositories.base import BaseRepository


class SpaceRepository(BaseRepository[Space]):
    """Space repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Space)

    async def get_by_user(self, user_id: UUID, skip: int = 0, limit: int = 100) -> List[Space]:
        """Get spaces the user created or is a member of."""
        member_space_ids = select(SpaceMember.space_id).where(SpaceMember.user_id == user_id)
        result = await self.db.execute(
            select(Space)
            .where(
                Space.deleted_at.is_(None),
                or_(Space.created_by == user_id, Space.id.in_(member_space_ids)),
            )
            .order_by(Space.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_user_with_stats(
        self, user_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[dict]:
        """Get spaces (created or member) with member and connection counts."""
        member_space_ids = select(SpaceMember.space_id).where(SpaceMember.user_id == user_id)
        stmt = (
            select(
                Space,
                func.count(distinct(SpaceMember.id)).label("member_count"),
                func.count(distinct(SpaceConnection.connection_id)).label("connection_count"),
            )
            .outerjoin(SpaceMember, Space.id == SpaceMember.space_id)
            .outerjoin(SpaceConnection, Space.id == SpaceConnection.space_id)
            .where(
                Space.deleted_at.is_(None),
                or_(Space.created_by == user_id, Space.id.in_(member_space_ids)),
            )
            .group_by(Space.id)
            .order_by(Space.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(stmt)

        spaces = []
        for row in result:
            space, member_count, connection_count = row
            space_data = {c.name: getattr(space, c.name) for c in space.__table__.columns}
            space_data["member_count"] = member_count
            space_data["connection_count"] = connection_count
            spaces.append(space_data)

        return spaces

    async def get_by_id(self, id: UUID) -> Optional[Space]:
        """
        Get entity by ID. Overridden to include deleted_at filter.

        Args:
            id: Entity ID

        Returns:
            Optional[Space]: Entity or None
        """
        result = await self.db.execute(
            select(self.model).where(self.model.id == id, self.model.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_space_crews(self, space_id: UUID) -> List[Crew]:
        """
        Get crews for a space.

        Args:
            space_id: Space ID

        Returns:
            List[Crew]: List of crews
        """
        result = await self.db.execute(
            select(Crew).where(Crew.space_id == space_id, Crew.deleted_at.is_(None))
        )
        return list(result.scalars().all())

    async def get_space_connections(self, space_id: UUID) -> List[SpaceConnection]:
        """
        Get connections for a space.

        Args:
            space_id: Space ID

        Returns:
            List[SpaceConnection]: List of space connections
        """
        result = await self.db.execute(
            # Filter out stale references (space_connections pointing to deleted/missing connections)
            select(SpaceConnection)
            .join(DataConnection, SpaceConnection.connection_id == DataConnection.id)
            .where(
                SpaceConnection.space_id == space_id,
                DataConnection.deleted_at.is_(None),
            )
            .options(selectinload(SpaceConnection.connection))
        )
        return list(result.scalars().all())

    async def get_space_connection(
        self, space_id: UUID, connection_id: UUID
    ) -> Optional[SpaceConnection]:
        """
        Get a specific space connection association.

        Args:
            space_id: Space ID
            connection_id: Connection ID

        Returns:
            Optional[SpaceConnection]: The association or None
        """
        result = await self.db.execute(
            select(SpaceConnection).where(
                SpaceConnection.space_id == space_id,
                SpaceConnection.connection_id == connection_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_spaces_by_connection_id(self, connection_id: UUID) -> List[Space]:
        """
        Get all spaces associated with a connection.

        Args:
            connection_id: Connection ID

        Returns:
            List[Space]: List of spaces linked to the connection
        """
        result = await self.db.execute(
            select(Space)
            .join(SpaceConnection, Space.id == SpaceConnection.space_id)
            .where(
                SpaceConnection.connection_id == connection_id,
                Space.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())


class SpaceMemberRepository(BaseRepository[SpaceMember]):
    """Space member repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, SpaceMember)

    async def get_by_space_and_user(self, space_id: UUID, user_id: UUID) -> Optional[SpaceMember]:
        """
        Get space member by space and user.

        Args:
            space_id: Space ID
            user_id: User ID

        Returns:
            Optional[SpaceMember]: Member or None
        """
        result = await self.db.execute(
            select(SpaceMember).where(
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_space_members(self, space_id: UUID) -> List[SpaceMember]:
        """
        Get all members of a space.

        Args:
            space_id: Space ID

        Returns:
            List[SpaceMember]: List of members
        """
        result = await self.db.execute(
            select(SpaceMember)
            .where(SpaceMember.space_id == space_id)
            .options(selectinload(SpaceMember.user))
        )
        return list(result.scalars().all())


class SpaceTableRepository(BaseRepository[SpaceTable]):
    """Space table repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, SpaceTable)

    async def get_space_tables(self, space_id: UUID) -> List[SpaceTable]:
        """
        Get all tables linked to a space.

        Args:
            space_id: Space ID

        Returns:
            List[SpaceTable]: List of linked tables
        """
        result = await self.db.execute(select(SpaceTable).where(SpaceTable.space_id == space_id))
        return list(result.scalars().all())

    async def get_space_table(
        self,
        space_id: UUID,
        connection_id: UUID,
        table_name: str,
        schema_name: Optional[str] = None,
    ) -> Optional[SpaceTable]:
        """
        Get a specific space table connection.

        Args:
            space_id: Space ID
            connection_id: Connection ID
            table_name: Table name
            schema_name: Schema name

        Returns:
            Optional[SpaceTable]: The association or None
        """
        query = select(SpaceTable).where(
            SpaceTable.space_id == space_id,
            SpaceTable.connection_id == connection_id,
            SpaceTable.table_name == table_name,
        )
        if schema_name:
            query = query.where(SpaceTable.schema_name == schema_name)
        else:
            query = query.where(SpaceTable.schema_name.is_(None))

        result = await self.db.execute(query)
        return result.scalar_one_or_none()
