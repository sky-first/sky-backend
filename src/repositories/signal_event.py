from sqlalchemy.ext.asyncio import AsyncSession
from src.models.signal_event import SignalEvent
from src.repositories.base import BaseRepository

class SignalEventRepository(BaseRepository[SignalEvent]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, SignalEvent)

def get_signal_event_repo(db: AsyncSession) -> SignalEventRepository:
    return SignalEventRepository(db)
