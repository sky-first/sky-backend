#!/usr/bin/env python3
import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from src.models.user import User
from src.models.planet import Planet, PlanetMember
from sqlalchemy import select

async def check_user_planets(email: str):
    database_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db")
    engine = create_async_engine(database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            print(f"❌ User {email} not found.")
            return

        print(f"👤 User: {user.name} ({user.role})")
        
        # Check owned planets
        result = await session.execute(select(Planet).where(Planet.owner_id == user.id))
        planets = result.scalars().all()
        print(f"🪐 Owned Planets ({len(planets)}):")
        for p in planets:
            print(f"  - {p.name} (ID: {p.id})")

        # Check memberships
        result = await session.execute(select(PlanetMember).where(PlanetMember.user_id == user.id))
        memberships = result.scalars().all()
        print(f"🤝 Memberships ({len(memberships)}):")
        for m in memberships:
            result = await session.execute(select(Planet).where(Planet.id == m.planet_id))
            planet = result.scalar_one_or_none()
            print(f"  - Planet: {planet.name if planet else 'UNKNOWN'} (Role: {m.role})")

    await engine.dispose()

if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "viewer@example.com"
    asyncio.run(check_user_planets(email))
