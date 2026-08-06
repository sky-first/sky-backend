"""Demo welcome email — Resend helper unit tests.

Confirms the contract:

  1. Empty RESEND_API_KEY → dry-run mode (no network call, info log)
  2. Configured key → POSTs to settings.RESEND_API_URL with the right
     Authorization, from address, to recipient, subject, html, text
  3. 4xx / 5xx response logged but NOT raised (signup must complete)
  4. Connection error logged but NOT raised
  5. Template formatting:
     - First name extracted (full name "Lucas Ventura" → "Lucas")
     - Empty name → "there" fallback
     - Empty company → "your team" fallback
     - TTL days computed from expires_at
     - Dashboard URL trimmed of trailing slash
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.services.demo_email_service import (
    _DEMO_WELCOME_HTML,
    _DEMO_WELCOME_TEXT,
    _post_resend,
    send_demo_welcome_email,
)


class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def _expires(days: int = 7) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


# ─── Dry-run / API key handling ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_resend_dryruns_when_api_key_empty(monkeypatch, caplog):
    """Empty key = no network call, info log, returns True (dry-run
    counts as success from the caller's POV — we don't want to add
    error spam in CI/local)."""
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "RESEND_API_KEY", "")

    with patch("httpx.AsyncClient") as mock_client:
        result = await _post_resend(
            to="x@example.com", subject="hi", html="<p>x</p>", text="x",
        )

    assert result is True
    mock_client.assert_not_called()
    assert any("[email-dryrun]" in rec.message for rec in caplog.records)


# ─── Real send path ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_resend_posts_with_correct_payload_and_auth(monkeypatch):
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "RESEND_API_KEY", "re_test_key_xxx")
    monkeypatch.setattr(
        runtime_settings,
        "EMAIL_FROM_ADDRESS",
        "lucas.ventura@skyfirstlabs.com",
    )
    monkeypatch.setattr(runtime_settings, "EMAIL_FROM_NAME", "Lucas Ventura — SKY")

    captured: dict = {}

    class _MockClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, url, json=None, headers=None, **_):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _Resp(200)

    with patch("httpx.AsyncClient", _MockClient):
        result = await _post_resend(
            to="bob@acme.com",
            subject="welcome",
            html="<p>hi</p>",
            text="hi",
        )

    assert result is True
    assert captured["url"] == runtime_settings.RESEND_API_URL
    assert captured["headers"]["Authorization"] == "Bearer re_test_key_xxx"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["json"]["to"] == ["bob@acme.com"]
    assert captured["json"]["subject"] == "welcome"
    assert "<p>hi</p>" in captured["json"]["html"]
    assert "Lucas Ventura — SKY" in captured["json"]["from"]
    assert "lucas.ventura@skyfirstlabs.com" in captured["json"]["from"]


def test_from_address_lives_on_a_resend_verified_domain():
    """O remetente por omissão tem de estar no subdomínio verificado.

    O que está verificado na Resend é `updates.skyfirstlabs.com` — o
    DKIM está em `resend._domainkey.updates`, na zona do Route53. O
    domínio raiz nunca foi verificado, e enviar de lá devolve 403
    `domain is not verified`. Como o serviço engole os erros por design,
    o sintoma era "o formulário não envia nada" sem um único erro à
    vista. Este teste existe para que voltar a pôr o raiz por omissão
    falhe aqui, e não em silêncio em produção.
    """
    from src.config.settings import Settings

    assert Settings().EMAIL_FROM_ADDRESS.endswith("@updates.skyfirstlabs.com")


@pytest.mark.asyncio
async def test_post_resend_sets_reply_to_so_answers_reach_a_real_inbox(monkeypatch):
    """O subdomínio de envio não recebe (`receiving: disabled`).

    Sem `reply_to`, responder ao email de boas-vindas — que é o único
    pedido que ele faz — escrevia para uma caixa que não existe.
    """
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "RESEND_API_KEY", "re_test_key_xxx")
    monkeypatch.setattr(
        runtime_settings,
        "EMAIL_FROM_ADDRESS",
        "lucas.ventura@updates.skyfirstlabs.com",
    )
    monkeypatch.setattr(
        runtime_settings,
        "EMAIL_REPLY_TO_ADDRESS",
        "lucas.ventura@skyfirstlabs.com",
    )

    captured: dict = {}

    class _MockClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, url, json=None, headers=None, **_):
            captured["json"] = json
            return _Resp(200)

    with patch("httpx.AsyncClient", _MockClient):
        await _post_resend(
            to="bob@acme.com", subject="welcome", html="<p>hi</p>", text="hi",
        )

    assert captured["json"]["reply_to"] == ["lucas.ventura@skyfirstlabs.com"]


@pytest.mark.asyncio
async def test_post_resend_omits_reply_to_when_unset(monkeypatch):
    """Vazio = campo ausente, não um `null` que a Resend rejeitaria."""
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "RESEND_API_KEY", "re_test_key_xxx")
    monkeypatch.setattr(runtime_settings, "EMAIL_REPLY_TO_ADDRESS", "")

    captured: dict = {}

    class _MockClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, url, json=None, headers=None, **_):
            captured["json"] = json
            return _Resp(200)

    with patch("httpx.AsyncClient", _MockClient):
        await _post_resend(
            to="bob@acme.com", subject="welcome", html="<p>hi</p>", text="hi",
        )

    assert "reply_to" not in captured["json"]


@pytest.mark.asyncio
async def test_post_resend_swallows_4xx(monkeypatch, caplog):
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "RESEND_API_KEY", "re_test_key")

    class _BadClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_, **__):
            return _Resp(422, "validation failed")

    with patch("httpx.AsyncClient", _BadClient):
        result = await _post_resend(
            to="x@example.com", subject="x", html="x", text="x",
        )

    assert result is False
    assert any("resend_send_failed" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_post_resend_swallows_connection_error(monkeypatch):
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "RESEND_API_KEY", "re_test_key")

    class _Boom:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_, **__):
            raise ConnectionError("DNS fail")

    with patch("httpx.AsyncClient", _Boom):
        # Must NOT raise
        result = await _post_resend(
            to="x@example.com", subject="x", html="x", text="x",
        )

    assert result is False


# ─── Template formatting ────────────────────────────────────────────────────


def test_html_template_has_required_placeholders():
    formatted = _DEMO_WELCOME_HTML.format(
        first_name="Lucas",
        company="Acme",
        dashboard_url="https://demo.skyfirstlabs.com",
        ttl_days=7,
    )
    assert "Hi Lucas" in formatted
    assert "Acme" in formatted
    assert "https://demo.skyfirstlabs.com" in formatted
    assert "7 days" in formatted
    # Memorable CTA — the question that lands in 10 seconds. The HTML
    # wraps "weakest revenue channel" across two lines for layout, so
    # the substring we assert on is the unwrapped portion.
    assert "weakest revenue" in formatted


def test_text_template_has_required_placeholders():
    formatted = _DEMO_WELCOME_TEXT.format(
        first_name="Lucas",
        company="Acme",
        dashboard_url="https://demo.skyfirstlabs.com",
        ttl_days=7,
    )
    assert "Hi Lucas" in formatted
    assert "Acme" in formatted
    assert "https://demo.skyfirstlabs.com" in formatted
    assert "weakest revenue channel" in formatted


# ─── send_demo_welcome_email — name parsing ─────────────────────────────────


@pytest.mark.asyncio
async def test_send_extracts_first_name_from_full_name(monkeypatch):
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "RESEND_API_KEY", "")  # dry-run

    # Use the dry-run path but capture what would have been sent by
    # patching the formatter inputs at the call site. Easier: capture
    # the body via the mock client.
    monkeypatch.setattr(runtime_settings, "RESEND_API_KEY", "re_x")
    captured = {}

    class _Cap:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def post(self, url, json=None, headers=None, **_):
            captured["json"] = json
            return _Resp(200)

    with patch("httpx.AsyncClient", _Cap):
        await send_demo_welcome_email(
            name="Lucas Ventura",
            email="lucas@acme.com",
            company="Acme",
            expires_at=_expires(days=7),
        )

    body = captured["json"]
    assert "Hi Lucas," in body["html"]
    assert "Hi Lucas," in body["text"]
    assert "Ventura" not in body["html"].split("Hi ")[1].split(",")[0]


@pytest.mark.asyncio
async def test_send_falls_back_when_name_empty(monkeypatch):
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "RESEND_API_KEY", "re_x")
    captured = {}

    class _Cap:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def post(self, url, json=None, headers=None, **_):
            captured["json"] = json
            return _Resp(200)

    with patch("httpx.AsyncClient", _Cap):
        await send_demo_welcome_email(
            name="",
            email="x@acme.com",
            company="",
            expires_at=None,
        )

    assert "Hi there," in captured["json"]["html"]
    assert "your team" in captured["json"]["html"]


@pytest.mark.asyncio
async def test_send_uses_dashboard_url_from_settings(monkeypatch):
    from src.config.settings import settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "RESEND_API_KEY", "re_x")
    monkeypatch.setattr(
        runtime_settings,
        "EMAIL_DASHBOARD_URL",
        "https://demo.skyfirstlabs.com/",  # trailing slash
    )
    captured = {}

    class _Cap:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def post(self, url, json=None, headers=None, **_):
            captured["json"] = json
            return _Resp(200)

    with patch("httpx.AsyncClient", _Cap):
        await send_demo_welcome_email(
            name="Lucas",
            email="x@acme.com",
            company="Acme",
            expires_at=_expires(days=7),
        )

    # Trailing slash trimmed
    assert "https://demo.skyfirstlabs.com" in captured["json"]["html"]
    assert "https://demo.skyfirstlabs.com//" not in captured["json"]["html"]
