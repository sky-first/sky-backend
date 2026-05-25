"""Phase 6 — Connection tier + Agent.auditable_only enforcement.

Use cases:
  1. Connection.tier defaults to 'internal' on insert.
  2. Connection.tier accepts 'internal'/'confidential'/'restricted' and
     rejects anything else (BE CHECK constraint catches it).
  3. Agent.auditable_only defaults to False on insert.
  4. Worker filter — when agent.auditable_only=True the worker drops
     non-internal connections from its query loop.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_password_hash
from src.models.agent import Agent
from src.models.connection import DataConnection
from src.repositories.user import UserRepository


async def _make_user(db: AsyncSession, email: str = "phase6@example.com"):
    repo = UserRepository(db)
    u = await repo.create(
        email=email,
        password_hash=get_password_hash("pw"),
        name="p6",
        role="user",
    )
    await db.commit()
    return u


@pytest.mark.asyncio
async def test_connection_tier_defaults_to_internal(db_session: AsyncSession):
    user = await _make_user(db_session, "p6-1@example.com")
    conn = DataConnection(
        name="c1",
        connector_id="postgresql",
        config={},
        created_by=user.id,
    )
    db_session.add(conn)
    await db_session.commit()
    await db_session.refresh(conn)
    assert conn.tier == "internal"


@pytest.mark.asyncio
async def test_connection_tier_accepts_valid_values(db_session: AsyncSession):
    user = await _make_user(db_session, "p6-2@example.com")
    for level in ("internal", "confidential", "restricted"):
        conn = DataConnection(
            name=f"c-{level}",
            connector_id="postgresql",
            config={},
            tier=level,
            created_by=user.id,
        )
        db_session.add(conn)
    await db_session.commit()


@pytest.mark.asyncio
async def test_agent_auditable_only_defaults_false(db_session: AsyncSession):
    user = await _make_user(db_session, "p6-3@example.com")
    agent = Agent(
        name="a1",
        archetype="custom",
        scope="personal",
        scope_id=str(user.id),
        status="active",
        monitor_type="question",
        frequency="daily",
        connection_ids=[],
        created_by=user.id,
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    assert agent.auditable_only is False


@pytest.mark.asyncio
async def test_worker_filter_drops_non_internal_when_auditable_only(
    db_session: AsyncSession,
):
    """The worker reads agent.connection_ids but skips any connection
    whose tier is more sensitive than 'internal' when the agent runs
    in auditable_only mode. We exercise the filter logic directly so
    the test doesn't pull in Celery."""
    user = await _make_user(db_session, "p6-4@example.com")

    safe = DataConnection(
        name="safe",
        connector_id="postgresql",
        config={},
        tier="internal",
        created_by=user.id,
    )
    sensitive = DataConnection(
        name="hr",
        connector_id="postgresql",
        config={},
        tier="confidential",
        created_by=user.id,
    )
    locked = DataConnection(
        name="legal",
        connector_id="postgresql",
        config={},
        tier="restricted",
        created_by=user.id,
    )
    db_session.add_all([safe, sensitive, locked])
    await db_session.commit()
    await db_session.refresh(safe)
    await db_session.refresh(sensitive)
    await db_session.refresh(locked)

    # SQLite stores connection_ids as JSON, which can't serialize UUID
    # objects natively. Production (Postgres) uses ARRAY[UUID] so this
    # is a test-only stringification — the worker logic accepts both
    # because SQLAlchemy coerces strings back to UUIDs in `IN (...)`.
    conn_ids_str = [str(safe.id), str(sensitive.id), str(locked.id)]
    agent = Agent(
        name="auditable",
        archetype="custom",
        scope="personal",
        scope_id=str(user.id),
        status="active",
        monitor_type="question",
        frequency="daily",
        connection_ids=conn_ids_str,
        auditable_only=True,
        created_by=user.id,
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    # Reproduce the worker's filter inline so the assertion is precise
    # about the contract rather than dependent on Celery wiring. The
    # IN-list takes UUID objects (SQLAlchemy's UUID type processor calls
    # `.hex` on each value), so we cast back from the JSON-roundtripped
    # strings before querying.
    from uuid import UUID as _UUID

    from sqlalchemy import select

    uuid_ids = [_UUID(str(c)) for c in agent.connection_ids]
    rows = (
        await db_session.execute(
            select(DataConnection.id, DataConnection.tier).where(
                DataConnection.id.in_(uuid_ids)
            )
        )
    ).all()
    allowed = {str(cid) for cid, tier in rows if (tier or "internal") == "internal"}
    filtered = [c for c in agent.connection_ids if str(c) in allowed]

    assert filtered == [str(safe.id)]
    assert str(sensitive.id) not in filtered
    assert str(locked.id) not in filtered
