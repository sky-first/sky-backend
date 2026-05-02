"""BeatsService — unit tests for quota check + consumption recording.

Coverage matrix:
  • cost_for_kind returns the right beat amount for known kinds
  • cost_for_kind defaults to 1 for unknown kinds (defensive)
  • plan_for_user routes demo / paid users correctly
  • check_and_record records a row and increments usage
  • check_and_record raises 402 when over the cap
  • usage_window aggregates correctly across multiple events
  • usage_window honours the rolling window (old events excluded)
  • record_only writes without a quota check
  • Demo cap math: 25 chats fit (25 × 20 = 500), 26th raises
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.plan_quotas import (
    PLAN_QUOTAS,
    cost_for_kind,
    plan_for_user,
)
from src.core.exceptions import PaymentRequiredError
from src.core.security import get_password_hash
from src.models.beat_consumption import BeatConsumption
from src.models.user import User
from src.repositories.user import UserRepository
from src.services.beats_service import BeatsService


async def _user(db: AsyncSession, *, role: str = "member", is_demo: bool = False) -> User:
    repo = UserRepository(db)
    user = await repo.create(
        email=f"{uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name="Beats Test",
        role=role,
    )
    if is_demo:
        user.is_demo = True
        await db.flush()
    return user


# ─── Cost lookup ────────────────────────────────────────────────────────────


def test_cost_for_kind_known_values():
    assert cost_for_kind("chat") == Decimal("20")
    assert cost_for_kind("suggest_title") == Decimal("5")
    assert cost_for_kind("agent_l1") == Decimal("0.2")
    assert cost_for_kind("agent_l2") == Decimal("1")
    assert cost_for_kind("agent_l3") == Decimal("20")


def test_cost_for_kind_unknown_defaults_to_one():
    # Defensive default — keeps the meter running if a deploy adds a
    # kind without registering it. Matches DEFAULT_KIND_COST.
    assert cost_for_kind("future_kind_not_registered") == Decimal("1")


# ─── Plan resolution ────────────────────────────────────────────────────────


def test_plan_for_user_demo_overrides_tenant():
    plan = plan_for_user(is_demo=True, tenant_tier="enterprise")
    assert plan.tier == "demo"
    assert plan.beats_per_period == Decimal("500")
    assert plan.period == timedelta(days=7)


def test_plan_for_user_falls_back_to_starter():
    plan = plan_for_user(is_demo=False, tenant_tier=None)
    assert plan.tier == "starter"


def test_plan_for_user_honours_known_tier():
    plan = plan_for_user(is_demo=False, tenant_tier="pro")
    assert plan.tier == "pro"
    assert plan.beats_per_period == Decimal("30000")


# ─── check_and_record ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_and_record_writes_row_and_returns_snapshot(db_session):
    user = await _user(db_session)
    snap = await BeatsService(db_session).check_and_record(
        user, kind="chat", source_id=None,
    )
    assert snap.used == Decimal("20")
    assert snap.limit == Decimal("5000")  # default starter
    assert snap.remaining == Decimal("4980")
    rows = (
        await db_session.execute(
            select(BeatConsumption).where(BeatConsumption.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].kind == "chat"
    assert rows[0].beats == Decimal("20")


@pytest.mark.asyncio
async def test_check_and_record_records_breakdown_per_kind(db_session):
    user = await _user(db_session)
    svc = BeatsService(db_session)
    await svc.check_and_record(user, kind="chat")
    await svc.check_and_record(user, kind="chat")
    await svc.check_and_record(user, kind="suggest_title")

    snap = await svc.usage_window(user, scope="user")
    assert snap.used == Decimal("45")  # 20 + 20 + 5
    assert snap.breakdown_by_kind["chat"] == Decimal("40")
    assert snap.breakdown_by_kind["suggest_title"] == Decimal("5")


# ─── Quota enforcement (the demo cap) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_demo_user_can_run_25_chats(db_session):
    """500 beat budget / 20 beats per chat = 25 chats."""
    user = await _user(db_session, is_demo=True)
    svc = BeatsService(db_session)
    for _ in range(25):
        await svc.check_and_record(user, kind="chat")

    snap = await svc.usage_window(user, scope="user")
    assert snap.used == Decimal("500")
    assert snap.remaining == Decimal("0")
    assert snap.percent_used == 100


@pytest.mark.asyncio
async def test_demo_user_26th_chat_raises_402(db_session):
    user = await _user(db_session, is_demo=True)
    svc = BeatsService(db_session)
    for _ in range(25):
        await svc.check_and_record(user, kind="chat")

    with pytest.raises(PaymentRequiredError) as exc:
        await svc.check_and_record(user, kind="chat")

    assert exc.value.status_code == 402
    assert "Demo" in exc.value.message
    assert exc.value.upgrade_cta == PLAN_QUOTAS["demo"].upgrade_cta


@pytest.mark.asyncio
async def test_quota_exceeded_does_not_record_the_failed_attempt(db_session):
    user = await _user(db_session, is_demo=True)
    svc = BeatsService(db_session)
    for _ in range(25):
        await svc.check_and_record(user, kind="chat")

    with pytest.raises(PaymentRequiredError):
        await svc.check_and_record(user, kind="chat")

    rows = (
        await db_session.execute(
            select(BeatConsumption).where(BeatConsumption.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 25  # not 26 — the failed call was not logged


# ─── Rolling window ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_usage_window_excludes_events_older_than_period(db_session):
    """Demo plan is 7-day rolling; events 8+ days old must not count."""
    user = await _user(db_session, is_demo=True)

    # Inject an old event by hand (bypassing the service so the
    # created_at backdates).
    old = BeatConsumption(
        id=uuid4(),
        user_id=user.id,
        tenant_id=None,
        kind="chat",
        beats=Decimal("400"),
        created_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db_session.add(old)
    await db_session.flush()

    snap = await BeatsService(db_session).usage_window(user, scope="user")
    # Old event is outside the 7-day window — must be excluded.
    assert snap.used == Decimal("0")


# ─── record_only (background-worker path) ───────────────────────────────────


@pytest.mark.asyncio
async def test_record_only_does_not_check_quota(db_session):
    """Workers (agent worker tier-router) call record_only after the
    L2 / L3 LLM call already ran. record_only writes the row without
    re-checking the quota — the gate fired earlier in the cycle.
    """
    user = await _user(db_session, is_demo=True)
    svc = BeatsService(db_session)

    # Push usage right up to the cap via the gated path.
    for _ in range(25):
        await svc.check_and_record(user, kind="chat")

    # record_only now writes one more event without raising. This is
    # the documented contract.
    await svc.record_only(user, kind="agent_l1")

    snap = await svc.usage_window(user, scope="user")
    # 25*20 + 0.2 = 500.2 — slightly over, but recorded.
    assert snap.used == Decimal("500.20")
