"""Backfill script for Planet Isolation."""

import asyncio
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Import models
from src.config.settings import settings
from src.models.ai import AIHistory, AIQuery, ChatMessage
from src.models.dashboard import Dashboard, Widget
from src.models.planet import Planet, PlanetMember
from src.models.user import User
from src.services.onboarding_service import ensure_default_planet_and_space

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def backfill():
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # 1. Ensure all users have a planet
        logger.info("Step 1: Ensuring all users have a personal planet...")
        result = await db.execute(select(User))
        users = result.scalars().all()

        for user in users:
            await ensure_default_planet_and_space(db, user)

        await db.commit()

        # 2. Map ChatMessages to Planet via Widget -> Dashboard
        logger.info("Step 2: Backfilling ChatMessages...")
        # Get all chat messages with null planet_id
        stmt = select(ChatMessage).where(ChatMessage.planet_id.is_(None))
        result = await db.execute(stmt)
        messages = result.scalars().all()

        for msg in messages:
            # Get widget's planet
            stmt = select(Dashboard.planet_id).join(Widget).where(Widget.id == msg.widget_id)
            res = await db.execute(stmt)
            planet_id = res.scalar_one_or_none()
            if planet_id:
                msg.planet_id = planet_id

        await db.commit()

        # 3. Map AIQueries and AIHistory to User's Personal Planet
        logger.info("Step 3: Backfilling AIQueries and AIHistory...")

        for user in users:
            # Get personal planet for user
            stmt = (
                select(Planet.id)
                .where(Planet.owner_id == user.id, Planet.type == "personal")
                .limit(1)
            )
            res = await db.execute(stmt)
            personal_planet_id = res.scalar_one_or_none()

            if not personal_planet_id:
                # Fallback to any planet owned by user
                stmt = select(Planet.id).where(Planet.owner_id == user.id).limit(1)
                res = await db.execute(stmt)
                personal_planet_id = res.scalar_one_or_none()

            if personal_planet_id:
                # Update AIQueries
                await db.execute(
                    update(AIQuery)
                    .where(AIQuery.user_id == user.id, AIQuery.planet_id.is_(None))
                    .values(planet_id=personal_planet_id)
                )

                # Update AIHistory
                await db.execute(
                    update(AIHistory)
                    .where(AIHistory.user_id == user.id, AIHistory.planet_id.is_(None))
                    .values(planet_id=personal_planet_id)
                )

        await db.commit()
        logger.info("Backfill completed successfully.")


if __name__ == "__main__":
    asyncio.run(backfill())
