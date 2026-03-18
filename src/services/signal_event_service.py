import logging
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.http_client import AIServiceHTTPClient
from src.repositories.signal_event import SignalEventRepository
from src.schemas.signal_event import SignalEventCreate, SignalEventResponse, SignalEventUpdate

logger = logging.getLogger(__name__)


class SignalEventService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = SignalEventRepository(db)
        self.ai_client = AIServiceHTTPClient()

    async def list_events(
        self, space_id: Optional[UUID] = None, crew_id: Optional[UUID] = None
    ) -> List[SignalEventResponse]:
        filters = {}
        if space_id:
            filters["space_id"] = space_id
        if crew_id:
            filters["crew_id"] = crew_id
        return await self.repository.get_all(filters=filters)

    async def get_event(
        self, event_id: UUID, space_id: Optional[UUID] = None, crew_id: Optional[UUID] = None
    ) -> SignalEventResponse:
        event = await self.repository.get_by_id(event_id)
        if (
            not event
            or (space_id and event.space_id != space_id)
            or (crew_id and event.crew_id != crew_id)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Signal Event not found"
            )
        return event

    async def create_event(
        self,
        schema: SignalEventCreate,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
    ) -> SignalEventResponse:
        data = schema.model_dump()
        if space_id:
            data["space_id"] = space_id
        if crew_id:
            data["crew_id"] = crew_id

        event = await self.repository.create(**data)
        await self.db.commit()
        await self.db.refresh(event)

        # Notify AI for ingestion
        try:
            payload = {
                "id": str(event.id),
                "entity_type": "signal_event",
                "category": event.category.value,
                "sub_type": event.sub_type,
                "nature": event.nature.value,
                "description": event.description,
                "start_date": event.start_date.isoformat(),
                "impact_date": event.impact_date.isoformat() if event.impact_date else None,
                "confidence": event.confidence.value,
                "space_id": str(event.space_id) if event.space_id else None,
                "crew_id": str(event.crew_id) if event.crew_id else None,
                "entity_details": {"relations": event.relations},
            }
            await self.ai_client.ingest_knowledge_graph(payload)
        except Exception as e:
            logger.error(f"Failed to trigger AI ingestion for signal event {event.id}: {e}")

        return event

    async def update_event(
        self,
        event_id: UUID,
        schema: SignalEventUpdate,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
    ) -> SignalEventResponse:
        # First check ownership
        await self.get_event(event_id, space_id=space_id, crew_id=crew_id)

        event = await self.repository.update(event_id, **schema.model_dump(exclude_unset=True))
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Signal Event not found"
            )

        await self.db.commit()
        await self.db.refresh(event)

        # Notify AI for ingestion (Update)
        try:
            payload = {
                "id": str(event.id),
                "entity_type": "signal_event",
                "category": event.category.value,
                "sub_type": event.sub_type,
                "nature": event.nature.value,
                "description": event.description,
                "start_date": event.start_date.isoformat(),
                "impact_date": event.impact_date.isoformat() if event.impact_date else None,
                "confidence": event.confidence.value,
                "space_id": str(event.space_id) if event.space_id else None,
                "crew_id": str(event.crew_id) if event.crew_id else None,
                "entity_details": {"relations": event.relations},
            }
            await self.ai_client.ingest_knowledge_graph(payload)
        except Exception as e:
            logger.error(f"Failed to trigger AI ingestion for updated signal event {event.id}: {e}")

        return event

    async def delete_event(
        self, event_id: UUID, space_id: Optional[UUID] = None, crew_id: Optional[UUID] = None
    ) -> None:
        # First check ownership
        await self.get_event(event_id, space_id=space_id, crew_id=crew_id)

        success = await self.repository.delete(event_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Signal Event not found"
            )
        await self.db.commit()
