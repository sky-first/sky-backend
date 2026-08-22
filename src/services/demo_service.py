"""Public demo (Cenário B) service.

Provisions a per-visitor sandbox: a User, a Space marked is_demo with
a TTL, a SpaceMember bridge, optional shared dataset Connection, and
issues a normal JWT pair so the FE behaves the same as for an SSO
login. Cleans up expired sandboxes via cleanup_expired_demo_spaces().

Anti-fraud:
  • Cloudflare Turnstile token verified server-side
  • Per-IP signup rate limit (Redis with in-memory fallback)
  • Throwaway email block list (validated in DemoSignupRequest)
  • Returning visitors with the same email get their existing sandbox
    instead of a fresh one — avoids brute-force volume
"""

from __future__ import annotations

import logging
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.core.exceptions import BadRequestError, ForbiddenError
from src.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    refresh_ttl_days,
)
from src.models.agent import Agent, AgentFinding
from src.models.connection import DataConnection
from src.models.enterprise_relationship import EnterpriseRelationship
from src.models.glossary import GlossaryTerm
from src.models.metric import Metric
from src.models.page import Page, PageMember
from src.models.space import Space, SpaceConnection, SpaceMember
from src.models.user import RefreshToken, User
from src.schemas.demo import DemoSignupRequest, DemoSignupResponse
from src.schemas.user import UserResponse
from src.services.agent_conversation_service import post_agent_answer
from src.services.demo_seed_data import GLOSSARY_TERMS, METRICS_DATA, RELATIONSHIPS_DATA

logger = logging.getLogger(__name__)


# ─── Per-IP signup rate limit (Redis if available, memory otherwise) ────────

# In-memory fallback: keyed by IP, holds a list of timestamps. Cleared
# implicitly when entries fall outside the rolling window.
_IP_SIGNUP_HITS: dict[str, list[float]] = defaultdict(list)


def _check_ip_rate_limit(ip: str, limit: int, window_seconds: int = 3600) -> bool:
    """True if under-limit, False if the IP has already hit `limit` signups
    in the trailing `window_seconds`.

    Uses Redis when configured, falls back to a process-local dict otherwise.
    """
    if not ip:
        # Unknown IP — fail-closed for safety.
        return False

    # Redis path
    try:
        import redis  # type: ignore

        if settings.REDIS_URL:
            r = redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=1)
            key = f"demo:signup:ip:{ip}"
            count = r.incr(key)
            if count == 1:
                r.expire(key, window_seconds)
            return int(count) <= limit
    except Exception as exc:  # pragma: no cover — only triggers in dev/no-redis
        logger.debug("demo rate limit Redis unavailable, falling back: %s", exc)

    # Memory fallback
    now = time.time()
    cutoff = now - window_seconds
    hits = [t for t in _IP_SIGNUP_HITS[ip] if t >= cutoff]
    hits.append(now)
    _IP_SIGNUP_HITS[ip] = hits
    return len(hits) <= limit


# ─── Cloudflare Turnstile ───────────────────────────────────────────────────


async def _verify_turnstile(token: str, remoteip: Optional[str]) -> bool:
    """Calls Cloudflare's siteverify. Returns True on a valid token."""
    secret = settings.TURNSTILE_SECRET_KEY
    if not secret:
        # In dev / test we skip verification but log it loudly so a
        # forgotten env in production doesn't silently allow bots through.
        logger.warning(
            "TURNSTILE_SECRET_KEY is empty — captcha verification skipped. "
            "DO NOT deploy demo to public internet without setting it."
        )
        return True

    payload = {"secret": secret, "response": token}
    if remoteip:
        payload["remoteip"] = remoteip

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(settings.TURNSTILE_VERIFY_URL, data=payload)
            if resp.status_code != 200:
                logger.warning("Turnstile siteverify HTTP %s", resp.status_code)
                return False
            data = resp.json()
            return bool(data.get("success"))
    except Exception as exc:
        logger.warning("Turnstile siteverify failed: %s", exc)
        return False


# ─── Universe embeddings auto-seed ──────────────────────────────────────────


def _trigger_universe_embedding_seed(space_id: str) -> None:
    """Fires the AI service's per-Space seed-embeddings endpoint without
    blocking the caller.

    The Universe Intelligence v2 canvas reads from the AI service's
    ``embeddings`` table. Until this hook landed, demo Spaces minted at
    signup had zero embeddings for metrics / glossary / relationships /
    agents — only the tables from the shared dataset connection (which
    were pre-embedded out-of-band) showed up. Visitors landed on a
    half-empty constellation for their first 30s on the platform.

    Implementation: ``asyncio.create_task`` so the POST runs in the
    background of the request's event loop. The response to the user
    returns immediately; the seed catches up within a few seconds.
    Errors are logged, never re-raised — if the AI service is down,
    the signup still succeeds and an admin can backfill manually via
    the ``seed_knowledge_embeddings.py`` CLI script.
    """
    import asyncio

    base = (settings.AI_SERVICE_URL or "http://localhost:8001").rstrip("/")
    url = f"{base}/spaces/{space_id}/seed-embeddings"

    async def _fire() -> None:
        try:
            # 90s caps the OpenAI batch — bigger Spaces (org-scope demos
            # with hundreds of metrics) might run slower; we never want
            # to retry mid-flight because the script's idempotent skip
            # keeps a partial run safe to re-seed later.
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(url)
                if resp.status_code >= 400:
                    logger.warning(
                        "universe_embedding_seed_failed space_id=%s status=%s body=%s",
                        space_id,
                        resp.status_code,
                        resp.text[:200],
                    )
                else:
                    logger.info(
                        "universe_embedding_seed_ok space_id=%s",
                        space_id,
                    )
        except Exception as exc:
            logger.warning(
                "universe_embedding_seed_unreachable space_id=%s err=%s",
                space_id,
                exc,
            )

    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_fire())
    except RuntimeError:
        # No running loop (e.g. called from a sync test). Run blocking
        # rather than skipping — better to slow a single test than to
        # silently lose the seed in production.
        asyncio.run(_fire())


# ─── Signup ─────────────────────────────────────────────────────────────────


class DemoService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _parse_connection_ids() -> list[UUID]:
        """Resolve the list of dataset connection UUIDs to wire onto a new
        demo Space. Reads DEMO_DATASET_CONNECTION_IDS first (CSV); falls
        back to the legacy DEMO_DATASET_CONNECTION_ID single value.
        Invalid entries are logged and skipped so one bad UUID doesn't
        break the entire signup flow.
        """
        plural = (getattr(settings, "DEMO_DATASET_CONNECTION_IDS", "") or "").strip()
        if plural:
            uuids: list[UUID] = []
            for raw in plural.split(","):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    uuids.append(UUID(raw))
                except (ValueError, TypeError):
                    logger.warning(
                        "DEMO_DATASET_CONNECTION_IDS contains invalid UUID %r — skipping.",
                        raw,
                    )
            return uuids

        singular = (settings.DEMO_DATASET_CONNECTION_ID or "").strip()
        if singular:
            try:
                return [UUID(singular)]
            except (ValueError, TypeError):
                logger.warning(
                    "DEMO_DATASET_CONNECTION_ID is set but not a valid UUID — skipping wire-up."
                )
        return []

    async def _find_sibling_demo_space(self, email_domain: str) -> Optional[Space]:
        """Return the active demo Space whose owner shares ``email_domain``.

        Used by item D (same-domain grouping): the first signup from
        @acme.com mints the Space and becomes owner; later signups
        from @acme.com join that Space instead of creating new ones.

        Returns None if:
          - email_domain is empty
          - no active (TTL not expired) demo Space exists for that domain
          - the only matching Space is owned by the calling user's own row
            (caller's been moved to _issue_returning before reaching here)
        """
        if not email_domain or "." not in email_domain:
            return None

        now = datetime.now(timezone.utc)
        # Match via SQL on User.email LIKE '%@<domain>' joined to
        # Space.created_by. The deleted_at filter on Space is implicit
        # via the demo_expires_at > now check (cron CASCADE-deletes
        # expired sandboxes anyway).
        q = await self.db.execute(
            select(Space)
            .join(User, User.id == Space.created_by)
            .where(
                Space.is_demo.is_(True),
                Space.demo_expires_at > now,
                User.is_demo.is_(True),
                User.email.like(f"%@{email_domain}"),
            )
            .order_by(Space.created_at.asc())  # oldest sibling = canonical
            .limit(1)
        )
        return q.scalar_one_or_none()

    async def _join_sibling_demo_space(
        self,
        *,
        payload: DemoSignupRequest,
        email_norm: str,
        sibling_space: Space,
        client_ip: Optional[str],
    ) -> DemoSignupResponse:
        """Mint a new User and attach them as an editor of an existing
        same-domain demo Space. Reuses the parent Space's TTL so the
        whole org's sandbox expires together. Logs loudly so the
        lead-gen pipeline can pick the event up.
        """
        # The new visitor's TTL = the sibling Space's TTL (same expiry
        # for the whole company so the sandbox doesn't get split into
        # an awkward "yours expired but theirs didn't" state).
        expires_at = sibling_space.demo_expires_at or (
            datetime.now(timezone.utc) + timedelta(days=max(1, int(settings.DEMO_TTL_DAYS)))
        )

        user = User(
            id=uuid4(),
            email=email_norm,
            password_hash=get_password_hash(secrets.token_urlsafe(32)),
            name=payload.name,
            role="user",
            email_verified=True,
            is_demo=True,
            demo_expires_at=expires_at,
            preferences={
                "demo_company": payload.company,
                "demo_role": payload.role or "",
                "demo_signup_ip": client_ip or "",
                "demo_joined_existing_space": str(sibling_space.id),
            },
        )
        self.db.add(user)
        await self.db.flush()

        # Editor role (Phase 7 vocabulary): full content writes
        # (dashboards, widgets, agents, AI) but cannot manage members,
        # edit Space settings, or delete crews. Owner of the demo
        # Space can promote them via the standard members endpoint.
        self.db.add(
            SpaceMember(
                id=uuid4(),
                space_id=sibling_space.id,
                user_id=user.id,
                role="editor",
            )
        )

        # Backfill the Knowledge seed if the sibling Space was minted
        # before the seed shipped — idempotent so the original owner's
        # Space stays untouched when it's already hydrated.
        await self._seed_demo_context(sibling_space, user)
        # Same idempotent backfill for the demo agents seed — keeps the
        # joiner's Pulse pill in sync with what a fresh signup would have.
        await self._seed_demo_agents(sibling_space, user)
        # Findings backfill: gives the Pulse panel pre-canned insights
        # so the joiner doesn't land on an empty "All clear" state.
        await self._seed_demo_findings(sibling_space)

        # Default Personal page first (see fresh-signup branch — the
        # owner-by-id idempotency in ensure_default_page_and_space
        # forces this to run before the Space-scoped seed below).
        from src.services.onboarding_service import ensure_default_page_and_space

        await ensure_default_page_and_space(self.db, user)

        # Default Space page named "{company} Board" — idempotent. The
        # joiner only triggers a create on Spaces that don't yet have
        # a Space-scoped page (older sandboxes seeded before this
        # helper shipped); the original signup already seeded it.
        await self._seed_demo_space_page(sibling_space, user, payload.company)

        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(sibling_space)

        # Fire-and-forget: hydrate the AI service's `embeddings` table
        # for this Space so the Universe canvas shows the full
        # constellation on first load. Sibling-join uses the original
        # owner's Space; if those embeddings already exist this is a
        # cheap idempotent no-op.
        _trigger_universe_embedding_seed(str(sibling_space.id))

        logger.info(
            "demo_same_domain_join space_id=%s owner_id=%s new_user_id=%s " "email=%s domain=%s",
            sibling_space.id,
            sibling_space.created_by,
            user.id,
            email_norm,
            email_norm.split("@", 1)[1],
        )

        # Welcome email also fires for same-domain joiners. Lucas's
        # 2026-04-29 review caught that gustavo.mendonca@thedatafirst.com
        # got the Slack signup ping but never an email — the cold-only
        # email gate was the bug. Same-domain joiners ARE prospects too,
        # they just landed via a teammate. Reuses the same template
        # since the message ("your sandbox is live, ask this question")
        # applies identically; later we can split into a "your colleague
        # invited you" variant if Lucas wants.
        from src.services.demo_email_service import send_demo_welcome_email

        await send_demo_welcome_email(
            name=user.name,
            email=user.email,
            company=payload.company,
            expires_at=expires_at,
        )

        return await self._issue_response(
            user,
            sibling_space,
            expires_at,
            is_returning=False,
        )

    async def _ensure_dataset_connections(self, space: Space) -> int:
        """Idempotently bind the configured demo dataset connections to ``space``.

        Reads ``DEMO_DATASET_CONNECTION_IDS`` (or the legacy singular)
        and, for each UUID that:
          (a) exists as a row in ``data_connections`` (so the FK insert
              won't 23503 on us), and
          (b) is not already bridged to this Space,
        adds a ``SpaceConnection`` row. Missing UUIDs are logged loudly
        — operationally that means the seed script wasn't run against
        this DB, or the env var was edited and points at a stale ID.

        After binding, fires AI-service ``discover_connection`` once per
        newly bound (connection, space) pair so the embeddings are
        re-indexed against the demo guest's space — without that step the
        AI answers "404 No metadata found" because the seed script
        indexed against the seed-admin's space, not the visitor's.

        Returns the number of rows added (0 on a no-op).

        Called from both ``_issue_new`` (initial provision) and
        ``_issue_returning`` (backfill for Spaces created before the env
        var was deployed). The session is NOT committed here — caller
        commits as part of its own transaction.
        """
        wanted = self._parse_connection_ids()
        if not wanted:
            # Sprint 1.17 round 6 (Lucas 2026-05-15): "cade os agentes? cade
            # as conexoes?" — silent no-op meant a fresh demo signup
            # landed on an empty Sources panel. Now we log loudly so the
            # operator sees the missing env var in the BE logs and can
            # set DEMO_DATASET_CONNECTION_IDS / DEMO_DATASET_CONNECTION_ID
            # without having to read the source code to know what's
            # blocking the seed.
            logger.warning(
                "demo_dataset_connection_ids missing — both "
                "DEMO_DATASET_CONNECTION_IDS and DEMO_DATASET_CONNECTION_ID "
                "are empty/invalid. Set them to a CSV of data_connection "
                "UUIDs (run scripts/seed_demo_connections.py first to mint "
                "them, then copy the IDs into your env). Demo space %s "
                "will end up with NO connections.",
                space.id,
            )
            return 0

        # 1. Filter to UUIDs that actually exist in data_connections.
        existing_q = await self.db.execute(
            select(DataConnection.id).where(DataConnection.id.in_(wanted))
        )
        existing_ids: set[UUID] = {row for row in existing_q.scalars().all()}
        missing = [str(u) for u in wanted if u not in existing_ids]
        if missing:
            logger.warning(
                "demo_dataset_connection_ids reference missing data_connections "
                "rows — these IDs will be skipped. Did the seed script run "
                "against this DB? missing=%s",
                missing,
            )
        if not existing_ids:
            logger.warning(
                "demo_dataset_connection_ids ALL stale — none of %d "
                "configured UUIDs exist in data_connections. Demo space "
                "%s will end up with NO connections. Re-run "
                "scripts/seed_demo_connections.py and update the env var.",
                len(wanted),
                space.id,
            )
            return 0

        # 2. Skip the ones already bound to avoid duplicate-key errors.
        already_q = await self.db.execute(
            select(SpaceConnection.connection_id).where(
                SpaceConnection.space_id == space.id,
                SpaceConnection.connection_id.in_(existing_ids),
            )
        )
        already: set[UUID] = {row for row in already_q.scalars().all()}

        added_ids: list[UUID] = []
        for conn_uuid in existing_ids:
            if conn_uuid in already:
                continue
            self.db.add(SpaceConnection(space_id=space.id, connection_id=conn_uuid))
            added_ids.append(conn_uuid)

        if added_ids:
            logger.info(
                "demo_space_connections_bound space_id=%s added=%d total_wanted=%d",
                space.id,
                len(added_ids),
                len(wanted),
            )

        # 3. Trigger AI-service discovery for SHARED indexing — pass
        # space_id=None so TableMetadata and EmbeddingRecord land with
        # space_id IS NULL. Lucas's 2026-05-05 review caught the original
        # behaviour: we were calling discover with the visitor's Space ID,
        # which made the AI re-ingest + re-embed the same demo dataset
        # once per visitor. The RAG retrieval filter
        # (see sky-poc-ai/core/rag/vector_store.py:_build_embedding_base_query)
        # already matches embeddings whose space_id IS NULL OR equals the
        # caller — so a single shared index is enough for every demo
        # Space that has this connection bridged.
        #
        # Why we still call this on every signup that adds new bridge
        # rows: ingest_from_connection_metadata_cache is idempotent
        # (DELETE+INSERT keyed by space_id IS NULL + connection_id), so
        # repeated calls just no-op the data. The AI request itself
        # stays in the background so signup latency is unaffected.
        if added_ids:
            from src.ai.http_client import AIServiceHTTPClient

            ai_client = AIServiceHTTPClient()
            for conn_uuid in added_ids:
                try:
                    await ai_client.discover_connection(
                        connection_id=str(conn_uuid),
                        # Sentinel: explicit "shared/global" intent.
                        # Footgun-safer than passing None — any caller
                        # that forgets the kwarg now hits ValueError
                        # instead of accidentally indexing a private
                        # connection as globally-readable.
                        space_id=AIServiceHTTPClient.SHARED_INDEX,
                        run_in_background=True,
                    )
                    logger.info(
                        "demo_ai_discover_dispatched_shared conn=%s",
                        conn_uuid,
                    )
                except Exception as exc:
                    logger.warning(
                        "demo_ai_discover_failed conn=%s err=%s",
                        conn_uuid,
                        exc,
                    )

        # Force the pending SpaceConnection rows to flush before returning.
        # AsyncSessionLocal runs with autoflush=False, so the inserts above
        # only become visible to subsequent SELECTs on this session after an
        # explicit flush. Without this, _seed_demo_agents() runs next in the
        # same transaction and reads zero rows from space_connections —
        # primary_conn falls back to None and the three seeded agents land
        # with connection_ids=[]. POST /agents/{id}/run/stream then 400s on
        # every "Run now" because it requires at least one connection.
        # Always flush — not just when rows were added. If all connections
        # were already bound in a previous call within the same transaction,
        # added_ids is empty and the conditional flush was skipped, leaving
        # _seed_demo_agents() unable to read those rows (autoflush=False).
        await self.db.flush()

        return len(added_ids)

    async def _seed_demo_context(self, space: Space, user: User) -> dict[str, int]:
        """Idempotently hydrate ``space`` with the baseline Knowledge content
        every demo visitor expects: Glossary terms, Metrics, and Enterprise
        Relationships connecting them.

        Without this, a fresh demo Space lands with five wired Connections
        but every Knowledge / Relationships sun-category orbiting Universe
        Intelligence reads count=0 — the visitor sees an empty graph and
        the AI has no Glossary/Metric anchor to resolve "what's MRR?".

        Idempotency: each entity is keyed by its natural identifier within
        the Space scope (term / slug / name) so re-running on a Space that
        was partially seeded by a prior signup attempt is a safe no-op.

        The session is NOT committed here — caller commits as part of its
        own transaction (alongside the User/Space/Member writes).

        Returns a counts dict for telemetry: ``{glossary, metrics, relationships}``.
        """
        # 1. Glossary — keyed on (space_id, term).
        existing_terms_q = await self.db.execute(
            select(GlossaryTerm.term).where(GlossaryTerm.space_id == space.id)
        )
        existing_terms = {row for row in existing_terms_q.scalars().all()}
        glossary_added = 0
        # Map term → id so the Relationships pass below can resolve targets
        # even on a re-run that finds them already inserted.
        term_to_id: dict[str, UUID] = {}
        for term, definition in GLOSSARY_TERMS:
            if term in existing_terms:
                continue
            row = GlossaryTerm(
                id=uuid4(),
                term=term,
                definition=definition,
                scope="space",
                scope_id=space.id,
                space_id=space.id,  # legacy column kept in sync
                owner_user_id=user.id,
                created_by_user_id=user.id,
            )
            self.db.add(row)
            term_to_id[term] = row.id
            glossary_added += 1

        # Re-fetch to capture rows that were already in place from a
        # previous partial seed (so the Relationships pass can still
        # resolve target_id). Cheap because Glossary is small.
        if glossary_added > 0 or not term_to_id:
            await self.db.flush()
            term_q = await self.db.execute(
                select(GlossaryTerm.id, GlossaryTerm.term).where(GlossaryTerm.space_id == space.id)
            )
            for row_id, row_term in term_q.all():
                term_to_id[row_term] = row_id

        # 2. Metrics — keyed on (scope='space', scope_id, slug).
        existing_metric_q = await self.db.execute(
            select(Metric.slug).where(
                Metric.scope == "space",
                Metric.scope_id == space.id,
            )
        )
        existing_slugs = {row for row in existing_metric_q.scalars().all()}
        metrics_added = 0
        for slug, name, description, unit, aggregation in METRICS_DATA:
            if slug in existing_slugs:
                continue
            self.db.add(
                Metric(
                    id=uuid4(),
                    name=name,
                    slug=slug,
                    description=description,
                    scope="space",
                    scope_id=space.id,
                    status="active",
                    unit=unit,
                    aggregation=aggregation,
                    owner_user_id=user.id,
                    created_by_user_id=user.id,
                )
            )
            metrics_added += 1

        # 3. Enterprise Relationships — keyed on (scope, scope_id, name).
        # The seed wires Glossary → Glossary so both endpoints exist as
        # real entities the FE can navigate to.
        existing_rel_q = await self.db.execute(
            select(EnterpriseRelationship.name).where(
                EnterpriseRelationship.scope == "space",
                EnterpriseRelationship.scope_id == space.id,
            )
        )
        existing_rel_names = {row for row in existing_rel_q.scalars().all()}
        relationships_added = 0
        for source_term, target_term, rel_type, description in RELATIONSHIPS_DATA:
            rel_name = f"{source_term} → {target_term}"
            if rel_name in existing_rel_names:
                continue
            source_id = term_to_id.get(source_term)
            target_id = term_to_id.get(target_term)
            if source_id is None or target_id is None:
                # Defensive — should never trigger because Glossary was
                # written above, but skip rather than corrupt the row.
                logger.warning(
                    "demo_seed: skipping relationship %s — missing glossary anchor",
                    rel_name,
                )
                continue
            self.db.add(
                EnterpriseRelationship(
                    id=uuid4(),
                    name=rel_name,
                    description=description,
                    sources=[{"id": str(source_id), "type": "glossary_term"}],
                    target_id=str(target_id),
                    target_type="glossary_term",
                    relationship_type=rel_type,
                    scope="space",
                    scope_id=space.id,
                    created_by=user.id,
                )
            )
            relationships_added += 1

        if glossary_added or metrics_added or relationships_added:
            logger.info(
                "demo_context_seeded space_id=%s glossary=%d metrics=%d relationships=%d",
                space.id,
                glossary_added,
                metrics_added,
                relationships_added,
            )
        return {
            "glossary": glossary_added,
            "metrics": metrics_added,
            "relationships": relationships_added,
        }

    async def _seed_demo_space_page(self, space: Space, user: User, company: str) -> int:
        """Create a default Space-scoped Page named "{company} Board".

        Without this, switching from Personal to the demo Space (or to a
        Crew inside it) lands the user on an empty page picker — either
        blank or carrying whatever placeholder the FE falls back to.
        Lucas's UX brief: "deve aparecer com o nome da empresa, ex.
        Microsoft Board". Naming the seeded page after the visitor's
        company makes the topbar selector immediately recognisable.

        Idempotent: skips if any Space-scoped page already exists for
        this Space (the joiner case in _join_sibling_demo_space hits
        this branch — original signup already seeded the page).

        Returns the number of pages added (0 on no-op, 1 on create).
        """
        from sqlalchemy import select as _select

        existing_q = await self.db.execute(
            _select(Page.id).where(Page.space_id == space.id, Page.deleted_at.is_(None)).limit(1)
        )
        if existing_q.scalar_one_or_none() is not None:
            return 0

        company_label = (company or "").strip() or "Demo"
        # Naming convention requested by Lucas (2026-05-08): use
        # "{company} Board's" — same pattern Personal mode uses
        # ("{first_name} Board's"). Truncate at 240 chars so the
        # " Board's" suffix never trips the 255-varchar limit on
        # pages.name.
        page_name = f"{company_label[:240]} Board's"

        page = Page(
            id=uuid4(),
            name=page_name,
            description="Default board for the demo Space — pre-seeded so the page picker is never empty.",
            type="team",
            color="#3B82F6",
            icon=None,
            owner_id=user.id,
            space_id=space.id,
            crew_id=None,
            is_active=True,
        )
        self.db.add(page)
        await self.db.flush()

        self.db.add(
            PageMember(
                id=uuid4(),
                page_id=page.id,
                user_id=user.id,
                role="owner",
            )
        )

        logger.info(
            "demo_space_page_seeded space_id=%s page_id=%s name=%r",
            space.id,
            page.id,
            page_name,
        )
        return 1

    async def _seed_demo_agents(self, space: Space, user: User) -> int:
        """Create 10 ready-to-run agents on a fresh demo Space.

        Lucas's 2026-05-13 brief: a new demo account should land with a
        rich agent constellation so the Pulse panel reads as "already
        watching the business" the moment the user logs in. The mix
        mirrors the B2B exec tier model:

          * 1 × L3 (deep, weekly) — cross-domain strategic audit
          * 3 × L2 (standard, daily) — domain monitors
          * 6 × L1 (quick, hourly/daily) — delta detectors

        L1/L2/L3 are encoded on the existing ``depth`` column
        (``quick``/``standard``/``deep``). No schema change required.

        Idempotent: skips entirely if any agent already exists for this
        Space — that keeps returning visitors (and the older 3-agent
        demos) from accidentally collecting duplicates.

        Connection-aware: pins every agent to the first dataset
        Connection bound to the Space so the run-stream endpoint has
        somewhere to query. Returns the number of agents added.
        """
        already_q = await self.db.execute(
            select(Agent.id).where(
                Agent.scope == "space",
                Agent.scope_id == str(space.id),
            )
        )
        if already_q.scalars().first() is not None:
            return 0

        bound_q = await self.db.execute(
            select(SpaceConnection.connection_id).where(SpaceConnection.space_id == space.id)
        )
        bound_conn_ids = list(bound_q.scalars().all())
        primary_conn = bound_conn_ids[0] if bound_conn_ids else None

        # Build a domain-label → connection_id map so each agent is pinned
        # to the right source(s) instead of the generic primary_conn.
        # Keys match the "connections" lists in the seed entries below.
        conn_by_label: dict[str, UUID] = {}
        if bound_conn_ids:
            label_q = await self.db.execute(
                select(DataConnection.id, DataConnection.name)
                .where(DataConnection.id.in_(bound_conn_ids))
            )
            for cid, cname in label_q.all():
                n = (cname or "").lower()
                if "sales" in n or "crm" in n:
                    conn_by_label["sales"] = cid
                if "finance" in n:
                    conn_by_label["finance"] = cid
                if "marketing" in n:
                    conn_by_label["marketing"] = cid
                if "web" in n or "analytics" in n:
                    conn_by_label["web"] = cid
                if "product" in n or "usage" in n:
                    conn_by_label["product"] = cid

        def _conns(*labels: str) -> list[UUID]:
            """Return connection UUIDs for the requested labels.
            Falls back to primary_conn so agents always have at least one."""
            result = [conn_by_label[lbl] for lbl in labels if lbl in conn_by_label]
            return result if result else ([primary_conn] if primary_conn else [])

        # Tier-coded seed list. ``depth`` is the canonical L1/L2/L3 marker
        # in the data model — the FE reads it to render tier badges and
        # the worker uses it to gate execution budget. Frequency is set
        # per tier (L1 cheap+fast, L3 expensive+weekly) so the demo's
        # beat consumption stays demo-friendly.
        #
        # ``connections`` lists which domain labels to wire — translated to
        # real UUIDs by _conns(). Focus texts are direct, answerable SQL
        # questions (not multi-objective directives) so the AI orchestrator
        # can map them to a specific table without ambiguity.
        seeds: list[dict] = [
            # ── 1 × L3 (deep) ───────────────────────────────────────
            {
                "name": "Strategic Health Audit",
                "archetype": "strategy_tracker",
                "depth": "deep",
                "frequency": "weekly",
                "connections": _conns("finance", "product"),
                "focus": (
                    "Show a summary: (1) total MRR from active subscriptions "
                    "grouped by plan type (starter, pro, enterprise), and "
                    "(2) count of accounts by health risk_level (churn, risk, "
                    "watch, healthy) from account_health. Return both results."
                ),
            },
            # ── 3 × L2 (standard) ───────────────────────────────────
            {
                "name": "Revenue Pulse",
                "archetype": "growth_intelligence",
                "depth": "standard",
                "frequency": "daily",
                "connections": _conns("finance", "sales"),
                "focus": (
                    "What is the current total MRR from active subscriptions? "
                    "Also show total open pipeline value grouped by stage "
                    "(prospect, qualified, negotiation) and the win rate from "
                    "closed deals."
                ),
            },
            {
                "name": "Customer Health Watch",
                "archetype": "risk_radar",
                "depth": "standard",
                "frequency": "daily",
                "connections": _conns("product", "sales"),
                "focus": (
                    "Show all accounts with risk_level of churn or risk in "
                    "account_health. Include their health score, seats used "
                    "versus seats paid, and last login date. Also show accounts "
                    "with no last_login_at."
                ),
            },
            {
                "name": "Operations Radar",
                "archetype": "operations_monitor",
                "depth": "standard",
                "frequency": "daily",
                "connections": _conns("product"),
                "focus": (
                    "Show accounts where seats_used divided by seats_paid is "
                    "below 0.5 (underutilization). Also show accounts where "
                    "last_login_at is NULL or older than 30 days. Include "
                    "account_id, score, and risk_level for each."
                ),
            },
            # ── 5 × L1 (quick) ──────────────────────────────────────
            # One demo agent slot is intentionally left free: the demo seeds
            # 9 agents against a DEMO_MAX_AGENTS_PER_USER cap of 10 so visitors
            # can still create at least one agent of their own.
            {
                "name": "Pipeline Velocity Delta",
                "archetype": "growth_intelligence",
                "depth": "quick",
                "frequency": "daily",
                "connections": _conns("sales"),
                "focus": (
                    "How many open deals (prospect, qualified, negotiation "
                    "stages) are there and what is the total pipeline value "
                    "per stage? Show average deal size and count by stage."
                ),
            },
            {
                "name": "Support Ticket Spike",
                "archetype": "operations_monitor",
                "depth": "quick",
                "frequency": "daily",
                "connections": _conns("product"),
                "focus": (
                    "From product_usage.feature_adoption, show average "
                    "times_used_30d per feature_name and count of accounts "
                    "where times_used_30d is below 50. Do not apply any date "
                    "filter — times_used_30d is already a pre-computed 30-day "
                    "metric. Rank features from least used to most used. "
                    "This identifies which product areas cause the most "
                    "customer friction."
                ),
            },
            {
                "name": "Payment Failure Tracker",
                "archetype": "risk_radar",
                "depth": "quick",
                "frequency": "daily",
                "connections": _conns("finance"),
                "focus": (
                    "Show all invoices with status overdue or sent. How many "
                    "are there and what is the total amount unpaid? Show count "
                    "and sum grouped by status."
                ),
            },
            {
                "name": "Sign-up Anomaly",
                "archetype": "growth_intelligence",
                "depth": "quick",
                "frequency": "daily",
                "connections": _conns("web", "marketing"),
                "focus": (
                    "How many signup events occurred in the web analytics events "
                    "table? Show counts by month and by UTM source from sessions. "
                    "Also show total leads by source from the marketing leads table."
                ),
            },
            {
                "name": "Login Failure Watch",
                "archetype": "risk_radar",
                "depth": "quick",
                "frequency": "daily",
                "connections": _conns("web"),
                "focus": (
                    "Show session volume by week from web_analytics.sessions "
                    "(count of started_at per week) and average pages_viewed "
                    "per session. Flag weeks where session count drops more "
                    "than 20% compared to the previous week. Also show the "
                    "top 3 pages (by page_path) visited in web_analytics."
                    "events grouped by page_path."
                ),
            },
        ]

        for seed in seeds:
            agent = Agent(
                id=uuid4(),
                name=seed["name"],
                archetype=seed["archetype"],
                scope="space",
                scope_id=str(space.id),
                scope_name=space.name,
                status="active",
                monitor_type="question",
                focus=seed["focus"],
                frequency=seed["frequency"],
                depth=seed["depth"],
                connection_ids=seed["connections"],
                created_by=user.id,
            )
            self.db.add(agent)

        logger.info(
            "demo_agents_seeded space_id=%s count=%d primary_conn=%s",
            space.id,
            len(seeds),
            primary_conn,
        )
        return len(seeds)

    async def _seed_demo_findings(self, space: Space) -> int:
        """Pre-populate one canned finding per demo agent.

        Lucas's 2026-05-13 brief: the Pulse panel needs to look "alive"
        the moment a demo visitor lands — empty cards kill the pitch.
        We can't run the real agents at signup (they'd hammer OpenAI and
        block the request) so we mint hand-crafted findings keyed off
        each agent's archetype. Severity / type mix is intentional:
        risks dominate L1/L2 so the eye lands on red rails first, the
        L3 surfaces a board-level summary insight.

        Idempotent: skips if any of this Space's agents already carry
        findings. Connection-aware: stamps the same primary_connection
        used by the agents so the Sources tab resolves to a real name.
        Returns the number of findings inserted.
        """
        agents_q = await self.db.execute(
            select(Agent).where(
                Agent.scope == "space",
                Agent.scope_id == str(space.id),
            )
        )
        agents_list = list(agents_q.scalars().all())
        if not agents_list:
            return 0

        # Already-seeded check: if ANY of these agents has a finding,
        # bail. Prevents re-runs from minting duplicates.
        agent_ids = [a.id for a in agents_list]
        existing_q = await self.db.execute(
            select(AgentFinding.id).where(AgentFinding.agent_id.in_(agent_ids)).limit(1)
        )
        if existing_q.scalars().first() is not None:
            return 0

        bound_q = await self.db.execute(
            select(SpaceConnection.connection_id).where(SpaceConnection.space_id == space.id)
        )
        bound_conn_ids = list(bound_q.scalars().all())
        primary_conn = bound_conn_ids[0] if bound_conn_ids else None

        # Index agents by name for direct lookup; this is more readable
        # than positional indexing into the seed list, and survives any
        # future reordering of the agent seeds above.
        by_name = {a.name: a for a in agents_list}

        # One canned finding per seeded agent. Each entry is keyed by
        # the agent's name (must match _seed_demo_agents exactly). When
        # an agent isn't present (e.g. partial seed, future renames)
        # we silently skip rather than KeyError.
        canned: dict[str, dict] = {
            "Strategic Health Audit": {
                "type": "insight",
                "severity": "high",
                "viz_kind": "line",
                "title": "Q-to-date health snapshot: revenue +12%, churn 4.8%, ops SLA 98.4%",
                "description": (
                    "Cross-domain audit consolidates Revenue Pulse, Customer Health "
                    "Watch and Operations Radar over the last 7 days. Net: growth "
                    "is healthy but customer-tier concentration is approaching the "
                    "guardrail. The next quarterly review should debate dependency "
                    "on the top 5 accounts."
                ),
                "recommendation": (
                    "Brief the leadership team on the top-5 ARR concentration "
                    "before contract renewals open in 6 weeks."
                ),
                "confidence": 0.91,
            },
            "Revenue Pulse": {
                "type": "opportunity",
                "severity": "medium",
                "viz_kind": "callout",
                "title": "Pipeline velocity up 18% WoW, driven by 3 mid-market deals",
                "description": (
                    "Stage-to-close time on Series B-stage prospects dropped from "
                    "34d to 28d week-over-week. Three accounts (Tessera, Lumen "
                    "Health, Northwind) account for 71% of the swing. Win-rate on "
                    "the same cohort stable at 32%."
                ),
                "recommendation": (
                    "Run a post-mortem on the Tessera deal — its 11-day close is "
                    "an outlier worth turning into a playbook."
                ),
                "confidence": 0.82,
            },
            "Customer Health Watch": {
                "type": "risk",
                "severity": "high",
                "viz_kind": "area",
                "title": "Acme Corp: NPS down 22 pts, support tickets up 3×",
                "description": (
                    "Acme Corp's monthly NPS dropped from 58 to 36 after the Q1 "
                    "outage. Support volume tripled in the same window. ARR "
                    "exposure: €184k (8-month contract, renewal in 64 days)."
                ),
                "recommendation": (
                    "Schedule a CSM call this week. Offer a service credit and a "
                    "roadmap review to rebuild trust before renewal."
                ),
                "confidence": 0.88,
                # Sprint 1.17 round 3 — every demo finding ships a small
                # `rows` payload so the FE sparkline / chart variant has
                # a series to render. Lucas asked for "cards where the
                # chart actually shows up"; without rows the FE falls
                # back to a text card.
                "rows": {
                    "columns": ["month", "nps"],
                    "data": [
                        ["Nov", 58], ["Dec", 56], ["Jan", 51],
                        ["Feb", 47], ["Mar", 41], ["Apr", 38], ["May", 36],
                    ],
                    "truncated": False,
                },
            },
            "Operations Radar": {
                "type": "risk",
                "severity": "high",
                "viz_kind": "kpi",
                "title": "Payment API p95 latency +340ms over 24h",
                "description": (
                    "p95 climbed from 180ms to 520ms in the last 24h. p99 doubled. "
                    "Error rate stable at 0.2% — the failure mode is slowness, "
                    "not exceptions. Connection pool saturation suspected."
                ),
                "recommendation": (
                    "Page the payments oncall. Increase pool size or roll back "
                    "the connection-handling change shipped on the 12th."
                ),
                "confidence": 0.86,
                "rows": {
                    "columns": ["hour", "p95_ms"],
                    "data": [
                        ["00:00", 180], ["04:00", 195], ["08:00", 220],
                        ["12:00", 280], ["16:00", 360], ["20:00", 460],
                        ["24:00", 520],
                    ],
                    "truncated": False,
                },
            },
            "Pipeline Velocity Delta": {
                "type": "insight",
                "severity": "medium",
                "viz_kind": "bullet_list",
                "title": "Stage 'Negotiation' deal age up 31% — 7 deals stalled >21d",
                "description": (
                    "Average time-in-stage for Negotiation jumped from 12.4 to "
                    "16.3 days. Seven open deals (€312k pipeline) have been in "
                    "Negotiation more than 21 days."
                ),
                "recommendation": (
                    "AE team review of the 7 stalled deals tomorrow. Surface "
                    "common blockers (legal, security, pricing) to GTM ops."
                ),
                "confidence": 0.79,
                "rows": {
                    "columns": ["week", "avg_days"],
                    "data": [
                        ["W-6", 11.8], ["W-5", 12.0], ["W-4", 12.4],
                        ["W-3", 13.2], ["W-2", 14.6], ["W-1", 15.5],
                        ["W-0", 16.3],
                    ],
                    "truncated": False,
                },
            },
            "Support Ticket Spike": {
                "type": "risk",
                "severity": "medium",
                "viz_kind": "pie",
                "title": "Inbound tickets 2.3× hourly baseline — likely related to v4.2 release",
                "description": (
                    "Last hour: 47 tickets vs. 20 baseline (same hour-of-week, "
                    "trailing 4w). 68% mention 'export' or 'CSV'. v4.2 shipped "
                    "the new export pipeline at 09:00 UTC."
                ),
                "recommendation": (
                    "Notify the v4.2 release captain. Consider hot-fix on the "
                    "export pipeline or temporary rollback of the change."
                ),
                "confidence": 0.84,
                "rows": {
                    "columns": ["hour", "tickets"],
                    "data": [
                        ["06:00", 18], ["07:00", 21], ["08:00", 23],
                        ["09:00", 28], ["10:00", 36], ["11:00", 42],
                        ["12:00", 47],
                    ],
                    "truncated": False,
                },
            },
            "Payment Failure Tracker": {
                "type": "risk",
                "severity": "critical",
                "viz_kind": "comparison_kpi",
                "title": "Failed payments doubled in last 4h — €18.4k ARR at risk",
                "description": (
                    "Failed-payment events: 142 in the last 4h vs. 65 baseline. "
                    "Top decline reasons: card_expired (38%), insufficient_funds "
                    "(24%), do_not_honor (19%). 12 accounts affected with active "
                    "subscriptions; €18.4k MRR exposure."
                ),
                "recommendation": (
                    "Trigger the dunning email sequence for the 12 affected "
                    "accounts. Investigate the do_not_honor spike with Stripe."
                ),
                "confidence": 0.93,
                "rows": {
                    "columns": ["hour", "failures"],
                    "data": [
                        ["-6h", 12], ["-5h", 15], ["-4h", 18],
                        ["-3h", 22], ["-2h", 28], ["-1h", 33],
                        ["now", 42],
                    ],
                    "truncated": False,
                },
            },
            "Sign-up Anomaly": {
                "type": "opportunity",
                "severity": "low",
                "viz_kind": "big_number",
                "title": "Organic channel sign-ups +47% (z = 3.1) — possible PR mention",
                "description": (
                    "Hourly organic sign-ups jumped from 22 to 32 (mean over "
                    "trailing 14d, σ = 3.2). UTM-less landings driving the lift. "
                    "Press monitor flagged a TechCrunch citation 90 min before "
                    "the surge."
                ),
                "recommendation": (
                    "Marketing: confirm the TechCrunch attribution and amplify on "
                    "LinkedIn while the wave is fresh."
                ),
                "confidence": 0.71,
                "rows": {
                    "columns": ["hour", "signups"],
                    "data": [
                        ["-6h", 18], ["-5h", 21], ["-4h", 22],
                        ["-3h", 24], ["-2h", 27], ["-1h", 30],
                        ["now", 32],
                    ],
                    "truncated": False,
                },
            },
            "Login Failure Watch": {
                "type": "insight",
                "severity": "low",
                "viz_kind": "bar",
                "title": "Auth failure rate stable at 0.8% — no anomaly this hour",
                "description": (
                    "Failed-login events: 14 in the last hour vs. 13 baseline. "
                    "All within healthy z-score range (|z| < 1). No password-"
                    "spraying signature. Continuing to monitor."
                ),
                "confidence": 0.95,
                "rows": {
                    "columns": ["hour", "failures"],
                    "data": [
                        ["-6h", 13], ["-5h", 14], ["-4h", 12],
                        ["-3h", 15], ["-2h", 13], ["-1h", 14],
                        ["now", 14],
                    ],
                    "truncated": False,
                },
            },
        }

        # Insert findings + bump the parent agent's last_execution_at /
        # executions_this_month so the FE renders the agent as "ran
        # recently" instead of "Never". We don't create AgentExecution
        # rows — the canned data is hand-crafted, not a real run.
        now = datetime.now(timezone.utc)
        inserted = 0
        for name, payload in canned.items():
            agent = by_name.get(name)
            if agent is None:
                continue
            finding = AgentFinding(
                id=uuid4(),
                agent_id=agent.id,
                type=payload["type"],
                severity=payload["severity"],
                title=payload["title"],
                description=payload["description"],
                recommendation=payload.get("recommendation"),
                confidence=payload.get("confidence"),
                connection_id=primary_conn,
                # Sprint 1.17 round 3 — chart rows attached so the FE
                # sparkline renders on the agent insight card. Without
                # this the card falls back to a text layout.
                rows=payload.get("rows"),
                # Sprint 1.17 round 5 — viz hint tells the Pulse FE
                # which card variant + widget kind to render so the
                # masonry has the variety Lucas asked for AND the
                # "Add to page" flow lands a consistent widget.
                viz_kind=payload.get("viz_kind"),
                dismissed=False,
            )
            self.db.add(finding)
            agent.last_execution_at = now
            agent.executions_this_month = (agent.executions_this_month or 0) + 1
            inserted += 1

            # O achado de demonstração também vai para a conversa do agente.
            #
            # Sem isto, os achados semeados eram os ÚNICOS sem fio: um insight
            # é uma conversa, e tocar-lhes caía num ecrã de detalhe sem saída,
            # exactamente nos achados que a demonstração existe para mostrar.
            #
            # `post_agent_answer` abre a conversa à primeira vez e reutiliza-a
            # daí em diante, portanto os vários achados do mesmo agente ficam
            # no mesmo fio — que é o histórico que se quer demonstrar.
            try:
                await self.db.flush()  # precisa do id para o ligar à mensagem
                await post_agent_answer(
                    self.db,
                    agent=agent,
                    answer=payload["description"],
                    finding_id=finding.id,
                )
            except Exception as exc:  # noqa: BLE001
                # A semente não pode falhar por causa disto: o achado já lá
                # está, e uma demonstração sem fio é melhor do que nenhuma.
                logger.warning(
                    "demo_finding_sem_conversa agent=%s erro=%s", agent.id, exc
                )

        logger.info(
            "demo_findings_seeded space_id=%s count=%d",
            space.id,
            inserted,
        )
        return inserted

    async def signup(
        self,
        payload: DemoSignupRequest,
        client_ip: Optional[str],
        user_agent: Optional[str] = None,
    ) -> DemoSignupResponse:
        if not settings.DEMO_ENABLED:
            raise ForbiddenError("Public demo is currently disabled.")

        ok = _check_ip_rate_limit(
            ip=client_ip or "unknown",
            limit=settings.DEMO_RATE_LIMIT_PER_IP_PER_HOUR,
        )
        if not ok:
            raise BadRequestError(
                "Too many signups from this network in the last hour. Try again later."
            )

        captcha_ok = await _verify_turnstile(payload.turnstile_token, client_ip)
        if not captcha_ok:
            raise BadRequestError("Captcha verification failed. Please refresh and try again.")

        email_norm = payload.email.lower().strip()
        email_domain = email_norm.split("@", 1)[1] if "@" in email_norm else ""

        # Returning visitor: same email → return their existing sandbox.
        existing = await self.db.execute(select(User).where(User.email == email_norm))
        existing_user: Optional[User] = existing.scalar_one_or_none()
        if existing_user is not None:
            if not existing_user.is_demo:
                # Email is already a real (SSO) user — refuse to mint a
                # demo sandbox under a real account.
                raise BadRequestError(
                    "This email is already registered. Please sign in via SSO instead."
                )
            return await self._issue_returning(existing_user, user_agent, client_ip)

        # Same-domain grouping (D): a colleague from the same company
        # already has a demo sandbox? Bind this new user as a member of
        # the SAME Space instead of creating a new one. Pre-A1 behavior
        # was "every email = new sandbox" which fragmented teams across
        # parallel demos and made the same-org collaboration story
        # impossible. Now: first signup mints the Space + becomes
        # owner; subsequent same-domain signups join as editor
        # (full content access, no member/space/connection management).
        # Owner can promote later if needed.
        sibling_space = await self._find_sibling_demo_space(email_domain)
        if sibling_space is not None:
            return await self._join_sibling_demo_space(
                payload=payload,
                email_norm=email_norm,
                sibling_space=sibling_space,
                client_ip=client_ip,
            )

        # Fresh sandbox.
        ttl_days = max(1, int(settings.DEMO_TTL_DAYS))
        expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)

        # User row — random placeholder password so /auth/login refuses
        # this account (only the demo JWT works).
        user = User(
            id=uuid4(),
            email=email_norm,
            password_hash=get_password_hash(secrets.token_urlsafe(32)),
            name=payload.name,
            role="user",
            email_verified=True,
            is_demo=True,
            demo_expires_at=expires_at,
            preferences={
                "demo_company": payload.company,
                "demo_role": payload.role or "",
                "demo_signup_ip": client_ip or "",
            },
        )
        self.db.add(user)
        await self.db.flush()

        # Space — owned by the demo user, marked is_demo with same TTL.
        # Name == raw company string ("Microsoft") so the FE perspective
        # toggle reads cleanly. Earlier signups prefixed "Demo — " which
        # produced "Demo — Microsoft" in the dropdown; the prefix carries
        # no information the visitor needs (every Space they see in demo
        # IS the demo) and clutters the label.
        space = Space(
            id=uuid4(),
            name=(payload.company or "Demo")[:255],
            description="Public demo sandbox. Auto-deleted after the TTL expires.",
            privacy="private",
            sensitivity="internal",
            created_by=user.id,
            is_demo=True,
            demo_expires_at=expires_at,
        )
        self.db.add(space)
        await self.db.flush()

        # Member bridge — guest is OWNER of their own sandbox so the
        # resolver grants the full Space-axis capabilities (Phase 7
        # vocabulary; the resolver also accepts the pre-Phase-7
        # owner alias on read for backward-compat). Earlier demo
        # signups used role="admin" which fell through to "guest" in
        # the pre-A1 enforcement and silently denied AI access on
        # first chat. See test_rbac_space_role_axis.py:S-80.
        member = SpaceMember(
            id=uuid4(),
            space_id=space.id,
            user_id=user.id,
            role="owner",
        )
        self.db.add(member)

        # Optional shared dataset connections. Two env vars are supported,
        # in this order:
        #   1. DEMO_DATASET_CONNECTION_IDS (comma-separated list) — wires
        #      every UUID in the list to the new Space. This is what the
        #      multi-schema synthetic dataset uses (CRM, Marketing,
        #      Finance, Web Analytics, Product Usage = 5 connections).
        #   2. DEMO_DATASET_CONNECTION_ID (single UUID, legacy) — kept
        #      for backwards compatibility with the original single-DB
        #      design. Used only when the plural is empty.
        # When both are empty the Space starts with no data — still valid
        # for click-the-buttons demos.
        await self._ensure_dataset_connections(space)

        # Hydrate Knowledge (Glossary + Metrics) and Enterprise
        # Relationships scoped to this Space so the visitor's Universe
        # Intelligence canvas isn't an empty ring of zero-counts. Same
        # transaction as the Space/User/Member writes — if it fails the
        # whole signup rolls back and the visitor retries cleanly.
        await self._seed_demo_context(space, user)
        await self._seed_demo_agents(space, user)
        # Findings seed runs after agents so the FK references are
        # already in the session. Pre-canned content per agent gives
        # the Pulse panel something to render on the very first load.
        await self._seed_demo_findings(space)

        # Default Personal page first — `ensure_default_page_and_space`
        # short-circuits if the user already owns ANY page (its check
        # is owner-by-id, not scope-aware), so it must run BEFORE the
        # Space-scoped seed below; otherwise the Space page would
        # satisfy its early-return and the visitor lands in Personal
        # mode without an "Ana's Board" entry. Idempotent.
        from src.services.onboarding_service import ensure_default_page_and_space

        await ensure_default_page_and_space(self.db, user)

        # Default Space-scoped page named "{company} Board" — so when
        # the visitor switches from Personal to the demo Space the page
        # picker lands on a sensible label (e.g. "Acme Corp Board")
        # instead of an empty / placeholder selector. Filtered by
        # space_id so the Personal page above doesn't satisfy the
        # idempotency check.
        await self._seed_demo_space_page(space, user, payload.company)

        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(space)

        # Fire-and-forget: hydrate the AI service's `embeddings` table
        # so the Universe canvas shows agents + knowledge + relationships
        # on first load. Runs in the request's event-loop background;
        # the 201 response is not blocked by the OpenAI roundtrip.
        _trigger_universe_embedding_seed(str(space.id))

        # Lead-gen Slack ping: cold signup — fires AFTER commit so a
        # webhook failure can't roll back the sandbox.
        await _post_slack_demo_signup(
            user=user,
            space=space,
            company=payload.company,
            role=payload.role,
            is_returning=False,
            is_same_domain_join=False,
            client_ip=client_ip,
        )

        # Welcome email (Resend) — sent ONLY on fresh cold signups.
        # Returning visitors don't get another welcome; same-domain
        # joiners get a different template (TODO: separate
        # "your colleague invited you" mail). Fire-and-forget.
        from src.services.demo_email_service import send_demo_welcome_email

        await send_demo_welcome_email(
            name=user.name,
            email=user.email,
            company=payload.company,
            expires_at=expires_at,
        )

        return await self._issue_response(user, space, expires_at, is_returning=False)

    async def _issue_returning(
        self,
        user: User,
        user_agent: Optional[str],
        client_ip: Optional[str],
    ) -> DemoSignupResponse:
        """Same email already had a sandbox — find it and re-issue tokens."""
        space_q = await self.db.execute(
            select(Space).where(Space.created_by == user.id, Space.is_demo.is_(True))
        )
        space = space_q.scalars().first()
        if space is None:
            # Edge case: user row exists but Space was already cleaned up
            # by the cron. Kill the orphan user so the next signup mints
            # a fresh sandbox cleanly.
            await self.db.execute(delete(User).where(User.id == user.id))
            await self.db.commit()
            raise BadRequestError(
                "Your previous demo expired. Please submit the form again to get a new sandbox."
            )

        # Backfill #1: returning visitor whose Space was provisioned
        # before DEMO_DATASET_CONNECTION_IDS was set ends up with an
        # empty Space — idempotent binder closes the gap.
        added = await self._ensure_dataset_connections(space)

        # Backfill #2: Spaces created before the Knowledge seed shipped
        # have empty Glossary / Metrics / Relationships. Re-run the
        # idempotent seed so a returning visitor sees the same hydrated
        # sandbox a fresh signup would get today.
        seeded = await self._seed_demo_context(space, user)
        seeded_any = any(seeded.values())

        # Backfill #3: same-shape backfill for the agents seed. Older
        # demo Spaces have no agents → Pulse pill stays empty. The
        # helper is idempotent (skips if any agent already exists for
        # the Space) so this is safe to run on every returning login.
        agents_seeded = await self._seed_demo_agents(space, user)

        # Backfill #3b: pre-canned findings per agent. Idempotent —
        # skips if any of the Space's agents already carry a finding.
        # Returning visitors whose agents have been running for real
        # therefore keep their organic findings; cold visitors get the
        # demo-ready insights so the Pulse panel doesn't read empty.
        findings_seeded = await self._seed_demo_findings(space)

        # Backfill #4: default Space-scoped Page. Demo Spaces minted
        # before this seed shipped have no Space-axis page, so the
        # topbar picker comes up empty when the visitor switches to
        # Space mode. We pull the company from the user's preferences
        # (set at signup) so the label matches what a fresh signup
        # would have produced.
        prefs = user.preferences or {}
        cached_company = prefs.get("demo_company") if isinstance(prefs, dict) else ""
        page_seeded = await self._seed_demo_space_page(space, user, cached_company or "")

        if added or seeded_any or agents_seeded or findings_seeded or page_seeded:
            await self.db.commit()

        # Fire-and-forget: backfill the universe embeddings if any new
        # BE data was added in this returning-login path. Idempotent on
        # the AI side, so the call is safe even when nothing changed.
        _trigger_universe_embedding_seed(str(space.id))

        # Slack ping intentionally NOT fired on returning login.
        # Lucas's 2026-04-30 brief: "se ele ja entrou antes nao
        # precisamos receber o alerta". Cold signup + same-domain
        # join still fire (that's lead-gen signal); a returning
        # visitor is just a re-login and would otherwise spam
        # #sky-demo-signups every time the prospect comes back.
        return await self._issue_response(
            user,
            space,
            user.demo_expires_at or datetime.now(timezone.utc),
            is_returning=True,
        )

    async def _issue_response(
        self,
        user: User,
        space: Space,
        expires_at: datetime,
        *,
        is_returning: bool,
    ) -> DemoSignupResponse:
        token_payload = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            "demo": True,
            "space_id": str(space.id),
        }
        access_token = create_access_token(token_payload)
        refresh_token = create_refresh_token(token_payload)

        # The refresh token MUST have a row in refresh_tokens: /auth/refresh
        # looks the token up there and rejects anything it cannot find. This
        # used to hand out a signed JWT with no row, so every demo session
        # died silently at the first silent refresh — 30 minutes in, the
        # prospect was thrown back to the sign-up form. Mirrors the login
        # path in AuthService so the row TTL matches the JWT exp.
        self.db.add(
            RefreshToken(
                user_id=user.id,
                token=refresh_token,
                expires_at=datetime.now(timezone.utc)
                + timedelta(days=refresh_ttl_days()),
                # A fresh demo session opens its own token family, exactly as
                # a fresh login does; rotations stay inside it.
                family_id=uuid4(),
            )
        )
        # Callers commit before reaching here, so this row needs its own
        # commit or it is discarded when the session closes.
        await self.db.commit()

        return DemoSignupResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            user=UserResponse.model_validate(user, from_attributes=True),
            space_id=str(space.id),
            demo_expires_at=expires_at.isoformat(),
            is_returning=is_returning,
        )

    # ─── SSO opt-in: provision the same demo content for an existing user ──

    async def get_personal_demo_status(self, user: User) -> dict:
        """Reports whether the current user has a personal Demo Sky
        workspace (and what's in it). Used by the FE banner to decide
        whether to show "Remove sample data" or the first-login modal.

        The status is derived from a single DB lookup keyed on
        (created_by=user.id, name='Demo Sky', is_demo=True). Returns:

            {
                "has_demo_space": bool,
                "space_id": Optional[str],
                "space_name": Optional[str],
                "metrics_count": int,
                "glossary_count": int,
                "connections_count": int,
            }
        """
        space_q = await self.db.execute(
            select(Space).where(
                Space.created_by == user.id,
                Space.is_demo.is_(True),
                Space.deleted_at.is_(None),
                Space.name == "Demo Sky",
            )
        )
        space = space_q.scalars().first()
        if space is None:
            return {
                "has_demo_space": False,
                "space_id": None,
                "space_name": None,
                "metrics_count": 0,
                "glossary_count": 0,
                "connections_count": 0,
            }

        metrics_q = await self.db.execute(
            select(Metric.id).where(
                Metric.scope == "space",
                Metric.scope_id == space.id,
            )
        )
        glossary_q = await self.db.execute(
            select(GlossaryTerm.id).where(GlossaryTerm.space_id == space.id)
        )
        connections_q = await self.db.execute(
            select(SpaceConnection.connection_id).where(SpaceConnection.space_id == space.id)
        )

        return {
            "has_demo_space": True,
            "space_id": str(space.id),
            "space_name": space.name,
            "metrics_count": len(metrics_q.scalars().all()),
            "glossary_count": len(glossary_q.scalars().all()),
            "connections_count": len(connections_q.scalars().all()),
        }

    async def remove_personal_demo_workspace(self, user: User) -> dict:
        """Hard-deletes the user's personal Demo Sky workspace and all
        its content. Bypasses the platform-level Space delete RBAC:
        the user opted into this space themselves and must always be
        able to clean it up, regardless of their tenant role
        (member / editor / viewer cannot normally delete spaces, but
        the demo space is theirs to control).

        Cascades:
          - SpaceMember rows (FK ondelete=CASCADE)
          - Crews and their child rows
          - SpaceConnection bridges (the underlying data_connections
            stay — they're shared across users)
          - Dashboards, widgets, chats inside the Space
          - Glossary, Metrics, Enterprise Relationships scoped to the
            Space (we delete these explicitly because their FK is
            scope_id, not a real FK to spaces.id, so CASCADE doesn't
            fire automatically)

        Idempotent: returning {removed: False} if no Demo Sky exists.
        Returns {removed: True, space_id, deleted_counts} on success.
        """
        space_q = await self.db.execute(
            select(Space).where(
                Space.created_by == user.id,
                Space.is_demo.is_(True),
                Space.deleted_at.is_(None),
                Space.name == "Demo Sky",
            )
        )
        space = space_q.scalars().first()
        if space is None:
            return {"removed": False, "space_id": None, "deleted": {}}

        space_id = space.id

        # Knowledge entities — keyed by scope_id (not a real FK to
        # spaces), so we delete them by hand before the Space goes.
        m_count = (await self.db.execute(
            delete(Metric).where(
                Metric.scope == "space",
                Metric.scope_id == space_id,
            )
        )).rowcount or 0
        g_count = (await self.db.execute(
            delete(GlossaryTerm).where(GlossaryTerm.space_id == space_id)
        )).rowcount or 0
        r_count = (await self.db.execute(
            delete(EnterpriseRelationship).where(
                EnterpriseRelationship.scope == "space",
                EnterpriseRelationship.scope_id == space_id,
            )
        )).rowcount or 0

        # Space deletion CASCADEs through SpaceMember, SpaceConnection,
        # SpaceTable, Crew, and any FK-attached content (dashboards,
        # widgets, chats, agents) per the existing FK setup.
        await self.db.execute(delete(Space).where(Space.id == space_id))

        await self.db.commit()

        logger.info(
            "demo_personal_workspace_removed user=%s space_id=%s "
            "metrics=%d glossary=%d relationships=%d",
            user.email, space_id, m_count, g_count, r_count,
        )

        return {
            "removed": True,
            "space_id": str(space_id),
            "deleted": {
                "metrics": m_count,
                "glossary": g_count,
                "relationships": r_count,
            },
        }

    async def provision_for_existing_user(self, user: User) -> dict:
        """Create a personal demo workspace for an already-authenticated
        user (e.g. SSO sign-in landing on an empty platform), populated
        with the same content a public ``/demo/signup`` visitor would
        get: 5 dataset connections, Glossary, Metrics, Enterprise
        Relationships, and 3 ready-to-run Agents.

        The Space is marked ``is_demo=True`` so it appears as a demo in
        the UI, but ``demo_expires_at`` is left ``NULL`` — this is opt-in
        exploration, not anti-fraud, so we don't reap it. The user can
        delete it any time from Space settings.

        Idempotent: if the user already owns a Space named ``Demo Sky``
        (created by a prior call), the function returns it as-is and
        only fills in any missing seed content.

        Returns a dict suitable for the API response::

            {
                "space_id": "...",
                "space_name": "Demo Sky",
                "is_new": True,
                "seeded": {"glossary": 14, "metrics": 5, "relationships": 3},
                "agents_added": 3,
                "connections_added": 5,
            }
        """
        existing_q = await self.db.execute(
            select(Space).where(
                Space.created_by == user.id,
                Space.is_demo.is_(True),
                Space.deleted_at.is_(None),
                Space.name == "Demo Sky",
            )
        )
        space = existing_q.scalars().first()
        is_new = space is None

        if space is None:
            space = Space(
                id=uuid4(),
                name="Demo Sky",
                description=(
                    "Sample workspace pre-loaded with example datasets, "
                    "metrics, and a glossary so you can explore Sky's "
                    "capabilities. Safe to delete any time."
                ),
                created_by=user.id,
                is_demo=True,
                # No demo_expires_at — opt-in exploration, no TTL.
                privacy="private",
                sensitivity="internal",
            )
            self.db.add(space)
            await self.db.flush()
            self.db.add(
                SpaceMember(
                    id=uuid4(),
                    space_id=space.id,
                    user_id=user.id,
                    role="owner",
                )
            )
            await self.db.flush()

        connections_added = await self._ensure_dataset_connections(space)
        seeded = await self._seed_demo_context(space, user)
        agents_added = await self._seed_demo_agents(space, user)
        await self._seed_demo_findings(space)

        await self.db.commit()
        await self.db.refresh(space)

        # Fire-and-forget: hydrate the AI service's embeddings for the
        # SSO-demo Space too. Same idempotent guarantees as the cold
        # signup path — re-seeding an already-embedded Space is free.
        _trigger_universe_embedding_seed(str(space.id))

        logger.info(
            "demo_provisioned_for_sso_user user=%s space_id=%s is_new=%s "
            "glossary=%d metrics=%d relationships=%d agents=%d connections=%d",
            user.email, space.id, is_new,
            seeded.get("glossary", 0), seeded.get("metrics", 0),
            seeded.get("relationships", 0),
            agents_added, connections_added,
        )

        return {
            "space_id": str(space.id),
            "space_name": space.name,
            "is_new": is_new,
            "seeded": seeded,
            "agents_added": agents_added,
            "connections_added": connections_added,
        }

    async def reseed_space(self, space_id: UUID, user: User) -> dict:
        """Idempotent re-seed for an existing Space — Sprint 1.17 round 6.

        Lucas review (2026-05-15): "cade os agentes? cade as conexoes?
        entrei com um usuário demo e nao vejo, entrei com minha conta
        owner e tambem nao vejo os agentes do space demo que deveria ter".
        The cold signup path was silently no-op'ing the connection
        bridge when the env var pointed at stale UUIDs, leaving demo
        Spaces empty. This admin-callable method re-runs every demo
        seed step (connections, knowledge, agents, findings) against
        an arbitrary Space so an operator can heal a broken sandbox
        in one HTTP call rather than re-running 4 CLI scripts.

        Safe to run on the same Space repeatedly — each seed step is
        idempotent. Returns a dict with the counts of what was added
        so the operator can confirm the heal happened.
        """
        space_q = await self.db.execute(
            select(Space).where(Space.id == space_id, Space.deleted_at.is_(None))
        )
        space = space_q.scalar_one_or_none()
        if space is None:
            raise BadRequestError(f"Space {space_id} not found.")

        connections_added = await self._ensure_dataset_connections(space)
        seeded = await self._seed_demo_context(space, user)
        agents_added = await self._seed_demo_agents(space, user)
        findings_added = await self._seed_demo_findings(space)

        await self.db.commit()
        await self.db.refresh(space)

        _trigger_universe_embedding_seed(str(space.id))

        logger.info(
            "demo_reseed_completed space_id=%s by=%s connections=%d "
            "knowledge=%s agents=%d findings=%d",
            space.id,
            user.email,
            connections_added,
            seeded,
            agents_added,
            findings_added,
        )

        return {
            "space_id": str(space.id),
            "space_name": space.name,
            "connections_added": connections_added,
            "knowledge": seeded,
            "agents_added": agents_added,
            "findings_added": findings_added,
        }


# ─── Slack lead-gen webhook on demo signup ─────────────────────────────────


def _slack_blocks_for_demo_signup(
    *,
    user: User,
    space: Space,
    company: str,
    role: Optional[str],
    is_returning: bool,
    is_same_domain_join: bool,
    client_ip: Optional[str],
) -> dict:
    """Slack block-kit payload for a demo sandbox provision event.

    Three event flavours emit this:
      1. Fresh signup — first @acme.com user
      2. Same-domain join (item D) — Nth @acme.com user attaches to
         the existing Space
      3. Returning visitor — same email re-issuing tokens
    """
    if is_returning:
        emoji = ":arrows_counterclockwise:"
        headline = f"Returning demo visitor: {company}"
    elif is_same_domain_join:
        emoji = ":handshake:"
        headline = f"Demo team-up: {company} (joined existing Space)"
    else:
        emoji = ":rocket:"
        headline = f"New demo signup: {company}"

    fields = [
        {"type": "mrkdwn", "text": f"*Visitor*\n{user.name or '—'}"},
        {"type": "mrkdwn", "text": f"*Email*\n{user.email}"},
        {"type": "mrkdwn", "text": f"*Company*\n{company}"},
        {"type": "mrkdwn", "text": f"*Role*\n{role or '—'}"},
        {"type": "mrkdwn", "text": f"*Space*\n{space.name}"},
        {
            "type": "mrkdwn",
            "text": f"*TTL*\n{space.demo_expires_at.isoformat() if space.demo_expires_at else '—'}",
        },
    ]
    if client_ip:
        fields.append({"type": "mrkdwn", "text": f"*Client IP*\n`{client_ip}`"})

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {headline}",
                "emoji": True,
            },
        },
        {"type": "section", "fields": fields},
    ]

    return {
        "text": f"{headline} — {user.email}",  # fallback for clients without block-kit
        "blocks": blocks,
    }


async def _post_slack_demo_signup(
    *,
    user: User,
    space: Space,
    company: str,
    role: Optional[str],
    is_returning: bool,
    is_same_domain_join: bool,
    client_ip: Optional[str],
) -> None:
    """Best-effort Slack POST. Failures are swallowed.

    Empty SLACK_DEMO_SIGNUPS_WEBHOOK_URL = log-only mode (useful for
    local dev / CI / before lead-gen channel is configured).
    """
    url = (getattr(settings, "SLACK_DEMO_SIGNUPS_WEBHOOK_URL", "") or "").strip()
    if not url:
        return

    body = _slack_blocks_for_demo_signup(
        user=user,
        space=space,
        company=company,
        role=role,
        is_returning=is_returning,
        is_same_domain_join=is_same_domain_join,
        client_ip=client_ip,
    )

    timeout = float(getattr(settings, "SLACK_DEMO_SIGNUPS_WEBHOOK_TIMEOUT", 5.0))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body)
        if resp.status_code >= 400:
            logger.error(
                "slack_demo_signup_webhook_failed status=%s user=%s body=%r",
                resp.status_code,
                user.email,
                resp.text[:300],
            )
        else:
            logger.info(
                "slack_demo_signup_webhook_delivered user=%s status=%s",
                user.email,
                resp.status_code,
            )
    except Exception as exc:  # noqa: BLE001 — webhook must not fail signup
        logger.exception("slack_demo_signup_webhook_error user=%s err=%s", user.email, exc)


# ─── Cron: cleanup ──────────────────────────────────────────────────────────


async def cleanup_expired_demo_spaces(db: AsyncSession) -> Tuple[int, int]:
    """Deletes demo Spaces (and their guest Users) past their TTL.

    Spaces cascade-delete their members, dashboards, widgets, chats by
    the FK setup. Users are owned by themselves so they need a separate
    delete pass once their Space is gone.

    AI-owned tables (`table_metadata`, `embeddings`) reference
    `spaces.id` with RESTRICT (no CASCADE), so they're cleared
    explicitly first. Without this, the Space DELETE would fail with
    a FK violation and demo Spaces would accumulate forever — Lucas's
    2026-05-05 review caught seven leftover space_ids in
    `table_metadata` from old per-visitor signups.

    Returns ``(spaces_deleted, users_deleted)``.
    """
    now = datetime.now(timezone.utc)

    expired_spaces_q = await db.execute(
        select(Space.id).where(
            Space.is_demo.is_(True),
            Space.demo_expires_at.is_not(None),
            Space.demo_expires_at < now,
        )
    )
    space_ids = [row[0] for row in expired_spaces_q.all()]
    spaces_deleted = 0
    if space_ids:
        # Clear the AI-owned per-space rows first (no CASCADE on the
        # FK to spaces.id). The order matters — embeddings has an FK
        # to table_metadata, so embeddings goes first.
        from sqlalchemy import text as _text

        try:
            await db.execute(
                _text("DELETE FROM embeddings WHERE space_id = ANY(:ids)"),
                {"ids": [str(s) for s in space_ids]},
            )
            await db.execute(
                _text("DELETE FROM table_metadata WHERE space_id = ANY(:ids)"),
                {"ids": [str(s) for s in space_ids]},
            )
        except Exception:
            # The AI tables may not exist yet in some test envs.
            # Don't block Space cleanup on a missing table — the FK
            # would already be NO-OP if the column has no data there.
            try:
                await db.rollback()
            except Exception:
                pass

        await db.execute(delete(Space).where(Space.id.in_(space_ids)))
        spaces_deleted = len(space_ids)

    # Delete expired guest users (regardless of whether their Space
    # still exists — covers orphans).
    expired_users_q = await db.execute(
        select(User.id).where(
            User.is_demo.is_(True),
            User.demo_expires_at.is_not(None),
            User.demo_expires_at < now,
        )
    )
    user_ids = [row[0] for row in expired_users_q.all()]
    users_deleted = 0
    if user_ids:
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        users_deleted = len(user_ids)

    await db.commit()
    logger.info(
        "demo cleanup pass: spaces=%d users=%d (now=%s)",
        spaces_deleted,
        users_deleted,
        now.isoformat(),
    )
    return spaces_deleted, users_deleted
