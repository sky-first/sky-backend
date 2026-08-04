"""BE-02 · Unified Insights feed — acceptance suite T-02.1…T-02.12.

Exercised at the service level (like the other Sky Mobile suites): the
endpoints are thin wrappers over ``InsightFeedService``, and T-02.11 (no token
→ 401) is enforced by the ``get_current_user`` dependency on every route.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.models.agent import Agent, AgentFinding
from src.models.crew import CrewMember
from src.models.insight_state import InsightState
from src.models.space import SpaceMember
from src.services.insight_feed_service import InsightFeedService, InvalidCursor

_UTC = timezone.utc
_BASE = datetime(2026, 1, 1, tzinfo=_UTC)


# ─── Fixtures / helpers ──────────────────────────────────────────────────────


def _member_of_space(session, user_id, space_id):
    session.add(SpaceMember(user_id=user_id, space_id=space_id, role="member"))


def _scan_finding(
    session,
    space_id,
    *,
    kind="insight",
    level="med",
    title="finding",
    created_at=None,
    series=None,
):
    finding = AgentFinding(
        agent_id=None,
        source="scan",
        space_id=space_id,
        agent_name="Autonomous scan",
        type=kind,
        severity=level,
        title=title,
        description=f"{title} — details",
        series=series if series is not None else [],
        stat_tiles=[],
        viz_kind="big_number",
    )
    if created_at is not None:
        finding.created_at = created_at
    session.add(finding)
    return finding


# ─── T-02.1 · scoped feed, newest first, correct fields ─────────────────────


@pytest.mark.asyncio
async def test_t02_1_feed_scoped_newest_first(db_session):
    user, space = uuid4(), uuid4()
    _member_of_space(db_session, user, space)
    for i in range(12):
        _scan_finding(db_session, space, title=f"f{i}", created_at=_BASE + timedelta(minutes=i))
    await db_session.commit()

    res = await InsightFeedService(db_session).list(user, "all", None, 20)

    assert len(res.items) == 12
    assert res.items[0].title == "f11"  # newest first
    assert res.items[-1].title == "f0"
    assert res.counts["all"] == 12
    assert res.items[0].deep_link.startswith("sky://insights/")


# ─── T-02.2 · filter=risk returns exactly the risks ─────────────────────────


@pytest.mark.asyncio
async def test_t02_2_filter_risk(db_session):
    user, space = uuid4(), uuid4()
    _member_of_space(db_session, user, space)
    for i in range(5):
        _scan_finding(db_session, space, kind="risk", title=f"r{i}")
    for i in range(7):
        _scan_finding(db_session, space, kind="insight", title=f"i{i}")
    await db_session.commit()

    res = await InsightFeedService(db_session).list(user, "risk", None, 20)

    assert len(res.items) == 5
    assert all(item.severity == "risk" for item in res.items)
    assert res.counts["risk"] == 5


# ─── T-02.3 · new user, no findings → empty (not an error) ───────────────────


@pytest.mark.asyncio
async def test_t02_3_empty_scope(db_session):
    res = await InsightFeedService(db_session).list(uuid4(), "all", None, 20)
    assert res.items == []
    assert res.next_cursor is None
    assert res.counts["all"] == 0


# ─── T-02.4 · keyset pagination is stable, no dupes/gaps ─────────────────────


@pytest.mark.asyncio
async def test_t02_4_keyset_pagination(db_session):
    user, space = uuid4(), uuid4()
    _member_of_space(db_session, user, space)
    for i in range(25):
        _scan_finding(db_session, space, title=f"f{i}", created_at=_BASE + timedelta(minutes=i))
    await db_session.commit()

    svc = InsightFeedService(db_session)
    page1 = await svc.list(user, "all", None, 20)
    assert len(page1.items) == 20 and page1.next_cursor is not None

    page2 = await svc.list(user, "all", page1.next_cursor, 20)
    assert len(page2.items) == 5 and page2.next_cursor is None

    ids1 = {i.id for i in page1.items}
    ids2 = {i.id for i in page2.items}
    assert ids1.isdisjoint(ids2)  # no dupes
    assert len(ids1 | ids2) == 25  # no gaps


# ─── T-02.5 & T-02.6 · isolation — out-of-scope invisible, detail → None (404)


@pytest.mark.asyncio
async def test_t02_5_6_isolation(db_session):
    user, my_space, other_space = uuid4(), uuid4(), uuid4()
    _member_of_space(db_session, user, my_space)
    mine = _scan_finding(db_session, my_space, title="mine")
    theirs = _scan_finding(db_session, other_space, title="theirs")
    await db_session.commit()

    svc = InsightFeedService(db_session)
    res = await svc.list(user, "all", None, 20)
    titles = {i.title for i in res.items}
    assert "mine" in titles and "theirs" not in titles

    # Detail of an out-of-scope finding → None → the endpoint returns 404
    # (never a 403 that would leak that the id exists).
    assert await svc.detail(user, str(theirs.id)) is None
    assert await svc.detail(user, str(mine.id)) is not None


# ─── T-02.7 · empty series still renders (no crash) ──────────────────────────


@pytest.mark.asyncio
async def test_t02_7_empty_series(db_session):
    user, space = uuid4(), uuid4()
    _member_of_space(db_session, user, space)
    finding = _scan_finding(db_session, space, title="agg", series=[])
    await db_session.commit()

    detail = await InsightFeedService(db_session).detail(user, str(finding.id))
    assert detail is not None
    assert detail.series == []
    assert detail.stat_tiles == []


# ─── T-02.8 · review is idempotent (per-user) ────────────────────────────────


@pytest.mark.asyncio
async def test_t02_8_review_idempotent(db_session):
    user, space = uuid4(), uuid4()
    _member_of_space(db_session, user, space)
    finding = _scan_finding(db_session, space, title="rev")
    await db_session.commit()

    svc = InsightFeedService(db_session)
    assert await svc.set_reviewed(user, str(finding.id), True) is True
    assert await svc.set_reviewed(user, str(finding.id), True) is True  # again
    await db_session.commit()

    states = (
        (
            await db_session.execute(
                select(InsightState).where(InsightState.finding_id == finding.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(states) == 1 and states[0].reviewed_at is not None

    res = await svc.list(user, "all", None, 20)
    assert next(i for i in res.items if i.id == str(finding.id)).reviewed is True


# ─── T-02.9 · pin is idempotent + toggles off ────────────────────────────────


@pytest.mark.asyncio
async def test_t02_9_pin_idempotent_and_toggle(db_session):
    user, space = uuid4(), uuid4()
    _member_of_space(db_session, user, space)
    finding = _scan_finding(db_session, space, title="pin")
    await db_session.commit()

    svc = InsightFeedService(db_session)
    await svc.set_pinned(user, str(finding.id), True)
    await svc.set_pinned(user, str(finding.id), True)  # idempotent
    await db_session.commit()
    res = await svc.list(user, "all", None, 20)
    assert next(i for i in res.items if i.id == str(finding.id)).pinned is True

    await svc.set_pinned(user, str(finding.id), False)  # toggle off
    await db_session.commit()
    res = await svc.list(user, "all", None, 20)
    assert next(i for i in res.items if i.id == str(finding.id)).pinned is False


# ─── T-02.10 · malformed cursor → 400 (InvalidCursor) ───────────────────────


@pytest.mark.asyncio
async def test_t02_10_malformed_cursor(db_session):
    svc = InsightFeedService(db_session)
    with pytest.raises(InvalidCursor):
        await svc.list(uuid4(), "all", "totally-not-a-cursor", 20)
    # valid base64 but not our JSON payload → still rejected
    with pytest.raises(InvalidCursor):
        await svc.list(uuid4(), "all", base64.urlsafe_b64encode(b"hello").decode(), 20)


# ─── T-02.12 · counts match the returned items ──────────────────────────────


@pytest.mark.asyncio
async def test_t02_12_counts_match(db_session):
    user, space = uuid4(), uuid4()
    _member_of_space(db_session, user, space)
    for i in range(3):
        _scan_finding(db_session, space, kind="opportunity", title=f"o{i}")
    for i in range(2):
        _scan_finding(db_session, space, kind="risk", title=f"r{i}")
    await db_session.commit()

    svc = InsightFeedService(db_session)
    res = await svc.list(user, "opportunity", None, 20)
    assert len(res.items) == res.counts["opportunity"] == 3
    assert res.counts["risk"] == 2
    assert res.counts["all"] == 5


# ─── Union · agent + scan findings in one feed, is_live derived ─────────────


@pytest.mark.asyncio
async def test_union_agent_and_scan_findings(db_session):
    user, space, crew = uuid4(), uuid4(), uuid4()
    _member_of_space(db_session, user, space)
    db_session.add(CrewMember(user_id=user, crew_id=crew, role="member"))

    agent = Agent(
        name="Revenue agent",
        scope="crew",
        scope_id=str(crew),
        status="active",
        last_execution_at=datetime.now(_UTC),
    )
    db_session.add(agent)
    await db_session.flush()
    db_session.add(
        AgentFinding(
            agent_id=agent.id,
            source="agent",
            type="risk",
            severity="high",
            title="agent-finding",
            description="from a registered agent",
        )
    )
    _scan_finding(db_session, space, title="scan-finding", created_at=datetime.now(_UTC))
    await db_session.commit()

    res = await InsightFeedService(db_session).list(user, "all", None, 20)
    by_title = {i.title: i for i in res.items}
    assert {"agent-finding", "scan-finding"} <= set(by_title)
    # Both are "live": the scan is recent; the agent is active + just executed.
    assert by_title["scan-finding"].is_live is True
    assert by_title["agent-finding"].is_live is True
    # featured = pinned OR high severity → the high-severity agent finding counts
    assert res.counts["featured"] >= 1
