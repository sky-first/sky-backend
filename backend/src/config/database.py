"""Database configuration and session management."""

import logging
from typing import AsyncGenerator, Dict, Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

from src.config.settings import settings

logger = logging.getLogger(__name__)

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
        "pool_recycle": 3600,  # Fechar conexões após 1 hora de inatividade
        "pool_reset_on_return": "commit",  # Resetar conexões ao retornar ao pool
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
    Uses context manager (async with) to ensure proper connection cleanup.

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
            # Explicitly close session to return connection to pool
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
    
    # Log pool configuration
    if "sqlite" not in settings.DATABASE_URL.lower():
        logger.info(
            f"🗄️ Database pool configured - "
            f"pool_size: {settings.DATABASE_POOL_SIZE}, "
            f"max_overflow: {settings.DATABASE_MAX_OVERFLOW}, "
            f"max_total: {settings.DATABASE_POOL_SIZE + settings.DATABASE_MAX_OVERFLOW}"
        )

    # Only auto-create tables for SQLite; for Postgres use migrations
    if "sqlite" in settings.DATABASE_URL.lower():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()


async def get_connection_pool_stats() -> Dict[str, Any]:
    """
    Get connection pool statistics.
    
    Returns:
        Dict with pool statistics including size, checked out, overflow, etc.
    """
    pool = engine.pool
    stats = {
        "pool_size": pool.size(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "checked_in": pool.checkedin(),
        "total_connections": pool.size() + pool.overflow(),
        "max_overflow": getattr(pool, "_max_overflow", 0),
        "pool_max_size": getattr(pool, "_max_overflow", 0) + pool.size(),
    }
    return stats


async def get_database_connections(db: AsyncSession) -> Dict[str, Any]:
    """
    Get active database connections from PostgreSQL.
    
    Args:
        db: Database session
        
    Returns:
        Dict with connection statistics from PostgreSQL
    """
    if "sqlite" in settings.DATABASE_URL.lower():
        return {"error": "SQLite does not support connection monitoring"}
    
    try:
        # Get total connections
        result = await db.execute(text("""
            SELECT 
                count(*) as total_connections,
                count(*) FILTER (WHERE state = 'active') as active_connections,
                count(*) FILTER (WHERE state = 'idle') as idle_connections,
                count(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction,
                count(*) FILTER (WHERE state = 'idle in transaction (aborted)') as idle_in_transaction_aborted
            FROM pg_stat_activity
            WHERE datname = current_database()
        """))
        total_stats = result.fetchone()
        
        # Get connections by application name
        result = await db.execute(text("""
            SELECT 
                application_name,
                count(*) as connection_count,
                count(*) FILTER (WHERE state = 'active') as active_count
            FROM pg_stat_activity
            WHERE datname = current_database()
            GROUP BY application_name
            ORDER BY connection_count DESC
        """))
        by_application = [
            {
                "application_name": row[0] or "unknown",
                "connection_count": row[1],
                "active_count": row[2]
            }
            for row in result.fetchall()
        ]
        
        # Get max_connections setting
        result = await db.execute(text("SHOW max_connections"))
        max_connections = int(result.scalar() or 100)
        
        return {
            "total_connections": total_stats[0] or 0,
            "active_connections": total_stats[1] or 0,
            "idle_connections": total_stats[2] or 0,
            "idle_in_transaction": total_stats[3] or 0,
            "idle_in_transaction_aborted": total_stats[4] or 0,
            "max_connections": max_connections,
            "connections_by_application": by_application,
            "connection_usage_percent": round((total_stats[0] or 0) / max_connections * 100, 2) if max_connections > 0 else 0,
        }
    except Exception as e:
        logger.error(f"Error getting database connections: {e}")
        return {"error": str(e)}


async def log_connection_stats() -> None:
    """Log current connection pool statistics."""
    try:
        pool_stats = await get_connection_pool_stats()
        logger.info(
            f"📊 Connection Pool Stats - "
            f"Size: {pool_stats['pool_size']}, "
            f"Checked Out: {pool_stats['checked_out']}, "
            f"Overflow: {pool_stats['overflow']}, "
            f"Total: {pool_stats['total_connections']}/{pool_stats['pool_max_size']}"
        )
    except Exception as e:
        logger.error(f"Error logging connection stats: {e}")

