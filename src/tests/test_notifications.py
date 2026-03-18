from uuid import uuid4

import pytest

from src.models.dashboard import Dashboard
from src.models.notification import NotificationType
from src.models.planet import Planet
from src.models.user import User
from src.schemas.comment import CommentCreate
from src.schemas.notification import NotificationCreate
from src.services.comment_service import CommentService
from src.services.notification_service import NotificationService


@pytest.fixture
async def test_user(db_session):
    user = User(
        id=uuid4(),
        email=f"test_{uuid4().hex[:6]}@example.com",
        name="Test User",
        password_hash="hash",
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.fixture
async def test_planet(db_session, test_user):
    planet = Planet(
        id=uuid4(),
        name="Test Planet",
        owner_id=test_user.id,
        type="team",
        color="#000000",
    )
    db_session.add(planet)
    await db_session.commit()
    return planet


@pytest.fixture
async def test_dashboard(db_session, test_user, test_planet):
    dashboard = Dashboard(
        id=uuid4(),
        name="Test Dashboard",
        created_by=test_user.id,
        planet_id=test_planet.id,
    )
    db_session.add(dashboard)
    await db_session.commit()
    return dashboard


async def test_create_notification(db_session, test_user):
    service = NotificationService(db_session)
    notif_data = NotificationCreate(
        user_id=test_user.id,
        type=NotificationType.NEW_INSIGHT_AVAILABLE,
        title="Test Title",
        description="Test Desc",
        entity_type="test",
        entity_id=str(uuid4()),
    )
    notif = await service.create(notif_data)
    assert notif.title == "Test Title"
    assert notif.is_read is False


async def test_get_unread_notifications(db_session, test_user):
    service = NotificationService(db_session)
    # Create two notifications
    for i in range(2):
        await service.create(
            NotificationCreate(
                user_id=test_user.id,
                type=NotificationType.DASHBOARD_EDITED_BY_OTHER,
                title=f"Title {i}",
                entity_type="test",
                entity_id=str(uuid4()),
            )
        )

    notifs = await service.get_for_user(test_user.id, unread_only=True)
    assert len(notifs) == 2

    count = await service.get_unread_count(test_user.id)
    assert count == 2


async def test_mark_as_read(db_session, test_user):
    service = NotificationService(db_session)
    notif = await service.create(
        NotificationCreate(
            user_id=test_user.id,
            type=NotificationType.COMMENT_MENTION,
            title="To be read",
            entity_type="test",
            entity_id=str(uuid4()),
        )
    )

    rows_updated = await service.mark_as_read(test_user.id, [notif.id])
    assert rows_updated == 1

    # Fetch again to verify
    notifs = await service.get_for_user(test_user.id)
    updated = notifs[0]
    assert updated.is_read is True
    assert updated.read_at is not None


async def test_mark_all_as_read(db_session, test_user):
    service = NotificationService(db_session)
    for _ in range(3):
        await service.create(
            NotificationCreate(
                user_id=test_user.id,
                type=NotificationType.NEW_INSIGHT_AVAILABLE,
                title="Bulk",
                entity_type="test",
                entity_id=str(uuid4()),
            )
        )

    await service.mark_all_as_read(test_user.id)
    count = await service.get_unread_count(test_user.id)
    assert count == 0


async def test_comment_mention_trigger(db_session, test_user, test_dashboard):
    comment_service = CommentService(db_session)
    notif_service = NotificationService(db_session)

    comment = await comment_service.create(
        user_id=uuid4(),  # Different user
        comment_data=CommentCreate(
            content="Hey @test", dashboard_id=test_dashboard.id, mentions=[test_user.id]
        ),
    )

    assert comment.content == "Hey @test"

    # Check if notification was created for test_user
    notifs = await notif_service.get_for_user(test_user.id)
    assert len(notifs) == 1
    assert notifs[0].type == NotificationType.COMMENT_MENTION


async def test_get_comments_by_dashboard(db_session, test_dashboard):
    service = CommentService(db_session)
    user_id = uuid4()
    await service.create(user_id, CommentCreate(content="C1", dashboard_id=test_dashboard.id))
    await service.create(user_id, CommentCreate(content="C2", dashboard_id=test_dashboard.id))

    comments = await service.get_by_dashboard(test_dashboard.id)
    assert len(comments) == 2
