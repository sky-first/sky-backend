"""RBAC service (effective permissions + enforcement).

This is the backend "source of truth" for RBAC. Frontend gating (Subtask 3) is
best-effort UX; this service makes the rules actually enforceable.

Phase 0 RBAC governance (2026-04-09):
    The historical platform-admin "bypass" on lines 131 and 165 below was
    silent — it short-circuited every permission check with no audit trail.
    Per docs/architecture/RBAC_GOVERNANCE_PLAN.md (sky-poc-infra), that
    bypass becomes the integration point for the future Sky Support JIT
    consent flow. Until that flow ships:

    1. Customer admins (`user.role == "admin"`) keep their bypass to avoid
       breaking running deploys, BUT every bypass is now logged so the gap
       is observable in our existing application logs.
    2. Any future user with `is_sky_operator=True` (a column we will add in
       the Sky Support JIT migration) is rejected unless an active JIT
       session is attached. The check is in place now so that adding the
       column later does not require touching this file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError
from src.models.user import User
from src.repositories.connection import ConnectionRepository
from src.repositories.crew import CrewMemberRepository
from src.repositories.permission import PermissionRepository, RolePermissionRepository

logger = logging.getLogger(__name__)


async def _is_sky_operator_without_jit(user: User, db: AsyncSession) -> bool:
    """Reject Sky operators that lack an active JIT consent session.

    Checks the `support_sessions` table for an active (non-revoked, non-expired)
    session for this operator. If none found, they are blocked.
    """
    if not getattr(user, "is_sky_operator", False):
        return False

    # Check for active JIT session in the database
    try:
        from datetime import datetime, timezone

        from sqlalchemy import text

        result = await db.execute(
            text(
                """
                SELECT id FROM support_sessions
                WHERE operator_id = :uid
                AND revoked_at IS NULL
                AND expires_at > :now
                LIMIT 1
            """
            ),
            {"uid": user.id, "now": datetime.now(timezone.utc)},
        )
        has_active_session = result.scalar_one_or_none() is not None
        return not has_active_session
    except Exception:
        # If support_sessions doesn't exist yet, fall back to denying
        return True


CrewRole = str  # commander | navigator | explorer | guest

ROLE_PRECEDENCE: Dict[str, int] = {
    "guest": 0,
    "explorer": 1,
    "navigator": 2,
    "commander": 3,
}


DEFAULT_ROLE_PERMISSIONS: Dict[str, Dict[str, bool]] = {
    # ═══════════════════════════════════════════════════════════════
    # Commander = Manager. Can do everything within their scope.
    # Manages people, creates structure, full CRUD on resources.
    # CANNOT do org-level admin things.
    # ═══════════════════════════════════════════════════════════════
    "commander": {
        # Pages & Dashboards
        "pages.view": True,
        "pages.create": True,
        "pages.edit": True,
        "pages.edit.others": True,
        "pages.delete": True,
        "pages.share": True,
        "pages.duplicate": True,
        "pages.members.view": True,
        "pages.members.manage": True,
        "pages.star": True,
        "dashboards.view": True,
        "dashboards.create": True,
        "dashboards.edit": True,
        "dashboards.delete": True,
        "dashboards.export": True,
        "dashboards.lock": True,
        "dashboards.duplicate": True,
        # Widgets
        "widgets.view": True,
        "widgets.create": True,
        "widgets.edit": True,
        "widgets.delete": True,
        "widgets.duplicate": True,
        "widgets.export": True,
        "widgets.refresh": True,
        "widgets.feedback": True,
        # Connections
        "connections.view": True,
        "connections.metadata.view": True,
        "connections.tables.view": True,
        "connections.schemas.view": True,
        "connections.status.view": True,
        "connections.metrics.view": True,
        "connections.create": True,
        "connections.edit": True,
        "connections.delete": True,
        "connections.test": True,
        "connections.sync": True,
        "connections.validate": True,
        # AI & Queries
        "ai.chat": True,
        "ai.query": True,
        "ai.history.view": True,
        "ai.history.delete": True,
        "ai.history.pin": True,
        "ai.history.export": True,
        "ai.generate": True,
        "ai.feedback": True,
        "ai.pipeline": True,
        "ai.davinci": True,
        # Spaces
        "spaces.view": True,
        "spaces.create": False,
        "spaces.edit": True,
        "spaces.delete": True,
        "spaces.members.view": True,
        "spaces.members.manage": True,
        "spaces.connections.view": True,
        "spaces.connections.manage": True,
        "spaces.crews.view": True,
        "spaces.tables.view": True,
        "spaces.stats.view": True,
        # Crews
        "crews.view": True,
        "crews.create": True,
        "crews.edit": True,
        "crews.delete": True,
        "crews.members.view": True,
        "crews.members.manage": True,
        "crews.stats.view": True,
        # Users — self-only at the crew level; other-user read is admin-only
        "users.self.edit": True,
        "users.self.permissions": True,
        # Agents
        "agents.view": True,
        "agents.create": True,
        "agents.edit": True,
        "agents.delete": True,
        "agents.run": True,
        "agents.pause": True,
        "agents.resume": True,
        "agents.manage": True,
        "agents.findings.view": True,
        "agents.findings.dismiss": True,
        # Strategy
        "strategy.view": True,
        "strategy.pillars.create": True,
        "strategy.pillars.edit": True,
        "strategy.pillars.delete": True,
        "strategy.objectives.create": True,
        "strategy.objectives.edit": True,
        "strategy.objectives.delete": True,
        "strategy.okrs.create": True,
        "strategy.okrs.edit": True,
        "strategy.okrs.delete": True,
        "strategy.keyresults.create": True,
        "strategy.keyresults.edit": True,
        "strategy.keyresults.delete": True,
        "strategy.initiatives.create": True,
        "strategy.initiatives.edit": True,
        "strategy.initiatives.delete": True,
        "strategy.assumptions.create": True,
        "strategy.assumptions.edit": True,
        "strategy.assumptions.delete": True,
        "strategy.cycles.create": True,
        "strategy.cycles.edit": True,
        "strategy.cycles.delete": True,
        # Events & Intelligence
        "events.view": True,
        "events.create": True,
        "events.edit": True,
        "events.delete": True,
        "intelligence.view": True,
        "intelligence.create": True,
        "intelligence.dismiss": True,
        "intelligence.delete": True,
        # Other
        "comments.view": True,
        "comments.create": True,
        "notifications.view": True,
        "notifications.read": True,
        "starred.view": True,
        "starred.manage": True,
        "files.upload": True,
        "files.view": True,
        "files.delete": True,
        "templates.view": True,
        "templates.create": True,
        "templates.apply": True,
        "templates.edit": True,
        "templates.delete": True,
        "enterprise.view": True,
        "enterprise.create": True,
        "enterprise.edit": True,
        "enterprise.delete": True,
        "enterprise.apis.view": True,
        "enterprise.apis.create": True,
        "connectors.view": True,
        "datasets.view": True,
        "datasets.delete": True,
        # Commander is a CREW role. Platform-level perms below are reserved
        # for platform_admin (and owner above it). Wave 3 of ADR-002 fixed
        # the leak where Commander accidentally had global config powers.
        "settings.view": True,  # read-only config view stays (benign)
        "permissions.view": False,  # RBAC matrix is admin-only
        "apikeys.manage": False,  # global tenant secrets
        "integrations.manage": False,  # global integrations
        "metrics.view": False,  # platform usage/metrics
        # Admin-only (commander cannot)
        "admin.users.manage": False,
        "users.invite": False,
        "users.edit": False,
        "users.delete": False,
        "users.view": False,  # managing other users = admin
        "users.permissions.view": False,  # reading other users' perms = admin
        "users.permissions.edit": False,
        "settings.edit": False,
        "permissions.edit": False,
        "audit.view": False,
        "audit.verify": False,
        "privacy.export": False,
        "privacy.delete": False,
        "support.settings": False,
        "support.revoke": False,
        "users.impersonate": False,
    },
    # ═══════════════════════════════════════════════════════════════
    # Navigator = Senior Developer. Can create, edit, use AI, share.
    # Cannot manage people or structure. Cannot delete.
    # ═══════════════════════════════════════════════════════════════
    "navigator": {
        # Pages & Dashboards
        "pages.view": True,
        "pages.create": True,
        "pages.edit": True,
        "pages.edit.others": True,
        "pages.delete": False,
        "pages.share": True,
        "pages.duplicate": True,
        "pages.members.view": True,
        "pages.members.manage": True,
        "pages.star": True,
        "dashboards.view": True,
        "dashboards.create": True,
        "dashboards.edit": True,
        "dashboards.delete": False,
        "dashboards.export": True,
        "dashboards.lock": False,
        "dashboards.duplicate": True,
        # Widgets
        "widgets.view": True,
        "widgets.create": True,
        "widgets.edit": True,
        "widgets.delete": False,
        "widgets.duplicate": True,
        "widgets.export": True,
        "widgets.refresh": True,
        "widgets.feedback": True,
        # Connections (view only, cannot manage)
        "connections.view": True,
        "connections.metadata.view": True,
        "connections.tables.view": True,
        "connections.schemas.view": True,
        "connections.status.view": True,
        "connections.metrics.view": True,
        "connections.create": False,
        "connections.edit": False,
        "connections.delete": False,
        "connections.test": False,
        "connections.sync": False,
        "connections.validate": False,
        # AI & Queries
        "ai.chat": True,
        "ai.query": True,
        "ai.history.view": True,
        "ai.history.delete": True,
        "ai.history.pin": True,
        "ai.history.export": True,
        "ai.generate": True,
        "ai.feedback": True,
        "ai.pipeline": True,
        "ai.davinci": True,
        # Spaces (view only)
        "spaces.view": True,
        "spaces.create": False,
        "spaces.edit": False,
        "spaces.delete": False,
        "spaces.members.view": True,
        "spaces.members.manage": False,
        "spaces.connections.view": True,
        "spaces.connections.manage": False,
        "spaces.crews.view": True,
        "spaces.tables.view": True,
        "spaces.stats.view": True,
        # Crews (view only)
        "crews.view": True,
        "crews.create": False,
        "crews.edit": False,
        "crews.delete": False,
        "crews.members.view": True,
        "crews.members.manage": False,
        "crews.stats.view": True,
        # Users
        "users.view": False,
        "users.permissions.view": False,
        "users.self.edit": True,
        "users.self.permissions": True,
        # Agents (navigator can run/pause/resume own runs, no create/edit/delete)
        "agents.view": True,
        "agents.create": True,
        "agents.edit": True,
        "agents.delete": False,
        "agents.run": True,
        "agents.pause": True,
        "agents.resume": True,
        "agents.manage": False,
        "agents.findings.view": True,
        "agents.findings.dismiss": True,
        # Strategy
        "strategy.view": True,
        "strategy.pillars.create": True,
        "strategy.pillars.edit": True,
        "strategy.pillars.delete": False,
        "strategy.objectives.create": True,
        "strategy.objectives.edit": True,
        "strategy.objectives.delete": False,
        "strategy.okrs.create": True,
        "strategy.okrs.edit": True,
        "strategy.okrs.delete": False,
        "strategy.keyresults.create": True,
        "strategy.keyresults.edit": True,
        "strategy.keyresults.delete": False,
        "strategy.initiatives.create": True,
        "strategy.initiatives.edit": True,
        "strategy.initiatives.delete": False,
        "strategy.assumptions.create": True,
        "strategy.assumptions.edit": True,
        "strategy.assumptions.delete": False,
        "strategy.cycles.create": False,
        "strategy.cycles.edit": False,
        "strategy.cycles.delete": False,
        # Events & Intelligence
        "events.view": True,
        "events.create": False,
        "events.edit": False,
        "events.delete": False,
        "intelligence.view": True,
        "intelligence.create": False,
        "intelligence.dismiss": True,
        "intelligence.delete": False,
        # Other
        "comments.view": True,
        "comments.create": True,
        "notifications.view": True,
        "notifications.read": True,
        "starred.view": True,
        "starred.manage": True,
        "files.upload": True,
        "files.view": True,
        "files.delete": False,
        "templates.view": True,
        "templates.create": False,
        "templates.apply": True,
        "templates.edit": False,
        "templates.delete": False,
        "enterprise.view": True,
        "enterprise.create": False,
        "enterprise.edit": False,
        "enterprise.delete": False,
        "enterprise.apis.view": True,
        "enterprise.apis.create": False,
        "connectors.view": True,
        "datasets.view": True,
        "datasets.delete": False,
        # Navigator is a CREW role too. Wave 3: metrics.view is platform-
        # admin-only and was previously leaking here.
        "settings.view": True,
        "permissions.view": False,
        "apikeys.manage": False,
        "integrations.manage": False,
        "metrics.view": False,
        "admin.users.manage": False,
        "users.invite": False,
        "users.edit": False,
        "users.delete": False,
        "users.permissions.edit": False,
        "settings.edit": False,
        "permissions.edit": False,
        "audit.view": False,
        "audit.verify": False,
        "privacy.export": False,
        "privacy.delete": False,
        "support.settings": False,
        "support.revoke": False,
        "users.impersonate": False,
    },
    # ═══════════════════════════════════════════════════════════════
    # Explorer = Developer. Creates own pages, uses AI, runs queries.
    # Cannot edit others' work. Cannot manage or delete.
    # ═══════════════════════════════════════════════════════════════
    "explorer": {
        # Pages & Dashboards
        "pages.view": True,
        "pages.create": True,
        "pages.edit": True,
        "pages.edit.others": False,
        "pages.delete": False,
        "pages.share": False,
        "pages.duplicate": True,
        "pages.members.view": True,
        "pages.members.manage": False,
        "pages.star": True,
        "dashboards.view": True,
        "dashboards.create": True,
        "dashboards.edit": True,
        "dashboards.delete": False,
        "dashboards.export": True,
        "dashboards.lock": False,
        "dashboards.duplicate": True,
        # Widgets
        "widgets.view": True,
        "widgets.create": True,
        "widgets.edit": True,
        "widgets.delete": False,
        "widgets.duplicate": True,
        "widgets.export": True,
        "widgets.refresh": True,
        "widgets.feedback": True,
        # Connections (view only)
        "connections.view": True,
        "connections.metadata.view": True,
        "connections.tables.view": True,
        "connections.schemas.view": True,
        "connections.status.view": True,
        "connections.metrics.view": False,
        "connections.create": False,
        "connections.edit": False,
        "connections.delete": False,
        "connections.test": False,
        "connections.sync": False,
        "connections.validate": False,
        # AI & Queries
        "ai.chat": True,
        "ai.query": True,
        "ai.history.view": True,
        "ai.history.delete": True,
        "ai.history.pin": True,
        "ai.history.export": False,
        "ai.generate": True,
        "ai.feedback": True,
        "ai.pipeline": False,
        "ai.davinci": True,
        # Spaces (view only)
        "spaces.view": True,
        "spaces.create": False,
        "spaces.edit": False,
        "spaces.delete": False,
        "spaces.members.view": True,
        "spaces.members.manage": False,
        "spaces.connections.view": True,
        "spaces.connections.manage": False,
        "spaces.crews.view": True,
        "spaces.tables.view": True,
        "spaces.stats.view": False,
        # Crews (view only)
        "crews.view": True,
        "crews.create": False,
        "crews.edit": False,
        "crews.delete": False,
        "crews.members.view": True,
        "crews.members.manage": False,
        "crews.stats.view": False,
        # Users
        "users.view": False,
        "users.permissions.view": False,
        "users.self.edit": True,
        "users.self.permissions": True,
        # Agents (explorer = view-only; no run/pause/resume)
        "agents.view": True,
        "agents.create": False,
        "agents.edit": False,
        "agents.delete": False,
        "agents.run": False,
        "agents.pause": False,
        "agents.resume": False,
        "agents.manage": False,
        "agents.findings.view": True,
        "agents.findings.dismiss": False,
        # Strategy
        "strategy.view": True,
        "strategy.pillars.create": False,
        "strategy.pillars.edit": False,
        "strategy.pillars.delete": False,
        "strategy.objectives.create": False,
        "strategy.objectives.edit": False,
        "strategy.objectives.delete": False,
        "strategy.okrs.create": False,
        "strategy.okrs.edit": False,
        "strategy.okrs.delete": False,
        "strategy.keyresults.create": False,
        "strategy.keyresults.edit": False,
        "strategy.keyresults.delete": False,
        "strategy.initiatives.create": False,
        "strategy.initiatives.edit": False,
        "strategy.initiatives.delete": False,
        "strategy.assumptions.create": False,
        "strategy.assumptions.edit": False,
        "strategy.assumptions.delete": False,
        "strategy.cycles.create": False,
        "strategy.cycles.edit": False,
        "strategy.cycles.delete": False,
        # Events & Intelligence
        "events.view": True,
        "events.create": False,
        "events.edit": False,
        "events.delete": False,
        "intelligence.view": True,
        "intelligence.create": False,
        "intelligence.dismiss": False,
        "intelligence.delete": False,
        # Other
        "comments.view": True,
        "comments.create": True,
        "notifications.view": True,
        "notifications.read": True,
        "starred.view": True,
        "starred.manage": True,
        "files.upload": True,
        "files.view": True,
        "files.delete": False,
        "templates.view": True,
        "templates.create": False,
        "templates.apply": True,
        "templates.edit": False,
        "templates.delete": False,
        "enterprise.view": True,
        "enterprise.create": False,
        "enterprise.edit": False,
        "enterprise.delete": False,
        "enterprise.apis.view": True,
        "enterprise.apis.create": False,
        "connectors.view": True,
        "datasets.view": True,
        "datasets.delete": False,
        "settings.view": True,
        "permissions.view": False,
        "apikeys.manage": False,
        "integrations.manage": False,
        "metrics.view": False,
        "admin.users.manage": False,
        "users.invite": False,
        "users.edit": False,
        "users.delete": False,
        "users.permissions.edit": False,
        "settings.edit": False,
        "permissions.edit": False,
        "audit.view": False,
        "audit.verify": False,
        "privacy.export": False,
        "privacy.delete": False,
        "support.settings": False,
        "support.revoke": False,
        "users.impersonate": False,
    },
    # ═══════════════════════════════════════════════════════════════
    # Guest/Viewer = Stakeholder. Sees everything shared with them.
    # Cannot create, edit, delete, or interact beyond viewing.
    # ═══════════════════════════════════════════════════════════════
    "guest": {
        # Pages & Dashboards — view only
        "pages.view": True,
        "pages.create": False,
        "pages.edit": False,
        "pages.edit.others": False,
        "pages.delete": False,
        "pages.share": False,
        "pages.duplicate": False,
        "pages.members.view": True,
        "pages.members.manage": False,
        "pages.star": True,
        "dashboards.view": True,
        "dashboards.create": False,
        "dashboards.edit": False,
        "dashboards.delete": False,
        "dashboards.export": False,
        "dashboards.lock": False,
        "dashboards.duplicate": False,
        # Widgets — view only
        "widgets.view": True,
        "widgets.create": False,
        "widgets.edit": False,
        "widgets.delete": False,
        "widgets.duplicate": False,
        "widgets.export": False,
        "widgets.refresh": False,
        "widgets.feedback": True,
        # Connections — view only
        "connections.view": True,
        "connections.metadata.view": True,
        "connections.tables.view": True,
        "connections.schemas.view": True,
        "connections.status.view": True,
        "connections.metrics.view": False,
        "connections.create": False,
        "connections.edit": False,
        "connections.delete": False,
        "connections.test": False,
        "connections.sync": False,
        "connections.validate": False,
        # AI — no queries
        "ai.chat": False,
        "ai.query": False,
        "ai.history.view": True,
        "ai.history.delete": False,
        "ai.history.pin": False,
        "ai.history.export": False,
        "ai.generate": False,
        "ai.feedback": True,
        "ai.pipeline": False,
        "ai.davinci": False,
        # Spaces & Crews — view only
        "spaces.view": True,
        "spaces.create": False,
        "spaces.edit": False,
        "spaces.delete": False,
        "spaces.members.view": True,
        "spaces.members.manage": False,
        "spaces.connections.view": True,
        "spaces.connections.manage": False,
        "spaces.crews.view": True,
        "spaces.tables.view": True,
        "spaces.stats.view": False,
        "crews.view": True,
        "crews.create": False,
        "crews.edit": False,
        "crews.delete": False,
        "crews.members.view": True,
        "crews.members.manage": False,
        "crews.stats.view": False,
        # Users
        "users.view": False,
        "users.permissions.view": False,
        "users.self.edit": True,
        "users.self.permissions": True,
        # Agents — view only (guest can't run/pause/resume)
        "agents.view": True,
        "agents.create": False,
        "agents.edit": False,
        "agents.delete": False,
        "agents.run": False,
        "agents.pause": False,
        "agents.resume": False,
        "agents.manage": False,
        "agents.findings.view": True,
        "agents.findings.dismiss": False,
        # Strategy — view only
        "strategy.view": True,
        "strategy.pillars.create": False,
        "strategy.pillars.edit": False,
        "strategy.pillars.delete": False,
        "strategy.objectives.create": False,
        "strategy.objectives.edit": False,
        "strategy.objectives.delete": False,
        "strategy.okrs.create": False,
        "strategy.okrs.edit": False,
        "strategy.okrs.delete": False,
        "strategy.keyresults.create": False,
        "strategy.keyresults.edit": False,
        "strategy.keyresults.delete": False,
        "strategy.initiatives.create": False,
        "strategy.initiatives.edit": False,
        "strategy.initiatives.delete": False,
        "strategy.assumptions.create": False,
        "strategy.assumptions.edit": False,
        "strategy.assumptions.delete": False,
        "strategy.cycles.create": False,
        "strategy.cycles.edit": False,
        "strategy.cycles.delete": False,
        # Events & Intelligence — view only
        "events.view": True,
        "events.create": False,
        "events.edit": False,
        "events.delete": False,
        "intelligence.view": True,
        "intelligence.create": False,
        "intelligence.dismiss": False,
        "intelligence.delete": False,
        # Other
        "comments.view": True,
        "comments.create": False,
        "notifications.view": True,
        "notifications.read": True,
        "starred.view": True,
        "starred.manage": True,
        "files.upload": False,
        "files.view": True,
        "files.delete": False,
        "templates.view": True,
        "templates.create": False,
        "templates.apply": False,
        "templates.edit": False,
        "templates.delete": False,
        "enterprise.view": True,
        "enterprise.create": False,
        "enterprise.edit": False,
        "enterprise.delete": False,
        "enterprise.apis.view": True,
        "enterprise.apis.create": False,
        "connectors.view": True,
        "datasets.view": True,
        "datasets.delete": False,
        "settings.view": True,
        "permissions.view": False,
        "apikeys.manage": False,
        "integrations.manage": False,
        "metrics.view": False,
        "admin.users.manage": False,
        "users.invite": False,
        "users.edit": False,
        "users.delete": False,
        "users.permissions.edit": False,
        "settings.edit": False,
        "permissions.edit": False,
        "audit.view": False,
        "audit.verify": False,
        "privacy.export": False,
        "privacy.delete": False,
        "support.settings": False,
        "support.revoke": False,
        "users.impersonate": False,
    },
}


@dataclass(frozen=True)
class EffectivePermissions:
    platform_role: str
    crew_role: str
    permissions: Dict[str, bool]


class RBACService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.crew_members = CrewMemberRepository(db)
        self.role_perms = RolePermissionRepository(db)
        self.connection_repo = ConnectionRepository(db)
        self.connection_perms = PermissionRepository(db)

    async def get_effective_permissions(
        self,
        user: User,
        *,
        crew_id: Optional[UUID] = None,
        space_id: Optional[UUID] = None,
        connection_id: Optional[UUID] = None,
    ) -> EffectivePermissions:
        # Sky operator without active JIT session: deny everything (Phase 0
        # forward-compatible guard rail; columns ship in the JIT migration).
        if await _is_sky_operator_without_jit(user, self.db):
            logger.warning(
                "rbac.deny_sky_operator_no_jit user_id=%s",
                getattr(user, "id", None),
            )
            return EffectivePermissions(
                platform_role=user.role or "sky_support",
                crew_role="guest",
                permissions={},
            )

        # Customer Owners and Admins bypass crew-level checks. This is the
        # temporary behavior — the Sky Support JIT migration replaces this
        # with the consent flow. Until then, log the bypass so operators can
        # audit post-hoc via application logs.
        #
        # Owner vs Admin: Owner is the tenant founder (single seat). Owner
        # passes EVERY permission, including tenant.delete / billing.manage /
        # tenant.transfer_ownership. Admin passes everything EXCEPT those
        # three — see assert_permission for the enforcement-time split.
        if user.role in ("admin", "owner"):
            logger.info(
                "rbac.admin_bypass.effective_permissions user_id=%s role=%s crew_id=%s space_id=%s connection_id=%s",
                getattr(user, "id", None),
                user.role,
                crew_id,
                space_id,
                connection_id,
            )
            # Return a merged map where known keys are True (unknown keys handled as True by enforcement).
            merged = {}
            for role_map in DEFAULT_ROLE_PERMISSIONS.values():
                merged.update({k: True for k in role_map.keys()})
            # Owner-exclusive perms must be included when the role is owner;
            # admin gets them as False so the assert_permission check can
            # draw the line.
            if user.role == "owner":
                merged["tenant.delete"] = True
                merged["tenant.transfer_ownership"] = True
                merged["billing.manage"] = True
            return EffectivePermissions(
                platform_role=user.role, crew_role="commander", permissions=merged
            )

        crew_role = await self._resolve_context_crew_role(
            user.id, crew_id=crew_id, space_id=space_id, connection_id=connection_id
        )

        defaults = DEFAULT_ROLE_PERMISSIONS.get(crew_role, DEFAULT_ROLE_PERMISSIONS["guest"])
        db_role = await self.role_perms.get_by_role(crew_role)
        merged = {
            **defaults,
            **(db_role.permissions if db_role and db_role.permissions else {}),
        }

        return EffectivePermissions(
            platform_role=user.role, crew_role=crew_role, permissions=merged
        )

    async def _audit_decision(
        self,
        user: User,
        permission_key: str,
        decision: str,
        reason: str,
        resource_kind: Optional[str] = None,
        resource_id: Optional[str] = None,
    ) -> None:
        """Fire-and-forget audit log write. Never blocks the request."""
        try:
            from src.services.audit_service import AuditService

            audit = AuditService(self.db)
            await audit.log_event(
                actor_kind="sky_support" if getattr(user, "is_sky_operator", False) else "user",
                actor_id=getattr(user, "id", None),
                actor_email=getattr(user, "email", None),
                action=permission_key,
                resource_kind=resource_kind,
                resource_id=resource_id,
                decision=decision,
                decision_reason=reason,
            )
        except Exception as exc:
            logger.debug("audit.write_skipped action=%s error=%s", permission_key, exc)

    async def assert_permission(
        self,
        user: User,
        permission_key: str,
        *,
        crew_id: Optional[UUID] = None,
        space_id: Optional[UUID] = None,
        connection_id: Optional[UUID] = None,
    ) -> None:
        resource_id = str(crew_id or space_id or connection_id or "")

        # Derive resource_kind so audit events are queryable per resource.
        if crew_id:
            resource_kind: Optional[str] = "crew"
        elif space_id:
            resource_kind = "space"
        elif connection_id:
            resource_kind = "connection"
        else:
            resource_kind = None

        # Sky operator without active JIT session: hard deny.
        if await _is_sky_operator_without_jit(user, self.db):
            await self._audit_decision(
                user,
                permission_key,
                "deny",
                "sky_support_no_jit",
                resource_kind=resource_kind,
                resource_id=resource_id,
            )
            raise ForbiddenError("Sky support access requires an active JIT consent session")

        # Owner-exclusive permissions — only the tenant Owner can run these,
        # regardless of their crew role or the admin bypass.
        OWNER_EXCLUSIVE_PERMS = {
            "tenant.delete",
            "tenant.transfer_ownership",
            "billing.manage",
        }

        # Owner bypass: owner passes every permission, including the three
        # owner-exclusive ones above.
        if user.role == "owner":
            await self._audit_decision(
                user,
                permission_key,
                "allow",
                "owner_bypass",
                resource_kind=resource_kind,
                resource_id=resource_id,
            )
            return

        # Admin bypass: passes everything EXCEPT owner-exclusive perms.
        if user.role == "admin":
            if permission_key in OWNER_EXCLUSIVE_PERMS:
                await self._audit_decision(
                    user,
                    permission_key,
                    "deny",
                    "admin_cannot_grant_owner_exclusive",
                    resource_kind=resource_kind,
                    resource_id=resource_id,
                )
                raise ForbiddenError(
                    f"Permission '{permission_key}' is reserved for the tenant Owner"
                )
            await self._audit_decision(
                user,
                permission_key,
                "allow",
                "admin_bypass",
                resource_kind=resource_kind,
                resource_id=resource_id,
            )
            return

        eff = await self.get_effective_permissions(
            user, crew_id=crew_id, space_id=space_id, connection_id=connection_id
        )

        if not eff.permissions.get(permission_key, False):
            await self._audit_decision(
                user,
                permission_key,
                "deny",
                f"role={eff.crew_role}",
                resource_kind=resource_kind,
                resource_id=resource_id,
            )
            raise ForbiddenError(f"Permission denied: {permission_key}")

        await self._audit_decision(
            user,
            permission_key,
            "allow",
            f"role={eff.crew_role}",
            resource_kind=resource_kind,
            resource_id=resource_id,
        )

    async def _resolve_context_crew_role(
        self,
        user_id: UUID,
        *,
        crew_id: Optional[UUID],
        space_id: Optional[UUID],
        connection_id: Optional[UUID],
    ) -> CrewRole:
        # Most specific: crew_id
        if crew_id:
            member = await self.crew_members.get_by_crew_and_user(crew_id, user_id)
            return member.role if member and member.role else "guest"  # type: ignore[return-value]

        # Next: resolve from space_id. Prefer the explicit space_members
        # role (two-axis RBAC) and fall back to the best crew role in
        # that space only when the user isn't a direct member. Space
        # roles (commander / navigator / explorer) share vocabulary
        # with crew roles on purpose — no mapping needed, a space
        # commander IS a commander for permission purposes. Platform
        # owner / admin have already bypassed above; this path is for
        # platform `member` users with scoped grants.
        if space_id:
            from sqlalchemy import select
            from src.models.space import SpaceMember

            res = await self.db.execute(
                select(SpaceMember.role).where(
                    SpaceMember.space_id == space_id,
                    SpaceMember.user_id == user_id,
                )
            )
            space_role = res.scalar_one_or_none()
            if space_role and space_role in ("commander", "navigator", "explorer"):
                return space_role  # type: ignore[return-value]
            return await self._best_role_for_user_in_space(user_id, space_id)

        # Next: resolve from connection_id (any crew/space permission that user belongs to)
        if connection_id:
            return await self._best_role_for_user_for_connection(user_id, connection_id)

        # Fallback: best role across all crews
        return await self._best_role_for_user_anywhere(user_id)

    async def _best_role_for_user_in_space(self, user_id: UUID, space_id: UUID) -> CrewRole:
        crew_ids = await self.crew_members.get_crew_ids_by_user_and_space(
            user_id=user_id, space_id=space_id
        )
        if not crew_ids:
            return "guest"

        best_role = "guest"
        best_score = ROLE_PRECEDENCE[best_role]
        for cid in crew_ids:
            member = await self.crew_members.get_by_crew_and_user(cid, user_id)
            role = member.role if member and member.role else "guest"  # type: ignore[assignment]
            score = ROLE_PRECEDENCE.get(role, 0)
            if score > best_score:
                best_score = score
                best_role = role
        return best_role

    async def _best_role_for_user_anywhere(self, user_id: UUID) -> CrewRole:
        crew_ids = await self.crew_members.get_crew_ids_by_user(user_id)
        
        from sqlalchemy import select
        from src.models.space import SpaceMember

        res = await self.db.execute(
            select(SpaceMember.role).where(SpaceMember.user_id == user_id)
        )
        space_roles = res.scalars().all()
        
        if not crew_ids and not space_roles:
            # User has no crew/space memberships — they're operating in their own
            # personal workspace (no shared/team context). Treat them as
            # commander of that personal world so they can bootstrap their
            # first page/dashboard. Once invited to crews/spaces, the best-role
            # resolution below takes over.
            return "commander"

        best_role = "guest"
        best_score = ROLE_PRECEDENCE[best_role]
        
        for role in space_roles:
            score = ROLE_PRECEDENCE.get(role, 0)
            if score > best_score:
                best_score = score
                best_role = role
                
        for cid in crew_ids:
            member = await self.crew_members.get_by_crew_and_user(cid, user_id)
            role = member.role if member and member.role else "guest"  # type: ignore[assignment]
            score = ROLE_PRECEDENCE.get(role, 0)
            if score > best_score:
                best_score = score
                best_role = role
        return best_role

    async def _best_role_for_user_for_connection(
        self, user_id: UUID, connection_id: UUID
    ) -> CrewRole:
        # Owner can manage their connections in the interim model.
        conn = await self.connection_repo.get_by_id(connection_id)
        if conn and conn.created_by == user_id:
            return "commander"

        # Look at connection_permissions, if any, and pick best role in any linked crew/space.
        perms = await self.connection_perms.get_by_connection_id(connection_id)
        best_role = "guest"
        best_score = ROLE_PRECEDENCE[best_role]

        for p in perms:
            if p.crew_id:
                member = await self.crew_members.get_by_crew_and_user(p.crew_id, user_id)
                role = member.role if member and member.role else "guest"  # type: ignore[assignment]
                score = ROLE_PRECEDENCE.get(role, 0)
                if score > best_score:
                    best_score = score
                    best_role = role
            elif p.space_id:
                role = await self._best_role_for_user_in_space(user_id, p.space_id)
                score = ROLE_PRECEDENCE.get(role, 0)
                if score > best_score:
                    best_score = score
                    best_role = role

        return best_role
