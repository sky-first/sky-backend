from typing import List, Optional
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.models.intelligence_signal import IntelligenceSignal
from src.repositories.base import BaseRepository


class IntelligenceSignalRepository(BaseRepository[IntelligenceSignal]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, IntelligenceSignal)

    async def get_by_planet(
        self,
        planet_id: UUID,
        category: Optional[str] = None,
        include_dismissed: bool = False,
    ) -> List[IntelligenceSignal]:
        """Fetch signals for a specific planet, optionally filtered by category."""
        query = select(IntelligenceSignal).where(
            IntelligenceSignal.planet_id == planet_id
        )

        if category:
            query = query.where(IntelligenceSignal.category == category)

        if not include_dismissed:
            query = query.where(IntelligenceSignal.is_dismissed.is_(None))

        query = query.order_by(IntelligenceSignal.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())


def get_intelligence_signal_repo(
    db: AsyncSession = Depends(get_db),
) -> IntelligenceSignalRepository:
    return IntelligenceSignalRepository(db)
