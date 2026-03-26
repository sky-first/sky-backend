import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import all models to ensure relations are defined before mapper initialization
from src.models.user import User, RefreshToken
from src.models.planet import Planet, PlanetMember
from src.models.workspace import Workspace, WorkspaceMember
from src.models.starred import StarredItem
from src.models.dashboard import Dashboard

from sqlalchemy import select, delete
from src.config.database import AsyncSessionLocal, engine
from src.config.settings import settings
from src.core.security import get_password_hash
from src.services.onboarding_service import ensure_default_planet_and_space

async def recreate_users():
    print(f" usando DATABASE_URL: {settings.DATABASE_URL}")

    users_to_create = [
        {
            "email": "admin@example.com",
            "password": "password123",
            "name": "Admin User",
            "role": "admin"
        },
        {
            "email": "viewer@example.com",
            "password": "password123",
            "name": "Viewer User",
            "role": "viewer"
        }
    ]

    async with AsyncSessionLocal() as session:
        for user_data in users_to_create:
            # Delete existing
            await session.execute(delete(User).where(User.email == user_data["email"]))
            
            # Create new
            user = User(
                email=user_data["email"],
                password_hash=get_password_hash(user_data["password"]),
                name=user_data["name"],
                role=user_data["role"],
                email_verified=True,
                has_completed_onboarding=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            
            # Ensure onboarding (planets, spaces, dashboards)
            await ensure_default_planet_and_space(session, user)
            print(f"✅ User {user_data['email']} recreated with password '{user_data['password']}'")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(recreate_users())
