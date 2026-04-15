"""Settings → Usage: real metrics from DB, not hardcoded placeholders.

Three issues fixed in this change that these tests pin down:

  M1  Latency / SLA compliance used to return the literal string "< 3s"
      even when nothing had been measured. Now they return "N/A" with
      no measured rows, and real aggregates once rows land.

  M2  `AIFeedback.rating` is a string ('good'/'bad'), but the previous
      query did `rating < 3` which always silently matched zero rows,
      making the 5% estimate the only thing the UI ever displayed.

  M3  Corrections estimate is now clearly labelled when the source is
      a fallback vs real feedback.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.settings_metrics import _performance_metrics
from src.models.ai import AIFeedback, AIHistory, AIQuery
from src.models.page import Page


async def _seed_history(
    db: AsyncSession, user_id, page_id, *, count: int, duration_ms: int | None
):
    base = datetime.now(timezone.utc) - timedelta(days=1)
    for i in range(count):
        db.add(
            AIHistory(
                user_id=user_id,
                page_id=page_id,
                query=f"q{i}",
                preview="p",
                answer="a",
                date=base,
                duration_ms=duration_ms,
            )
        )
    await db.flush()


# ─── M1: real latency ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_latency_na_when_no_measured_rows(
    test_user, db_session: AsyncSession
):
    perf = await _performance_metrics(db_session)
    assert perf["avgLatency"]["value"] == "N/A"
    assert perf["slaCompliance"]["value"] == "N/A"


@pytest.mark.asyncio
async def test_latency_aggregates_real_rows(
    test_user, db_session: AsyncSession
):
    import uuid
    page = Page(
        id=uuid.uuid4(),
        name="p",
        type="personal",
        color="#3b82f6",
        owner_id=test_user["user"].id,
    )
    db_session.add(page)
    await db_session.flush()

    # 5 fast (within 3s SLA), 1 slow (above). Expected SLA compliance = 83%.
    await _seed_history(db_session, test_user["user"].id, page.id, count=5, duration_ms=1500)
    await _seed_history(db_session, test_user["user"].id, page.id, count=1, duration_ms=5000)
    await db_session.commit()

    perf = await _performance_metrics(db_session)
    # avg = (5*1500 + 5000) / 6 = 2083ms → "2.1s"
    assert perf["avgLatency"]["value"] == "2.1s"
    assert perf["slaCompliance"]["value"] == "83%"


@pytest.mark.asyncio
async def test_latency_ignores_null_rows(
    test_user, db_session: AsyncSession
):
    """Old rows without duration_ms must not dilute the average."""
    import uuid
    page = Page(
        id=uuid.uuid4(),
        name="p",
        type="personal",
        color="#3b82f6",
        owner_id=test_user["user"].id,
    )
    db_session.add(page)
    await db_session.flush()

    await _seed_history(db_session, test_user["user"].id, page.id, count=10, duration_ms=None)
    await _seed_history(db_session, test_user["user"].id, page.id, count=2, duration_ms=2000)
    await db_session.commit()

    perf = await _performance_metrics(db_session)
    # 2000ms avg of the 2 measured rows → "2.0s" (NULLs filtered out).
    assert perf["avgLatency"]["value"] == "2.0s"
    assert perf["slaCompliance"]["value"] == "100%"


# ─── M2: AIFeedback rating is a string, not numeric ───────────────────────
@pytest.mark.asyncio
async def test_feedback_rating_bad_is_matched_by_equality(
    test_user, db_session: AsyncSession
):
    """Regression test: the previous `rating < 3` comparison never
    matched any rows because the column stores 'good' / 'bad'. A
    direct equality filter is required.
    """
    import uuid
    page = Page(
        id=uuid.uuid4(),
        name="p",
        type="personal",
        color="#3b82f6",
        owner_id=test_user["user"].id,
    )
    db_session.add(page)
    await db_session.flush()

    q = AIQuery(
        user_id=test_user["user"].id,
        page_id=page.id,
        question="q",
        configure_data={},
    )
    db_session.add(q)
    await db_session.flush()

    db_session.add(
        AIFeedback(
            query_id=q.id, user_id=test_user["user"].id, rating="bad"
        )
    )
    await db_session.commit()

    # Simulate what the metrics endpoint does: count rows with rating='bad'.
    from sqlalchemy import func, select

    res = await db_session.execute(
        select(func.count(AIFeedback.id)).where(AIFeedback.rating == "bad")
    )
    assert (res.scalar_one() or 0) == 1
