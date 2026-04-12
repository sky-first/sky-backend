"""TDD test suite for the notifications overhaul — Groups A (CRUD) and B (Preferences).

These tests exercise the new endpoints and the preference-aware notification
gating added in feat/DO2025-notifications-overhaul. Written RED-first:
every test describes the expected contract and should turn GREEN as the
implementation is wired correctly.
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.notification import NOTIFICATION_CATEGORY, Notification, NotificationType
from src.schemas.notification import NotificationCreate
from src.services.notification_preference_service import NotificationPreferenceService
from src.services.notification_service import NotificationService


def auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _seed(db: AsyncSession, user_id, n_type="dashboard_updated", title="Test", read=False):
    """Helper: insert a notification directly and return it."""
    svc = NotificationService(db)
    notif = await svc.create(
        NotificationCreate(
            user_id=user_id,
            type=n_type,
            title=title,
            entity_type="dashboard",
            entity_id=str(uuid4()),
            deep_link="/dashboards/test",
        )
    )
    if read and notif:
        await svc.mark_notification_as_read(notif.id, user_id)
    return notif


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP A — Notification CRUD
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestNotificationCRUD:
    """A1–A9: list, count, mark-read, delete, categories."""

    # A1 — List notifications (paginated)
    async def test_a1_list_notifications_returns_user_notifications(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]
        await _seed(db_session, user.id, title="First")
        await _seed(db_session, user.id, title="Second")

        resp = await async_client.get("/api/v1/notifications?limit=10", headers=auth(test_user_with_tokens))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        titles = {n["title"] for n in data}
        assert "First" in titles
        assert "Second" in titles

    # A1b — Pagination respects limit/offset
    async def test_a1b_list_respects_limit(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]
        for i in range(5):
            await _seed(db_session, user.id, title=f"N{i}")

        resp = await async_client.get("/api/v1/notifications?limit=2", headers=auth(test_user_with_tokens))
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    # A2 — Unread filter
    async def test_a2_list_unread_only(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]
        await _seed(db_session, user.id, title="Unread")
        await _seed(db_session, user.id, title="Read", read=True)

        resp = await async_client.get(
            "/api/v1/notifications?unread_only=true", headers=auth(test_user_with_tokens)
        )
        assert resp.status_code == 200
        titles = [n["title"] for n in resp.json()]
        assert "Unread" in titles
        assert "Read" not in titles

    # A3 — Unread count
    async def test_a3_unread_count(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]
        await _seed(db_session, user.id, title="U1")
        await _seed(db_session, user.id, title="U2")
        await _seed(db_session, user.id, title="R1", read=True)

        resp = await async_client.get("/api/v1/notifications/unread-count", headers=auth(test_user_with_tokens))
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

    # A4 — Mark single as read
    async def test_a4_mark_as_read(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]
        notif = await _seed(db_session, user.id)

        resp = await async_client.post(
            f"/api/v1/notifications/{notif.id}/read", headers=auth(test_user_with_tokens)
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Verify count dropped
        count_resp = await async_client.get(
            "/api/v1/notifications/unread-count", headers=auth(test_user_with_tokens)
        )
        assert count_resp.json()["count"] == 0

    # A4b — Mark non-existent returns 404
    async def test_a4b_mark_nonexistent_returns_404(
        self, async_client: AsyncClient, test_user_with_tokens: dict
    ):
        resp = await async_client.post(
            f"/api/v1/notifications/{uuid4()}/read", headers=auth(test_user_with_tokens)
        )
        assert resp.status_code == 404

    # A5 — Mark all as read
    async def test_a5_mark_all_as_read(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]
        await _seed(db_session, user.id)
        await _seed(db_session, user.id)

        resp = await async_client.post("/api/v1/notifications/read-all", headers=auth(test_user_with_tokens))
        assert resp.status_code == 200
        assert resp.json()["updated"] >= 2

        count_resp = await async_client.get(
            "/api/v1/notifications/unread-count", headers=auth(test_user_with_tokens)
        )
        assert count_resp.json()["count"] == 0

    # A6 — Delete single notification
    async def test_a6_delete_single(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]
        notif = await _seed(db_session, user.id)

        resp = await async_client.delete(
            f"/api/v1/notifications/{notif.id}", headers=auth(test_user_with_tokens)
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1

        # Verify it's gone
        list_resp = await async_client.get("/api/v1/notifications", headers=auth(test_user_with_tokens))
        ids = [n["id"] for n in list_resp.json()]
        assert str(notif.id) not in ids

    # A6b — Delete non-existent returns 404
    async def test_a6b_delete_nonexistent_returns_404(
        self, async_client: AsyncClient, test_user_with_tokens: dict
    ):
        resp = await async_client.delete(
            f"/api/v1/notifications/{uuid4()}", headers=auth(test_user_with_tokens)
        )
        assert resp.status_code == 404

    # A7 — Delete all notifications
    async def test_a7_delete_all(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]
        await _seed(db_session, user.id, title="D1")
        await _seed(db_session, user.id, title="D2")
        await _seed(db_session, user.id, title="D3")

        resp = await async_client.delete("/api/v1/notifications", headers=auth(test_user_with_tokens))
        assert resp.status_code == 200
        assert resp.json()["deleted"] >= 3

        list_resp = await async_client.get("/api/v1/notifications", headers=auth(test_user_with_tokens))
        assert len(list_resp.json()) == 0

    # A8 — Delete by category
    async def test_a8_delete_by_category(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]
        await _seed(db_session, user.id, n_type="agent_finding", title="Agent insight")
        await _seed(db_session, user.id, n_type="comment_mention", title="You were mentioned")

        resp = await async_client.delete(
            "/api/v1/notifications?category=agents", headers=auth(test_user_with_tokens)
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] >= 1

        # Mention should still be there
        list_resp = await async_client.get("/api/v1/notifications", headers=auth(test_user_with_tokens))
        remaining = [n["title"] for n in list_resp.json()]
        assert "You were mentioned" in remaining
        assert "Agent insight" not in remaining

    # A9 — Categories endpoint
    async def test_a9_categories_returns_list(
        self, async_client: AsyncClient, test_user_with_tokens: dict
    ):
        resp = await async_client.get("/api/v1/notifications/categories", headers=auth(test_user_with_tokens))
        assert resp.status_code == 200
        cats = resp.json()["categories"]
        assert "agents" in cats
        assert "mentions" in cats
        assert "collaboration" in cats
        assert "dashboards" in cats


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP B — Preferences (Mute / Pause / Focus Mode)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestNotificationPreferences:
    """B1–B10: pause, mute by category, mute by source, suppression logic."""

    # B1 — Pause all (focus mode ON)
    async def test_b1_pause_all(
        self, async_client: AsyncClient, test_user_with_tokens: dict
    ):
        resp = await async_client.post(
            "/api/v1/notifications/preferences/pause",
            json={"paused": True},
            headers=auth(test_user_with_tokens),
        )
        assert resp.status_code == 200
        assert resp.json()["paused"] is True

    # B2 — Resume (focus mode OFF)
    async def test_b2_resume(
        self, async_client: AsyncClient, test_user_with_tokens: dict
    ):
        # First pause
        await async_client.post(
            "/api/v1/notifications/preferences/pause",
            json={"paused": True},
            headers=auth(test_user_with_tokens),
        )
        # Then resume
        resp = await async_client.post(
            "/api/v1/notifications/preferences/pause",
            json={"paused": False},
            headers=auth(test_user_with_tokens),
        )
        assert resp.status_code == 200
        assert resp.json()["paused"] is False

    # B3 — Mute by category
    async def test_b3_mute_category(
        self, async_client: AsyncClient, test_user_with_tokens: dict
    ):
        resp = await async_client.put(
            "/api/v1/notifications/preferences",
            json={
                "preferences": [
                    {"scope_type": "category", "scope_value": "agents", "channel": "all", "enabled": False}
                ]
            },
            headers=auth(test_user_with_tokens),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["scope_type"] == "category"
        assert data[0]["scope_value"] == "agents"
        assert data[0]["enabled"] is False

    # B4 — Mute by source
    async def test_b4_mute_source(
        self, async_client: AsyncClient, test_user_with_tokens: dict
    ):
        agent_id = str(uuid4())
        resp = await async_client.put(
            "/api/v1/notifications/preferences",
            json={
                "preferences": [
                    {"scope_type": "source", "scope_value": f"agent:{agent_id}", "channel": "all", "enabled": False}
                ]
            },
            headers=auth(test_user_with_tokens),
        )
        assert resp.status_code == 200
        assert resp.json()[0]["scope_value"] == f"agent:{agent_id}"

    # B5 — Unmute (re-enable)
    async def test_b5_unmute(
        self, async_client: AsyncClient, test_user_with_tokens: dict
    ):
        # Mute
        await async_client.put(
            "/api/v1/notifications/preferences",
            json={"preferences": [{"scope_type": "category", "scope_value": "agents", "enabled": False}]},
            headers=auth(test_user_with_tokens),
        )
        # Unmute
        resp = await async_client.put(
            "/api/v1/notifications/preferences",
            json={"preferences": [{"scope_type": "category", "scope_value": "agents", "enabled": True}]},
            headers=auth(test_user_with_tokens),
        )
        assert resp.status_code == 200
        assert resp.json()[0]["enabled"] is True

    # B6 — List preferences
    async def test_b6_list_preferences(
        self, async_client: AsyncClient, test_user_with_tokens: dict
    ):
        # Set a preference first
        await async_client.put(
            "/api/v1/notifications/preferences",
            json={"preferences": [{"scope_type": "category", "scope_value": "mentions", "enabled": False}]},
            headers=auth(test_user_with_tokens),
        )

        resp = await async_client.get(
            "/api/v1/notifications/preferences", headers=auth(test_user_with_tokens)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert any(p["scope_value"] == "mentions" for p in data)

    # B7 — Notification suppressed when focus mode active
    async def test_b7_focus_mode_suppresses_notification(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]

        # Enable focus mode
        pref_svc = NotificationPreferenceService(db_session)
        await pref_svc.toggle_pause(user.id, True)

        # Try to create — should be suppressed
        svc = NotificationService(db_session)
        result = await svc.create(
            NotificationCreate(
                user_id=user.id,
                type="agent_finding",
                title="This should be muted",
                entity_type="agent",
                entity_id=str(uuid4()),
            )
        )
        assert result is None

        # Count should be 0
        count = await svc.get_unread_count(user.id)
        assert count == 0

    # B8 — Notification suppressed when category muted
    async def test_b8_category_mute_suppresses(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]

        # Mute agents category
        pref_svc = NotificationPreferenceService(db_session)
        await pref_svc.update_preferences(
            user.id,
            [__import__("src.schemas.notification_preference", fromlist=["NotificationPreferenceCreate"]).NotificationPreferenceCreate(
                scope_type="category", scope_value="agents", channel="all", enabled=False
            )]
        )

        # Agent notification should be suppressed
        svc = NotificationService(db_session)
        result = await svc.create(
            NotificationCreate(
                user_id=user.id,
                type="agent_finding",
                title="Muted agent insight",
                entity_type="agent",
                entity_id=str(uuid4()),
            )
        )
        assert result is None

    # B9 — Notification suppressed when specific source muted
    async def test_b9_source_mute_suppresses(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]
        agent_id = str(uuid4())

        # Mute this specific agent
        pref_svc = NotificationPreferenceService(db_session)
        await pref_svc.update_preferences(
            user.id,
            [__import__("src.schemas.notification_preference", fromlist=["NotificationPreferenceCreate"]).NotificationPreferenceCreate(
                scope_type="source", scope_value=f"agent:{agent_id}", channel="all", enabled=False
            )]
        )

        # Notification from THAT agent → suppressed
        svc = NotificationService(db_session)
        result = await svc.create(
            NotificationCreate(
                user_id=user.id,
                type="agent_finding",
                title="Muted source",
                entity_type="agent",
                entity_id=agent_id,
            )
        )
        assert result is None

    # B10 — Notification NOT suppressed when DIFFERENT source muted
    async def test_b10_different_source_not_suppressed(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]
        muted_agent = str(uuid4())
        other_agent = str(uuid4())

        # Mute one specific agent
        pref_svc = NotificationPreferenceService(db_session)
        await pref_svc.update_preferences(
            user.id,
            [__import__("src.schemas.notification_preference", fromlist=["NotificationPreferenceCreate"]).NotificationPreferenceCreate(
                scope_type="source", scope_value=f"agent:{muted_agent}", channel="all", enabled=False
            )]
        )

        # Notification from a DIFFERENT agent → should go through
        svc = NotificationService(db_session)
        result = await svc.create(
            NotificationCreate(
                user_id=user.id,
                type="agent_finding",
                title="Different agent — not muted",
                entity_type="agent",
                entity_id=other_agent,
            )
        )
        assert result is not None
        assert result.title == "Different agent — not muted"


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP C — Event Producers (service-level)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestNotificationProducers:
    """C1, C6–C8: verify that service calls create notifications."""

    # C6 — Page member added creates notification
    async def test_c6_page_member_added_notification(
        self, async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
    ):
        user = test_user_with_tokens["user"]
        # Create a page, then add a second user
        from src.services.page_service import PageService
        from src.schemas.page import PageCreate

        page_svc = PageService(db_session)
        page = await page_svc.create_page(user, PageCreate(name="Notify Test", type="personal", color="#3B82F6"))

        # Create another user to be the member
        from src.repositories.user import UserRepository
        from src.core.security import get_password_hash

        user_repo = UserRepository(db_session)
        member_user = await user_repo.create(
            email="member@test.com",
            password_hash=get_password_hash("pass123"),
            name="Member User",
            role="user",
        )
        await db_session.commit()

        from src.schemas.page import PageMemberCreate
        await page_svc.add_member(page.id, user, PageMemberCreate(user_id=member_user.id, role="viewer"))

        # Check that the member received a notification
        svc = NotificationService(db_session)
        notifs = await svc.get_notifications(member_user.id)
        assert any("Notify Test" in (n.title or "") for n in notifs)


# ═══════════════════════════════════════════════════════════════════════════════
# CATALOG — Sanity checks on the type → category mapping
# ═══════════════════════════════════════════════════════════════════════════════


class TestNotificationCatalog:
    """Verify the NOTIFICATION_CATEGORY dict is complete and consistent."""

    def test_every_enum_value_has_a_category(self):
        for member in NotificationType:
            assert member.value in NOTIFICATION_CATEGORY, (
                f"NotificationType.{member.name} ({member.value}) has no entry in NOTIFICATION_CATEGORY"
            )

    def test_category_values_are_known(self):
        known = {"agents", "dashboards", "pages", "mentions", "collaboration", "connections", "strategy", "system"}
        for ntype, category in NOTIFICATION_CATEGORY.items():
            assert category in known, f"Unknown category '{category}' for type '{ntype}'"
