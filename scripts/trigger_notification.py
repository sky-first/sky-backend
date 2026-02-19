import asyncio
import sys
import os

# Add the src directory to the path
sys.path.append(os.getcwd())

from src.config.database import init_db, get_db
from src.services.notification_service import NotificationService
from src.services.comment_service import CommentService
from src.schemas.notification import NotificationCreate
from src.schemas.comment import CommentCreate
from src.models.notification import NotificationType, Notification
from src.models.user import User
from src.models.dashboard import Dashboard
from sqlalchemy.future import select
from sqlalchemy import delete

# Trigger all models registration
import src.models


async def trigger_test_notification():
    print("🚀 Initializing database...")
    await init_db()

    async for db in get_db():
        # 1. Get a user to notify (the first one)
        result = await db.execute(select(User).limit(1))
        user = result.scalars().first()

        if not user:
            print("❌ No users found in database.")
            return

        # 2. Get a dashboard (optional, but good for deep linking)
        result = await db.execute(select(Dashboard).limit(1))
        dashboard = result.scalars().first()
        dashboard_id = dashboard.id if dashboard else "3fa85f64-5717-4562-b3fc-2c963f66afa6"

        print(f"👤 Notifying User: {user.email} (ID: {user.id})")
        print(f"📊 Using Dashboard ID: {dashboard_id}")

        # Clean current notifications
        print(f"🧹 Clearing notifications for user {user.id}...")
        await db.execute(delete(Notification).where(Notification.user_id == user.id))
        await db.commit()

        # 3. Create a Direct Notification (Simple way)
        notification_service = NotificationService(db)
        await notification_service.create(
            NotificationCreate(
                user_id=user.id,
                type=NotificationType.NEW_INSIGHT_AVAILABLE,
                title="🚀 Test Notification!",
                description="This notification was generated via script to test the frontend bell.",
                entity_type="test",
                entity_id=str(user.id),
                deep_link=f"/dashboards/{dashboard_id}" if dashboard else None,
            )
        )
        print("✅ Direct Notification created!")

        # 4. Create a Comment Mention (Complete way)
        comment_service = CommentService(db)
        if dashboard:
            await comment_service.create(
                user_id=user.id,  # As if they mentioned themselves
                comment_data=CommentCreate(
                    content="Check this out! @test", dashboard_id=dashboard.id, mentions=[user.id]
                ),
            )
            print("✅ Comment Mention triggered!")

        print("\n✨ Done! Now check your Dashboard Bell 🔔 (you might need to refresh).")
        break


if __name__ == "__main__":
    asyncio.run(trigger_test_notification())
