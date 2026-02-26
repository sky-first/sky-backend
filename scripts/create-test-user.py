#!/usr/bin/env python3
"""Script to create a test user for development."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.core.security import get_password_hash
from src.models.planet import Planet  # noqa: F401
from src.models.user import User

# Import related models to register relationships (avoid mapper lookup errors)
from src.models.workspace import Workspace  # noqa: F401


async def create_test_user():
    """Create a test user."""
    import os

    # Database URL from environment or default
    database_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db"
    )

    engine = create_async_engine(database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        # Check if user already exists
        from sqlalchemy import select

        result = await session.execute(select(User).where(User.email == "test@example.com"))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            # Update password to ensure it matches current reference
            existing_user.password_hash = get_password_hash("Test@2024!Secure")
            session.add(existing_user)
            await session.commit()
            print("✅ Test user already exists (password refreshed).")
            print("   Email: test@example.com")
            print("   Password: Test@2024!Secure")
            return

        # Create test user
        test_user = User(
            email="test@example.com",
            password_hash=get_password_hash("Test@2024!Secure"),
            name="Test User",
            role="user",
            email_verified=True,
            has_completed_onboarding=True,
        )

        session.add(test_user)
        await session.commit()

        print("✅ Test user created successfully!")
        print("   Email: test@example.com")
        print("   Password: Test@2024!Secure")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_test_user())
