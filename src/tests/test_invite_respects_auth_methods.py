"""Invite flow must honour the tenant's ``auth_methods`` config.

Lucas surfaced the gap (2026-05-30): the invite endpoint sent the
accept-invite email regardless of SSO config, so an invitee on a
Google-only workspace would set a password they could never use to
log in. These tests pin the new ``_assert_password_invite_allowed``
guard against both branches: when the tenant has ``password=true``
the helper is a no-op, and when it's disabled the helper raises with
the SSO-only copy the FE will surface.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import BadRequestError
from src.services.user_service import UserService


def _service_with_tenant(auth_methods: dict | None) -> UserService:
    svc = UserService.__new__(UserService)
    svc.db = MagicMock()

    class _Row:
        def __init__(self, value):
            self._value = value

        def first(self):
            return (self._value,) if self._value is not None else None

    svc.db.execute = AsyncMock(return_value=_Row(auth_methods))
    return svc


@pytest.mark.asyncio
async def test_password_allowed_passes_silently(monkeypatch):
    svc = _service_with_tenant({"password": True, "google": True})
    monkeypatch.setattr(
        "src.core.tenant_context.current_tenant",
        lambda: MagicMock(slug="alpha"),
    )
    # Should NOT raise.
    await svc._assert_password_invite_allowed()


@pytest.mark.asyncio
async def test_password_disabled_raises_sso_only_message(monkeypatch):
    svc = _service_with_tenant({"password": False, "google": True})
    monkeypatch.setattr(
        "src.core.tenant_context.current_tenant",
        lambda: MagicMock(slug="alpha"),
    )
    with pytest.raises(BadRequestError) as info:
        await svc._assert_password_invite_allowed()
    assert "SSO" in str(info.value)


@pytest.mark.asyncio
async def test_default_methods_floor_blocks_when_no_tenant(monkeypatch):
    """Single-tenant deployments without a resolver fall through to
    ``DEFAULT_AUTH_METHODS`` (Google-only). Invite must refuse there
    too — that's how we avoid silently breaking POC environments."""
    svc = UserService.__new__(UserService)
    svc.db = MagicMock()
    monkeypatch.setattr(
        "src.core.tenant_context.current_tenant",
        lambda: None,
    )
    with pytest.raises(BadRequestError):
        await svc._assert_password_invite_allowed()


@pytest.mark.asyncio
async def test_get_current_tenant_context_raising_does_not_crash(monkeypatch):
    """The ``get_current_tenant_context`` helper raises in some startup
    paths (no contextvar set). The guard should swallow that and fall
    back to the default floor rather than 500."""
    svc = UserService.__new__(UserService)
    svc.db = MagicMock()
    def _raise() -> None:
        raise RuntimeError("no context set")
    monkeypatch.setattr(
        "src.core.tenant_context.current_tenant", _raise
    )
    with pytest.raises(BadRequestError):
        await svc._assert_password_invite_allowed()
