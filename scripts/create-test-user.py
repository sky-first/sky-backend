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


async def create_users():
    """Create test users."""
    import os
    import uuid
    from sqlalchemy import text, select

    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:09SQUOARD5OvNCXd8KRjUse0qq0DLvACGN%2BO2XwriDY%3D@localhost:5433/ai_saas_db",
    )

    engine = create_async_engine(database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    users_to_create = [
        {"email": "admin@example.com", "name": "Admin User", "role": "admin"},
        {"email": "viewer@example.com", "name": "Viewer User", "role": "user"},
    ]

    async with async_session() as session:
        for u_data in users_to_create:
            # Raw SQL select to check if exists
            result = await session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": u_data["email"]}
            )
            existing_user_id = result.scalar()

            if existing_user_id:
                await session.execute(
                    text("UPDATE users SET password_hash = :pw_hash, role = :role WHERE id = :id"),
                    {
                        "pw_hash": get_password_hash("password123"),
                        "role": u_data["role"],
                        "id": existing_user_id
                    }
                )
                print(f"✅ User {u_data['email']} updated.")
            else:
                user_id = uuid.uuid4()
                await session.execute(
                    text("INSERT INTO users (id, email, password_hash, name, role) VALUES (:id, :email, :pw_hash, :name, :role)"),
                    {
                        "id": user_id,
                        "email": u_data["email"],
                        "pw_hash": get_password_hash("password123"),
                        "name": u_data["name"],
                        "role": u_data["role"]
                    }
                )
                print(f"✅ User {u_data['email']} created.")

            await session.commit()
            
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_users())
