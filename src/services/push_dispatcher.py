"""Push dispatcher (BE-06) — turns a created notification into device pushes.

Wired into ``NotificationService.create_notification``: once a row is
written (which already means the user hasn't muted it — mute/focus is
enforced upstream, T-06.5), this decides whether the notification is
*material* enough to interrupt a phone, fans it out to every device the
user owns (T-06.7), and prunes tokens the provider rejects (T-06.6).
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.device_repository import DeviceRepository
from src.schemas.notification import NotificationResponse
from src.services.push_provider import PushMessage, PushProvider, build_push_provider

logger = logging.getLogger(__name__)

# Only a *material* agent finding earns a push (masterplan §6.2 / T-06.3).
# Routine run notifications (insight_agent_result, agent_cycle_no_findings)
# deliberately stay in-app only (T-06.4).
PUSH_ELIGIBLE_TYPES = {
    "insight_agent_material",
    "agent_finding",
}


class PushDispatcher:
    """Fan a push-eligible notification out to a user's registered devices."""

    def __init__(self, db: AsyncSession, provider: Optional[PushProvider] = None):
        self.devices = DeviceRepository(db)
        self.provider = provider or build_push_provider()

    async def dispatch(self, notif: NotificationResponse) -> int:
        """Send ``notif`` to every device of its user. Returns pushes sent.

        No-ops (returns 0) for non-material types or a user with no
        registered device — the common case before the mobile app ships.
        """
        if notif.type not in PUSH_ELIGIBLE_TYPES:
            return 0

        devices = await self.devices.list_for_user(notif.user_id)
        if not devices:
            return 0

        data = {
            "entity_type": notif.entity_type,
            "entity_id": notif.entity_id,
        }
        if notif.deep_link:
            data["deep_link"] = notif.deep_link

        messages = [
            PushMessage(
                token=d.push_token,
                title=notif.title,
                body=notif.description or "",
                provider=d.provider,
                data=data,
            )
            for d in devices
        ]

        result = await self.provider.send(messages)
        if result.invalid_tokens:
            pruned = await self.devices.prune_tokens(result.invalid_tokens)
            logger.info("pruned %d invalid push token(s)", pruned)
        return result.sent
