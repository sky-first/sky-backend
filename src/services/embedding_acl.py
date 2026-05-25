"""W2 — permission-scoped embedding retrieval.

Wraps a DB query with a pluggable cache and routes every returned ID
through the pure ``context_acl.filter_visible`` gate. Belt-and-suspenders:
even if the SQL prefilter misses an edge, the Python gate fails closed.

Master plan §3.3 (Resolução de ``authorized_embedding_ids``).

Usage from chat/agent path::

    svc = EmbeddingACLService(db, cache=RedisCacheBackend())
    ids = await svc.list_authorized_embedding_ids(
        user_id=current_user.id,
        space_id=space.id,
        crew_ids=user_crew_ids,
        is_personal=False,
    )
    # pass ``ids`` down to the Runpod AI service as ``authorized_embedding_ids``
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from typing import Iterable, List, Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.context_document import ContextDocument
from src.services.context_acl import (
    VisibilityContext,
    is_visible_to_context,
)

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 60
MAX_PREFILTER_ROWS = 50_000  # hard cap on the broad candidate fetch


# ---------------------------------------------------------------------------
#  Cache backends (pluggable — Redis in prod, in-memory in tests)
# ---------------------------------------------------------------------------


class CacheBackend(ABC):
    """Minimal async KV contract used by the ACL layer.

    Any class that can answer ``get``/``set``/``delete_pattern`` works. The
    default prod backend is Redis (via ``src.utils.cache.CacheService``);
    tests inject an in-memory dict via ``InMemoryCacheBackend``.
    """

    @abstractmethod
    async def get(self, key: str) -> Optional[str]: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl: int) -> None: ...

    @abstractmethod
    async def delete_pattern(self, pattern: str) -> int: ...


class InMemoryCacheBackend(CacheBackend):
    """Process-local dict backend — intended for tests only.

    TTL is honoured best-effort: a wall-clock expiry is checked on read.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}

    async def get(self, key: str) -> Optional[str]:
        import time

        hit = self._store.get(key)
        if not hit:
            return None
        value, exp = hit
        if exp and time.time() > exp:
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ttl: int) -> None:
        import time

        exp = time.time() + ttl if ttl and ttl > 0 else 0
        self._store[key] = (value, exp)

    async def delete_pattern(self, pattern: str) -> int:
        # Very narrow glob support — only prefix matches with trailing "*".
        if not pattern.endswith("*"):
            if pattern in self._store:
                self._store.pop(pattern)
                return 1
            return 0
        prefix = pattern[:-1]
        stale = [k for k in self._store if k.startswith(prefix)]
        for k in stale:
            self._store.pop(k, None)
        return len(stale)


class RedisCacheBackend(CacheBackend):
    """Thin adapter over ``src.utils.cache.CacheService``. Imported lazily
    so tests don't need a live Redis to import this module."""

    async def get(self, key: str) -> Optional[str]:
        from src.utils.cache import CacheService

        return await CacheService.get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        from src.utils.cache import CacheService

        await CacheService.set(key, value, ttl=ttl)

    async def delete_pattern(self, pattern: str) -> int:
        from src.utils.cache import CacheService

        return await CacheService.delete_pattern(pattern)


# ---------------------------------------------------------------------------
#  Service
# ---------------------------------------------------------------------------


class EmbeddingACLService:
    """Resolves ``authorized_embedding_ids`` for a caller + scope.

    Parameters:
      db:    an ``AsyncSession`` (may be ``None`` for pure in-memory tests
             where ``candidate_docs`` is injected).
      cache: optional ``CacheBackend``. When ``None``, every call hits the DB.
      ttl:   cache TTL in seconds. Defaults to 60s (matches master plan §3.4).
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        cache: Optional[CacheBackend] = None,
        ttl: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.db = db
        self.cache = cache
        self.ttl = ttl

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    async def list_authorized_embedding_ids(
        self,
        user_id: UUID,
        space_id: Optional[UUID] = None,
        crew_ids: Sequence[UUID] = (),
        is_personal: bool = False,
        allowed_space_ids: Sequence[UUID] = (),
        kinds: Optional[Sequence[str]] = None,
        *,
        candidate_docs: Optional[Iterable[ContextDocument]] = None,
    ) -> List[UUID]:
        """Return the IDs of context docs the caller is allowed to see.

        ``candidate_docs`` is a test seam — when provided, the DB fetch is
        skipped and the ACL gate runs against the injected iterable. Prod
        callers never pass this.
        """
        cache_key = self._cache_key(
            user_id=user_id,
            space_id=space_id,
            crew_ids=crew_ids,
            is_personal=is_personal,
            allowed_space_ids=allowed_space_ids,
            kinds=kinds,
        )

        if self.cache is not None:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                try:
                    return [UUID(x) for x in json.loads(cached)]
                except (ValueError, json.JSONDecodeError):
                    # Corrupt cache entry — fall through to recompute.
                    logger.warning(
                        "Discarding corrupt embedding-ACL cache entry key=%s",
                        cache_key,
                    )

        candidates: Iterable[ContextDocument]
        if candidate_docs is not None:
            candidates = candidate_docs
        else:
            candidates = await self._fetch_candidates(
                user_id=user_id,
                space_id=space_id,
                allowed_space_ids=allowed_space_ids,
                kinds=kinds,
                is_personal=is_personal,
            )

        ctx = VisibilityContext(
            user_id=user_id,
            space_id=space_id,
            crew_ids=list(crew_ids),
            is_personal=is_personal,
            allowed_space_ids=list(allowed_space_ids),
        )
        visible_ids: List[UUID] = [c.id for c in candidates if is_visible_to_context(c, ctx)]

        if self.cache is not None:
            await self.cache.set(
                cache_key,
                json.dumps([str(i) for i in visible_ids]),
                self.ttl,
            )

        return visible_ids

    async def invalidate_user(self, user_id: UUID) -> int:
        """Drop every cached entry for ``user_id``. Call when space/crew
        memberships change or on logout."""
        if self.cache is None:
            return 0
        return await self.cache.delete_pattern(f"rag_acl:{user_id}:*")

    async def invalidate_all(self) -> int:
        """Emergency switch — e.g. after a bulk ACL migration."""
        if self.cache is None:
            return 0
        return await self.cache.delete_pattern("rag_acl:*")

    # ------------------------------------------------------------------
    #  Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(
        *,
        user_id: UUID,
        space_id: Optional[UUID],
        crew_ids: Sequence[UUID],
        is_personal: bool,
        allowed_space_ids: Sequence[UUID],
        kinds: Optional[Sequence[str]],
    ) -> str:
        """Deterministic cache key per (user, scope, kinds).

        Crews + allowed-spaces are sorted before hashing so argument order
        never causes a miss. ``kinds=None`` and ``kinds=[]`` hash the same
        ("no filter").
        """
        scope = {
            "user": str(user_id),
            "space": str(space_id) if space_id else "",
            "crews": sorted(str(c) for c in crew_ids or ()),
            "personal": 1 if is_personal else 0,
            "allowed": sorted(str(s) for s in allowed_space_ids or ()),
            "kinds": sorted(kinds) if kinds else [],
        }
        blob = json.dumps(scope, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
        return f"rag_acl:{user_id}:{digest}"

    async def _fetch_candidates(
        self,
        *,
        user_id: UUID,
        space_id: Optional[UUID],
        allowed_space_ids: Sequence[UUID],
        kinds: Optional[Sequence[str]],
        is_personal: bool,
    ) -> List[ContextDocument]:
        """Broad prefilter. The authoritative gate is ``is_visible_to_context``
        — this only narrows the DB read.

        Intentionally simple: fetch every doc whose scope COULD match the
        caller. ``deleted_at IS NULL`` and kind-filter are always applied
        so the prefilter never leaks tombstones. The ``visibility`` column
        is NOT filtered here — the Python gate decides that.
        """
        if self.db is None:
            return []

        stmt = select(ContextDocument).where(ContextDocument.deleted_at.is_(None))

        if kinds:
            stmt = stmt.where(ContextDocument.kind.in_(list(kinds)))

        # Space-mode: prefilter to public + user-owned + same-space docs.
        # Personal-mode: prefilter to public + user-owned + any-allowed-space.
        # Both cases include visibility='user' scoped docs for this user.
        scope_space_ids: List[UUID] = []
        if space_id is not None:
            scope_space_ids.append(space_id)
        if is_personal and allowed_space_ids:
            scope_space_ids.extend(allowed_space_ids)

        # Build the OR: visibility=public OR owner=user OR space_id IN (...)
        # We keep the conditions permissive — the Python gate does the strict
        # check. A broader read is fine; a too-narrow read would be a bug.
        from sqlalchemy import or_

        or_clauses = [
            ContextDocument.visibility == "public",
            ContextDocument.owner_user_id == user_id,
        ]
        if scope_space_ids:
            or_clauses.append(ContextDocument.space_id.in_(scope_space_ids))
        stmt = stmt.where(or_(*or_clauses))

        stmt = stmt.limit(MAX_PREFILTER_ROWS)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())
