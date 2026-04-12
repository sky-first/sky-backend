"""Notification preference repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.notification import NOTIFICATION_CATEGORY, NotificationPreference


class NotificationPreferenceRepository:
    """Repository for NotificationPreference CRUD + mute checks."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_by_user(self, user_id: UUID) -> List[NotificationPreference]:
        """Return every preference row for a user."""
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == user_id
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def upsert(
        self,
        user_id: UUID,
        scope_type: str,
        scope_value: Optional[str],
        channel: str,
        enabled: bool,
    ) -> NotificationPreference:
        """Insert or update a preference row (match on unique constraint)."""
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.scope_type == scope_type,
            NotificationPreference.scope_value == scope_value if scope_value else NotificationPreference.scope_value.is_(None),
            NotificationPreference.channel == channel,
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.enabled = enabled
            await self.db.commit()
            await self.db.refresh(existing)
            return existing

        pref = NotificationPreference(
            user_id=user_id,
            scope_type=scope_type,
            scope_value=scope_value,
            channel=channel,
            enabled=enabled,
        )
        self.db.add(pref)
        await self.db.commit()
        await self.db.refresh(pref)
        return pref

    async def is_globally_paused(self, user_id: UUID) -> bool:
        """Check if the user has focus mode on (global pause)."""
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.scope_type == "global",
            NotificationPreference.scope_value.is_(None),
            NotificationPreference.channel == "all",
            NotificationPreference.enabled == False,  # noqa: E712
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def is_muted(
        self,
        user_id: UUID,
        notification_type: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        channel: str = "in_app",
    ) -> bool:
        """Evaluate the preference chain for a single notification.

        Resolution order (first match wins):
            1. Global pause — blocks everything
            2. Category mute — blocks the entire category (e.g. "agents")
            3. Source mute — blocks a specific entity (e.g. "agent:<uuid>")
        """
        prefs = await self.get_all_by_user(user_id)
        if not prefs:
            return False

        for p in prefs:
            if not _channel_matches(p.channel, channel):
                continue

            # 1. Global pause
            if p.scope_type == "global" and p.scope_value is None and not p.enabled:
                return True

            # 2. Category mute
            category = NOTIFICATION_CATEGORY.get(notification_type)
            if (
                p.scope_type == "category"
                and category
                and p.scope_value == category
                and not p.enabled
            ):
                return True

            # 3. Source mute
            if (
                p.scope_type == "source"
                and entity_type
                and entity_id
                and p.scope_value == f"{entity_type}:{entity_id}"
                and not p.enabled
            ):
                return True

        return False


def _channel_matches(pref_channel: str, target_channel: str) -> bool:
    """Check if a preference's channel applies to the target channel."""
    return pref_channel == "all" or pref_channel == target_channel
