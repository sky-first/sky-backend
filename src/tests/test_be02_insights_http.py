"""BE-02 · Insights feed — endpoint-level acceptance (G2).

The feed logic is covered at the service level in test_insight_feed.py; G2
promotes the security-critical and contract rows to the HTTP layer: the §14
auth matrix (T-02.11), cross-scope isolation (T-02.5/2.6 → 404, no existence
leak), the empty-feed contract (T-02.3), a filter (T-02.2), review idempotency
(T-02.8) and malformed-cursor handling (T-02.10).

Multi-tenant mode is off here, so the BE-01 device gate on the router is a
no-op — this suite isolates BE-02's own content-plane scoping.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.agent import AgentFinding
from src.models.space import SpaceMember
from src.tests.acceptance_helpers import assert_auth_matrix, bearer


def _member(db, user_id, space_id):
    db.add(SpaceMember(user_id=user_id, space_id=space_id, role="member"))


def _finding(db, space_id, *, kind="insight", level="med", title="finding"):
    f = AgentFinding(
        agent_id=None,
        source="scan",
        space_id=space_id,
        agent_name="Autonomous scan",
        type=kind,
        severity=level,
        title=title,
        description=f"{title} — details",
        series=[],
        stat_tiles=[],
        viz_kind="big_number",
    )
    db.add(f)
    return f


# ─── T-02.11 · §14 auth matrix ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_t02_11_auth_matrix(async_client, expired_token, invalid_token):
    await assert_auth_matrix(
        async_client,
        "GET",
        "/api/v1/insights",
        expired_token=expired_token,
        invalid_token=invalid_token,
    )


# ─── T-02.3 · empty scope → 200 {items:[], next_cursor:null} ────────────────
@pytest.mark.asyncio
async def test_t02_3_empty_feed(async_client, valid_access_token):
    r = await async_client.get("/api/v1/insights", headers=bearer(valid_access_token))
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == [] and body["next_cursor"] is None


# ─── T-02.1 · feed returns the member's findings ────────────────────────────
@pytest.mark.asyncio
async def test_t02_1_feed_returns_member_findings(
    async_client, test_user, valid_access_token, db_session
):
    space = uuid4()
    _member(db_session, test_user["user"].id, space)
    _finding(db_session, space, title="visible")
    await db_session.commit()

    r = await async_client.get("/api/v1/insights", headers=bearer(valid_access_token))
    assert r.status_code == 200
    assert any(i["title"] == "visible" for i in r.json()["items"])


# ─── T-02.2 · filter=risk returns only risks ────────────────────────────────
@pytest.mark.asyncio
async def test_t02_2_filter_risk(async_client, test_user, valid_access_token, db_session):
    space = uuid4()
    _member(db_session, test_user["user"].id, space)
    _finding(db_session, space, kind="risk", title="a risk")
    _finding(db_session, space, kind="insight", title="an insight")
    await db_session.commit()

    r = await async_client.get(
        "/api/v1/insights", params={"filter": "risk"}, headers=bearer(valid_access_token)
    )
    titles = [i["title"] for i in r.json()["items"]]
    assert "a risk" in titles and "an insight" not in titles


# ─── T-02.6 · out-of-scope finding is absent from the feed ──────────────────
@pytest.mark.asyncio
async def test_t02_6_out_of_scope_absent_from_feed(
    async_client, test_user, valid_access_token, db_session
):
    mine, theirs = uuid4(), uuid4()
    _member(db_session, test_user["user"].id, mine)  # member of `mine` only
    _finding(db_session, mine, title="mine")
    _finding(db_session, theirs, title="theirs")
    await db_session.commit()

    r = await async_client.get("/api/v1/insights", headers=bearer(valid_access_token))
    titles = [i["title"] for i in r.json()["items"]]
    assert "mine" in titles and "theirs" not in titles


# ─── T-02.5 · out-of-scope detail → 404 (never a 403 existence leak) ────────
@pytest.mark.asyncio
async def test_t02_5_out_of_scope_detail_is_404(async_client, valid_access_token, db_session):
    other = uuid4()  # a space the authenticated user is NOT a member of
    f = _finding(db_session, other, title="secret")
    await db_session.commit()
    await db_session.refresh(f)

    r = await async_client.get(f"/api/v1/insights/{f.id}", headers=bearer(valid_access_token))
    assert r.status_code == 404


# ─── T-02.8 · review is idempotent ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_t02_8_review_idempotent(async_client, test_user, valid_access_token, db_session):
    space = uuid4()
    _member(db_session, test_user["user"].id, space)
    f = _finding(db_session, space, title="to review")
    await db_session.commit()
    await db_session.refresh(f)

    for _ in range(2):
        r = await async_client.post(
            f"/api/v1/insights/{f.id}/review",
            json={"reviewed": True},
            headers=bearer(valid_access_token),
        )
        assert r.status_code == 200


# ─── T-02.10 · malformed cursor → 400 (not 500) ─────────────────────────────
@pytest.mark.asyncio
async def test_t02_10_malformed_cursor_is_400(async_client, valid_access_token):
    r = await async_client.get(
        "/api/v1/insights",
        params={"cursor": "%%%not-a-real-cursor%%%"},
        headers=bearer(valid_access_token),
    )
    assert r.status_code == 400
