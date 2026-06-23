import asyncio
import sys
import os

# Add src to path
sys.path.append(os.getcwd())

from src.config.database import AsyncSessionLocal
from src.models.user import User
from sqlalchemy import select


async def list_users():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        print(f"Found {len(users)} users:")
        for u in users:
            print(f"ID: {u.id} | Email: {u.email} | Role: {u.role}")


if __name__ == "__main__":
    asyncio.run(list_users())
