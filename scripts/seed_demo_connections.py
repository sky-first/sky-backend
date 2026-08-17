#!/usr/bin/env python3
"""Seed the 5 fixed demo Azure-Postgres connections under a single demo Space.

Run after `seed-rbac-demo-users.py`. Creates:

  * the real owner user (lucas.ventura@skyfirstlabs.com, platform=owner) so
    the SSO login lands on an account that already owns the demo data;
  * a Space "Demo — Sky" owned by that user;
  * 5 PostgreSQL DataConnection rows pointing at the host configured in
    DEMO_PG_HOST, one per business schema
    (crm / marketing / finance / web_analytics / product_usage);
  * one space_connection row per connection so the Space sees them.

Idempotent — re-running upserts.

Contra a base de um CLIENTE (Model B)
------------------------------------
Serve para dar a um cliente os dados de demonstração sem lhe copiar nada:
as 5 ligações apontam para a mesma base de demonstração, e o que fica na
base do cliente são só as linhas que dizem "esta ligação existe".

    DATABASE_URL=<base do cliente>       # tenant_<slug>
    DEMO_OWNER_EMAIL=<email que existe lá>
    DEMO_SPACE_NAME="Dados de demonstração"

Sem `DEMO_OWNER_EMAIL` o script procura `rbac.owner@example.com`, que só
existe na base da demo, e morre com "user not found".
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

# Make the project root importable so we can use src.* helpers.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# .env.local must be sourced before importing src.config — DATABASE_URL,
# ENCRYPTION_KEY etc. come from there. The shell wrapper handles that;
# this script asserts the env is in place.
if not os.environ.get("DATABASE_URL"):
    print("Set DATABASE_URL first (source .env.local).", file=sys.stderr)
    sys.exit(1)

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from src.config.database import AsyncSessionLocal  # noqa: E402
from src.models.user import User  # noqa: E402
from src.models.space import Space, SpaceConnection, SpaceMember  # noqa: E402
from src.models.connection import DataConnection  # noqa: E402
from src.utils.encryption import encrypt_dict  # noqa: E402

# O dono das ligações e do espaço.
#
# Era fixo em `rbac.owner@example.com`, que só existe na base da demo. Passou
# a ser parametrizável quando a equipa SkyFirst virou cliente (Model B): o
# `tenant_skyfirstlabs` tem uma base própria, e lá o utilizador que existe é
# o da pessoa, não o da demo. Sem isto, o script morria com "user not found"
# em qualquer base que não fosse a da demo — que passou a ser toda a gente.
#
# O valor por omissão é o de antes, para os semeadores existentes não
# mudarem de comportamento.
OWNER_EMAIL = os.environ.get("DEMO_OWNER_EMAIL", "rbac.owner@example.com")
OWNER_NAME = "RBAC Owner"
# Idem: um cliente que peça os dados de demonstração não quer um espaço
# chamado "Demo — Sky" no meio do trabalho dele.
SPACE_NAME = os.environ.get("DEMO_SPACE_NAME", "Demo — Sky")

DEMO_HOST = os.environ.get("DEMO_PG_HOST", "")
DEMO_PORT = int(os.environ.get("DEMO_PG_PORT", "5432"))
DEMO_DB = os.environ.get("DEMO_PG_DB", "postgres")
DEMO_USER = os.environ.get("DEMO_PG_USER", "")
DEMO_PASS = os.environ.get("DEMO_PG_PASSWORD", "")
# Local Docker uses "disable"; Azure requires "require"
DEMO_SSL_MODE = os.environ.get("DEMO_PG_SSL_MODE", "require")

if not (DEMO_HOST and DEMO_USER and DEMO_PASS):
    print(
        "Missing DEMO_PG_HOST / DEMO_PG_USER / DEMO_PG_PASSWORD env vars.\n"
        "Add them to .env.local — they configure the 5 fixed demo Postgres\n"
        "connections (Sales / Marketing / Finance / Web Analytics / Product Usage).",
        file=sys.stderr,
    )
    sys.exit(1)

DEMO_CONNECTIONS = [
    {"name": "Demo — Sales", "schema": "crm"},
    {"name": "Demo — Marketing", "schema": "marketing"},
    {"name": "Demo — Finance", "schema": "finance"},
    {"name": "Demo — Web Analytics", "schema": "web_analytics"},
    {"name": "Demo — Product Usage", "schema": "product_usage"},
]


async def upsert_owner(db: AsyncSession) -> User:
    # The owner user must already exist — created by `seed-rbac-demo-users.py`.
    # We deliberately do NOT auto-create users here: this script is
    # exclusively about wiring the demo data, not about provisioning
    # identities.
    res = await db.execute(select(User).where(User.email == OWNER_EMAIL))
    user = res.scalar_one_or_none()
    if not user:
        print(
            f"  ✗ user {OWNER_EMAIL} not found in this database.\n"
            "    Na base da demo: correr scripts/seed-rbac-demo-users.py primeiro.\n"
            "    Na base de um cliente: passar DEMO_OWNER_EMAIL com um email que\n"
            "    exista lá — o admin semeado no provisionamento serve.",
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"  ↻ user {OWNER_EMAIL} (id={user.id}) found, role={user.role}")
    return user


async def upsert_space(db: AsyncSession, owner: User) -> Space:
    res = await db.execute(
        select(Space).where(Space.name == SPACE_NAME, Space.created_by == owner.id)
    )
    space = res.scalar_one_or_none()
    if space:
        print(f"  ↻ space {SPACE_NAME!r} (id={space.id}) — already exists")
        return space
    space = Space(
        id=uuid.uuid4(),
        name=SPACE_NAME,
        created_by=owner.id,
        description="Fixed demo workspace seeded with the 5 reference Postgres schemas.",
    )
    db.add(space)
    await db.flush()
    db.add(SpaceMember(space_id=space.id, user_id=owner.id, role="owner"))
    await db.flush()
    print(f"  ✓ space {SPACE_NAME!r} created (id={space.id})")
    return space


async def upsert_connection(
    db: AsyncSession,
    owner: User,
    space: Space,
    name: str,
    schema_name: str,
) -> DataConnection:
    res = await db.execute(
        select(DataConnection).where(
            DataConnection.name == name,
            DataConnection.created_by == owner.id,
            DataConnection.deleted_at.is_(None),
        )
    )
    conn = res.scalar_one_or_none()

    config_plain = {
        "host": DEMO_HOST,
        "port": DEMO_PORT,
        "database": DEMO_DB,
        "username": DEMO_USER,
        "password": DEMO_PASS,
        "schema": schema_name,
        "ssl_mode": DEMO_SSL_MODE,
    }
    config_stored = encrypt_dict(config_plain)

    if conn:
        conn.config = config_stored
        conn.status = "active"
        await db.flush()
        print(f"  ↻ connection {name!r} (id={conn.id}) — refreshed config")
    else:
        conn = DataConnection(
            id=uuid.uuid4(),
            name=name,
            connector_id="postgresql",
            description=f"Demo PostgreSQL — schema '{schema_name}'.",
            status="active",
            config=config_stored,
            created_by=owner.id,
            tier="internal",
        )
        db.add(conn)
        await db.flush()
        print(f"  ✓ connection {name!r} created (id={conn.id}, schema={schema_name})")

    res = await db.execute(
        select(SpaceConnection).where(
            SpaceConnection.space_id == space.id,
            SpaceConnection.connection_id == conn.id,
        )
    )
    if not res.scalar_one_or_none():
        db.add(SpaceConnection(space_id=space.id, connection_id=conn.id))
        await db.flush()
        print(f"      → linked to space {space.name!r}")
    return conn


async def main() -> None:
    print("=" * 60)
    print("Seeding fixed demo connections")
    print("=" * 60)
    async with AsyncSessionLocal() as db:
        owner = await upsert_owner(db)
        space = await upsert_space(db, owner)
        created_ids = []
        for spec in DEMO_CONNECTIONS:
            conn = await upsert_connection(db, owner, space, spec["name"], spec["schema"])
            if conn is not None:
                created_ids.append(conn.id)
        await db.commit()

    # Run metadata discovery on each connection — without this the AI
    # service rejects every chat / agent run with
    # "404 No metadata found for this connection". Done in a fresh
    # session so the introspection runs against fully-committed rows.
    if created_ids:
        from src.services.connection_service import ConnectionService

        async with AsyncSessionLocal() as db2:
            svc = ConnectionService(db2)
            owner2 = (await db2.execute(select(User).where(User.email == OWNER_EMAIL))).scalar_one()
            for cid in created_ids:
                try:
                    await svc.sync_connection(cid, owner2)
                    print(f"  metadata synced: {cid}")
                except Exception as exc:
                    print(f"  WARN: metadata sync failed for {cid}: {exc}")

    print("\nDone. Demo Space + 5 connections wired (metadata discovery included).")


if __name__ == "__main__":
    asyncio.run(main())
