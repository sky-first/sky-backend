"""Slack ticket-created webhook unit tests.

Confirms that:
  1. With SLACK_TICKETS_WEBHOOK_URL empty, the helper is a no-op (no
     outbound HTTP). This is the dev/local mode and what runs by
     default in CI.
  2. With a URL configured, the helper POSTs a Slack block-kit payload
     containing the ticket subject, severity, category, reporter
     email, status, and a deep-link button when APP_PUBLIC_URL is set.
  3. Webhook failures (5xx, timeout, connection error) DO NOT propagate
     out of the helper — the ticket creation must not fail because
     Slack is having a bad day.
  4. Body preview is truncated at 500 chars so a 16k-char ticket body
     doesn't blow up the Slack message.

These tests live next to the helper rather than in the wider ticket
service test file so a failure here points directly at the webhook
contract.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.models.ticket import Ticket, TicketCategory, TicketSeverity, TicketStatus
from src.models.user import User
from src.services.ticket_service import (
    _post_slack_ticket_created,
    _slack_blocks_for_created,
)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _make_ticket(*, body: str = "Body of the ticket", subject: str = "Test subject") -> Ticket:
    """Construct an in-memory Ticket — not persisted, just the fields the
    helpers read."""
    t = Ticket(
        reporter_user_id=uuid4(),
        subject=subject,
        body=body,
        category=TicketCategory.BUG.value,
        severity=TicketSeverity.HIGH.value,
        status=TicketStatus.OPEN.value,
    )
    t.id = uuid4()
    return t


def _make_reporter() -> User:
    u = User(email="reporter@example.com", name="Test Reporter", role="member")
    u.id = uuid4()
    return u


class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


# ─── Block-kit shape ────────────────────────────────────────────────────────


def test_blocks_carry_severity_emoji_and_subject():
    ticket = _make_ticket(subject="Database is on fire")
    reporter = _make_reporter()
    payload = _slack_blocks_for_created(ticket, reporter)
    header = payload["blocks"][0]
    assert header["type"] == "header"
    assert "Database is on fire" in header["text"]["text"]
    # high severity → :rotating_light: per _SEVERITY_EMOJI map
    assert ":rotating_light:" in header["text"]["text"]
    # text fallback for clients without block-kit rendering
    assert "Database is on fire" in payload["text"]


def test_blocks_include_severity_category_reporter_status_fields():
    ticket = _make_ticket()
    reporter = _make_reporter()
    payload = _slack_blocks_for_created(ticket, reporter)
    section_fields = payload["blocks"][1]["fields"]
    field_text = " ".join(f["text"] for f in section_fields)
    assert "Severity" in field_text
    assert ticket.severity in field_text
    assert "Category" in field_text
    assert ticket.category in field_text
    assert "Reporter" in field_text
    assert reporter.email in field_text
    assert "Status" in field_text


def test_blocks_truncate_long_body_to_500_chars():
    long_body = "X" * 1200
    ticket = _make_ticket(body=long_body)
    reporter = _make_reporter()
    payload = _slack_blocks_for_created(ticket, reporter)
    # Find the section with body preview (has "type":"section" and "text" key)
    quote_section = next(
        b for b in payload["blocks"]
        if b.get("type") == "section" and "text" in b and isinstance(b["text"], dict)
    )
    text = quote_section["text"]["text"]
    # Truncated to 497 + ellipsis = 498 chars total under the quote `>>>` prefix
    assert "…" in text
    assert len(text) < 600  # 500-cap + small prefix overhead


def test_blocks_include_open_ticket_button_when_app_url_set(monkeypatch):
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(
        runtime_settings, "APP_PUBLIC_URL", "https://workspace-stg.skyfirstlabs.com",
    )
    ticket = _make_ticket()
    reporter = _make_reporter()
    payload = _slack_blocks_for_created(ticket, reporter)
    actions = next(b for b in payload["blocks"] if b.get("type") == "actions")
    button = actions["elements"][0]
    assert button["type"] == "button"
    assert button["text"]["text"] == "Open ticket"
    assert button["url"].startswith("https://workspace-stg.skyfirstlabs.com")
    assert str(ticket.id) in button["url"]


def test_blocks_omit_button_when_app_url_empty(monkeypatch):
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "APP_PUBLIC_URL", "")
    ticket = _make_ticket()
    reporter = _make_reporter()
    payload = _slack_blocks_for_created(ticket, reporter)
    has_action = any(b.get("type") == "actions" for b in payload["blocks"])
    assert not has_action


# ─── Outbound helper behaviour ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_helper_is_noop_when_url_empty(monkeypatch):
    """Default config (no webhook URL) must not hit the network.

    This is the contract for local dev + CI runs where every test
    creates tickets — without the no-op guard we'd flood Slack with
    thousands of fake notifications.
    """
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "SLACK_TICKETS_WEBHOOK_URL", "")
    ticket = _make_ticket()
    reporter = _make_reporter()

    with patch("httpx.AsyncClient") as mock_client:
        await _post_slack_ticket_created(ticket=ticket, reporter=reporter)
    # AsyncClient must not have been instantiated
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_helper_posts_blocks_when_url_configured(monkeypatch):
    """With a URL set, the helper POSTs the block-kit payload."""
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(
        runtime_settings,
        "SLACK_TICKETS_WEBHOOK_URL",
        "https://hooks.slack.com/services/TEST/TEST/TEST",
    )
    ticket = _make_ticket(subject="Disk full")
    reporter = _make_reporter()

    captured = {}

    class _MockClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, url, json=None, **_):
            captured["url"] = url
            captured["json"] = json
            return _Resp(200)

    with patch("httpx.AsyncClient", _MockClient):
        await _post_slack_ticket_created(ticket=ticket, reporter=reporter)

    assert captured["url"] == "https://hooks.slack.com/services/TEST/TEST/TEST"
    assert "blocks" in captured["json"]
    # Subject ended up in the payload
    payload_str = str(captured["json"])
    assert "Disk full" in payload_str


@pytest.mark.asyncio
async def test_helper_swallows_5xx(monkeypatch, caplog):
    """A failed Slack response must not bubble out of the helper.

    The DB is the source of truth — losing the Slack ping is logged
    but never breaks ticket creation.
    """
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(
        runtime_settings,
        "SLACK_TICKETS_WEBHOOK_URL",
        "https://hooks.slack.com/services/X/Y/Z",
    )
    ticket = _make_ticket()
    reporter = _make_reporter()

    class _BoomClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_, **__):
            return _Resp(500, "Slack edge died")

    with patch("httpx.AsyncClient", _BoomClient):
        # Must NOT raise
        await _post_slack_ticket_created(ticket=ticket, reporter=reporter)

    # Error should be logged
    assert any(
        "slack_ticket_webhook_failed" in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_helper_swallows_connection_error(monkeypatch):
    """An exception raised inside httpx (timeout, DNS fail, etc.) must
    not propagate. ``DemoService.create`` already committed the ticket
    by this point — the user shouldn't see a 500."""
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(
        runtime_settings,
        "SLACK_TICKETS_WEBHOOK_URL",
        "https://hooks.slack.com/services/X/Y/Z",
    )
    ticket = _make_ticket()
    reporter = _make_reporter()

    class _ExplodingClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_, **__):
            raise ConnectionError("DNS resolution failed")

    with patch("httpx.AsyncClient", _ExplodingClient):
        # Must NOT raise
        await _post_slack_ticket_created(ticket=ticket, reporter=reporter)
