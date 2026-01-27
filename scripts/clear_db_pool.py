#!/usr/bin/env python3
"""
Script to clear database connection pool
This forces SQLAlchemy to create new connections with the updated schema
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.database import close_db, engine


async def clear_pool():
    """Clear database connection pool."""
    print("Clearing database connection pool...")
    await close_db()
    print("✅ Pool cleared. Please restart your uvicorn server.")
    print("   The new connections will use the updated schema with planet_id.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(clear_pool())
