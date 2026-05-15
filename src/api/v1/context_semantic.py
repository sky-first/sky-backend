"""Universe Intelligence v2 — semantic-map + search proxy.

Thin proxy that fronts the AI service's ``/semantic/map`` and
``/semantic/search`` endpoints. Its job is exclusively ACL resolution:

  * Reads the caller's actual scope from Postgres (Personal = own
    `user_id` + every Space they belong to; Space:<id> = membership-
    checked space). Never trusts caller-provided scope IDs blindly.
  * Forwards the resolved scope to the AI service.
  * Returns the response unchanged.

This separation keeps the AI service stateless on auth — it just
projects whatever embeddings the BE says are visible. The BE keeps
ACL logic centralised here, next to the rest of the v1 surface.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.config.settings import settings
from src.models.space import SpaceMember
from src.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Schemas mirrored from AI service (kept loose to avoid drift) ──


class SemanticMapResponse(BaseModel):
    points: List[Dict[str, Any]]
    # ``edges`` carries enterprise_relationship links between SemanticPoints
    # — relationships are not points themselves any more (see AI service
    # `_build_relationship_edges`). Old AI versions without the field
    # default to empty.
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    model: str
    dim: int
    count: int
    n_clusters: int
    umap_params: Dict[str, Any]


class SemanticSearchHit(BaseModel):
    id: str
    score: float
    kind: str
    label: str
    snippet: Optional[str] = None


class SemanticSearchResponse(BaseModel):
    query: str
    hits: List[SemanticSearchHit]
    model: str
    dim: int


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    scope: str = Field(
        "personal",
        description=(
            "Either 'personal' (caller's own embeddings + their Spaces) "
            "or 'space:<uuid>' to scope to a specific Space."
        ),
    )
    top_k: int = Field(10, ge=1, le=100)


# ─── ACL resolution ───────────────────────────────────────────────────


async def _expand_with_shared_connection_spaces(
    db: AsyncSession,
    member_space_ids: List[UUID],
) -> List[UUID]:
    """Demo accounts (and any tenant that shares a connection from a
    "library" workspace) link to data through ``space_connections``.
    The embeddings for those connections' columns live in the source
    workspace's ``space_id`` — not in the consumer's. If we only scope
    by the caller's ``space_members`` rows, the universe comes back
    empty for every demo user even though they see 5 connections in
    the Sources panel.

    This helper takes the caller's direct memberships and adds the
    source ``data_connections.space_id`` for every connection shared
    *into* any of those spaces, returning the unique union. The result
    is the set of space_ids whose embeddings the caller is legitimately
    allowed to project on the universe canvas.
    """
    if not member_space_ids:
        return []
    # Raw SQL because ``DataConnection.space_id`` is in the DB schema but
    # not declared on the SQLAlchemy model (column added via migration,
    # never back-mapped). Reading via ``text`` is safe — the only bind
    # is a list of UUIDs the caller is already entitled to read.
    rows = await db.execute(
        sql_text(
            """
            SELECT DISTINCT dc.space_id
            FROM data_connections dc
            JOIN space_connections sc ON sc.connection_id = dc.id
            WHERE sc.space_id = ANY(:member_ids)
              AND dc.space_id IS NOT NULL
            """
        ),
        {"member_ids": [str(s) for s in member_space_ids]},
    )
    shared = {r[0] for r in rows.all()}
    # Union — keep direct memberships and add the shared sources.
    out = set(member_space_ids) | shared
    return list(out)


async def _resolve_scope(
    scope: str,
    user: User,
    db: AsyncSession,
) -> Dict[str, Any]:
    """Resolve the caller-provided ``scope`` string into a dict of
    explicit IDs that the AI service can trust:

      ``{user_id, space_ids[], crew_ids[], include_personal}``

    Rules:
      * ``"personal"`` → user_id = caller; space_ids = every Space the
        caller belongs to **plus** every space that owns a connection
        shared into one of those memberships (so demo + shared-data
        scenarios surface their embeddings). include_personal = True.
      * ``"space:<uuid>"`` → membership check; space_ids = [uuid] +
        any source spaces of connections shared into it.
      * Anything else → 400.
    """
    if scope == "personal":
        space_rows = await db.execute(
            select(SpaceMember.space_id).where(SpaceMember.user_id == user.id)
        )
        member_space_ids: List[UUID] = [r[0] for r in space_rows.all()]
        all_space_ids = await _expand_with_shared_connection_spaces(
            db, member_space_ids
        )
        return {
            "user_id": str(user.id),
            "space_ids": [str(s) for s in all_space_ids],
            "crew_ids": [],
            "include_personal": True,
        }
    if scope.startswith("space:"):
        raw = scope.split(":", 1)[1]
        try:
            space_uuid = UUID(raw)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid space UUID in scope: {raw}",
            ) from e
        member = await db.execute(
            select(SpaceMember.id).where(
                SpaceMember.user_id == user.id,
                SpaceMember.space_id == space_uuid,
            )
        )
        if member.first() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"You are not a member of Space {space_uuid}.",
            )
        all_space_ids = await _expand_with_shared_connection_spaces(
            db, [space_uuid]
        )
        return {
            "user_id": str(user.id),
            "space_ids": [str(s) for s in all_space_ids],
            "crew_ids": [],
            "include_personal": False,
        }
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unknown scope: {scope!r}. Use 'personal' or 'space:<uuid>'.",
    )


def _ai_base_url() -> str:
    return (settings.AI_SERVICE_URL or "http://localhost:8001").rstrip("/")


# ─── /context/semantic-map ────────────────────────────────────────────


@router.get(
    "/semantic-map",
    response_model=SemanticMapResponse,
    summary="Universe Intelligence v2 — projected embeddings (UMAP)",
)
async def get_semantic_map(
    scope: str = Query("personal", description="'personal' or 'space:<uuid>'"),
    n_components: int = Query(3, ge=2, le=3),
    n_neighbors: int = Query(15, ge=2, le=100),
    min_dist: float = Query(0.1, ge=0.0, le=1.0),
    enable_clustering: bool = Query(True),
    min_cluster_size: int = Query(5, ge=2, le=50),
    limit: int = Query(2000, ge=1, le=10000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SemanticMapResponse:
    """Returns the projected coordinates of every embedding the caller
    can see, plus a cluster_id per point (for the FE's LOD zoom).

    Empty list when the caller has no embeddings in scope (no Space
    memberships and no Personal docs) — the FE renders a "connect a
    source" empty state.
    """
    acl = await _resolve_scope(scope, current_user, db)
    payload = {
        **acl,
        "n_components": n_components,
        "n_neighbors": n_neighbors,
        "min_dist": min_dist,
        "enable_clustering": enable_clustering,
        "min_cluster_size": min_cluster_size,
        "limit": limit,
    }
    url = f"{_ai_base_url()}/semantic/map"
    # UMAP for 1-2k points is ~3s; 60s leaves headroom for cold start
    # of the AI service venv. The FE shows a "loading universe" state.
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(url, json=payload)
        except httpx.HTTPError as e:
            logger.error("AI service unreachable for /semantic/map: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service unavailable",
            ) from e
    if response.status_code != 200:
        logger.error(
            "AI /semantic/map returned %s: %s",
            response.status_code,
            response.text[:200],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI service error {response.status_code}",
        )
    return SemanticMapResponse(**response.json())


# ─── /context/semantic-search ─────────────────────────────────────────


@router.post(
    "/semantic-search",
    response_model=SemanticSearchResponse,
    summary="Top-K semantic search over the caller's embedding scope",
)
async def post_semantic_search(
    body: SemanticSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SemanticSearchResponse:
    """Embeds ``query`` and returns the top-K nearest embeddings — used
    by the Universe Intelligence "ask anything" box to drive the lit-
    path overlay (RAG trace, Phase E).
    """
    if not body.query.strip():
        raise HTTPException(400, "Query is empty.")
    acl = await _resolve_scope(body.scope, current_user, db)
    payload = {
        **acl,
        "query": body.query,
        "top_k": body.top_k,
    }
    url = f"{_ai_base_url()}/semantic/search"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, json=payload)
        except httpx.HTTPError as e:
            logger.error("AI service unreachable for /semantic/search: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service unavailable",
            ) from e
    if response.status_code != 200:
        logger.error(
            "AI /semantic/search returned %s: %s",
            response.status_code,
            response.text[:200],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI service error {response.status_code}",
        )
    return SemanticSearchResponse(**response.json())
