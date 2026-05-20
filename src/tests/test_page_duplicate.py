"""Page duplication service tests.

Validates the guarantees QA cases UC-*-PAG-005/006 call out:
- Copy gets a fresh UUID distinct from the original.
- Name is suffixed with " (Copy)".
- Every dashboard is cloned with fresh UUIDs + copied canvas_settings + is_locked=False.
- Every widget (including `type='infographic'`) is cloned with fresh UUIDs but
  `connection_id` / `query_id` are preserved as references.
- The original page is untouched by the clone.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.widget import Widget
from src.models.page import Page
from src.services.page_service import PageService


@pytest.mark.asyncio
async def test_duplicate_page_copies_everything_with_fresh_ids(db_session, test_user):
    user = test_user["user"]

    # Seed: 1 page → 2 dashboards → (3 + 2) widgets (incl. one infographic)
    page = Page(
        id=uuid4(),
        name="Weekly Ops",
        description="Original ops dashboard",
        type="personal",
        color="#3b82f6",
        icon="chart",
        owner_id=user.id,
    )
    db_session.add(page)
    await db_session.flush()

    # Dashboard concept folded into Page in 2026-05-20. Canvas state moved
    # onto the page itself; we update it here to mirror what dash_a held.
    page.canvas_settings = {"scale": 1.5, "position": {"x": 120, "y": 40}}
    page.is_locked = True
    await db_session.flush()

    conn_id = uuid4()
    query_id = uuid4()

    widgets = [
        Widget(
            id=uuid4(),
            page_id=page.id,
            type="chart",
            title="Sales trend",
            position={"x": 0, "y": 0},
            size={"width": 400, "height": 300},
            data={"values": [1, 2, 3]},
            config={"chart_type": "bar"},
            connection_id=conn_id,
            query_id=query_id,
        ),
        Widget(
            id=uuid4(),
            page_id=page.id,
            type="infographic",
            title="Coffee infographic",
            position={"x": 420, "y": 0},
            size={"width": 480, "height": 360},
            data={"cards": ["a", "b"]},
            config={"variant": "visual"},
        ),
        Widget(
            id=uuid4(),
            page_id=page.id,
            type="kpi",
            title="Margin",
            position={"x": 0, "y": 320},
            size={"width": 200, "height": 120},
            data={},
            config={},
        ),
        Widget(
            id=uuid4(),
            page_id=page.id,
            type="text",
            title="Notes",
            position={"x": 0, "y": 0},
            size={"width": 400, "height": 100},
        ),
        Widget(
            id=uuid4(),
            page_id=page.id,
            type="table",
            title="Line items",
            position={"x": 0, "y": 120},
            size={"width": 800, "height": 400},
        ),
    ]
    db_session.add_all(widgets)
    await db_session.commit()

    # Act
    svc = PageService(db_session)
    result = await svc.duplicate_page(page.id, user)

    # The copy exists and is distinct
    assert result.id != page.id
    assert result.name == "Weekly Ops (Copy)"
    assert result.owner_id == user.id

    # Canvas state cloned from the original page; is_locked resets to False
    # (copies always start unlocked).
    from sqlalchemy import select

    assert result.canvas_settings == {"scale": 1.5, "position": {"x": 120, "y": 40}}
    assert result.is_locked is False

    # Widgets cloned onto the new page; UUIDs are fresh; infographic preserved
    copied_widget_rows = (
        (
            await db_session.execute(
                select(Widget).where(Widget.page_id == result.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(copied_widget_rows) == 5

    original_widget_ids = {w.id for w in widgets}
    assert all(cw.id not in original_widget_ids for cw in copied_widget_rows)
    assert any(cw.type == "infographic" for cw in copied_widget_rows)

    # Referenced ids preserved (not cloned)
    sales_copy = next(cw for cw in copied_widget_rows if cw.title == "Sales trend")
    assert sales_copy.connection_id == conn_id
    assert sales_copy.query_id == query_id

    # Original page untouched
    await db_session.refresh(page)
    assert page.name == "Weekly Ops"
    original_widgets_still = (
        (
            await db_session.execute(
                select(Widget).where(Widget.page_id == page.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(original_widgets_still) == 5


@pytest.mark.asyncio
async def test_duplicate_page_strips_stuck_isloading_on_infographic(db_session, test_user):
    """Regression: originals left at {isLoading:true} (AI save race, aborted
    generation, etc.) must not propagate that stuck state to the duplicate.

    The clone should render instead of spinning indefinitely.
    """
    user = test_user["user"]
    page = Page(
        id=uuid4(),
        name="Ops",
        type="personal",
        owner_id=user.id,
        color="#3b82f6",
        icon="chart",
    )
    db_session.add(page)
    await db_session.flush()

    db_session.add(
        Widget(
            id=uuid4(),
            page_id=page.id,
            type="infographic",
            title="Stuck",
            position={"x": 0, "y": 0},
            size={"width": 400, "height": 300},
            data={
                "type": "mix",
                "section": "trajectory",
                "isLoading": True,  # stuck — AI save never completed
            },
        )
    )
    await db_session.commit()

    svc = PageService(db_session)
    result = await svc.duplicate_page(page.id, user)

    from sqlalchemy import select

    copied_widget = (
        await db_session.execute(select(Widget).where(Widget.page_id == result.id))
    ).scalar_one()

    assert copied_widget.data["isLoading"] is False
    # Non-loading flags preserved
    assert copied_widget.data["type"] == "mix"
    assert copied_widget.data["section"] == "trajectory"


@pytest.mark.asyncio
async def test_duplicate_page_deep_copies_nested_widget_data(db_session, test_user):
    """Regression: the clone's data should not share nested references with
    the original, so mutating the clone can't corrupt the source row.
    """
    user = test_user["user"]
    page = Page(
        id=uuid4(),
        name="Deep",
        type="personal",
        owner_id=user.id,
        color="#000000",
        icon="page",
    )
    db_session.add(page)
    await db_session.flush()
    original_data = {
        "infographic_data": {
            "title": "X",
            "drivers": [{"name": "a"}, {"name": "b"}],
        },
        "isLoading": False,
    }
    db_session.add(
        Widget(
            id=uuid4(),
            page_id=page.id,
            type="infographic",
            title="Keep",
            position={"x": 0, "y": 0},
            size={"width": 400, "height": 300},
            data=original_data,
        )
    )
    await db_session.commit()

    svc = PageService(db_session)
    await svc.duplicate_page(page.id, user)

    # Mutate the original after cloning — the copy must be unaffected
    original_data["infographic_data"]["drivers"][0]["name"] = "MUTATED"

    from sqlalchemy import select

    copied = (
        await db_session.execute(
            select(Widget).where(Widget.page_id != page.id)
        )
    ).scalar_one()
    assert copied.data["infographic_data"]["drivers"][0]["name"] == "a"


@pytest.mark.asyncio
async def test_duplicate_page_rejects_non_member(db_session, test_user):
    from src.core.exceptions import ForbiddenError
    from src.models.user import User
    from src.repositories.user import UserRepository

    owner = test_user["user"]
    page = Page(
        id=uuid4(),
        name="Private",
        type="personal",
        owner_id=owner.id,
        color="#000000",
        icon="page",
    )
    db_session.add(page)
    await db_session.commit()

    # Create an unrelated user (not owner, not member)
    outsider = await UserRepository(db_session).create(
        email="outsider@example.com",
        password_hash="x",
        name="Out",
        role="user",
    )
    await db_session.commit()

    svc = PageService(db_session)
    with pytest.raises(ForbiddenError):
        await svc.duplicate_page(page.id, outsider)
