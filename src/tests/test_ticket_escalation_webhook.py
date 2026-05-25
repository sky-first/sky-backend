"""Tests for the Sky on-call escalation webhook (#81).

The escalate flow already updates the DB and emits a structured log
line. This adds an outbound POST to TICKET_ESCALATION_WEBHOOK_URL when
the setting is configured. These tests pin:

  * Webhook URL empty → no HTTP call (log-only mode).
  * Webhook URL set   → exactly one POST with the documented payload
    + the bearer token in the Authorization header.
  * Webhook receiver returns 5xx → escalation still succeeds (DB is
    the source of truth, the webhook is best-effort).
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.models.ticket import Ticket, TicketCategory, TicketSeverity, TicketStatus
from src.models.user import User
from src.services.ticket_service import (
    _escalation_payload,
    _post_escalation_webhook,
)


def _make_ticket() -> Ticket:
    t = Ticket(
        id=uuid4(),
        reporter_user_id=uuid4(),
        subject="DB latency spike on prod",
        body="See logs from 14:32 UTC.",
        category=TicketCategory.INFRASTRUCTURE.value
        if hasattr(TicketCategory, "INFRASTRUCTURE")
        else "infrastructure",
        severity=TicketSeverity.HIGH.value if hasattr(TicketSeverity, "HIGH") else "high",
        status=TicketStatus.ESCALATED.value,
        context={},
        external_ref=None,
    )
    return t


def _make_user() -> User:
    return User(
        id=uuid4(),
        email="ops@example.com",
        name="Ops",
        password_hash="x",
        role="admin",
    )


def test_escalation_payload_shape():
    t = _make_ticket()
    u = _make_user()
    body = _escalation_payload(t, u, "please review")
    # Contract — alerting rules pin on these keys.
    for required in (
        "event",
        "ticket_id",
        "subject",
        "category",
        "severity",
        "status",
        "reporter_user_id",
        "escalated_by_user_id",
        "escalated_by_email",
        "note",
        "external_ref",
    ):
        assert required in body, f"missing key: {required}"
    assert body["event"] == "ticket_escalated"
    assert body["ticket_id"] == str(t.id)
    assert body["escalated_by_email"] == "ops@example.com"
    assert body["note"] == "please review"


@pytest.mark.asyncio
async def test_no_url_no_http_call():
    """Empty URL = log-only mode. We must NOT open an HTTP client."""
    with patch("src.services.ticket_service.settings") as settings_mock, patch(
        "src.services.ticket_service.httpx.AsyncClient"
    ) as client_cls:
        settings_mock.TICKET_ESCALATION_WEBHOOK_URL = ""
        settings_mock.TICKET_ESCALATION_WEBHOOK_TOKEN = ""
        settings_mock.TICKET_ESCALATION_WEBHOOK_TIMEOUT = 5.0
        await _post_escalation_webhook(
            ticket=_make_ticket(), actor=_make_user(), note=None
        )
    client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_url_set_posts_once_with_bearer_header():
    """When configured, exactly one POST with bearer + JSON body."""
    posted_url: List[str] = []
    posted_headers: List[Dict[str, str]] = []
    posted_json: List[Dict[str, Any]] = []

    response = MagicMock(status_code=204, text="")

    async def fake_post(url, headers=None, json=None, **_kwargs):
        posted_url.append(url)
        posted_headers.append(headers or {})
        posted_json.append(json or {})
        return response

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = fake_post

    with patch("src.services.ticket_service.settings") as settings_mock, patch(
        "src.services.ticket_service.httpx.AsyncClient", return_value=fake_client
    ):
        settings_mock.TICKET_ESCALATION_WEBHOOK_URL = "https://hooks.sky.example/escalate"
        settings_mock.TICKET_ESCALATION_WEBHOOK_TOKEN = "s3cr3t"
        settings_mock.TICKET_ESCALATION_WEBHOOK_TIMEOUT = 5.0
        await _post_escalation_webhook(
            ticket=_make_ticket(), actor=_make_user(), note="please review"
        )

    assert posted_url == ["https://hooks.sky.example/escalate"]
    assert posted_headers[0]["Authorization"] == "Bearer s3cr3t"
    assert posted_headers[0]["Content-Type"] == "application/json"
    assert posted_json[0]["event"] == "ticket_escalated"


@pytest.mark.asyncio
async def test_receiver_5xx_does_not_raise():
    """A failing webhook must NOT raise — DB is the source of truth."""
    response = MagicMock(status_code=503, text="upstream down")

    async def fake_post(url, headers=None, json=None, **_kwargs):
        return response

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = fake_post

    with patch("src.services.ticket_service.settings") as settings_mock, patch(
        "src.services.ticket_service.httpx.AsyncClient", return_value=fake_client
    ):
        settings_mock.TICKET_ESCALATION_WEBHOOK_URL = "https://hooks.sky.example/escalate"
        settings_mock.TICKET_ESCALATION_WEBHOOK_TOKEN = ""
        settings_mock.TICKET_ESCALATION_WEBHOOK_TIMEOUT = 5.0
        # Must not raise.
        await _post_escalation_webhook(
            ticket=_make_ticket(), actor=_make_user(), note=None
        )


@pytest.mark.asyncio
async def test_network_exception_swallowed():
    """A network blow-up while posting must not propagate either."""

    async def boom(*_args, **_kwargs):
        raise RuntimeError("connection reset")

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = boom

    with patch("src.services.ticket_service.settings") as settings_mock, patch(
        "src.services.ticket_service.httpx.AsyncClient", return_value=fake_client
    ):
        settings_mock.TICKET_ESCALATION_WEBHOOK_URL = "https://hooks.sky.example/escalate"
        settings_mock.TICKET_ESCALATION_WEBHOOK_TOKEN = ""
        settings_mock.TICKET_ESCALATION_WEBHOOK_TIMEOUT = 5.0
        await _post_escalation_webhook(
            ticket=_make_ticket(), actor=_make_user(), note=None
        )
