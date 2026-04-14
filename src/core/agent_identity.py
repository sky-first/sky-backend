"""Agent identity resolution — decide who an agent runs as.

The decision table (from the agent master plan):

  Page scope      │  Identity             │  Survives creator leaving
  ────────────────┼───────────────────────┼──────────────────────────
  Personal page   │  the creator user     │  No — agent is paused
  Crew page       │  sp-crew-{crew_id}    │  Yes — runs indefinitely
  Space page      │  sp-space-{space_id}  │  Yes — runs indefinitely

`attributed_to_user_id` is always set on every agent run row to the
`created_by` at the time of the run — this is the audit trail regardless
of whether the runtime identity is a user or a service principal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.models.page import Page
from src.models.service_principal import ServicePrincipal


IdentityType = Literal["user", "service_principal"]


@dataclass(frozen=True)
class ResolvedIdentity:
    """The identity an agent will run as, plus its audit attribution."""

    identity_type: IdentityType
    identity_id: UUID
    attributed_to_user_id: UUID

    # Denormalised helpers so callers don't have to re-query.
    space_id: Optional[UUID]
    crew_id: Optional[UUID]


async def resolve_identity_for_page(
    *,
    db: AsyncSession,
    page_id: UUID,
    creator_user_id: UUID,
) -> ResolvedIdentity:
    """Return the identity a new agent on this page should run as.

    Precedence:
      1. If the page is scoped to a crew → sp-crew-{crew_id}
      2. If the page is scoped to a space → sp-space-{space_id}
      3. Otherwise (personal page) → the creator user

    Raises:
        NotFoundError: page doesn't exist, or its scope claims an SP that
            doesn't exist (should be impossible — SPs are auto-created on
            space/crew creation). Surfacing the error beats silently
            falling back to the creator, which would be a security hole.
    """
    page = (
        await db.execute(select(Page).where(Page.id == page_id))
    ).scalar_one_or_none()
    if page is None:
        raise NotFoundError(f"Page {page_id} not found")

    # Crew-scoped page takes precedence (more specific than space).
    if page.crew_id:
        sp = (
            await db.execute(
                select(ServicePrincipal).where(
                    ServicePrincipal.crew_id == page.crew_id
                )
            )
        ).scalar_one_or_none()
        if sp is None:
            raise NotFoundError(
                f"Crew {page.crew_id} has no service principal — "
                "invariant violation, crews auto-create one on creation"
            )
        return ResolvedIdentity(
            identity_type="service_principal",
            identity_id=sp.id,
            attributed_to_user_id=creator_user_id,
            space_id=page.space_id,
            crew_id=page.crew_id,
        )

    # Space-scoped page.
    if page.space_id:
        sp = (
            await db.execute(
                select(ServicePrincipal).where(
                    ServicePrincipal.space_id == page.space_id
                )
            )
        ).scalar_one_or_none()
        if sp is None:
            raise NotFoundError(
                f"Space {page.space_id} has no service principal — "
                "invariant violation, spaces auto-create one on creation"
            )
        return ResolvedIdentity(
            identity_type="service_principal",
            identity_id=sp.id,
            attributed_to_user_id=creator_user_id,
            space_id=page.space_id,
            crew_id=None,
        )

    # Personal page.
    return ResolvedIdentity(
        identity_type="user",
        identity_id=creator_user_id,
        attributed_to_user_id=creator_user_id,
        space_id=None,
        crew_id=None,
    )
