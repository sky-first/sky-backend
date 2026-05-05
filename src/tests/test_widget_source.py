"""Tests for the widget provenance ``source`` column added in Lucas's
2026-05-05 audit.

The audit asked: "alguém de backend consegue ir na API e de fato ver
que foi gerada automaticamente e não foi feita por IA?". The new
column lets an operator answer that with a simple ``WHERE source =
'manual'`` filter on the widgets table.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.dashboard import Dashboard, Widget
from src.models.user import User
from src.schemas.dashboard import DashboardCreate, WidgetCreate
from src.services.dashboard_service import DashboardService
from src.core.security import get_password_hash


async def _seed_user_dashboard(db: AsyncSession) -> tuple[User, Dashboard]:
    from src.repositories.user import UserRepository
    from src.services.onboarding_service import ensure_default_page_and_space

    user = await UserRepository(db).create(
        email=f"widget-src-{uuid.uuid4()}@example.com",
        password_hash=get_password_hash("x"),
        name="WidgetSource Tester",
        role="user",
    )
    await ensure_default_page_and_space(db, user)
    await db.commit()
    await db.refresh(user)

    svc = DashboardService(db)
    # Use the user's first page to host the dashboard.
    from src.repositories.page import PageRepository
    pages = await PageRepository(db).get_by_owner(user.id)
    assert pages, "ensure_default_page_and_space should have created a page"
    dash = await svc.create_dashboard(
        user, DashboardCreate(name="Audit Test Dashboard", page_id=pages[0].id)
    )
    return user, dash


@pytest.mark.asyncio
async def test_widget_source_defaults_to_manual(db_session: AsyncSession):
    """A WidgetCreate that omits ``source`` must end up tagged
    ``manual`` so the audit query can rely on a non-NULL value for
    every newly-created row."""
    user, dash = await _seed_user_dashboard(db_session)
    svc = DashboardService(db_session)

    res = await svc.create_widget(
        user,
        WidgetCreate(
            dashboard_id=dash.id,
            type="chart",
            title="No-source Widget",
            position={"x": 0, "y": 0},
            size={"width": 100, "height": 100},
        ),
    )
    assert res.source == "manual"

    # Confirm it landed in the DB row, not just the response model.
    db_row = (
        await db_session.execute(select(Widget).where(Widget.id == res.id))
    ).scalar_one()
    assert db_row.source == "manual"


@pytest.mark.asyncio
async def test_widget_source_honours_ai_synthesis_value(
    db_session: AsyncSession,
):
    """When the FE explicitly stamps ``ai_synthesis`` (Create Analysis
    on a real AI answer), the value must persist."""
    user, dash = await _seed_user_dashboard(db_session)
    svc = DashboardService(db_session)

    res = await svc.create_widget(
        user,
        WidgetCreate(
            dashboard_id=dash.id,
            type="chart",
            title="AI-stamped Widget",
            position={"x": 0, "y": 0},
            size={"width": 100, "height": 100},
            source="ai_synthesis",
        ),
    )
    assert res.source == "ai_synthesis"


@pytest.mark.asyncio
async def test_widget_source_rejects_unknown_value():
    """Schema must reject sources outside the agreed enum so a
    misbehaving caller can't sneak in arbitrary tags."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        WidgetCreate(
            dashboard_id=uuid.uuid4(),
            type="chart",
            title="Bad source",
            position={"x": 0, "y": 0},
            size={"width": 100, "height": 100},
            source="totally-made-up",
        )
