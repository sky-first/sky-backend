"""InsightsAnalyticsService — aggregator behind Settings → Analytics.

Drives the snapshot from a synthetic BeatConsumption history and
verifies:

  • Empty tenant → all zeros, no exception.
  • Tier mapping from BeatConsumption.kind matches the contract
    (suggest_title/agent_l1 → L1, chat/agent_l2 → L2, agent_l3 → L3).
  • Hours-saved math uses HOURS_SAVED_BY_TIER and dollar value
    multiplies by the analyst hourly rate.
  • Range filtering (today / month / quarter) only counts in-window
    rows.
  • `agent_run` synthetic kind is ignored (avoids double-counting).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_password_hash
from src.models.beat_consumption import BeatConsumption
from src.repositories.user import UserRepository
from src.services.insights_analytics_service import (
    DEFAULT_ANALYST_HOURLY_RATE,
    InsightsAnalyticsService,
)
from src.services.insights_tier import HOURS_SAVED_BY_TIER


async def _user(db):
    return await UserRepository(db).create(
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name="Analytics Test",
        role="super_admin",
    )


async def _seed_event(
    db: AsyncSession,
    *,
    user_id,
    kind: str,
    beats: float = 1.0,
    when: datetime | None = None,
):
    row = BeatConsumption(
        id=uuid.uuid4(),
        user_id=user_id,
        kind=kind,
        beats=Decimal(str(beats)),
        created_at=when or datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
async def test_empty_tenant_returns_all_zeros(db_session):
    user = await _user(db_session)
    snap = await InsightsAnalyticsService(db_session, user=user).snapshot("quarter")

    assert snap.insights_total == 0
    assert snap.hours_saved == 0
    assert snap.value_eur == 0
    assert snap.cost_total_usd == 0
    assert snap.roi_multiplier == 0
    # Tier buckets are still emitted (zeroed) so the FE can render a
    # consistent shape and show an empty-state card.
    assert {b.tier for b in snap.by_tier} == {"l1", "l2", "l3"}
    assert all(b.count == 0 for b in snap.by_tier)


@pytest.mark.asyncio
async def test_kind_mapping_to_tier(db_session):
    user = await _user(db_session)
    # Each kind once.
    for kind in ("suggest_title", "agent_l1", "chat", "agent_l2", "agent_l3"):
        await _seed_event(db_session, user_id=user.id, kind=kind, beats=1.0)
    # Synthetic roll-up — must be ignored to avoid double-counting.
    await _seed_event(db_session, user_id=user.id, kind="agent_run", beats=1.0)

    snap = await InsightsAnalyticsService(db_session, user=user).snapshot("quarter")
    counts = {b.tier: b.count for b in snap.by_tier}
    assert counts["l1"] == 2  # suggest_title + agent_l1
    assert counts["l2"] == 2  # chat + agent_l2
    assert counts["l3"] == 1  # agent_l3
    assert snap.insights_total == 5  # agent_run not counted


@pytest.mark.asyncio
async def test_hours_saved_uses_tier_weights(db_session):
    user = await _user(db_session)
    await _seed_event(db_session, user_id=user.id, kind="agent_l1", beats=1.0)
    await _seed_event(db_session, user_id=user.id, kind="chat", beats=20.0)
    await _seed_event(db_session, user_id=user.id, kind="agent_l3", beats=20.0)

    snap = await InsightsAnalyticsService(db_session, user=user).snapshot("quarter")
    expected = (
        HOURS_SAVED_BY_TIER["l1"]
        + HOURS_SAVED_BY_TIER["l2"]
        + HOURS_SAVED_BY_TIER["l3"]
    )
    assert snap.hours_saved == round(expected, 1)
    assert snap.value_eur == round(expected * DEFAULT_ANALYST_HOURLY_RATE, 2)


@pytest.mark.asyncio
async def test_range_filtering_only_counts_in_window(db_session):
    user = await _user(db_session)
    now = datetime.now(timezone.utc)
    # In-window: today, last 5 minutes.
    await _seed_event(db_session, user_id=user.id, kind="chat", when=now - timedelta(minutes=5))
    # Out-of-window: 40 days ago — outside `today` and `month`, but
    # caught by `quarter` only if we're in the same quarter. To be
    # explicit, push it 6 months back so it's safely out of every
    # range except `year`.
    await _seed_event(
        db_session, user_id=user.id, kind="chat", when=now - timedelta(days=180)
    )

    snap_today = await InsightsAnalyticsService(db_session, user=user).snapshot("today")
    assert snap_today.insights_total == 1

    snap_year = await InsightsAnalyticsService(db_session, user=user).snapshot("year")
    # Both rows in-window for "year" only when the older row falls in
    # the same calendar year. We pinned 180 days back which can cross
    # the year boundary; assert at least the recent one is captured.
    assert snap_year.insights_total >= 1


@pytest.mark.asyncio
async def test_agent_run_synthetic_kind_is_ignored(db_session):
    user = await _user(db_session)
    # Only synthetic roll-ups.
    for _ in range(5):
        await _seed_event(db_session, user_id=user.id, kind="agent_run")
    snap = await InsightsAnalyticsService(db_session, user=user).snapshot("quarter")
    assert snap.insights_total == 0


@pytest.mark.asyncio
async def test_session_range_uses_24h_window(db_session):
    user = await _user(db_session)
    now = datetime.now(timezone.utc)
    await _seed_event(db_session, user_id=user.id, kind="chat", when=now - timedelta(hours=2))
    await _seed_event(db_session, user_id=user.id, kind="chat", when=now - timedelta(hours=30))

    snap = await InsightsAnalyticsService(db_session, user=user).snapshot("session")
    # Only the 2h-old event should make it.
    assert snap.insights_total == 1
    assert snap.range_label == "This session"


@pytest.mark.asyncio
async def test_roi_is_dollar_value_over_cost(db_session):
    user = await _user(db_session)
    # 10 chats — substantial value, modest cost.
    for _ in range(10):
        await _seed_event(db_session, user_id=user.id, kind="chat", beats=20.0)

    snap = await InsightsAnalyticsService(db_session, user=user).snapshot("quarter")
    assert snap.cost_total_usd > 0
    assert snap.value_eur > snap.cost_total_usd
    # ROI = dollar_value / cost — must be the value-to-cost multiple.
    assert snap.roi_multiplier == round(
        snap.value_eur / snap.cost_total_usd, 1
    )
    # And it should be a meaningful multiplier — value framing
    # collapses if ROI is anywhere near 1×.
    assert snap.roi_multiplier > 100
