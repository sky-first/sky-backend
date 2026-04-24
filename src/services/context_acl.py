"""W1 — context ACL pure helpers.

This module holds **pure** functions (no DB, no network, no globals) that
answer: "given a ContextDocument and a caller's scope, is it visible?".
Keeping them pure keeps W2 (``permission_service.list_authorized_embedding_ids``)
trivial to audit and test, and lets retrieval logic in-memory filter batches
without round-tripping to the DB.

Security stance: **fail-closed**. Every ambiguous case returns ``False``.

Matches master plan §2 (Modelo de Contexto) and §3 (Retrieval Permission
Chain).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence


# Visibility values the schema allows (mirror the CHECK constraint in
# migrations/versions/add_context_documents_20260415.py). Unknown values must
# fail CLOSED — we do NOT add enums here to avoid importing the model.
_VALID_VISIBILITIES: frozenset[str] = frozenset({"public", "space", "crew", "user"})


@dataclass(frozen=True)
class VisibilityContext:
    """What the caller is "seeing from". Populated by permission_service
    after resolving memberships; fed into the ACL filter.

    Fields:
      user_id:          authenticated caller.
      space_id:         active space (``None`` = personal aggregate view).
      crew_ids:         caller's crew memberships that apply to this request.
      is_personal:      True when the caller is in Personal mode.
      allowed_space_ids: spaces the caller belongs to — consulted ONLY when
                        ``is_personal=True`` so Personal can aggregate
                        across spaces the user is actually in. In Space
                        mode, ``space_id`` is authoritative.
    """

    user_id: uuid.UUID
    space_id: Optional[uuid.UUID]
    crew_ids: Sequence[uuid.UUID] = ()
    is_personal: bool = False
    allowed_space_ids: Sequence[uuid.UUID] = field(default_factory=list)


def sanitize_body_for_hash(body: str) -> str:
    """Deliberate passthrough — documents the rule that ``content_hash`` is
    computed over RAW bytes. Any sanitization happens at render time (when
    the body is inserted into the prompt), never at hash time. Changing
    this would let an attacker poison cache: craft a body that sanitizes
    to the same string as a cached row, then pre-seed the cache with a
    booby-trapped "original" body.
    """
    return body


def _coerce_uuid(value: object) -> Optional[uuid.UUID]:
    """Accept both ``UUID`` and ``str`` (SQLite JSON round-trip returns str)
    and normalize. Invalid → ``None``."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


def _coerce_uuid_list(values: Iterable[object]) -> List[uuid.UUID]:
    return [u for u in (_coerce_uuid(v) for v in values or []) if u is not None]


def is_visible_to_context(doc, ctx: VisibilityContext) -> bool:
    """Return True iff the caller (``ctx``) may see ``doc``. Fails closed.

    Decision tree (first match wins):
      1. Tombstoned (``deleted_at`` set)            → False
      2. Unknown visibility value                   → False  (data corruption)
      3. visibility=public                           → True
      4. visibility=user                             → (owner_user_id == caller)
      5. visibility=space                            →
           - space_id must be set (else False)
           - caller's space_id matches, OR
           - personal aggregate includes this space
      6. visibility=crew                             →
           - space_id must be set AND crew_ids non-empty
           - space scope must match (same rules as §5)
           - caller's crew_ids must intersect doc's crew_ids
      7. default                                     → False

    `user_id` in VisibilityContext is currently used only for visibility=user.
    Tenant isolation is implicit via space membership; cross-tenant attacks
    manifest as "user has no space membership in target's tenant", which
    falls through to False.
    """
    # [1] tombstones
    if getattr(doc, "deleted_at", None) is not None:
        return False

    vis = getattr(doc, "visibility", None)
    # [2] corruption / injection
    if not isinstance(vis, str) or vis not in _VALID_VISIBILITIES:
        return False

    # [3] public
    if vis == "public":
        return True

    doc_owner = _coerce_uuid(getattr(doc, "owner_user_id", None))
    doc_space = _coerce_uuid(getattr(doc, "space_id", None))
    doc_crew_ids_raw = getattr(doc, "crew_ids", None) or []
    doc_crew_ids = _coerce_uuid_list(doc_crew_ids_raw)

    # [4] user scope
    if vis == "user":
        if doc_owner is None:
            return False
        return doc_owner == ctx.user_id

    # space/crew require a real space_id
    if doc_space is None:
        return False

    allowed_space_ids = _coerce_uuid_list(ctx.allowed_space_ids)
    caller_crew_ids = _coerce_uuid_list(ctx.crew_ids)

    space_match = (
        (ctx.space_id is not None and _coerce_uuid(ctx.space_id) == doc_space)
        or (ctx.is_personal and doc_space in allowed_space_ids)
    )

    # [5] space scope
    if vis == "space":
        return bool(space_match)

    # [6] crew scope
    if vis == "crew":
        if not space_match:
            return False
        if not doc_crew_ids:
            return False  # data corruption — crew scope with no crews
        return any(cid in caller_crew_ids for cid in doc_crew_ids)

    # [7] default fail-closed
    return False


def filter_visible(docs: Iterable, ctx: VisibilityContext) -> List:
    """Batch helper — returns only the docs visible to ``ctx``."""
    return [d for d in docs if is_visible_to_context(d, ctx)]
