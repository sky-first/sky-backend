"""Test the public demo signup flow.

Anti-fraud (the user explicitly called these out):
  • Captcha required (Turnstile)
  • Per-IP rate limit
  • Throwaway email block
  • Schema-level field shape validation
  • DEMO_ENABLED gate
  • Returning visitor returns existing sandbox (no duplicate Spaces)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.models.space import Space
from src.models.user import User
from src.schemas.demo import DemoSignupRequest
from src.services import demo_service
from src.services.demo_service import (
    DemoService,
    cleanup_expired_demo_spaces,
)


def _ok_payload(**overrides: Any) -> DemoSignupRequest:
    base = {
        "name": "Lucas Ventura",
        "email": "lucas@acme.com",
        "company": "Acme Corp",
        "role": "Director",
        "turnstile_token": "stub-ok-token",
    }
    base.update(overrides)
    return DemoSignupRequest(**base)


@pytest.fixture(autouse=True)
def _enable_demo_and_skip_captcha(monkeypatch: pytest.MonkeyPatch):
    """Each test runs with demo enabled, captcha bypassed, and the
    rate-limit forced onto the in-memory backend (Redis would persist
    counters across tests and make assertions flaky)."""
    monkeypatch.setattr(settings, "DEMO_ENABLED", True)
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", "")  # empty → skip verify
    monkeypatch.setattr(settings, "DEMO_RATE_LIMIT_PER_IP_PER_HOUR", 100)
    monkeypatch.setattr(settings, "DEMO_TTL_DAYS", 7)
    monkeypatch.setattr(settings, "DEMO_DATASET_CONNECTION_ID", "")
    monkeypatch.setattr(settings, "REDIS_URL", "")  # force in-memory fallback
    # Reset the in-memory IP rate-limit dict so tests don't leak hits.
    demo_service._IP_SIGNUP_HITS.clear()
    yield
    demo_service._IP_SIGNUP_HITS.clear()


@pytest.mark.asyncio
async def test_signup_creates_user_space_and_member(db_session: AsyncSession):
    service = DemoService(db_session)
    resp = await service.signup(_ok_payload(), client_ip="1.2.3.4")

    assert resp.access_token
    assert resp.refresh_token
    assert resp.is_returning is False
    assert resp.user.email == "lucas@acme.com"

    user_q = await db_session.execute(select(User).where(User.email == "lucas@acme.com"))
    user = user_q.scalar_one()
    assert user.is_demo is True
    assert user.demo_expires_at is not None

    space_q = await db_session.execute(select(Space).where(Space.id == user.id))
    # Use created_by since space.id != user.id
    space_q = await db_session.execute(select(Space).where(Space.created_by == user.id))
    space = space_q.scalar_one()
    assert space.is_demo is True
    assert space.demo_expires_at == user.demo_expires_at
    assert "Demo — Acme Corp" in space.name


@pytest.mark.asyncio
async def test_signup_provisions_default_personal_page(db_session: AsyncSession):
    """Lucas's 2026-05-05 review: pure-API callers (smoke tests, our
    QA, partners) used to hit `No active page found for user` on the
    first /ai/query because /demo/signup never invoked the onboarding
    helper. The FE worked around it by creating a page on dashboard
    mount, but anyone bypassing the FE was stuck. This pins the fix.
    """
    from src.repositories.page import PageRepository

    service = DemoService(db_session)
    resp = await service.signup(_ok_payload(), client_ip="2.2.2.2")

    user_q = await db_session.execute(select(User).where(User.email == resp.user.email))
    user = user_q.scalar_one()

    pages = await PageRepository(db_session).get_by_owner(user.id)
    assert pages, "demo signup must create at least one Personal page"
    assert pages[0].owner_id == user.id
    assert pages[0].type == "personal"


@pytest.mark.asyncio
async def test_signup_rejects_when_demo_disabled(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "DEMO_ENABLED", False)
    service = DemoService(db_session)
    with pytest.raises(Exception) as exc:
        await service.signup(_ok_payload(), client_ip="1.2.3.4")
    assert "disabled" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_signup_rate_limits_per_ip(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "DEMO_RATE_LIMIT_PER_IP_PER_HOUR", 2)
    service = DemoService(db_session)

    await service.signup(_ok_payload(email="a@acme.com"), client_ip="9.9.9.9")
    await service.signup(_ok_payload(email="b@acme.com"), client_ip="9.9.9.9")
    with pytest.raises(Exception) as exc:
        await service.signup(_ok_payload(email="c@acme.com"), client_ip="9.9.9.9")
    assert "too many" in str(exc.value).lower()

    # A different IP is unaffected.
    await service.signup(_ok_payload(email="d@acme.com"), client_ip="8.8.8.8")


@pytest.mark.asyncio
async def test_signup_rejects_invalid_captcha(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", "test-secret-not-empty")

    async def _fake_verify(token: str, remoteip: str | None) -> bool:
        return False

    monkeypatch.setattr(demo_service, "_verify_turnstile", _fake_verify)

    service = DemoService(db_session)
    with pytest.raises(Exception) as exc:
        await service.signup(_ok_payload(), client_ip="1.2.3.4")
    assert "captcha" in str(exc.value).lower()


def test_throwaway_emails_blocked_by_schema():
    with pytest.raises(ValueError) as exc:
        DemoSignupRequest(
            name="Bot",
            email="bot@mailinator.com",
            company="Acme",
            turnstile_token="x",
        )
    assert "work email" in str(exc.value).lower()


def test_schema_rejects_garbage_name_and_company():
    with pytest.raises(ValueError):
        DemoSignupRequest(
            name="<<<>>>",  # garbage
            email="ok@acme.com",
            company="Acme",
            turnstile_token="x",
        )
    with pytest.raises(ValueError):
        DemoSignupRequest(
            name="Lucas",
            email="ok@acme.com",
            company="x",  # too short (>= 2 OK; 1 char is rejected by min_length)
            turnstile_token="x",
        )


@pytest.mark.asyncio
async def test_returning_visitor_gets_existing_sandbox(db_session: AsyncSession):
    service = DemoService(db_session)
    first = await service.signup(_ok_payload(), client_ip="1.2.3.4")
    second = await service.signup(_ok_payload(), client_ip="1.2.3.4")

    assert second.is_returning is True
    assert second.space_id == first.space_id

    # Only ONE Space, ONE User in DB despite two signup calls.
    space_q = await db_session.execute(select(Space).where(Space.is_demo.is_(True)))
    assert len(space_q.scalars().all()) == 1
    user_q = await db_session.execute(select(User).where(User.is_demo.is_(True)))
    assert len(user_q.scalars().all()) == 1


@pytest.mark.asyncio
async def test_signup_refuses_real_user_email(db_session: AsyncSession):
    """If the email already belongs to a real (SSO) user, we MUST NOT
    issue a demo JWT under their identity."""
    real = User(
        email="real@bigcorp.com",
        password_hash="x",
        name="Real Person",
        role="user",
        is_demo=False,
    )
    db_session.add(real)
    await db_session.commit()

    service = DemoService(db_session)
    with pytest.raises(Exception) as exc:
        await service.signup(_ok_payload(email="real@bigcorp.com"), client_ip="1.2.3.4")
    assert "already registered" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_cleanup_deletes_expired_spaces_and_users(db_session: AsyncSession):
    past = datetime.now(timezone.utc) - timedelta(days=1)

    # Past-expiry guest user + space (will be deleted)
    expired_user = User(
        email="expired@acme.com",
        password_hash="x",
        name="Expired",
        role="user",
        is_demo=True,
        demo_expires_at=past,
    )
    db_session.add(expired_user)
    await db_session.flush()
    expired_space = Space(
        name="Demo — Old",
        created_by=expired_user.id,
        is_demo=True,
        demo_expires_at=past,
    )
    db_session.add(expired_space)
    await db_session.commit()

    # Future-expiry guest user + space (must survive)
    future = datetime.now(timezone.utc) + timedelta(days=5)
    keep_user = User(
        email="keep@acme.com",
        password_hash="x",
        name="Keep",
        role="user",
        is_demo=True,
        demo_expires_at=future,
    )
    db_session.add(keep_user)
    await db_session.flush()
    keep_space = Space(
        name="Demo — Fresh",
        created_by=keep_user.id,
        is_demo=True,
        demo_expires_at=future,
    )
    db_session.add(keep_space)
    await db_session.commit()

    spaces_deleted, users_deleted = await cleanup_expired_demo_spaces(db_session)
    assert spaces_deleted == 1
    assert users_deleted == 1

    survivors = await db_session.execute(select(Space).where(Space.is_demo.is_(True)))
    assert len(survivors.scalars().all()) == 1
    survivors_u = await db_session.execute(select(User).where(User.is_demo.is_(True)))
    assert len(survivors_u.scalars().all()) == 1


@pytest.mark.asyncio
async def test_signup_seeds_three_demo_agents(db_session: AsyncSession):
    """Lucas's 2026-05-05 QA: a fresh demo Space must come pre-loaded with
    3 ready-to-run agents so the Pulse pill has signal to render and the
    Set-up-Agent mission has a working entry point. Returning logins are
    a no-op (the helper is idempotent) and DO NOT mint duplicates."""
    from src.models.agent import Agent

    service = DemoService(db_session)
    resp = await service.signup(_ok_payload(), client_ip="1.2.3.4")

    agents_q = await db_session.execute(
        select(Agent).where(Agent.scope == "space", Agent.scope_id == resp.space_id)
    )
    agents = agents_q.scalars().all()
    assert len(agents) == 3, f"expected 3 demo agents, got {len(agents)}"

    names = {a.name for a in agents}
    assert names == {"Revenue Pulse", "Customer Health Watch", "Operations Radar"}

    for a in agents:
        assert a.status == "active"
        assert a.created_by == resp.user.id
        assert a.scope == "space"
        assert a.monitor_type == "question"
        assert a.focus and len(a.focus) > 20

    # Returning login must not duplicate the agents.
    await service.signup(_ok_payload(), client_ip="1.2.3.4")
    again_q = await db_session.execute(
        select(Agent).where(Agent.scope == "space", Agent.scope_id == resp.space_id)
    )
    assert len(again_q.scalars().all()) == 3, "returning login duplicated the agents"


@pytest.mark.asyncio
async def test_signup_endpoint_integration(client, monkeypatch: pytest.MonkeyPatch):
    """End-to-end through FastAPI with the real router wiring."""
    monkeypatch.setattr(settings, "DEMO_ENABLED", True)
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", "")
    monkeypatch.setattr(settings, "DEMO_RATE_LIMIT_PER_IP_PER_HOUR", 100)
    demo_service._IP_SIGNUP_HITS.clear()

    resp = client.post(
        "/api/v1/demo/signup",
        json={
            "name": "Lucas Ventura",
            "email": "lucas@acme.com",
            "company": "Acme Corp",
            "role": "Director",
            "turnstile_token": "stub-ok",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["space_id"]
    assert body["is_returning"] is False


# ─── SSO opt-in: provision_for_existing_user ────────────────────────────────


def _as_uuid(s):
    """SQLAlchemy 2.x's UUID type binds the column with .hex on the raw
    value, which means passing a stringified UUID into a `==` comparison
    crashes mid-bind. Coerce back to uuid.UUID for queries."""
    import uuid as _uuid
    return _uuid.UUID(s) if isinstance(s, str) else s


@pytest.mark.asyncio
async def test_provision_for_existing_user_creates_demo_space_and_seeds(
    db_session: AsyncSession,
):
    """First call mints a 'Demo Sky' Space owned by the user, with the
    same baseline content (Glossary, Metrics, Relationships, Agents) a
    public /demo/signup visitor receives — but **without** a TTL,
    because this is opt-in exploration, not anti-fraud."""
    from src.core.security import get_password_hash
    from src.models.glossary import GlossaryTerm
    from src.models.metric import Metric

    user = User(
        email="sso-user@skyfirstlabs.com",
        password_hash=get_password_hash("placeholder"),
        name="SSO User",
        role="user",
        email_verified=True,
        is_demo=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    service = DemoService(db_session)
    result = await service.provision_for_existing_user(user)

    assert result["is_new"] is True
    assert result["space_name"] == "Demo Sky"
    assert result["seeded"]["glossary"] > 0
    assert result["seeded"]["metrics"] > 0

    space = (await db_session.execute(
        select(Space).where(Space.id == _as_uuid(result["space_id"]))
    )).scalar_one()
    assert space.is_demo is True
    # Critical: opt-in flow has NO TTL — cleanup_expired_demo_spaces must
    # not reap a space the user explicitly chose to create.
    assert space.demo_expires_at is None
    assert space.created_by == user.id

    # Seed actually landed in Lucas's space (not in some shared scope).
    metrics_in_space = (await db_session.execute(
        select(Metric).where(
            Metric.scope == "space",
            Metric.scope_id == space.id,
        )
    )).scalars().all()
    assert len(metrics_in_space) == result["seeded"]["metrics"]

    glossary_in_space = (await db_session.execute(
        select(GlossaryTerm).where(GlossaryTerm.space_id == space.id)
    )).scalars().all()
    assert len(glossary_in_space) == result["seeded"]["glossary"]


@pytest.mark.asyncio
async def test_provision_for_existing_user_is_idempotent(db_session: AsyncSession):
    """Second call must not mint a second 'Demo Sky' Space — that would
    leave the user with N copies after every modal click. Reuses the
    existing one and reports is_new=False with zero seed deltas."""
    from src.core.security import get_password_hash

    user = User(
        email="sso-idempotent@skyfirstlabs.com",
        password_hash=get_password_hash("placeholder"),
        name="SSO User",
        role="user",
        email_verified=True,
        is_demo=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    service = DemoService(db_session)
    first = await service.provision_for_existing_user(user)
    second = await service.provision_for_existing_user(user)

    assert first["is_new"] is True
    assert second["is_new"] is False
    assert second["space_id"] == first["space_id"]
    # Re-run finds everything already seeded — counts are 0.
    assert second["seeded"] == {"glossary": 0, "metrics": 0, "relationships": 0}
    assert second["agents_added"] == 0

    # Exactly one Space, not two.
    spaces = (await db_session.execute(
        select(Space).where(
            Space.created_by == user.id,
            Space.name == "Demo Sky",
            Space.deleted_at.is_(None),
        )
    )).scalars().all()
    assert len(spaces) == 1


@pytest.mark.asyncio
async def test_personal_demo_status_and_removal(db_session: AsyncSession):
    """Status reports counts; remove cleans up the Space + the
    Glossary/Metrics scoped to it (FK on scope_id is informational,
    not a real CASCADE, so the service must delete them by hand)."""
    from src.core.security import get_password_hash
    from src.models.glossary import GlossaryTerm
    from src.models.metric import Metric

    user = User(
        email="sso-cleanup@skyfirstlabs.com",
        password_hash=get_password_hash("placeholder"),
        name="SSO User",
        role="user",
        email_verified=True,
        is_demo=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    service = DemoService(db_session)

    # Pre-state: nothing yet.
    pre = await service.get_personal_demo_status(user)
    assert pre["has_demo_space"] is False
    assert pre["metrics_count"] == 0
    assert pre["glossary_count"] == 0

    # Provision then re-check status.
    provisioned = await service.provision_for_existing_user(user)
    status = await service.get_personal_demo_status(user)
    assert status["has_demo_space"] is True
    assert status["space_id"] == provisioned["space_id"]
    assert status["metrics_count"] >= 1
    assert status["glossary_count"] >= 1

    # Remove and verify the Space + scoped Knowledge are gone.
    removed = await service.remove_personal_demo_workspace(user)
    assert removed["removed"] is True
    assert removed["space_id"] == provisioned["space_id"]
    assert removed["deleted"]["metrics"] >= 1
    assert removed["deleted"]["glossary"] >= 1

    # Space row is gone.
    space_uuid = _as_uuid(provisioned["space_id"])
    assert (await db_session.execute(
        select(Space).where(Space.id == space_uuid)
    )).scalar_one_or_none() is None

    # Knowledge scoped to that space is gone too (no orphans).
    leftover_metrics = (await db_session.execute(
        select(Metric).where(
            Metric.scope == "space",
            Metric.scope_id == space_uuid,
        )
    )).scalars().all()
    assert leftover_metrics == []
    leftover_glossary = (await db_session.execute(
        select(GlossaryTerm).where(GlossaryTerm.space_id == space_uuid)
    )).scalars().all()
    assert leftover_glossary == []

    # Idempotent re-call: nothing left to remove.
    again = await service.remove_personal_demo_workspace(user)
    assert again["removed"] is False
    assert again["space_id"] is None
