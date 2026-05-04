"""Insights Analytics endpoint — auth + Owner-only gate.

Pins:
  • Owner gets 200 with the snapshot shape.
  • Admin and Member get 403 — this surface is decision-maker territory.
  • Range query param round-trips to the response.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, get_password_hash
from src.models.beat_consumption import BeatConsumption
from src.repositories.user import UserRepository


async def _user_with_role(db: AsyncSession, role: str):
    repo = UserRepository(db)
    user = await repo.create(
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name=f"{role} test",
        role=role,
    )
    await db.commit()
    return user


def _auth_headers(user) -> dict:
    token = create_access_token(
        {"sub": str(user.id), "email": user.email, "role": user.role}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_owner_gets_200_with_snapshot_shape(async_client, db_session):
    user = await _user_with_role(db_session, "owner")
    res = await async_client.get(
        "/api/v1/me/insights-analytics", headers=_auth_headers(user)
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # Hero
    for key in ("insights_total", "hours_saved", "dollar_value_usd"):
        assert key in body
    # Cost transparency
    for key in ("cost_total_usd", "cost_per_insight_usd", "tokens_total", "roi_multiplier"):
        assert key in body
    # Tier breakdown — must always include all three buckets, even
    # when zero, so the FE can render a stable shape.
    assert {b["tier"] for b in body["by_tier"]} == {"l1", "l2", "l3"}


@pytest.mark.asyncio
async def test_admin_is_forbidden(async_client, db_session):
    user = await _user_with_role(db_session, "admin")
    res = await async_client.get(
        "/api/v1/me/insights-analytics", headers=_auth_headers(user)
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_member_is_forbidden(async_client, db_session):
    user = await _user_with_role(db_session, "member")
    res = await async_client.get(
        "/api/v1/me/insights-analytics", headers=_auth_headers(user)
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_range_query_param_round_trips(async_client, db_session):
    user = await _user_with_role(db_session, "owner")
    res = await async_client.get(
        "/api/v1/me/insights-analytics?range=session",
        headers=_auth_headers(user),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["range"] == "session"
    assert body["range_label"] == "This session"


@pytest.mark.asyncio
async def test_invalid_range_is_validation_error(async_client, db_session):
    user = await _user_with_role(db_session, "owner")
    res = await async_client.get(
        "/api/v1/me/insights-analytics?range=lifetime",
        headers=_auth_headers(user),
    )
    # FastAPI validates Literal types — 422 is the expected envelope.
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_empty_state_returns_zeros_not_error(async_client, db_session):
    """Brand-new tenant has no beats — must not 500."""
    user = await _user_with_role(db_session, "owner")
    res = await async_client.get(
        "/api/v1/me/insights-analytics", headers=_auth_headers(user)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["insights_total"] == 0
    assert body["hours_saved"] == 0
    assert body["dollar_value_usd"] == 0


@pytest.mark.asyncio
async def test_owner_sees_seeded_events(async_client, db_session):
    user = await _user_with_role(db_session, "owner")
    # Seed three chats and one agent_l3.
    for _ in range(3):
        db_session.add(
            BeatConsumption(
                id=uuid.uuid4(),
                user_id=user.id,
                kind="chat",
                beats=Decimal("20"),
            )
        )
    db_session.add(
        BeatConsumption(
            id=uuid.uuid4(),
            user_id=user.id,
            kind="agent_l3",
            beats=Decimal("20"),
        )
    )
    await db_session.commit()

    res = await async_client.get(
        "/api/v1/me/insights-analytics", headers=_auth_headers(user)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["insights_total"] == 4
    counts = {b["tier"]: b["count"] for b in body["by_tier"]}
    assert counts["l2"] == 3
    assert counts["l3"] == 1
