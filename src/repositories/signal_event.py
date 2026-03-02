from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import get_db
from src.models.signal_event import SignalEvent
from src.repositories.base import BaseRepository

class SignalEventRepository(BaseRepository[SignalEvent]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, SignalEvent)

def get_signal_event_repo(db: AsyncSession = Depends(get_db)) -> SignalEventRepository:
    return SignalEventRepository(db)
