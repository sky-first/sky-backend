#!/usr/bin/env python3
"""Create test user using backend configuration."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from sqlalchemy import select

from src.config.database import AsyncSessionLocal, engine
from src.config.settings import settings
from src.core.security import get_password_hash
from src.models.planet import Planet  # noqa: F401
from src.models.user import User
from src.models.workspace import Workspace  # noqa: F401


async def create_test_user():
    """Create test user."""
    # Ensure tables exist
    from src.config.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # Check if user already exists
        result = await session.execute(select(User).where(User.email == "test@example.com"))
        existing_user = result.scalar_one_or_none()

        # New secure password: Test@2024!Secure
        new_password = "Test@2024!Secure"

        if existing_user:
            # Update password if user exists
            existing_user.password_hash = get_password_hash(new_password)
            existing_user.name = "Test User"
            existing_user.role = "admin"
            existing_user.email_verified = True
            existing_user.has_completed_onboarding = True
            await session.commit()
            print("✅ Test user updated successfully:")
            print(f"   Email: {existing_user.email}")
            print(f"   Password: {new_password}")
            return

        # Create test user
        test_user = User(
            email="test@example.com",
            password_hash=get_password_hash(new_password),
            name="Test User",
            role="admin",
            email_verified=True,
            has_completed_onboarding=True,
        )

        session.add(test_user)
        await session.commit()

        print("✅ Test user created successfully!")
        print("   Email: test@example.com")
        print(f"   Password: {new_password}")
        print(
            f"   Database: {settings.DATABASE_URL.split('@')[1] if '@' in settings.DATABASE_URL else 'N/A'}"
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_test_user())
