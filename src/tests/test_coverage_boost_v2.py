from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.page import Page
from src.models.user import User
from src.schemas.dashboard import (
    DashboardCreate,
    DashboardDuplicateRequest,
    DashboardUpdate,
    WidgetCreate,
    WidgetUpdate,
)
from src.schemas.page import PageCreate, PageMemberCreate, PageUpdate
from src.services.dashboard_service import DashboardService
from src.services.page_service import PageService


@pytest.mark.asyncio
class TestDashboardServiceBoost:
    async def test_dashboard_crud_full_success(self, db_session: AsyncSession, test_user: dict):
        user = test_user["user"]
        dash_service = DashboardService(db_session)
        page_service = PageService(db_session)

        # 1. Create Page first
        page_data = PageCreate(name="Test Page", type="personal", color="#123456")
        page_res = await page_service.create_page(user, page_data)

        # 2. Create Dashboard
        dash_data = DashboardCreate(name="My Dash", page_id=page_res.id)
        dash_res = await dash_service.create_dashboard(user, dash_data)
        assert dash_res.name == "My Dash"
        assert dash_res.page_id == page_res.id

        # 3. Get Dashboard
        got_dash = await dash_service.get_dashboard(dash_res.id, user)
        assert got_dash.id == dash_res.id

        # 4. List Page Dashboards
        dash_list = await dash_service.get_page_dashboards(page_res.id, user)
        assert len(dash_list) >= 1

        # 5. Update Dashboard
        updated_dash = await dash_service.update_dashboard(
            dash_res.id, user, DashboardUpdate(name="Renamed Dash", is_locked=True)
        )
        assert updated_dash.name == "Renamed Dash"
        assert updated_dash.is_locked is True

        # 6. Create Widget
        widget_data = WidgetCreate(
            dashboard_id=dash_res.id,
            type="chart",
            title="Widget 1",
            position={"x": 10, "y": 20},
            size={"width": 100, "height": 200},
        )
        widget_res = await dash_service.create_widget(user, widget_data)
        assert widget_res.title == "Widget 1"

        # 7. Get Widget
        got_widget = await dash_service.get_widget(widget_res.id, user)
        assert got_widget.id == widget_res.id

        # 8. Get Dashboard Widgets
        widgets = await dash_service.get_dashboard_widgets(dash_res.id, user)
        assert len(widgets) >= 1

        # 9. Update Widget
        updated_widget = await dash_service.update_widget(
            widget_res.id, user, WidgetUpdate(title="New Title")
        )
        assert updated_widget.title == "New Title"

        # 10. Duplicate Widget
        dup_widget = await dash_service.duplicate_widget(widget_res.id, user)
        assert "Copy" in dup_widget.title

        # 11. Export Widget
        exported = await dash_service.export_widget(widget_res.id, user)
        assert exported["title"] == "New Title"

        # 12. Get Widget Data
        w_data = await dash_service.get_widget_data(widget_res.id, user)
        assert "data" in w_data

        # 13. Refresh Widget Data
        refreshed = await dash_service.refresh_widget_data(widget_res.id, user)
        assert "last_updated" in refreshed

        # 14. Export Dashboard
        exp_dash = await dash_service.export_dashboard(dash_res.id, user)
        assert exp_dash.dashboard.id == dash_res.id
        assert len(exp_dash.widgets) >= 2

        # 15. Duplicate Dashboard
        dup_dash = await dash_service.duplicate_dashboard(
            dash_res.id, user, DashboardDuplicateRequest(name="Cloned Dash")
        )
        assert dup_dash.name == "Cloned Dash"

        # 16. Lock/Unlock
        locked = await dash_service.lock_dashboard(dash_res.id, user)
        assert locked.is_locked is True
        unlocked = await dash_service.unlock_dashboard(dash_res.id, user)
        assert unlocked.is_locked is False

        # 17. Delete Dashboard
        await dash_service.delete_dashboard(dash_res.id, user)
        with pytest.raises(NotFoundError):
            await dash_service.get_dashboard(dash_res.id, user)

    async def test_dashboard_failures(self, db_session: AsyncSession, test_user: dict):
        user = test_user["user"]
        service = DashboardService(db_session)

        with pytest.raises(NotFoundError):
            await service.get_dashboard(uuid4(), user)

        with pytest.raises(NotFoundError):
            await service.update_dashboard(uuid4(), user, DashboardUpdate(name="X"))

        with pytest.raises(NotFoundError):
            await service.create_widget(
                user,
                WidgetCreate(
                    dashboard_id=uuid4(),
                    type="chart",
                    title="T",
                    position={"x": 0, "y": 0},
                    size={"width": 1, "height": 1},
                ),
            )


@pytest.mark.asyncio
class TestPageServiceBoost:
    async def test_page_crud_full_success(self, db_session: AsyncSession, test_user: dict):
        user = test_user["user"]
        service = PageService(db_session)

        # 1. Create
        page_data = PageCreate(name="P1", type="personal", color="#000000")
        page = await service.create_page(user, page_data)
        assert page.name == "P1"

        # 2. Get
        got = await service.get_page(page.id, user)
        assert got.id == page.id

        # 3. Get User Pages
        pages = await service.get_user_pages(user)
        assert len(pages) >= 1

        # 4. Update
        updated = await service.update_page(page.id, user, PageUpdate(name="P2"))
        assert updated.name == "P2"

        # 5. Switch
        switched = await service.switch_page(page.id, user)
        assert switched.is_active is True

        # 6. Add Member
        other_user = User(id=uuid4(), email="other@test.com", name="Other", password_hash="hash")
        db_session.add(other_user)
        await db_session.commit()

        member = await service.add_member(
            page.id, user, PageMemberCreate(user_id=other_user.id, role="viewer")
        )
        assert member.user_id == other_user.id

        # 7. Get Members
        members = await service.get_page_members(page.id, user)
        assert len(members) >= 2

        # 8. Update Member Role
        updated_member = await service.update_member_role(page.id, other_user.id, "admin", user)
        assert updated_member.role == "admin"

        # 9. Remove Member
        await service.remove_member(page.id, other_user.id, user)
        members_after = await service.get_page_members(page.id, user)
        assert len(members_after) == 1

        # 10. Delete Page
        await service.delete_page(page.id, user)
        with pytest.raises(NotFoundError):
            await service.get_page(page.id, user)

    async def test_page_failures(self, db_session: AsyncSession, test_user: dict):
        user = test_user["user"]
        service = PageService(db_session)

        with pytest.raises(NotFoundError):
            await service.get_page(uuid4(), user)

        with pytest.raises(ForbiddenError):
            # Try to remove owner
            p = await service.create_page(
                user, PageCreate(name="P", type="personal", color="#000000")
            )
            await service.remove_member(p.id, user.id, user)

    async def test_page_switch_logic(self, db_session: AsyncSession, test_user: dict):
        user = test_user["user"]
        service = PageService(db_session)

        p1 = await service.create_page(
            user, PageCreate(name="P1", type="personal", color="#000000")
        )
        p2 = await service.create_page(
            user, PageCreate(name="P2", type="personal", color="#000000")
        )

        await service.switch_page(p1.id, user)

        # Verify p1 is active, p2 is not
        p1_db = await db_session.get(Page, p1.id)
        p2_db = await db_session.get(Page, p2.id)
        assert p1_db.is_active is True

        await service.switch_page(p2.id, user)
        # Re-fetch or refresh
        await db_session.refresh(p1_db)
        await db_session.refresh(p2_db)
        assert p2_db.is_active is True
        assert p1_db.is_active is False
