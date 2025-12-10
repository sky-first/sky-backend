#!/usr/bin/env python3
"""Update test user password to a more secure one."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from sqlalchemy import select, update
from src.config.database import AsyncSessionLocal, engine
from src.models.user import User
from src.core.security import get_password_hash


async def update_password():
    """Update test user password."""
    async with AsyncSessionLocal() as session:
        # Find user
        result = await session.execute(
            select(User).where(User.email == "test@example.com")
        )
        user = result.scalar_one_or_none()
        
        if not user:
            print("❌ Test user not found!")
            return
        
        # New secure password: Test@2024!Secure
        new_password = "Test@2024!Secure"
        new_password_hash = get_password_hash(new_password)
        
        # Update password
        await session.execute(
            update(User)
            .where(User.email == "test@example.com")
            .values(password_hash=new_password_hash)
        )
        await session.commit()
        
        print("✅ Password updated successfully!")
        print(f"   Email: test@example.com")
        print(f"   New Password: {new_password}")
        print("\n⚠️  Note: Update this password in LOGIN_CREDENTIALS.md")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(update_password())
