"""Notification preference service — manage mute/pause rules."""

from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.notification_preference_repository import NotificationPreferenceRepository
from src.schemas.notification_preference import (
    NotificationPreferenceCreate,
    NotificationPreferenceResponse,
)


class NotificationPreferenceService:
    """Business logic for notification preferences."""

    def __init__(self, db: AsyncSession):
        self.repo = NotificationPreferenceRepository(db)

    async def get_preferences(self, user_id: UUID) -> List[NotificationPreferenceResponse]:
        """Return all preference rows for a user."""
        rows = await self.repo.get_all_by_user(user_id)
        return [NotificationPreferenceResponse.model_validate(r) for r in rows]

    async def update_preferences(
        self, user_id: UUID, prefs: List[NotificationPreferenceCreate]
    ) -> List[NotificationPreferenceResponse]:
        """Batch upsert preferences."""
        results = []
        for p in prefs:
            row = await self.repo.upsert(
                user_id=user_id,
                scope_type=p.scope_type,
                scope_value=p.scope_value,
                channel=p.channel,
                enabled=p.enabled,
            )
            results.append(NotificationPreferenceResponse.model_validate(row))
        return results

    async def toggle_pause(self, user_id: UUID, paused: bool) -> bool:
        """Toggle focus mode (global pause)."""
        await self.repo.upsert(
            user_id=user_id,
            scope_type="global",
            scope_value=None,
            channel="all",
            enabled=not paused,  # enabled=False means paused
        )
        return paused

    async def is_paused(self, user_id: UUID) -> bool:
        """Check if user has focus mode on."""
        return await self.repo.is_globally_paused(user_id)
