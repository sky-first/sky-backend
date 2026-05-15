"""Context Layer health endpoint.

Backs two surfaces with one row per context `kind`:

  * Administration → Context Health card (operational view)
  * Universe Intelligence sidebar — the embedding-space sphere shows
    the live doc-count per canonical family next to each cluster
    (Connections / Knowledge / Relationships / Platform / Outputs)

Returned fields per kind:
  * doc_count   — how many live (non-deleted) docs of that kind exist
  * last_indexed_at — the most recent `indexed_at` timestamp (None if
                      nothing has ever been indexed)
  * stale_count — how many live docs have a NULL `indexed_at` or one
                  older than 24h (the ingest worker should re-embed
                  these; count > 0 means the worker is behind)

Authenticated end-users may read this — the aggregate counts do not
reveal sensitive content (they are tenant-wide totals, not per-row
data). Per-doc ACL scoping is enforced on the retrieval endpoints
(`/context/rows/...`) and on the upcoming `/context/semantic-map`
endpoint (Phase 2 of the Universe Intelligence v2 plan).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
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
    last_indexed_at: Optional[datetime]
    ok: bool

    model_config = ConfigDict(from_attributes=True)


class ContextHealthResponse(BaseModel):
    generated_at: datetime
    kinds: List[KindHealth]
    total_docs: int
    total_stale: int


@router.get(
    "/health",
    response_model=ContextHealthResponse,
    summary="Context Layer ingestion health per kind",
)
async def get_context_health(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ContextHealthResponse:
    # Authenticated end-users may read this — see module docstring.
    # `current_user` is injected only so the auth dependency runs.
    _ = current_user

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
