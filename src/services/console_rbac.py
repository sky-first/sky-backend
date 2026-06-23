"""Role-based access control for the Internal Console (Projeto B It4).

Two responsibilities:

* **Grant management** — load/grant/revoke roles in
  ``console_role_grants``. Used by ``/api/console/v1/role-grants``.
* **Permissions enforcement** — a tabular ``PERMISSIONS`` mapping
  (action → set of roles) and a ``assert_permission()`` helper the
  routes call to authorise.

The 9 roles come from docs/projeto-b-roles-and-use-cases.md (CEO,
CTO, Tech Lead, DevOps, Backend Eng, AI Eng, CSM, Sales, Finance,
Support, DPO — actually 11 once you count CTO and Tech Lead). The
permissions table here mirrors the matrix in that doc.

The bootstrap path: when ``console_role_grants`` is empty for a
user but the user's email is in ``CONSOLE_ADMIN_EMAILS``, they get
an automatic CEO grant on first read. After that, the DB is
authoritative.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Iterable, List, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.internal_console import ConsoleRole, ConsoleRoleGrant

logger = logging.getLogger(__name__)


# ── Permissions matrix ─────────────────────────────────────────────


PERMISSIONS: dict[str, Set[ConsoleRole]] = {
    # Tenant lifecycle
    "tenant.read": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.TECH_LEAD,
        ConsoleRole.DEVOPS,
        ConsoleRole.BACKEND_ENG,
        ConsoleRole.AI_ENG,
        ConsoleRole.CSM,
        ConsoleRole.SALES,
        ConsoleRole.FINANCE,
        ConsoleRole.SUPPORT,
        ConsoleRole.DPO,
    },
    "tenant.create": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.DEVOPS,
        ConsoleRole.SALES,
    },
    "tenant.update_settings": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.DEVOPS,
    },
    "tenant.change_tier": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.CSM,
    },
    "tenant.suspend": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.DEVOPS,
    },
    "tenant.destroy": {ConsoleRole.CEO, ConsoleRole.CTO},
    "tenant.update_bedrock_profile": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.AI_ENG,
    },
    # CSM
    "csm.read": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.CSM,
        ConsoleRole.SALES,
        ConsoleRole.SUPPORT,
    },
    "csm.write": {ConsoleRole.CEO, ConsoleRole.CSM},
    # Infra
    "infra.read": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.TECH_LEAD,
        ConsoleRole.DEVOPS,
        ConsoleRole.BACKEND_ENG,
        ConsoleRole.AI_ENG,
    },
    "infra.write": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.DEVOPS,
    },
    "logs.read": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.TECH_LEAD,
        ConsoleRole.DEVOPS,
        ConsoleRole.BACKEND_ENG,
        ConsoleRole.AI_ENG,
        ConsoleRole.SUPPORT,  # scoped to one tenant — enforced upstream
    },
    "logs.psql": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.DEVOPS,
        ConsoleRole.DPO,
    },
    "logs.shell": {ConsoleRole.CEO, ConsoleRole.CTO, ConsoleRole.DEVOPS},
    # Cost + revenue
    "cost.platform": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.DEVOPS,
        ConsoleRole.AI_ENG,
        ConsoleRole.FINANCE,
    },
    "cost.per_tenant": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.DEVOPS,
        ConsoleRole.AI_ENG,
        ConsoleRole.CSM,
        ConsoleRole.SALES,
        ConsoleRole.FINANCE,
    },
    "revenue.read": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.CSM,
        ConsoleRole.SALES,
        ConsoleRole.FINANCE,
    },
    "revenue.gross_margin": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.FINANCE,
    },
    "invoice.read": {
        ConsoleRole.CEO,
        ConsoleRole.CSM,
        ConsoleRole.SALES,
        ConsoleRole.FINANCE,
    },
    "invoice.write": {ConsoleRole.CEO, ConsoleRole.FINANCE},
    # Audit
    "audit.read": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.TECH_LEAD,
        ConsoleRole.DEVOPS,
        ConsoleRole.BACKEND_ENG,
        ConsoleRole.AI_ENG,
        ConsoleRole.CSM,
        ConsoleRole.SALES,
        ConsoleRole.FINANCE,
        ConsoleRole.SUPPORT,
        ConsoleRole.DPO,
    },
    "audit.export_dsar": {ConsoleRole.CEO, ConsoleRole.CTO, ConsoleRole.DPO},
    # Compliance
    "compliance.read": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.CSM,
        ConsoleRole.SALES,
        ConsoleRole.DPO,
    },
    "compliance.write": {ConsoleRole.CEO, ConsoleRole.DPO},
    # Support
    "support.read": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.CSM,
        ConsoleRole.SUPPORT,
    },
    "support.write": {
        ConsoleRole.CEO,
        ConsoleRole.SUPPORT,
        ConsoleRole.CSM,
    },
    "impersonate": {ConsoleRole.CEO, ConsoleRole.SUPPORT},
    # RBAC itself
    "rbac.read": {role for role in ConsoleRole},
    "rbac.write": {ConsoleRole.CEO, ConsoleRole.CTO},
    # Incidents / alerts
    "alerts.ack": {
        ConsoleRole.CEO,
        ConsoleRole.CTO,
        ConsoleRole.DEVOPS,
        ConsoleRole.AI_ENG,
        ConsoleRole.CSM,
    },
}


def _bootstrap_admin_emails() -> Set[str]:
    raw = os.getenv("CONSOLE_ADMIN_EMAILS") or ""
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


# ── Grant management ───────────────────────────────────────────────


async def load_active_roles(
    db: AsyncSession, user_email: str
) -> List[ConsoleRole]:
    email = (user_email or "").lower()
    rows = (
        await db.execute(
            select(ConsoleRoleGrant).where(
                ConsoleRoleGrant.user_email == email,
                ConsoleRoleGrant.revoked_at.is_(None),
            )
        )
    ).scalars().all()
    if rows:
        return [ConsoleRole(r.role) for r in rows]
    if email in _bootstrap_admin_emails():
        await _ensure_grant(
            db, email=email, role=ConsoleRole.CEO, granted_by="bootstrap"
        )
        return [ConsoleRole.CEO]
    return []


async def _ensure_grant(
    db: AsyncSession,
    *,
    email: str,
    role: ConsoleRole,
    granted_by: str,
) -> None:
    existing = (
        await db.execute(
            select(ConsoleRoleGrant).where(
                ConsoleRoleGrant.user_email == email,
                ConsoleRoleGrant.role == role.value,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.revoked_at is not None:
            existing.revoked_at = None
            existing.revoked_by = None
            existing.granted_by = granted_by
            existing.granted_at = datetime.now(timezone.utc)
            await db.flush()
        return
    grant = ConsoleRoleGrant(
        user_email=email,
        role=role.value,
        granted_by=granted_by,
    )
    db.add(grant)
    await db.flush()


async def grant_role(
    db: AsyncSession,
    *,
    user_email: str,
    role: ConsoleRole,
    granted_by: str,
) -> None:
    await _ensure_grant(
        db, email=user_email.lower(), role=role, granted_by=granted_by
    )


async def revoke_role(
    db: AsyncSession,
    *,
    user_email: str,
    role: ConsoleRole,
    revoked_by: str,
) -> bool:
    row = (
        await db.execute(
            select(ConsoleRoleGrant).where(
                ConsoleRoleGrant.user_email == user_email.lower(),
                ConsoleRoleGrant.role == role.value,
                ConsoleRoleGrant.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    row.revoked_at = datetime.now(timezone.utc)
    row.revoked_by = revoked_by
    await db.flush()
    return True


async def list_role_grants(db: AsyncSession) -> List[ConsoleRoleGrant]:
    rows = (
        await db.execute(
            select(ConsoleRoleGrant)
            .where(ConsoleRoleGrant.revoked_at.is_(None))
            .order_by(ConsoleRoleGrant.user_email, ConsoleRoleGrant.role)
        )
    ).scalars().all()
    return list(rows)


# ── Permission check ───────────────────────────────────────────────


def has_permission(roles: Iterable[ConsoleRole], action: str) -> bool:
    allowed = PERMISSIONS.get(action)
    if allowed is None:
        logger.warning("rbac_unknown_action", extra={"action": action})
        return False
    return any(r in allowed for r in roles)


def assert_permission(roles: Iterable[ConsoleRole], action: str) -> None:
    """Raise HTTPException(403) when the caller lacks permission."""
    from fastapi import HTTPException, status

    if not has_permission(roles, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "permission_denied",
                "required_action": action,
                "user_roles": [r.value for r in roles],
            },
        )


__all__ = [
    "PERMISSIONS",
    "assert_permission",
    "grant_role",
    "has_permission",
    "list_role_grants",
    "load_active_roles",
    "revoke_role",
]
