"""Context-event emitter — Phase 2.2.

When a domain row is inserted, updated, or soft-deleted, we push a small
event onto the Redis stream ``context:ingest``. The AI service consumes
that stream, renders the row through its template, embeds the body, and
upserts a ``context_documents`` row.

Design decisions:

1. **Session-scoped capture, commit-scoped publish.** SQLAlchemy fires
   after_insert / after_update / after_delete *before* the transaction
   commits, which is the wrong moment to publish — a rollback would
   poison the stream. We collect events on the session in after_flush,
   then publish them in after_commit (or discard in after_rollback).

2. **Fire-and-forget publishing.** A failed Redis publish MUST NOT abort
   a user-facing request. We log and move on. The ingest worker has a
   periodic reconciliation sweep (Phase 2.7 backfill) that re-seeds any
   rows whose events were lost.

3. **Declarative model → kind map.** Every model that participates in
   the context layer has a ``ContextMapping`` entry. The emitter reads
   the mapping, resolves the RBAC scope from well-known attribute names
   (space_id, crew_id, owner_user_id, created_by), and emits the event.
   Adding a new kind is one line in the mapping plus a render template
   on the AI-service side.

4. **Async publish, sync listeners.** SQLAlchemy events are synchronous.
   We use ``asyncio.create_task`` from a background loop we own
   (initialised in ``init_context_events``). If the loop isn't running
   yet (early startup, or in sync CLI contexts), we fall back to a
   direct ``redis-py`` publish in a thread.

The Redis stream format is stable — changing it is a breaking change
that requires the AI-service ingest worker to be updated in lockstep.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.orm import Session, UOWTransaction

logger = logging.getLogger(__name__)

CONTEXT_STREAM = "context:ingest"
_PENDING_KEY = "_context_pending_events"

# The publish strategy is a module-level hook so tests can swap it for an
# in-memory sink. Production callers should stay on the default.
_publisher: Optional[Callable[[list["ContextEvent"]], None]] = None


def set_publisher(fn: Optional[Callable[[list["ContextEvent"]], None]]) -> None:
    """Override the publisher (tests only). Pass None to restore default."""
    global _publisher
    _publisher = fn


# ───────────────────────────── mapping ────────────────────────────────────
@dataclass(frozen=True)
class ContextMapping:
    """How one ORM model maps to a context document.

    Attributes:
        model:        the SQLAlchemy mapped class.
        kind:         string kind discriminator (goal / okr / widget / …).
        source_table: literal name written to context_documents.source_table
                      (usually matches ``model.__tablename__``).
        visibility:   default visibility when the row has no explicit flag.
                      Scope attributes override at event time.
        resolve_kind: optional callable (instance) -> kind. Used when one
                      table maps to multiple kinds (e.g. signal_events →
                      internal vs external vs trend vs macro).
    """

    model: Any
    kind: str
    source_table: str
    visibility: str = "space"
    resolve_kind: Optional[Callable[[Any], str]] = None


# Registry filled by register_context_mapping().
_mappings: dict[Any, ContextMapping] = {}


def register_context_mapping(mapping: ContextMapping) -> None:
    """Register a model → kind mapping.

    The actual change detection happens at the Session level via
    ``after_flush`` (see ``_install_session_hooks``), which iterates
    ``session.new / dirty / deleted``. That approach is simpler and
    more reliable than mapper-level listeners, especially in the async
    session world where primary keys may not be bound on the target at
    the moment a per-row event fires.
    """
    _mappings[mapping.model] = mapping


# ─────────────────────────── event payload ────────────────────────────────
@dataclass
class ContextEvent:
    action: str  # 'upsert' | 'delete'
    kind: str
    source_table: str
    source_id: str
    space_id: Optional[str] = None
    crew_id: Optional[str] = None
    owner_user_id: Optional[str] = None
    visibility: str = "space"
    meta: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "action": self.action,
                "kind": self.kind,
                "source_table": self.source_table,
                "source_id": self.source_id,
                "space_id": self.space_id,
                "crew_id": self.crew_id,
                "owner_user_id": self.owner_user_id,
                "visibility": self.visibility,
                "meta": self.meta,
            }
        )


# ──────────────────────── scope extraction ────────────────────────────────
def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _extract_scope(obj: Any) -> dict[str, Optional[str]]:
    space_id = getattr(obj, "space_id", None)
    crew_id = getattr(obj, "crew_id", None)
    owner_user_id = getattr(obj, "owner_user_id", None)
    if owner_user_id is None:
        owner_user_id = getattr(obj, "created_by", None)
    if owner_user_id is None:
        owner_user_id = getattr(obj, "user_id", None)
    return {
        "space_id": _stringify(space_id),
        "crew_id": _stringify(crew_id),
        "owner_user_id": _stringify(owner_user_id),
    }


def _build_event(action: str, mapping: ContextMapping, obj: Any) -> ContextEvent:
    kind = mapping.kind
    if mapping.resolve_kind is not None:
        try:
            kind = mapping.resolve_kind(obj) or mapping.kind
        except Exception:
            logger.exception("resolve_kind failed for %s — falling back to default", mapping.model.__name__)
    scope = _extract_scope(obj)
    return ContextEvent(
        action=action,
        kind=kind,
        source_table=mapping.source_table,
        source_id=_stringify(getattr(obj, "id", None)) or "",
        space_id=scope["space_id"],
        crew_id=scope["crew_id"],
        owner_user_id=scope["owner_user_id"],
        visibility=mapping.visibility,
    )


# ───────────────────────── session-level hooks ────────────────────────────
_installed_classes: set = set()


def _install_session_hooks(session_cls) -> None:
    # Idempotent: a second call for the same class is a no-op. Without this
    # guard, repeated registration (e.g. across tests) accumulates listeners
    # and every flush produces N-times duplicated events.
    if session_cls in _installed_classes:
        return
    _installed_classes.add(session_cls)
    @event.listens_for(session_cls, "after_flush")
    def _snapshot_changes(sess: Session, flush_context: UOWTransaction) -> None:
        pending = sess.info.setdefault(_PENDING_KEY, [])

        # New rows → upsert. session.new is a set of persistent-new instances
        # available inside after_flush (they still have their id at this
        # point because client-side defaults ran in before_flush).
        for obj in sess.new:
            mapping = _mappings.get(type(obj))
            if mapping is None:
                continue
            evt = _build_event("upsert", mapping, obj)
            if evt.source_id:
                pending.append(evt)

        # Updated rows → upsert, or delete if deleted_at transitioned to set.
        for obj in sess.dirty:
            mapping = _mappings.get(type(obj))
            if mapping is None:
                continue
            if getattr(obj, "deleted_at", None) is not None:
                action = "delete"
            else:
                action = "upsert"
            evt = _build_event(action, mapping, obj)
            if evt.source_id:
                pending.append(evt)

        # Hard-deleted rows → delete.
        for obj in sess.deleted:
            mapping = _mappings.get(type(obj))
            if mapping is None:
                continue
            evt = _build_event("delete", mapping, obj)
            if evt.source_id:
                pending.append(evt)

    @event.listens_for(session_cls, "after_commit")
    def _drain_on_commit(sess: Session) -> None:
        pending = sess.info.pop(_PENDING_KEY, None)
        if pending:
            _publish(pending)

    @event.listens_for(session_cls, "after_rollback")
    def _discard_on_rollback(sess: Session) -> None:
        sess.info.pop(_PENDING_KEY, None)


# ────────────────────────── Redis publishing ──────────────────────────────
# The Redis client is lazily acquired. In async contexts we obtain the
# shared `redis.asyncio` connection used by the rest of the service. In
# sync contexts (CLI, Alembic backfill) we fall back to a throw-away
# sync client from the same URL. Both are fire-and-forget.


def _publish(events: Iterable[ContextEvent]) -> None:
    events_list = list(events)
    if _publisher is not None:
        try:
            _publisher(events_list)
        except Exception:
            logger.exception("custom publisher raised — events dropped")
        return

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        loop.create_task(_async_publish(events_list))
        return

    # Sync context — use a short-lived client synchronously.
    _sync_publish(events_list)


async def _async_publish(events: list[ContextEvent]) -> None:
    try:
        from src.config.redis import get_redis

        client = await get_redis()
        if client is None:
            logger.debug("Redis unavailable — dropping %d context events", len(events))
            return
        for evt in events:
            try:
                await client.xadd(CONTEXT_STREAM, {"payload": evt.to_json()}, maxlen=100_000, approximate=True)
            except Exception:
                logger.exception(
                    "Failed to XADD to %s for %s/%s",
                    CONTEXT_STREAM,
                    evt.source_table,
                    evt.source_id,
                )
    except Exception:
        logger.exception("async context publish failed")


def _sync_publish(events: list[ContextEvent]) -> None:
    try:
        import redis

        from src.config.settings import settings

        url = settings.REDIS_URL or "redis://localhost:6379/0"
        client = redis.from_url(url, decode_responses=True)
        for evt in events:
            try:
                client.xadd(CONTEXT_STREAM, {"payload": evt.to_json()}, maxlen=100_000, approximate=True)
            except Exception:
                logger.exception(
                    "Failed to XADD (sync) to %s for %s/%s",
                    CONTEXT_STREAM,
                    evt.source_table,
                    evt.source_id,
                )
    except Exception:
        logger.exception("sync context publish failed")


# ───────────────────────────── bootstrap ──────────────────────────────────
def init_context_events(session_cls=None) -> None:
    """Call once during application startup.

    Registers the mapping table (strategy/events/widgets/etc) and installs
    the session-level drain hooks.

    IMPORTANT — `after_flush` / `after_commit` / `after_rollback` are
    events defined on `sqlalchemy.orm.Session` (the sync base class).
    `async_sessionmaker` + `AsyncSession` don't expose them directly;
    internally every AsyncSession runs its flush through a sync
    `Session` instance, and Session-level events fire for that sync
    session. So we always bind to the base `Session` class regardless
    of what the caller passes. The `session_cls` parameter is kept for
    backward compat with test fixtures that passed the sync session
    class directly — it's simply ignored unless it looks like a valid
    Session subclass.
    """
    from sqlalchemy.orm import Session as _BaseSession

    target_cls = _BaseSession
    # Backward compat: tests that already pass _BaseSession keep
    # working. Anything that's NOT a Session subclass (e.g. an
    # async_sessionmaker from production code) falls back to the base
    # class instead of raising.
    if session_cls is not None:
        try:
            if isinstance(session_cls, type) and issubclass(session_cls, _BaseSession):
                target_cls = session_cls
        except TypeError:
            # session_cls wasn't a class at all (e.g. an instance of
            # async_sessionmaker) — ignore and use the base.
            pass

    _install_session_hooks(target_cls)
    _register_default_mappings()


def _register_default_mappings() -> None:
    """Declarative map of every domain model → context kind.

    Kept small and explicit on purpose so reviewers can see every kind
    that participates in the brain at a glance.
    """
    # Local import avoids circular dependencies during module load.
    from src.models.connection import DataConnection
    from src.models.conversation import Conversation, Message
    from src.models.crew import Crew, CrewMember
    from src.models.dashboard import Widget
    from src.models.enterprise_relationship import EnterpriseRelationship
    from src.models.glossary import GlossaryTerm
    from src.models.signal_event import SignalEvent
    from src.models.space import Space, SpaceMember
    from src.models.starred import StarredItem
    from src.models.user import User

    # Strategy mappings (Pillar / Objective / OKR / Initiative / KeyResult /
    # Assumption / Cycle) were removed in the 2026-04-25 Knowledge refactor.
    # Their kinds (pillar / goal / okr / initiative / kpi / risk) will
    # re-appear when Phase 2 lands `metric` and `glossary_term` registrations
    # — they fold into Metric attributes (tags, target_value, thresholds)
    # rather than separate entities.

    # Glossary — short vocabulary terms (GMV / MAU / Churn / …) scoped to space/crew.
    register_context_mapping(ContextMapping(model=GlossaryTerm, kind="glossary", source_table="glossary_terms"))

    # Events / Signals — kind resolved from category (internal / external / trend / macro).
    register_context_mapping(
        ContextMapping(
            model=SignalEvent,
            kind="event_internal",
            source_table="signal_events",
            resolve_kind=_signal_event_kind,
        )
    )

    # Relationships
    register_context_mapping(
        ContextMapping(
            model=EnterpriseRelationship,
            kind="relationship",
            source_table="user_enterprise_relationships",
        )
    )

    # Platform fabric — users, spaces, crews, memberships.
    # `user` documents are public by default (discoverable across spaces
    # for "who owns X" questions); values themselves are PII and get
    # masked at response time by the render template's pii_flags.
    register_context_mapping(ContextMapping(model=User, kind="user", source_table="users", visibility="public"))
    register_context_mapping(ContextMapping(model=Space, kind="space", source_table="spaces"))
    register_context_mapping(ContextMapping(model=Crew, kind="crew", source_table="crews"))
    register_context_mapping(ContextMapping(model=SpaceMember, kind="membership", source_table="space_members"))
    register_context_mapping(ContextMapping(model=CrewMember, kind="membership", source_table="crew_members"))

    # Connections — the data-source catalog. Tables / columns live in
    # AI-service-owned tables (table_metadata / column_metadata) — those
    # are ingested on that side directly, not through this stream.
    register_context_mapping(ContextMapping(model=DataConnection, kind="connection", source_table="data_connections"))

    # Outputs & social
    register_context_mapping(ContextMapping(model=Widget, kind="widget", source_table="widgets"))
    register_context_mapping(ContextMapping(model=Conversation, kind="conversation", source_table="conversations"))
    register_context_mapping(ContextMapping(model=Message, kind="message", source_table="messages"))
    register_context_mapping(ContextMapping(model=StarredItem, kind="pin", source_table="starred_items"))


def _signal_event_kind(obj: Any) -> str:
    """Map signal_events.category → context kind.

    The SignalCategory enum (INTERNAL / EXTERNAL / TRENDS) covers the
    first three context kinds. We don't yet have a stored "MACRO"
    category — the master plan reserves ``event_macro`` for
    macro-economic signals that will ship alongside external-API
    ingestion; for now, unknown categories bucket into ``event_internal``
    which is the safest default (more restrictive retrieval scope).
    """
    category = getattr(obj, "category", None)
    if category is None:
        return "event_internal"
    # Enum vs raw string — handle both.
    value = getattr(category, "value", category)
    if not isinstance(value, str):
        return "event_internal"
    v = value.upper()
    if v == "INTERNAL":
        return "event_internal"
    if v == "EXTERNAL":
        return "event_external"
    if v == "TRENDS":
        return "event_trend"
    if v == "MACRO":
        return "event_macro"
    return "event_internal"
