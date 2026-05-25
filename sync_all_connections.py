"""
Sync metadata + generate embeddings for all active connections.

Calls backend API (port 8000) + AI service (port 8001) using a locally
generated JWT token (no manual login needed).

Usage:
    python sync_all_connections.py [--dry-run]
"""
import asyncio
import sys
import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Load .env.local first
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env.local", override=True)

import httpx
import jwt  # PyJWT

DRY_RUN = "--dry-run" in sys.argv
BACKEND_URL = "http://localhost:8000"
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8001")
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM = "HS256"

DB_URL = (
    f"postgresql+asyncpg://"
    f"postgres:postgres"
    f"@localhost:5432/ai_saas_db"
)


def make_admin_token(user_id: str, email: str) -> str:
    """Generate a short-lived JWT token for an admin user."""
    payload = {
        "sub": user_id,
        "email": email,
        "role": "owner",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_admin_user() -> dict:
    """Get an owner/admin user ID from the DB."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        row = await session.execute(text(
            "SELECT id::text, email FROM users "
            "WHERE role IN ('owner','admin') AND deleted_at IS NULL "
            "ORDER BY role LIMIT 1"
        ))
        user = row.mappings().first()

    await engine.dispose()
    return dict(user) if user else None


async def get_connections() -> list:
    """Get all connections with their space IDs and owner info from the DB."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        rows = await session.execute(text("""
            SELECT
                dc.id::text       AS connection_id,
                dc.name           AS connection_name,
                dc.status,
                u.id::text        AS owner_id,
                u.email           AS owner_email,
                u.role            AS owner_role,
                array_agg(sc.space_id::text)
                    FILTER (WHERE sc.space_id IS NOT NULL) AS space_ids
            FROM data_connections dc
            LEFT JOIN space_connections sc ON sc.connection_id = dc.id
            LEFT JOIN users u ON u.id = dc.created_by
            WHERE dc.deleted_at IS NULL
            GROUP BY dc.id, dc.name, dc.status, u.id, u.email, u.role
            ORDER BY dc.name
        """))
        connections = [dict(r) for r in rows.mappings().all()]

    await engine.dispose()
    return connections


async def backend_sync(client: httpx.AsyncClient, token: str, connection_id: str) -> bool:
    """Trigger backend schema sync via POST /connections/{id}/sync."""
    try:
        resp = await client.post(
            f"{BACKEND_URL}/api/v1/connections/{connection_id}/sync",
            headers={"Authorization": f"Bearer {token}"},
            timeout=120,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                print("  ✓ Schema synced from source DB")
                return True
            else:
                print(f"  ✗ Sync returned failure: {data.get('message', '?')}")
                return False
        else:
            print(f"  ✗ Sync HTTP {resp.status_code}: {resp.text[:300]}")
            return False
    except Exception as e:
        print(f"  ✗ Sync error: {e}")
        return False


async def ai_full_refresh(client: httpx.AsyncClient, connection_id: str, space_id: str) -> bool:
    """Call AI service full-refresh (metadata ingestion + embeddings)."""
    try:
        resp = await client.post(
            f"{AI_SERVICE_URL}/connections/{connection_id}/full-refresh",
            params={"space_id": space_id},
            timeout=300,
        )
        if resp.status_code == 200:
            data = resp.json()
            meta = data.get("metadata_rows_inserted", "?")
            emb = data.get("embeddings_created", "?")
            print(f"    ✓ {meta} metadata rows, {emb} embeddings")
            return True
        else:
            print(f"    ✗ HTTP {resp.status_code}: {resp.text[:300]}")
            return False
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False


async def print_final_state():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        rows = await session.execute(text("""
            SELECT dc.name,
                   COALESCE(jsonb_array_length(cm.tables::jsonb), 0) AS table_count,
                   (SELECT count(*) FROM table_metadata tm
                    WHERE tm.data_connection_id = dc.id) AS embedding_rows
            FROM data_connections dc
            LEFT JOIN connection_metadata cm ON cm.connection_id = dc.id
            WHERE dc.deleted_at IS NULL
            ORDER BY dc.name
        """))
        result = rows.mappings().all()

    await engine.dispose()

    print("\n=== Final State ===")
    print(f"{'Connection':<35} {'Tables':>8} {'Embeddings':>12}")
    print("-" * 58)
    for r in result:
        ok = r["table_count"] > 0 and r["embedding_rows"] > 0
        mark = "✓" if ok else ("~" if r["table_count"] > 0 else "✗")
        print(f"{mark} {r['name']:<33} {r['table_count']:>8} {r['embedding_rows']:>12}")


async def main():
    if not JWT_SECRET:
        print("ERROR: JWT_SECRET_KEY not found in .env.local")
        sys.exit(1)

    print(f"Backend:    {BACKEND_URL}")
    print(f"AI service: {AI_SERVICE_URL}")
    print(f"Dry run:    {DRY_RUN}\n")

    admin = await get_admin_user()
    if not admin:
        print("ERROR: No owner/admin user found in DB")
        sys.exit(1)

    token = make_admin_token(admin["id"], admin["email"])
    print(f"Auth as: {admin['email']} ({admin['id'][:8]}...)\n")

    connections = await get_connections()
    if not connections:
        print("No connections found.")
        return

    print(f"Found {len(connections)} connection(s):\n")

    # Cache tokens per owner_id to avoid re-generating for every connection
    token_cache: dict[str, str] = {}

    async with httpx.AsyncClient() as client:
        for conn in connections:
            space_ids = conn["space_ids"] or []
            owner_id = conn.get("owner_id") or admin["id"]
            owner_email = conn.get("owner_email") or admin["email"]
            owner_role = conn.get("owner_role") or "owner"

            prefix = "[DRY RUN] " if DRY_RUN else ""
            print(f"{prefix}→ {conn['connection_name']} [{conn['status']}]")
            print(f"  ID:     {conn['connection_id']}")
            print(f"  Owner:  {owner_email}")
            print(f"  Spaces: {space_ids or '(none)'}")

            if DRY_RUN:
                print()
                continue

            # Generate token for this connection's owner
            if owner_id not in token_cache:
                token_cache[owner_id] = make_admin_token(owner_id, owner_email)
            conn_token = token_cache[owner_id]

            # Step 1: Backend metadata sync
            print("  Step 1: Syncing schema from source DB...")
            await backend_sync(client, conn_token, conn["connection_id"])

            # Step 2: AI service embedding per space
            if space_ids:
                print(f"  Step 2: AI full-refresh ({len(space_ids)} space(s))...")
                for space_id in space_ids:
                    print(f"    → Space {space_id[:8]}...")
                    await ai_full_refresh(client, conn["connection_id"], space_id)
            else:
                print("  Step 2: No spaces — skipping AI refresh")

            print()

    if not DRY_RUN:
        await print_final_state()


if __name__ == "__main__":
    asyncio.run(main())
