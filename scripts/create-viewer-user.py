import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import select
from src.core.security import get_password_hash
from src.models.user import User
from src.services.onboarding_service import ensure_default_planet_and_space

async def create_viewer_user():
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:09SQUOARD5OvNCXd8KRjUse0qq0DLvACGN%2BO2XwriDY%3D@localhost:5433/ai_saas_db",
    )

    engine = create_async_engine(database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(select(User).where(User.email == "viewer@example.com"))
        user = result.scalar_one_or_none()

        if user:
            user.password_hash = get_password_hash("password123")
            user.role = "viewer"
            session.add(user)
            await session.commit()
            print("✅ Viewer user updated.")
        else:
            user = User(
                email="viewer@example.com",
                password_hash=get_password_hash("password123"),
                name="Viewer User",
                role="viewer",
                email_verified=True,
                has_completed_onboarding=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            print("✅ Viewer user created.")
        
        # Ensure default planet/dashboard via onboarding service
        await ensure_default_planet_and_space(session, user)
        print("✅ Default planet and dashboard ensured.")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(create_viewer_user())
