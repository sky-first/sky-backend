"""Multi-tenant isolation integration framework (Projeto A — PR #4).

The Phase 1-2 PRs do not change any business logic, so a classical
integration test against the real ``TenantConnectionManager`` is not
yet meaningful — there is no handler that picks a tenant-scoped
session yet. What this file does provide is the **isolation fixture**
that Phase 3 PRs will reuse: spin up two throwaway in-memory SQLite
engines, attach each to a distinct ``TenantContext``, and verify that
data written through tenant A's session is unreachable from tenant
B's session.

The fixture is intentionally session-scoped per-test so a faulty test
cannot leak rows across cases. ``StaticPool`` keeps the in-memory
database alive for the duration of the test.

The second half of the file is a **static analysis canary** — it
walks ``src/`` and shouts when application code imports
``AsyncSessionLocal`` directly. Once Phase 5 PR #14 enforces
tenant-scoping, the only legal call sites are the manager itself, the
resolver middleware (registry lookup needs the platform pool), and
the lifespan hook. The canary keeps an explicit allow-list.
"""

from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path
from typing import Iterator, Tuple

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.config.database import Base
from src.core.tenant_context import TenantContext
from src.models.tenant import Tenant


# ─── Fixture: two isolated tenants ──────────────────────────────────


def _make_tenant_session_factory(slug: str):
    """Return ``(engine, session_maker)`` bound to a fresh in-memory DB.

    Each tenant gets its own engine; StaticPool ensures the single
    in-memory file is kept alive across sessions.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, maker


@pytest_asyncio.fixture
async def two_tenants() -> Iterator[Tuple[TenantContext, AsyncSession, TenantContext, AsyncSession]]:
    """Yield (ctx_a, session_a, ctx_b, session_b).

    Both sessions point at independent in-memory SQLite databases.
    Schema is provisioned once per fixture instance.
    """
    engine_a, maker_a = _make_tenant_session_factory("alpha")
    engine_b, maker_b = _make_tenant_session_factory("beta")

    # Provision schema independently on each engine.
    for engine in (engine_a, engine_b):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    ctx_a = TenantContext(
        slug="alpha", id=uuid.uuid4(), tier="starter", display_name="Alpha"
    )
    ctx_b = TenantContext(
        slug="beta", id=uuid.uuid4(), tier="starter", display_name="Beta"
    )

    session_a = maker_a()
    session_b = maker_b()
    try:
        yield ctx_a, session_a, ctx_b, session_b
    finally:
        await session_a.close()
        await session_b.close()
        await engine_a.dispose()
        await engine_b.dispose()


def _persist_canary_tenant(session, slug: str):
    """Insert a row in the ``tenant_registry`` table. Used as the
    canary — if isolation is broken, the other session sees it."""
    tenant = Tenant(
        id=uuid.uuid4(),
        slug=slug,
        display_name=f"Canary {slug}",
        tier="starter",
        db_host="x",
        db_port=5432,
        db_name=slug,
        db_credentials_secret_arn="arn:x",
        redis_host="x",
        redis_credentials_secret_arn="arn:x",
        sso_provider="google",
    )
    session.add(tenant)
    return tenant


# ─── Isolation canaries ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_in_tenant_a_is_invisible_to_tenant_b(two_tenants):
    ctx_a, session_a, ctx_b, session_b = two_tenants

    _persist_canary_tenant(session_a, "alpha-canary")
    await session_a.commit()

    # Tenant B reads from a completely different engine.
    result = await session_b.execute(select(Tenant))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_writes_in_both_tenants_independently(two_tenants):
    ctx_a, session_a, ctx_b, session_b = two_tenants

    _persist_canary_tenant(session_a, "alpha-row")
    _persist_canary_tenant(session_b, "beta-row")
    await session_a.commit()
    await session_b.commit()

    a_rows = (await session_a.execute(select(Tenant))).scalars().all()
    b_rows = (await session_b.execute(select(Tenant))).scalars().all()

    assert {r.slug for r in a_rows} == {"alpha-row"}
    assert {r.slug for r in b_rows} == {"beta-row"}


@pytest.mark.asyncio
async def test_rollback_in_tenant_a_does_not_affect_tenant_b(two_tenants):
    ctx_a, session_a, ctx_b, session_b = two_tenants

    _persist_canary_tenant(session_a, "alpha-rollback")
    await session_a.rollback()

    _persist_canary_tenant(session_b, "beta-commit")
    await session_b.commit()

    a_rows = (await session_a.execute(select(Tenant))).scalars().all()
    b_rows = (await session_b.execute(select(Tenant))).scalars().all()

    assert a_rows == []
    assert {r.slug for r in b_rows} == {"beta-commit"}


# ─── Static analysis: direct AsyncSessionLocal imports ──────────────
# When Phase 5 lands, anything outside the allow-list that imports
# AsyncSessionLocal is suspicious — it is a code path that bypasses the
# tenant resolver entirely.

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _PROJECT_ROOT / "src"

# Modules that legitimately consume the global pool TODAY. The list is
# the truth of where direct AsyncSessionLocal usage lives at the start
# of Projeto A. Phase 3 PRs (#6-8) migrate the api.v1 callers; Phase 4
# migrates the workers. Each migration PR removes the corresponding
# entry from this set — the test fails loudly the day someone adds a
# NEW direct caller without justification.
_ALLOWED_REFS = {
    str((_SRC_ROOT / "config" / "database.py").resolve()),
    str((_SRC_ROOT / "config" / "tenant_connection_manager.py").resolve()),
    str((_SRC_ROOT / "api" / "middleware" / "tenant_resolver.py").resolve()),
    # Legacy direct callers — slated for migration in later Projeto A PRs.
    str((_SRC_ROOT / "api" / "deps.py").resolve()),
    str((_SRC_ROOT / "api" / "v1" / "agents.py").resolve()),
    str((_SRC_ROOT / "api" / "v1" / "presence.py").resolve()),
    str((_SRC_ROOT / "services" / "auth_service.py").resolve()),
    str((_SRC_ROOT / "workers" / "agent_revocation_worker.py").resolve()),
    str((_SRC_ROOT / "workers" / "agent_worker.py").resolve()),
    str((_SRC_ROOT / "workers" / "ai_worker.py").resolve()),
    str((_SRC_ROOT / "workers" / "cache_warming_worker.py").resolve()),
    str((_SRC_ROOT / "workers" / "insight_agent_worker.py").resolve()),
    str((_SRC_ROOT / "workers" / "knowledge_worker.py").resolve()),
    str((_SRC_ROOT / "workers" / "sync_worker.py").resolve()),
    # Projeto B Console — WebSocket log streamer cannot use the DI
    # dependency (FastAPI WS handlers don't go through the same DI),
    # one-shot lookup on the platform pool for tenant existence check.
    str((_SRC_ROOT / "api" / "v1" / "console.py").resolve()),
    # Pricing Fase 1 — platform-wide aggregator: rolls query counters
    # for every tenant and recomputes storage totals once per day. Has
    # to iterate across tenants, so it operates on the platform pool
    # rather than entering a per-tenant context for each row. Fase 3
    # swaps this for per-tenant accounting when source tables grow
    # ``tenant_id`` columns.
    str((_SRC_ROOT / "workers" / "pricing_worker.py").resolve()),
}

_ASYNC_LOCAL_NAME = "AsyncSessionLocal"


def _python_files_under(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "tests" not in p.parts]


def _imports_async_session_local(path: Path) -> bool:
    """Return True if ``path`` mentions AsyncSessionLocal in any import."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False

    if _ASYNC_LOCAL_NAME not in source:
        return False

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == _ASYNC_LOCAL_NAME:
                    return True
    return False


def test_async_session_local_is_only_imported_by_the_allow_list():
    """Catch new code paths that bypass ``TenantConnectionManager``.

    This test is informational during Phase 1-4 (it lets the existing
    direct-pool code stay) and becomes enforcing in Phase 5 PR #14
    when the allow-list is locked down. Today the assertion just
    enumerates what is currently importing the symbol so we keep an
    eye on it.
    """
    callers = []
    for path in _python_files_under(_SRC_ROOT):
        if _imports_async_session_local(path):
            callers.append(str(path.resolve()))

    unexpected = set(callers) - _ALLOWED_REFS
    assert unexpected == set(), (
        "New direct AsyncSessionLocal importers detected — they must "
        "either use TenantConnectionManager.session_for() or be added "
        "to the explicit _ALLOWED_REFS allow-list with reasoning. "
        f"Unexpected: {sorted(unexpected)}"
    )


# ─── Static analysis: raw `select()` literacy ───────────────────────
# This is a soft canary — once Phase 3 migrations land we expect
# repositories to use the tenant session passed in, not to re-open one.
# Tracked here as a count, not a hard assertion, so the number can
# only go DOWN as the refactor progresses.

_RAW_SELECT_PATTERN = re.compile(r"\bAsyncSessionLocal\s*\(\s*\)")


def test_raw_async_session_local_instantiation_baseline():
    """Track usage of bare ``AsyncSessionLocal()`` in src/.

    Failing this test means somebody added a NEW direct call. Reducing
    the baseline is fine — bump the number down when refactoring.
    """
    count = 0
    for path in _python_files_under(_SRC_ROOT):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        count += len(_RAW_SELECT_PATTERN.findall(source))

    # Baseline as of Projeto A PR #4 — measured by inspecting the
    # checked-in code. Phase 3-4 PRs reduce this; the test fails
    # loudly if a new direct call lands. Bumping the number UP
    # requires touching this baseline deliberately.
    BASELINE = 21  # bumped 2026-05-30 — pricing_worker.py needs platform-wide pool
    assert count <= BASELINE, (
        f"Raw AsyncSessionLocal() count grew from {BASELINE} to {count}. "
        f"New callers should use TenantConnectionManager.session_for()."
    )
