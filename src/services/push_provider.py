"""Push transport providers (BE-06).

The dispatcher decides *who* gets a push; a provider knows *how* to send
it. The seam keeps the vendor swappable and testable: the default
``LoggingPushProvider`` needs no credentials and no device, so the whole
registry + dispatch + prune path is exercisable today, before APNs/FCM
keys and a dev build (which mints real tokens) exist.

Selected via ``PUSH_PROVIDER`` (``log`` default, or ``expo``). Prod is
expected to send raw APNs/FCM directly (no Expo relay) — that provider
lands with its credentials; it implements the same ``send`` contract.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Protocol

logger = logging.getLogger(__name__)


@dataclass
class PushMessage:
    """One push, addressed to a single device token."""

    token: str
    title: str
    body: str = ""
    provider: str = "expo"
    # Deep-link + entity so tapping the push opens the exact screen (T-06.9).
    data: Dict[str, str] = field(default_factory=dict)


@dataclass
class PushResult:
    """Outcome of a send. ``invalid_tokens`` are pruned from the registry."""

    sent: int = 0
    invalid_tokens: List[str] = field(default_factory=list)


class PushProvider(Protocol):
    async def send(self, messages: List[PushMessage]) -> PushResult: ...


class LoggingPushProvider:
    """Default provider — records the intent without an external call.

    Sends nothing over the wire (no creds, no network), so it is safe in
    dev/test and never prunes a token. Swapped for a real transport once
    credentials exist.
    """

    async def send(self, messages: List[PushMessage]) -> PushResult:
        for m in messages:
            logger.info(
                "push (noop): to=%s title=%r deep_link=%s",
                m.token[:12] + "…",
                m.title,
                m.data.get("deep_link"),
            )
        return PushResult(sent=len(messages), invalid_tokens=[])


class ExpoPushProvider:
    """Sends via Expo's push service. Only usable for ``ExponentPushToken``s.

    Parses the response so tokens Expo reports as ``DeviceNotRegistered``
    are handed back for pruning (T-06.6). Imported lazily so the service
    boots without httpx configured.
    """

    ENDPOINT = "https://exp.host/--/api/v2/push/send"

    async def send(self, messages: List[PushMessage]) -> PushResult:
        import httpx

        payload = [
            {
                "to": m.token,
                "title": m.title,
                "body": m.body,
                "data": m.data,
            }
            for m in messages
        ]
        invalid: List[str] = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.ENDPOINT, json=payload)
                resp.raise_for_status()
                receipts = (resp.json() or {}).get("data", [])
            for msg, receipt in zip(messages, receipts):
                err = (receipt or {}).get("details", {}).get("error")
                if receipt.get("status") == "error" and err == "DeviceNotRegistered":
                    invalid.append(msg.token)
        except Exception as exc:  # a transport failure must not break notify
            logger.warning("expo push failed: %s", exc)
            return PushResult(sent=0, invalid_tokens=[])
        return PushResult(sent=len(messages) - len(invalid), invalid_tokens=invalid)


def build_push_provider() -> PushProvider:
    """Log-only by default; ``PUSH_PROVIDER=expo`` selects the Expo transport."""
    choice = os.getenv("PUSH_PROVIDER", "log").lower()
    if choice == "expo":
        return ExpoPushProvider()
    return LoggingPushProvider()
