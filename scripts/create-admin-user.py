#!/usr/bin/env python3
import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from src.core.security import get_password_hash
from src.models.user import User

async def create_admin_user():
    database_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db")
    engine = create_async_engine(database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(User).where(User.email == "admin@example.com"))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            existing_user.password_hash = get_password_hash("password123")
            existing_user.role = "admin"
            session.add(existing_user)
            await session.commit()
            print("✅ Admin user updated.")
            return

        admin_user = User(
            email="admin@example.com",
            password_hash=get_password_hash("password123"),
            name="Admin User",
            role="admin",
            email_verified=True,
            has_completed_onboarding=True,
        )
        session.add(admin_user)
        await session.commit()
        print("✅ Admin user created.")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(create_admin_user())
