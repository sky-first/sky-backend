"""Tests for the widget provenance ``source`` column added in Lucas's
2026-05-05 audit.

The audit asked: "alguém de backend consegue ir na API e de fato ver
que foi gerada automaticamente e não foi feita por IA?". The new
column lets an operator answer that with a simple ``WHERE source =
'manual'`` filter on the widgets table.

Rewritten 2026-05-20 after the Dashboard concept was folded into Page —
widgets now hang directly off a page.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.page import Page
from src.models.user import User
from src.models.widget import Widget
from src.schemas.widget import WidgetCreate
from src.services.widget_service import WidgetService
from src.core.security import get_password_hash


async def _seed_user_page(db: AsyncSession) -> tuple[User, Page]:
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

    # Use the user's first page directly — page IS the canvas now.
    from src.repositories.page import PageRepository
    pages = await PageRepository(db).get_by_owner(user.id)
    assert pages, "ensure_default_page_and_space should have created a page"
    return user, pages[0]


@pytest.mark.asyncio
async def test_widget_source_defaults_to_manual(db_session: AsyncSession):
    """A WidgetCreate that omits ``source`` must end up tagged
    ``manual`` so the audit query can rely on a non-NULL value for
    every newly-created row."""
    user, page = await _seed_user_page(db_session)
    svc = WidgetService(db_session)

    res = await svc.create_widget(
        user,
        WidgetCreate(
            page_id=page.id,
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
    user, page = await _seed_user_page(db_session)
    svc = WidgetService(db_session)

    res = await svc.create_widget(
        user,
        WidgetCreate(
            page_id=page.id,
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
            page_id=uuid.uuid4(),
            type="chart",
            title="Bad source",
            position={"x": 0, "y": 0},
            size={"width": 100, "height": 100},
            source="totally-made-up",
        )
