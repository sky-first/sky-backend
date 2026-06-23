"""Tests for ``src.api.console_auth`` (Projeto B B#3)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

_ = SimpleNamespace  # used by test_require_sky_team_*; silence unused-import linter

from src.api.console_auth import (
    _allowed_email_set,
    _dev_bypass_enabled,
    audit_action,
    audited,
    is_sky_team_member,
    role_for,
)
from src.models.internal_console import (
    AuditAction,
    AuditResult,
    InternalConsoleAudit,
)
from src.models.user import User


def _user(email: str = "x@skyfirstlabs.com", is_sky_op: bool = False) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        password_hash="",
        name="x",
        role="user",
        email_verified=True,
        has_completed_onboarding=True,
        is_sky_operator=is_sky_op,
    )


def _request_with_host(host: str = "console-stg.skyfirstlabs.com"):
    """Fabricate a minimal Request stand-in carrying a Host header so
    ``_assert_console_host`` (the first guard inside
    ``require_sky_team``) lets the call through.

    Tests that exercise the auth/role logic should pass an allowed
    host here; tests that want to assert the host-gate itself can pass
    a forbidden one.
    """
    return SimpleNamespace(
        headers={"host": host},
        url=SimpleNamespace(hostname=host, path="/api/console/v1/me"),
    )


# ── is_sky_team_member ─────────────────────────────────────────────


def test_is_sky_operator_true_grants_access(monkeypatch):
    monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("CONSOLE_DEV_BYPASS", raising=False)
    assert is_sky_team_member(_user(is_sky_op=True)) is True


def test_email_in_allowlist_grants_access(monkeypatch):
    monkeypatch.setenv("CONSOLE_ALLOWED_EMAILS", "lucas@skyfirstlabs.com,paulo@skyfirstlabs.com")
    monkeypatch.delenv("CONSOLE_DEV_BYPASS", raising=False)
    assert is_sky_team_member(_user(email="lucas@skyfirstlabs.com")) is True
    assert is_sky_team_member(_user(email="PAULO@skyfirstlabs.com")) is True  # case-insensitive
    assert is_sky_team_member(_user(email="outsider@example.com")) is False


def test_dev_bypass_grants_access_in_dev(monkeypatch):
    from src.config.settings import settings

    monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
    monkeypatch.setenv("CONSOLE_DEV_BYPASS", "true")
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    assert is_sky_team_member(_user(email="outsider@example.com")) is True


def test_dev_bypass_does_NOT_grant_in_production(monkeypatch):
    from src.config.settings import settings

    monkeypatch.setenv("CONSOLE_DEV_BYPASS", "true")
    monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert is_sky_team_member(_user(email="outsider@example.com")) is False


def test_dev_bypass_does_NOT_grant_in_staging(monkeypatch):
    """Gap #5 from the 2026-05-30 security posture audit. Staging is a
    public host with real tenant data — the dev bypass must be local
    only."""
    from src.config.settings import settings

    monkeypatch.setenv("CONSOLE_DEV_BYPASS", "true")
    monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    assert is_sky_team_member(_user(email="outsider@example.com")) is False


def test_default_user_is_denied(monkeypatch):
    monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("CONSOLE_DEV_BYPASS", raising=False)
    assert is_sky_team_member(_user()) is False


# ── require_sky_team ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_require_sky_team_raises_403_for_outsider(monkeypatch):
    from src.api import console_auth

    monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("CONSOLE_DEV_BYPASS", raising=False)

    outsider = _user(email="outsider@example.com")

    async def _fake_get_current_user(**_kwargs):
        return outsider

    monkeypatch.setattr(console_auth, "get_current_user", _fake_get_current_user)

    with pytest.raises(HTTPException) as info:
        await console_auth.require_sky_team(
            request=_request_with_host("console-stg.skyfirstlabs.com")
        )
    assert info.value.status_code == 403
    assert info.value.detail["error"] == "sky_team_required"


@pytest.mark.asyncio
async def test_require_sky_team_passes_for_sky_operator(monkeypatch):
    from src.api import console_auth

    user = _user(is_sky_op=True)

    async def _fake_get_current_user(**_kwargs):
        return user

    monkeypatch.setattr(console_auth, "get_current_user", _fake_get_current_user)
    returned = await console_auth.require_sky_team(
        request=_request_with_host("console-stg.skyfirstlabs.com")
    )
    assert returned is user


@pytest.mark.asyncio
async def test_require_sky_team_rejects_404_on_main_app_host(monkeypatch):
    """Even a real Sky-team operator hitting /api/console/v1/* from the
    main customer host gets 404 — the host gate runs first so the
    operator surface is invisible outside its dedicated subdomain."""
    from src.api import console_auth

    user = _user(is_sky_op=True)

    async def _fake_get_current_user(**_kwargs):
        return user

    monkeypatch.setattr(console_auth, "get_current_user", _fake_get_current_user)
    monkeypatch.delenv("CONSOLE_ALLOWED_HOSTS", raising=False)
    with pytest.raises(HTTPException) as info:
        await console_auth.require_sky_team(
            request=_request_with_host("sky-stg.skyfirstlabs.com")
        )
    assert info.value.status_code == 404


# Move helper before the original tests so they can use it.


# ── role_for ───────────────────────────────────────────────────────


def test_role_admin(monkeypatch):
    monkeypatch.setenv("CONSOLE_ADMIN_EMAILS", "lucas@skyfirstlabs.com")
    monkeypatch.delenv("CONSOLE_OPERATOR_EMAILS", raising=False)
    assert role_for(_user(email="lucas@skyfirstlabs.com")) == "admin"


def test_role_operator_resolves_to_support(monkeypatch):
    # The ladder renamed ``operator`` → ``support`` (more meaningful in
    # the customer-facing context); the env var name is kept for
    # back-compat so old deployments do not break.
    monkeypatch.delenv("CONSOLE_ADMIN_EMAILS", raising=False)
    monkeypatch.setenv("CONSOLE_OPERATOR_EMAILS", "paulo@skyfirstlabs.com")
    assert role_for(_user(email="paulo@skyfirstlabs.com")) == "support"


def test_role_default_read_only(monkeypatch):
    monkeypatch.delenv("CONSOLE_ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("CONSOLE_OPERATOR_EMAILS", raising=False)
    assert role_for(_user(email="x@skyfirstlabs.com")) == "read_only"


# ── audit_action ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_action_writes_row(db_session):
    actor = _user(email="lucas@skyfirstlabs.com", is_sky_op=True)
    await audit_action(
        db_session,
        actor=actor,
        action=AuditAction.VIEW_TENANT,
        tenant_slug="gbt",
        result=AuditResult.SUCCESS,
        request_payload={"x": 1},
        actor_ip="10.0.0.1",
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            select(InternalConsoleAudit).where(
                InternalConsoleAudit.actor_email == "lucas@skyfirstlabs.com"
            )
        )
    ).scalar_one()
    assert row.action == "view_tenant"
    assert row.tenant_slug == "gbt"
    assert row.result == "success"


@pytest.mark.asyncio
async def test_audit_action_swallows_errors(db_session):
    """If the insert fails, the helper logs and continues — must not raise."""
    # Pass a payload that breaks the CHECK constraint indirectly by
    # corrupting the session would be complex. Instead use a fake
    # session that explodes on .add() — the helper must still return
    # without raising.
    class _ExplodingSession:
        def add(self, *_):
            raise RuntimeError("simulated DB error")

        async def flush(self):  # pragma: no cover — never reached
            return None

    fake = _ExplodingSession()
    actor = _user()
    # Should not raise.
    await audit_action(
        fake,
        actor=actor,
        action=AuditAction.VIEW_TENANT,
        tenant_slug="x",
        result=AuditResult.SUCCESS,
    )


# ── audited decorator ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audited_records_success(db_session):
    actor = _user(email="x@skyfirstlabs.com", is_sky_op=True)

    @audited(AuditAction.UPDATE_TENANT, tenant_kwarg="slug")
    async def handler(*, request, user, db, slug, payload=None):
        return {"ok": True, "slug": slug}

    request = SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"))
    payload = SimpleNamespace(
        model_dump=lambda: {"display_name": "X", "secret": "shouldredact"}
    )
    result = await handler(
        request=request, user=actor, db=db_session, slug="gbt", payload=payload
    )
    assert result == {"ok": True, "slug": "gbt"}
    await db_session.commit()

    row = (
        await db_session.execute(
            select(InternalConsoleAudit).where(
                InternalConsoleAudit.tenant_slug == "gbt"
            )
        )
    ).scalar_one()
    assert row.action == "update_tenant"
    assert row.result == "success"
    assert row.actor_ip == "1.2.3.4"
    # secret-key redacted
    assert row.request_payload["secret"] == "***REDACTED***"


@pytest.mark.asyncio
async def test_audited_records_failure_on_http_exception(db_session):
    actor = _user(email="x@skyfirstlabs.com", is_sky_op=True)

    @audited(AuditAction.SUSPEND_TENANT)
    async def handler(*, request, user, db, slug):
        raise HTTPException(status_code=404, detail="not found")

    request = SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"))
    with pytest.raises(HTTPException):
        await handler(request=request, user=actor, db=db_session, slug="ghost")
    await db_session.commit()

    row = (
        await db_session.execute(
            select(InternalConsoleAudit).where(
                InternalConsoleAudit.tenant_slug == "ghost"
            )
        )
    ).scalar_one()
    assert row.action == "suspend_tenant"
    assert row.result == "failure"
    assert row.result_details["status_code"] == 404


# ── Console host isolation ─────────────────────────────────────────


def test_assert_console_host_accepts_default_console_subdomains(monkeypatch):
    from src.api.console_auth import _assert_console_host

    monkeypatch.delenv("CONSOLE_ALLOWED_HOSTS", raising=False)
    for host in (
        "console.skyfirstlabs.com",
        "console-stg.skyfirstlabs.com",
        "localhost",
        "127.0.0.1",
    ):
        _assert_console_host(_request_with_host(host))  # no raise


def test_assert_console_host_strips_port(monkeypatch):
    from src.api.console_auth import _assert_console_host

    monkeypatch.delenv("CONSOLE_ALLOWED_HOSTS", raising=False)
    _assert_console_host(_request_with_host("console-stg.skyfirstlabs.com:443"))


def test_assert_console_host_rejects_main_app_host_with_404(monkeypatch):
    """A customer landing on sky-stg.skyfirstlabs.com must not even
    learn the Console exists. 404 (not 403) is intentional."""
    from src.api.console_auth import _assert_console_host

    monkeypatch.delenv("CONSOLE_ALLOWED_HOSTS", raising=False)
    with pytest.raises(HTTPException) as exc:
        _assert_console_host(_request_with_host("sky-stg.skyfirstlabs.com"))
    assert exc.value.status_code == 404


def test_assert_console_host_rejects_arbitrary_attacker_host(monkeypatch):
    from src.api.console_auth import _assert_console_host

    monkeypatch.delenv("CONSOLE_ALLOWED_HOSTS", raising=False)
    for host in (
        "attacker.example.com",
        "skyfirstlabs.com.attacker.com",  # subdomain spoof
        "sky-prd.skyfirstlabs.com",
        "demo.skyfirstlabs.com",
    ):
        with pytest.raises(HTTPException) as exc:
            _assert_console_host(_request_with_host(host))
        assert exc.value.status_code == 404, host


def test_assert_console_host_honours_env_override(monkeypatch):
    """``CONSOLE_ALLOWED_HOSTS=`` env replaces the default set entirely
    so an operator can lock the Console down to a single host in prod."""
    from src.api.console_auth import _assert_console_host

    monkeypatch.setenv("CONSOLE_ALLOWED_HOSTS", "ops.example.com")
    _assert_console_host(_request_with_host("ops.example.com"))  # allowed
    # Defaults are dropped when env is non-empty — even console.* gets 404.
    with pytest.raises(HTTPException) as exc:
        _assert_console_host(_request_with_host("console-stg.skyfirstlabs.com"))
    assert exc.value.status_code == 404
