"""Context-row fetch endpoint — feeds the AI service's ingest worker.

When the backend mutates a row that participates in the context layer
(see `src/core/context_events.py`), it pushes an event onto the
`context:ingest` Redis stream with `(source_table, source_id)`. The
worker in sky-poc-ai needs to hydrate that tuple into a full row dict
so its render template can produce title/body/metadata before the
row is embedded into `context_documents`.

Before this endpoint existed, every ingest event was silently dropped
with "skipped_no_row" — which meant NO user-created glossary term,
pillar, event, or widget ever reached the context layer. Nothing the
AI retrieved could cite them.

The endpoint is intentionally generic: one route, a model registry,
and a row-to-dict serializer. Adding a new context kind only requires
extending the registry + adding a render template on the AI side.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.connection import DataConnection
from src.models.conversation import Conversation, Message
from src.models.crew import Crew, CrewMember
from src.models.widget import Widget
from src.models.enterprise_relationship import EnterpriseRelationship
from src.models.glossary import GlossaryTerm
from src.models.space import Space, SpaceMember
from src.models.starred import StarredItem
from src.models.user import User
# Strategy entities removed in Knowledge refactor (2026-04-25). Phase 2
# adds `metric` + `glossary_term` to MODEL_REGISTRY below.
from src.services.rbac_service import RBACService

router = APIRouter()


# ─── Registry ─────────────────────────────────────────────────────────────
# Source-table name (as written to context_documents.source_table) →
# SQLAlchemy model class. Mirrors the mappings in
# `src/core/context_events._register_default_mappings`. Keep the two in
# sync — a mismatch here means events emit but never hydrate.

MODEL_REGISTRY: Dict[str, Any] = {
    # Strategy + Events/Signals entries were removed in the Knowledge
    # refactor (Phase 1a + 1b). Phase 2 will add "metrics" and replace
    # "glossary_terms" with the rebuilt schema.
    "glossary_terms": GlossaryTerm,
    "user_enterprise_relationships": EnterpriseRelationship,
    "users": User,
    "spaces": Space,
    "crews": Crew,
    "space_members": SpaceMember,
    "crew_members": CrewMember,
    "data_connections": DataConnection,
    "widgets": Widget,
    "conversations": Conversation,
    "messages": Message,
    "starred_items": StarredItem,
}


# ─── Serializer ───────────────────────────────────────────────────────────
def row_to_dict(row: Any) -> Dict[str, Any]:
    """Convert a SQLAlchemy row into a JSON-safe dict.

    Reads the model's mapped columns directly rather than using __dict__,
    which avoids leaking SQLAlchemy internals (_sa_instance_state) or
    lazy-loaded relationship attributes. Enum values are flattened to
    their string form; UUIDs and datetimes become strings so the JSON
    response stays shallow and simple for the AI renderer.
    """
    if not hasattr(row, "__table__"):
        return {}
    result: Dict[str, Any] = {}
    for col in row.__table__.columns:
        value = getattr(row, col.name, None)
        if value is None:
            result[col.name] = None
        elif isinstance(value, Enum):
            result[col.name] = value.value
        elif isinstance(value, UUID):
            result[col.name] = str(value)
        elif isinstance(value, datetime):
            result[col.name] = value.isoformat()
        elif isinstance(value, (bytes, bytearray)):
            result[col.name] = value.hex()
        else:
            result[col.name] = value
    return result


# ─── Endpoint ─────────────────────────────────────────────────────────────
@router.get("/rows/{source_table}/{source_id}")
async def get_context_row(
    source_table: str = Path(..., description="Table name as written to context_documents.source_table"),
    source_id: str = Path(..., description="Primary-key UUID of the row"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Return the row identified by (source_table, source_id) as a dict.

    404 on unknown table or missing row — the ingest worker treats that
    as "row was deleted, soft-delete the document" so it's the correct
    response in both cases.

    Auth: requires the caller to hold `connections.view` so service
    accounts / admins from the AI service can read but regular users
    can't cherry-pick rows through this generic endpoint.
    """
    await RBACService(db).assert_permission(current_user, "connections.view")

    model = MODEL_REGISTRY.get(source_table)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown source_table: {source_table}")

    try:
        source_uuid = UUID(source_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="source_id must be a UUID")

    stmt = select(model).where(model.id == source_uuid)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="row not found")

    # Soft-deleted rows look the same to the ingest worker as hard-deleted
    # ones — return 404 so it soft-deletes the document, keeping the
    # evidence trail clean for past agent runs.
    if getattr(row, "deleted_at", None) is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="row soft-deleted")

    return row_to_dict(row)
