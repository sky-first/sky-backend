"""Context Layer health endpoint — Phase 5.4.

Backs the Administration → Context Health card with one row per
context `kind`:

  * doc_count   — how many live (non-deleted) docs of that kind exist
  * last_indexed_at — the most recent `indexed_at` timestamp (None if
                      nothing has ever been indexed)
  * stale_count — how many live docs have a NULL `indexed_at` or one
                  older than 24h (the ingest worker should re-embed
                  these; count > 0 means the worker is behind)

Admin-only. Returns zeros for unknown kinds (so the frontend can
render the full 26-kind grid without branching).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.context_document import ContextDocument, ContextDocumentKind
from src.models.user import User

router = APIRouter()


# 24h is the "freshness" budget — anything older is considered stale
# enough that the Context Health panel should flag it for admin review.
STALE_THRESHOLD = timedelta(hours=24)


class KindHealth(BaseModel):
    kind: str
    doc_count: int
    stale_count: int
    last_indexed_at: datetime | None
    ok: bool

    model_config = ConfigDict(from_attributes=True)


class ContextHealthResponse(BaseModel):
    generated_at: datetime
    kinds: List[KindHealth]
    total_docs: int
    total_stale: int


def _require_admin(user: User) -> None:
    """Lock to admins only. The Context Health tab is an Administration
    surface — end users don't need to see ingestion internals.
    """
    role = (getattr(user, "role", None) or "").lower()
    if role not in {"admin", "superadmin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required.",
        )


@router.get(
    "/health",
    response_model=ContextHealthResponse,
    summary="Context Layer ingestion health per kind (admin only)",
)
async def get_context_health(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ContextHealthResponse:
    _require_admin(current_user)

    now = datetime.now(timezone.utc)
    stale_cutoff = now - STALE_THRESHOLD

    # One grouped query pulls the per-kind stats in a single round-trip.
    # (func.count with a filter for stale rows keeps the query narrow.)
    query = (
        select(
            ContextDocument.kind,
            func.count(ContextDocument.id).label("doc_count"),
            func.max(ContextDocument.indexed_at).label("last_indexed_at"),
            func.sum(
                case(
                    (ContextDocument.indexed_at.is_(None), 1),
                    (ContextDocument.indexed_at < stale_cutoff, 1),
                    else_=0,
                )
            ).label("stale_count"),
        )
        .where(ContextDocument.deleted_at.is_(None))
        .group_by(ContextDocument.kind)
    )

    try:
        rows = (await db.execute(query)).all()
    except Exception:
        # Migration hasn't run yet / pgvector not enabled — return
        # an all-empty grid rather than 500ing the admin page.
        rows = []

    by_kind = {
        r.kind: KindHealth(
            kind=r.kind,
            doc_count=int(r.doc_count or 0),
            stale_count=int(r.stale_count or 0),
            last_indexed_at=r.last_indexed_at,
            ok=(r.stale_count or 0) == 0 and (r.doc_count or 0) > 0,
        )
        for r in rows
    }

    # Ensure every canonical kind appears in the response, even when
    # zero docs exist yet — the admin UI renders a 26-cell grid and
    # zero-state cells should show "—" instead of a missing row.
    all_kinds: list[KindHealth] = []
    for kind_enum in ContextDocumentKind:
        k = kind_enum.value
        all_kinds.append(
            by_kind.get(
                k,
                KindHealth(
                    kind=k,
                    doc_count=0,
                    stale_count=0,
                    last_indexed_at=None,
                    ok=False,  # zero docs → not "ok" per the grid
                ),
            )
        )

    total_docs = sum(h.doc_count for h in all_kinds)
    total_stale = sum(h.stale_count for h in all_kinds)

    return ContextHealthResponse(
        generated_at=now,
        kinds=all_kinds,
        total_docs=total_docs,
        total_stale=total_stale,
    )
