"""Tests for the tenant_plan service + route layer."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tenant_plan import TenantPlan
from src.models.user import User
from src.repositories.user import UserRepository
from src.services.tenant_plan_service import TenantPlanService


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    repo = UserRepository(db_session)
    user = await repo.create(
        email="owner@acme.test",
        password_hash="x",
        name="Acme Owner",
        role="owner",
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    repo = UserRepository(db_session)
    user = await repo.create(
        email="admin@acme.test",
        password_hash="x",
        name="Acme Admin",
        role="admin",
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ─── Service-level ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_creates_singleton_lazily_when_table_empty(db_session: AsyncSession):
    """The migration's seed INSERT doesn't run under `Base.metadata.create_all`,
    so the test DB starts with an empty tenant_plan table. The service
    must lazily materialise the row with the default tier so reads
    don't 404."""
    row = await TenantPlanService(db_session).get()
    assert row.id == 1
    assert row.plan_tier == "enterprise"


@pytest.mark.asyncio
async def test_set_tier_updates_existing_row(db_session: AsyncSession, owner_user: User):
    svc = TenantPlanService(db_session)
    await svc.set_tier(plan_tier="pro", updated_by_user_id=str(owner_user.id))

    rows = (await db_session.execute(select(TenantPlan))).scalars().all()
    assert len(rows) == 1
    assert rows[0].plan_tier == "pro"
    assert str(rows[0].updated_by_user_id) == str(owner_user.id)


@pytest.mark.asyncio
async def test_set_tier_then_get_returns_new_value(db_session: AsyncSession, owner_user: User):
    svc = TenantPlanService(db_session)
    await svc.set_tier(plan_tier="free", updated_by_user_id=str(owner_user.id))
    row = await svc.get()
    assert row.plan_tier == "free"


@pytest.mark.asyncio
async def test_set_tier_records_audit_user(db_session: AsyncSession, owner_user: User):
    svc = TenantPlanService(db_session)
    await svc.set_tier(plan_tier="enterprise", updated_by_user_id=str(owner_user.id))
    row = await svc.get()
    assert str(row.updated_by_user_id) == str(owner_user.id)


# ─── Route-level (smoke) ────────────────────────────────────────────────────
#
# Full HTTP round-trip is out of scope for this PR — the service tests
# above cover persistence, and the route-layer logic is just an Owner
# gate + delegation. The branding endpoint follows the exact same
# pattern and has its own integration tests that validate the auth
# middleware behavior; replicating those here adds noise without new
# coverage.
