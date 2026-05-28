"""CSM + tenant health + renewals service (Projeto B It3 — B#17-18).

Reads / writes ``console_tenant_csm_notes`` and computes a per-tenant
health score from a handful of inputs the CSM cares about.

The health score is a deterministic 0-100 integer composed of four
weighted sub-scores, each clipped to 0-25:

* **capacity_health (25 weight)** — closer to limit = lower score
* **activity_health (25 weight)** — recent queries / agents / logins
* **support_health (25 weight)** — open tickets vs baseline
* **lifecycle_health (25 weight)** — recency of CSM contact + tier
  status (suspended / overdue / renewal too far out)

Sub-scores are computed in :func:`_breakdown` and exposed in the
response so the UI can show why the number is what it is.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.internal_console import ConsoleCSMNotes
from src.models.tenant import Tenant
from src.schemas.internal_console import (
    CSMNotesRead,
    CSMNotesUpdate,
    RenewalEntry,
)
from src.services import pricing_tiers


# ── CSM notes CRUD ─────────────────────────────────────────────────


async def get_or_create_notes(
    db: AsyncSession, tenant_slug: str
) -> ConsoleCSMNotes:
    """Idempotent lookup. Creates an empty row on first read so the
    UI doesn't have to differentiate between "no notes" and "tenant
    doesn't exist"."""
    row = (
        await db.execute(
            select(ConsoleCSMNotes).where(
                ConsoleCSMNotes.tenant_slug == tenant_slug
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = ConsoleCSMNotes(tenant_slug=tenant_slug, tags=[])
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        row = (
            await db.execute(
                select(ConsoleCSMNotes).where(
                    ConsoleCSMNotes.tenant_slug == tenant_slug
                )
            )
        ).scalar_one()
    return row


async def update_notes(
    db: AsyncSession,
    tenant_slug: str,
    payload: CSMNotesUpdate,
    actor_email: str,
) -> ConsoleCSMNotes:
    row = await get_or_create_notes(db, tenant_slug)
    if payload.notes_markdown is not None:
        row.notes_markdown = payload.notes_markdown
    if payload.tags is not None:
        row.tags = payload.tags
    if payload.last_contact_at is not None:
        row.last_contact_at = payload.last_contact_at
    if payload.nps_score is not None:
        row.nps_score = payload.nps_score
    row.updated_by = actor_email
    await db.flush()
    return row


# ── Health score ───────────────────────────────────────────────────


_HEALTH_WEIGHTS = {
    "capacity": 25,
    "activity": 25,
    "support": 25,
    "lifecycle": 25,
}


def _breakdown(
    tenant: Tenant,
    notes: ConsoleCSMNotes,
    open_tickets: int = 0,
    days_since_login: int = 0,
    queries_last_7d: int = 0,
) -> Dict[str, int]:
    """Compute 4 sub-scores. Each is clipped to its weight ceiling."""

    # Capacity: closer to limit is worse. Use max across dimensions.
    used = tenant.capacity_used or {}
    limits = tenant.capacity_limits or {}
    max_pct = 0.0
    for key in ("agents", "sources", "indexed_gb"):
        u = float(used.get(key, 0))
        lim = float(limits.get(key, 0)) or 1.0
        pct = min(100.0, 100.0 * u / lim)
        if pct > max_pct:
            max_pct = pct
    # 0% used → full weight, 100% → 0, linearly.
    capacity = round((1.0 - max_pct / 100.0) * _HEALTH_WEIGHTS["capacity"])

    # Activity: rule-of-thumb mapping.
    if queries_last_7d >= 200:
        activity = _HEALTH_WEIGHTS["activity"]
    elif queries_last_7d >= 50:
        activity = round(0.7 * _HEALTH_WEIGHTS["activity"])
    elif queries_last_7d >= 10:
        activity = round(0.4 * _HEALTH_WEIGHTS["activity"])
    else:
        activity = 0

    # Support: 0 tickets → full, 5+ → 0.
    if open_tickets == 0:
        support = _HEALTH_WEIGHTS["support"]
    elif open_tickets <= 2:
        support = round(0.6 * _HEALTH_WEIGHTS["support"])
    elif open_tickets <= 4:
        support = round(0.3 * _HEALTH_WEIGHTS["support"])
    else:
        support = 0

    # Lifecycle: suspended / overdue / no-contact-in-a-month are bad.
    lifecycle_pct = 1.0
    if not tenant.is_active:
        lifecycle_pct = 0.0
    elif notes.last_contact_at is None:
        lifecycle_pct = 0.5
    else:
        last_contact = notes.last_contact_at
        if last_contact.tzinfo is None:
            last_contact = last_contact.replace(tzinfo=timezone.utc)
        days_since_contact = (
            datetime.now(timezone.utc) - last_contact
        ).days
        if days_since_contact > 90:
            lifecycle_pct = 0.2
        elif days_since_contact > 30:
            lifecycle_pct = 0.6
        else:
            lifecycle_pct = 1.0
    lifecycle = round(lifecycle_pct * _HEALTH_WEIGHTS["lifecycle"])

    return {
        "capacity": int(capacity),
        "activity": int(activity),
        "support": int(support),
        "lifecycle": int(lifecycle),
    }


def health_score(
    tenant: Tenant,
    notes: ConsoleCSMNotes,
    open_tickets: int = 0,
    days_since_login: int = 0,
    queries_last_7d: int = 0,
) -> tuple[int, Dict[str, int]]:
    bd = _breakdown(
        tenant=tenant,
        notes=notes,
        open_tickets=open_tickets,
        days_since_login=days_since_login,
        queries_last_7d=queries_last_7d,
    )
    return sum(bd.values()), bd


async def build_csm_response(
    db: AsyncSession, tenant_slug: str
) -> Optional[CSMNotesRead]:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
    ).scalar_one_or_none()
    if tenant is None:
        return None
    notes = await get_or_create_notes(db, tenant_slug)
    from src.services.console_telemetry_real import query_tenant_activity_7d

    points = await query_tenant_activity_7d(tenant)
    queries_7d = int(sum(p.value for p in points))
    score, bd = health_score(
        tenant=tenant,
        notes=notes,
        open_tickets=0,
        queries_last_7d=queries_7d,
    )
    return CSMNotesRead(
        tenant_slug=tenant_slug,
        notes_markdown=notes.notes_markdown,
        tags=list(notes.tags or []),
        last_contact_at=notes.last_contact_at,
        nps_score=notes.nps_score,
        health_score=score,
        health_breakdown=bd,
        next_renewal_at=notes.next_renewal_at,
        updated_at=notes.updated_at,
        updated_by=notes.updated_by,
    )


# ── Renewals ───────────────────────────────────────────────────────


async def upcoming_renewals(
    db: AsyncSession, days_ahead: int = 90
) -> List[RenewalEntry]:
    """Renewals due in the next N days.

    Combines the registry (tier, display_name) with the CSM notes
    (next_renewal_at) — when next_renewal_at is missing on the CSM
    row, we mock it from created_at + 365 days so the UI always has
    something to render in local dev.
    """
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days_ahead)
    tenants = (await db.execute(select(Tenant))).scalars().all()

    out: List[RenewalEntry] = []
    for t in tenants:
        notes = await get_or_create_notes(db, t.slug)
        renewal = notes.next_renewal_at
        if renewal is None:
            created = t.created_at
            if created and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            renewal = (created or now) + timedelta(days=365)
        if renewal.tzinfo is None:
            renewal = renewal.replace(tzinfo=timezone.utc)
        if renewal > horizon:
            continue
        days_until = (renewal - now).days
        preset = pricing_tiers.get_tier(t.tier)
        monthly = (
            (preset.headline_price_eur or 0) / 12.0
            if preset and preset.headline_price_eur
            else 0.0
        )
        status = (
            "overdue"
            if days_until < 0
            else "upcoming"
        )
        out.append(
            RenewalEntry(
                tenant_slug=t.slug,
                display_name=t.display_name,
                tier=t.tier,
                next_renewal_at=renewal,
                days_until=days_until,
                monthly_amount_eur=round(monthly, 2),
                status=status,
            )
        )
    out.sort(key=lambda r: r.days_until)
    return out
