"""Cache warming candidate selection for AI response cache.

Subtask 1: select the best candidates to warm (what to precompute).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.ai import AIQuery
from src.models.dashboard import Widget
from src.models.space import SpaceConnection


@dataclass(frozen=True)
class WarmCandidate:
    """A single cache-warming candidate."""

    user_id: UUID
    space_id: str
    connection_id: str
    question: str
    count: int
    last_used_at: datetime


def _normalize_question(question: str) -> str:
    q = (question or "").strip().lower()
    # collapse whitespace to make repeated questions stable
    q = " ".join(q.split())
    return q


async def _resolve_space_id_for_connection(db: AsyncSession, connection_id: UUID) -> Optional[str]:
    """Resolve a connection_id to a space_id via space_connections."""
    stmt = (
        select(SpaceConnection.space_id)
        .where(SpaceConnection.connection_id == connection_id)
        .limit(1)
    )
    space_uuid = await db.scalar(stmt)
    return str(space_uuid) if space_uuid else None


def _pick_top_n_per_connection(
    groups: Dict[Tuple[str, str], Tuple[int, datetime, UUID, str]],
    *,
    top_n_per_connection: int,
) -> List[Tuple[str, str, int, datetime, UUID, str]]:
    """
    Convert grouped stats into an ordered list.

    groups key: (connection_id_str, normalized_question)
    groups value: (count, last_used_at, user_id, original_question)
    """
    by_conn: Dict[str, List[Tuple[str, int, datetime, UUID, str]]] = {}
    for (conn_id, norm_q), (count, last_used, user_id, original_question) in groups.items():
        by_conn.setdefault(conn_id, []).append(
            (norm_q, count, last_used, user_id, original_question)
        )

    selected: List[Tuple[str, str, int, datetime, UUID, str]] = []
    for conn_id, items in by_conn.items():
        items.sort(key=lambda t: (-t[1], -t[2].timestamp()))
        for norm_q, count, last_used, user_id, original_question in items[:top_n_per_connection]:
            selected.append((conn_id, norm_q, count, last_used, user_id, original_question))

    # Global ordering: most frequent first, then most recent
    selected.sort(key=lambda t: (-t[2], -t[3].timestamp()))
    return selected


async def get_ai_cache_warm_candidates(
    db: AsyncSession,
    *,
    lookback_hours: int = 24,
    top_n_per_connection: int = 10,
    min_question_length: int = 6,
    max_scan_rows: int = 5000,
    max_total: int = 200,
) -> List[WarmCandidate]:
    """
    Select warm candidates from recent completed AI queries that are linked to widgets
    (so we can reliably infer connection_id).

    Returns a small list of candidates per connection, ordered by (frequency, recency).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    # Pull recent, completed queries that are tied to widgets with connection_id.
    stmt = (
        select(AIQuery.user_id, AIQuery.question, AIQuery.updated_at, Widget.connection_id)
        .join(Widget, Widget.id == AIQuery.widget_id)
        .where(AIQuery.status == "completed")
        .where(AIQuery.updated_at >= cutoff)
        .where(Widget.connection_id.is_not(None))
        .order_by(AIQuery.updated_at.desc())
        .limit(max_scan_rows)
    )
    rows = (await db.execute(stmt)).all()

    # Group by (connection_id, normalized_question)
    groups: Dict[Tuple[str, str], Tuple[int, datetime, UUID, str]] = {}
    for user_id, question, updated_at, connection_uuid in rows:
        if not question or len(str(question).strip()) < min_question_length:
            continue
        if not connection_uuid:
            continue

        conn_id_str = str(connection_uuid)
        original_q = str(question).strip()
        norm_q = _normalize_question(original_q)
        if not norm_q or len(norm_q) < min_question_length:
            continue

        key = (conn_id_str, norm_q)
        if key not in groups:
            groups[key] = (1, updated_at, user_id, original_q)
        else:
            count, last_used, uid, oq = groups[key]
            new_count = count + 1
            # keep the newest timestamp + question variant closest to newest
            if updated_at and (not last_used or updated_at > last_used):
                groups[key] = (new_count, updated_at, user_id, original_q)
            else:
                groups[key] = (new_count, last_used, uid, oq)

    picked = _pick_top_n_per_connection(groups, top_n_per_connection=top_n_per_connection)
    if not picked:
        return []

    # Resolve space_id for each connection_id once.
    space_by_conn: Dict[str, Optional[str]] = {}
    out: List[WarmCandidate] = []
    for conn_id_str, _norm_q, count, last_used, user_id, original_q in picked:
        if len(out) >= max_total:
            break
        if conn_id_str not in space_by_conn:
            try:
                space_by_conn[conn_id_str] = await _resolve_space_id_for_connection(
                    db, UUID(conn_id_str)
                )
            except Exception:
                space_by_conn[conn_id_str] = None

        space_id = space_by_conn.get(conn_id_str)
        if not space_id:
            continue

        out.append(
            WarmCandidate(
                user_id=user_id,
                space_id=space_id,
                connection_id=conn_id_str,
                question=original_q,
                count=count,
                last_used_at=last_used,
            )
        )

    return out
