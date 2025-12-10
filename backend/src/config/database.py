"""Database configuration and session management."""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from src.config.settings import settings

# Create async engine
# SQLite doesn't support pool_size and max_overflow
engine_kwargs = {
    "echo": settings.DEBUG,
    "future": True,
}

# Only add pool settings for non-SQLite databases
if "sqlite" not in settings.DATABASE_URL.lower():
    engine_kwargs.update({
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "pool_pre_ping": settings.DATABASE_POOL_PRE_PING,
    })
else:
    # SQLite-specific settings
    engine_kwargs.update({
        "connect_args": {"check_same_thread": False},
        "poolclass": None,  # Use NullPool for SQLite
    })

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency to get database session.

    Yields:
        AsyncSession: Database session
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database.
    For Postgres (and other non-SQLite), schema is managed by Alembic migrations,
    so we skip create_all to avoid duplicate object/type errors.
    For SQLite (dev/testing), we still create_all.
    """
    # Invalidate any stale connections in the pool
    await engine.dispose()

    # Only auto-create tables for SQLite; for Postgres use migrations
    if "sqlite" in settings.DATABASE_URL.lower():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()

