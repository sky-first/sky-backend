"""Tests for Context Health endpoint — Phase 5.4."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.context_document import ContextDocument


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _seed_doc(
    db: AsyncSession,
    *,
    kind: str,
    indexed_at: datetime | None = None,
    deleted_at: datetime | None = None,
) -> ContextDocument:
    doc = ContextDocument(
        kind=kind,
        source_table=f"{kind}s",
        source_id=uuid.uuid4(),
        title=f"{kind} doc",
        body="body",
        meta={},
        visibility="space",
        pii_flags=[],
        language="pt",
        indexed_at=indexed_at,
        deleted_at=deleted_at,
    )
    db.add(doc)
    await db.flush()
    return doc


# ─── H1 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_non_admin_can_read_aggregate_counts(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    # The Universe Intelligence sidebar shows the live per-family
    # embedding counts to every end-user — the previous admin-only
    # gate was removed when this surface became product, not admin
    # tooling. The endpoint must still require authentication; only
    # the role check is gone.
    test_user_with_tokens["user"].role = "user"
    await db_session.commit()

    resp = await async_client.get(
        "/api/v1/context/health",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected(async_client: AsyncClient):
    resp = await async_client.get("/api/v1/context/health")
    # Auth dependency rejects missing/invalid bearer with 401.
    assert resp.status_code in {
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,  # Some auth middlewares prefer 403 for missing token.
    }


# ─── H2 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_admin_sees_full_26_kind_grid(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    # Promote to admin + don't seed any docs — endpoint must still
    # return a row per kind (zero state).
    test_user_with_tokens["user"].role = "admin"
    await db_session.commit()

    resp = await async_client.get(
        "/api/v1/context/health",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    # 26 canonical kinds — if we add one the test fails and forces the
    # author to think about what they changed.
    assert len(data["kinds"]) == 26
    assert data["total_docs"] == 0
    assert data["total_stale"] == 0
    # Every row is zero-state, not-ok (zero docs is not a healthy state).
    assert all(k["doc_count"] == 0 for k in data["kinds"])
    assert all(not k["ok"] for k in data["kinds"])


# ─── H3 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_counts_live_docs_and_ignores_soft_deleted(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    test_user_with_tokens["user"].role = "admin"
    now = datetime.now(timezone.utc)
    # 2 live + 1 soft-deleted — expect doc_count = 2 for 'goal'.
    await _seed_doc(db_session, kind="goal", indexed_at=now)
    await _seed_doc(db_session, kind="goal", indexed_at=now)
    await _seed_doc(db_session, kind="goal", indexed_at=now, deleted_at=now)
    await db_session.commit()

    resp = await async_client.get(
        "/api/v1/context/health",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    goal = next(k for k in resp.json()["kinds"] if k["kind"] == "goal")
    assert goal["doc_count"] == 2
    assert goal["stale_count"] == 0
    assert goal["ok"] is True


# ─── H4 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_stale_count_flags_rows_older_than_24h_and_unindexed(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    test_user_with_tokens["user"].role = "admin"
    now = datetime.now(timezone.utc)

    # Fresh (within 24h)
    await _seed_doc(db_session, kind="okr", indexed_at=now - timedelta(hours=1))
    # Stale (older than 24h)
    await _seed_doc(db_session, kind="okr", indexed_at=now - timedelta(hours=30))
    # Never indexed — should count as stale too.
    await _seed_doc(db_session, kind="okr", indexed_at=None)
    await db_session.commit()

    resp = await async_client.get(
        "/api/v1/context/health",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    okr = next(k for k in resp.json()["kinds"] if k["kind"] == "okr")
    assert okr["doc_count"] == 3
    assert okr["stale_count"] == 2
    # ok = all docs fresh; here 2/3 are stale → not ok.
    assert okr["ok"] is False
