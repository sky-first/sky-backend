import asyncio
import sys
import os

# Add src to path
sys.path.append(os.getcwd())

from src.config.database import AsyncSessionLocal
from src.models.user import User
from sqlalchemy import select, update

async def set_admin(email: str):
    async with AsyncSessionLocal() as session:
        # Find user
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        
        if not user:
            print(f"User with email {email} not found.")
            return

        # Update role
        await session.execute(
            update(User)
            .where(User.email == email)
            .values(role="admin")
        )
        await session.commit()
        print(f"User {email} successfully promoted to admin.")

if __name__ == "__main__":
    email = "gustavo.mendonca@skyfirstlabs.com"
    asyncio.run(set_admin(email))
