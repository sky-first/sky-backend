"""agent_worker tier-router — unit tests for the L1 delta-check helper.

Coverage matrix:
  • since=None → True (first run never short-circuits)
  • connection_ids=[] → True (preserves legacy "no connections" path)
  • Connection.updated_at > since → True
  • Connection.last_metadata_update > since → True
  • All timestamps <= since → False (the actual money-saving case)
  • Mix of stale + fresh → True (any one connection moved → escalate)

Note on timezones: the test DB is SQLite, which stores datetimes as
naive ISO8601 strings even when the column type is TIMESTAMPTZ. If we
pass aware UTC datetimes here we get a mixed naive/aware comparison
in `_connections_changed_since` and pytest fails. Using utcnow()
(naive) keeps both sides comparable inside SQLite while preserving
the same temporal semantics — production runs on PostgreSQL where
both ends are aware and the helper handles that branch fine.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_password_hash
from src.models.connection import DataConnection
from src.repositories.user import UserRepository
from src.workers.agent_worker import _connections_changed_since


async def _user(db: AsyncSession):
    return await UserRepository(db).create(
        email=f"{uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name="Tier Router Test",
        role="member",
    )


async def _connection(
    db: AsyncSession,
    *,
    owner,
    updated_at: datetime | None = None,
    last_metadata_update: datetime | None = None,
):
    conn = DataConnection(
        id=uuid4(),
        name=f"conn-{uuid4().hex[:6]}",
        connector_id="postgresql",
        config={"host": "localhost"},
        created_by=owner.id,
    )
    if updated_at is not None:
        conn.updated_at = updated_at
    if last_metadata_update is not None:
        conn.last_metadata_update = last_metadata_update
    db.add(conn)
    await db.flush()
    return conn


@pytest.mark.asyncio
async def test_no_prior_run_always_runs(db_session: AsyncSession):
    """First-ever run has no `since` to compare against; must escalate."""
    user = await _user(db_session)
    conn = await _connection(db_session, owner=user)
    assert await _connections_changed_since(db_session, [conn.id], None) is True


@pytest.mark.asyncio
async def test_empty_connection_list_runs(db_session: AsyncSession):
    """Agents without connections preserve the legacy run-anyway path."""
    since = datetime.utcnow() - timedelta(hours=1)
    assert await _connections_changed_since(db_session, [], since) is True


@pytest.mark.asyncio
async def test_connection_updated_after_since_runs(db_session: AsyncSession):
    user = await _user(db_session)
    since = datetime.utcnow() - timedelta(hours=2)
    conn = await _connection(
        db_session,
        owner=user,
        updated_at=datetime.utcnow(),
    )
    assert await _connections_changed_since(db_session, [conn.id], since) is True


@pytest.mark.asyncio
async def test_metadata_refresh_after_since_runs(db_session: AsyncSession):
    """A metadata re-sync must wake the agent up, not just row edits."""
    user = await _user(db_session)
    since = datetime.utcnow() - timedelta(hours=2)
    long_ago = datetime.utcnow() - timedelta(days=10)
    conn = await _connection(
        db_session,
        owner=user,
        updated_at=long_ago,
        last_metadata_update=datetime.utcnow(),
    )
    assert await _connections_changed_since(db_session, [conn.id], since) is True


@pytest.mark.asyncio
async def test_all_stale_skips(db_session: AsyncSession):
    """The actual budget-saving case: nothing moved since last run."""
    user = await _user(db_session)
    long_ago = datetime.utcnow() - timedelta(days=10)
    since = datetime.utcnow() - timedelta(hours=1)
    conn = await _connection(
        db_session,
        owner=user,
        updated_at=long_ago,
        last_metadata_update=long_ago,
    )
    assert await _connections_changed_since(db_session, [conn.id], since) is False


@pytest.mark.asyncio
async def test_any_fresh_connection_triggers_run(db_session: AsyncSession):
    """If at least one connection moved, the whole agent escalates."""
    user = await _user(db_session)
    since = datetime.utcnow() - timedelta(hours=1)
    long_ago = datetime.utcnow() - timedelta(days=10)

    stale = await _connection(
        db_session, owner=user, updated_at=long_ago, last_metadata_update=long_ago
    )
    fresh = await _connection(
        db_session, owner=user, updated_at=datetime.utcnow()
    )
    result = await _connections_changed_since(
        db_session, [stale.id, fresh.id], since
    )
    assert result is True
