#!/usr/bin/env python3
"""Seed role_permissions table with default permissions.

This script populates the role_permissions table with the default permissions
defined in src/services/rbac_service.py. It should be run after migrations
to ensure the system has the required permission data.

Usage:
    python scripts/seed_role_permissions.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.config.settings import get_settings
from src.models.permission import RolePermission

# Default permissions are now sourced directly from rbac_service.py so this
# script and the runtime stay in sync. Previously the dictionary was inlined
# here and drifted out of date (still referenced legacy "createPlanets" keys
# while the runtime moved to "pages.create"/"agents.run"/etc.).
from src.services.rbac_service import DEFAULT_ROLE_PERMISSIONS  # noqa: E402


async def seed_role_permissions():
    """Seed the role_permissions table with default permissions."""
    settings = get_settings()

    # Create async engine
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )

    # Create async session
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        try:
            print("🔍 Checking existing role permissions...")

            # Check existing permissions
            result = await session.execute(select(RolePermission))
            existing_perms = result.scalars().all()
            existing_roles = {perm.role for perm in existing_perms}

            print(f"   Found {len(existing_roles)} existing roles: {existing_roles}")

            # Insert or update each role
            inserted = 0
            updated = 0

            for role, permissions in DEFAULT_ROLE_PERMISSIONS.items():
                if role in existing_roles:
                    # Update existing
                    result = await session.execute(
                        select(RolePermission).where(RolePermission.role == role)
                    )
                    role_perm = result.scalar_one()
                    role_perm.permissions = permissions
                    updated += 1
                    print(f"   ✏️  Updated role: {role}")
                else:
                    # Insert new
                    role_perm = RolePermission(role=role, permissions=permissions)
                    session.add(role_perm)
                    inserted += 1
                    print(f"   ✅ Inserted role: {role}")

            # Commit changes
            await session.commit()

            print("\n✨ Seed completed successfully!")
            print(f"   📊 Inserted: {inserted} roles")
            print(f"   📝 Updated: {updated} roles")
            print(f"   🎯 Total roles: {len(DEFAULT_ROLE_PERMISSIONS)}")

        except Exception as e:
            await session.rollback()
            print(f"\n❌ Error seeding role permissions: {e}")
            raise
        finally:
            await engine.dispose()


if __name__ == "__main__":
    print("=" * 60)
    print("🌱 Seeding role_permissions table")
    print("=" * 60)
    asyncio.run(seed_role_permissions())
