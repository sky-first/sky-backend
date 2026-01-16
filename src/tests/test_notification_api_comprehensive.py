
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4
from datetime import datetime, timezone

from src.models.notification import Notification, NotificationType
from src.models.comment import Comment
from src.models.dashboard import Dashboard
from src.models.planet import Planet
from src.schemas.notification import NotificationCreate
from src.services.notification_service import NotificationService

def get_auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}

@pytest.mark.asyncio
class TestNotificationAPI:
    """Tests for notification API endpoints."""

    async def test_list_notifications(self, client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession):
        user = test_user_with_tokens["user"]
        service = NotificationService(db_session)

        # Create a test notification
        await service.create(NotificationCreate(
            user_id=user.id,
            type=NotificationType.DASHBOARD_UPDATED,
            title="Update",
            entity_type="dashboard",
            entity_id=str(uuid4())
        ))

        headers = get_auth_headers(test_user_with_tokens["access_token"])
        response = client.get("/api/v1/notifications/", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["title"] == "Update"

    async def test_unread_count(self, client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession):
        user = test_user_with_tokens["user"]
        service = NotificationService(db_session)

        await service.create(NotificationCreate(
            user_id=user.id,
            type=NotificationType.NEW_INSIGHT_AVAILABLE,
            title="Insight",
            entity_type="metric",
            entity_id=str(uuid4())
        ))

        headers = get_auth_headers(test_user_with_tokens["access_token"])
        response = client.get("/api/v1/notifications/unread-count", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 1

    async def test_mark_as_read(self, client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession):
        user = test_user_with_tokens["user"]
        service = NotificationService(db_session)

        notif = await service.create(NotificationCreate(
            user_id=user.id,
            type=NotificationType.COMMENT_MENTION,
            title="Mention",
            entity_type="comment",
            entity_id=str(uuid4())
        ))

        headers = get_auth_headers(test_user_with_tokens["access_token"])
        response = client.post(f"/api/v1/notifications/{notif.id}/read", headers=headers)
        assert response.status_code == 200
        assert response.json()["updated"] == 1

        # Verify in DB
        updated_notif = await db_session.get(Notification, notif.id)
        assert updated_notif.is_read is True

    async def test_mark_all_as_read(self, client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession):
        user = test_user_with_tokens["user"]
        service = NotificationService(db_session)

        for _ in range(2):
            await service.create(NotificationCreate(
                user_id=user.id,
                type=NotificationType.DASHBOARD_UPDATED,
                title="Bulk",
                entity_type="dashboard",
                entity_id=str(uuid4())
            ))

        headers = get_auth_headers(test_user_with_tokens["access_token"])
        response = client.post("/api/v1/notifications/read-all", headers=headers)
        assert response.status_code == 200
        assert response.json()["updated"] >= 2

@pytest.mark.asyncio
class TestCommentAPI:
    """Tests for comment API endpoints."""

    async def test_create_comment_and_trigger_notification(self, client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession):
        user = test_user_with_tokens["user"]

        # Create another user to mention
        from src.models.user import User
        other_user = User(
            id=uuid4(), email="other@example.com", name="Other User", password_hash="hash"
        )
        db_session.add(other_user)
        await db_session.commit()

        # Setup: Planet and Dashboard
        planet = Planet(
            id=uuid4(), name="Test Planet", owner_id=user.id, type="team", color="#000000",
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)
        )
        db_session.add(planet)
        await db_session.commit()

        dashboard = Dashboard(
            id=uuid4(), name="Test Dash", created_by=user.id, planet_id=planet.id,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)
        )
        db_session.add(dashboard)
        await db_session.commit()

        headers = get_auth_headers(test_user_with_tokens["access_token"])
        comment_data = {
            "dashboard_id": str(dashboard.id),
            "content": "Hello @other",
            "mentions": [str(other_user.id)]
        }

        response = client.post("/api/v1/comments/", json=comment_data, headers=headers)
        assert response.status_code == 201

        # Verify notification was created for the mention
        other_user_id = other_user.id
        from sqlalchemy.future import select
        # Refresh session to ensure we see the committed changes from the API call
        db_session.expire_all()
        stmt = select(Notification).where(Notification.user_id == other_user_id)
        result = await db_session.execute(stmt)
        all_notifs = result.scalars().all()

        stmt = select(Notification).where(Notification.user_id == other_user_id, Notification.type == NotificationType.COMMENT_MENTION)
        result = await db_session.execute(stmt)
        notif = result.scalars().first()
        assert notif is not None
        assert "mentioned" in notif.title.lower()

    async def test_get_dashboard_comments(self, client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession):
        user = test_user_with_tokens["user"]

        # Setup: Planet and Dashboard
        planet = Planet(
            id=uuid4(), name="Test Planet", owner_id=user.id, type="team", color="#000000",
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)
        )
        db_session.add(planet)
        await db_session.commit()

        dashboard = Dashboard(
            id=uuid4(), name="Test Dash", created_by=user.id, planet_id=planet.id,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)
        )
        db_session.add(dashboard)
        await db_session.commit()

        # Create a comment
        comment = Comment(
            id=uuid4(), user_id=user.id, dashboard_id=dashboard.id, content="Comment 1",
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)
        )
        db_session.add(comment)
        await db_session.commit()

        headers = get_auth_headers(test_user_with_tokens["access_token"])
        response = client.get(f"/api/v1/comments?dashboard_id={dashboard.id}", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["content"] == "Comment 1"
