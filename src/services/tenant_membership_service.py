"""Central user↔tenant membership — the authorization primitive for BE-01.

Thin, stateless data-access over :class:`TenantMembership`. All methods take
an explicit :class:`AsyncSession` bound to the *platform registry* database
(the same DB that holds ``tenant_registry``), so callers stay in control of
the transaction and the service never opens its own connection.

The two hot-path methods — :meth:`is_member` and :meth:`list_for_user` — are
what the device tenant resolver and the workspace switcher call. They are
deliberately keyed only on ``user_id``/``tenant_id`` so a caller can wrap them
in a short-TTL cache without leaking anything tenant-specific.
"""

from __future__ import annotations

from typing import List, Union
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tenant_membership import TenantMembership

_UUIDLike = Union[str, UUID]


def _as_uuid(value: _UUIDLike) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


class TenantMembershipService:
    """Data-access for the central membership registry.

    Every method is a static helper — there is no per-instance state — so it
    can be called from a request handler, a middleware, or a background job
    with whatever session that context already holds.
    """

    @staticmethod
    async def is_member(session: AsyncSession, user_id: _UUIDLike, tenant_id: _UUIDLike) -> bool:
        """True iff ``user_id`` currently has a membership row for ``tenant_id``.

        This is re-evaluated on every device request: revoking membership
        (off-boarding) takes effect immediately, regardless of any still-valid
        access token the user may present.
        """
        result = await session.execute(
            select(TenantMembership.id)
            .where(TenantMembership.user_id == _as_uuid(user_id))
            .where(TenantMembership.tenant_id == _as_uuid(tenant_id))
            .limit(1)
        )
        return result.first() is not None

    @staticmethod
    async def list_for_user(session: AsyncSession, user_id: _UUIDLike) -> List[TenantMembership]:
        """Every tenant the user may act as — powers the workspace switcher."""
        result = await session.execute(
            select(TenantMembership)
            .where(TenantMembership.user_id == _as_uuid(user_id))
            .order_by(TenantMembership.created_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def upsert(
        session: AsyncSession,
        user_id: _UUIDLike,
        tenant_id: _UUIDLike,
        role: str = "member",
    ) -> TenantMembership:
        """Idempotently record that ``user_id`` is a member of ``tenant_id``.

        Called on every successful login so the registry stays in sync with
        who has actually been provisioned into a tenant. Returns the existing
        row (updating its role if it changed) or the newly-created one. The
        caller owns the commit.
        """
        uid, tid = _as_uuid(user_id), _as_uuid(tenant_id)
        existing = (
            await session.execute(
                select(TenantMembership)
                .where(TenantMembership.user_id == uid)
                .where(TenantMembership.tenant_id == tid)
            )
        ).scalar_one_or_none()

        if existing is not None:
            if role and existing.role != role:
                existing.role = role
            return existing

        membership = TenantMembership(user_id=uid, tenant_id=tid, role=role)
        session.add(membership)
        await session.flush()  # populate PK without forcing the caller's commit
        return membership

    @staticmethod
    async def revoke(session: AsyncSession, user_id: _UUIDLike, tenant_id: _UUIDLike) -> None:
        """Remove the membership (off-boarding). The caller owns the commit."""
        await session.execute(
            delete(TenantMembership)
            .where(TenantMembership.user_id == _as_uuid(user_id))
            .where(TenantMembership.tenant_id == _as_uuid(tenant_id))
        )
