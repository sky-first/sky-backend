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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError
from src.core.permissions import TENANT_ADMIN_ROLES, is_tenant_admin
from src.models.space import SpaceMember
from src.models.user import User
from src.repositories.connection import ConnectionRepository
from src.repositories.crew import CrewMemberRepository
from src.repositories.permission import PermissionRepository, RolePermissionRepository

logger = logging.getLogger(__name__)


async def _e_o_cliente_de_casa(user: User, ctx) -> bool:
    """O cliente actual é o dono do domínio do email deste operador?

    Falha fechada: qualquer dúvida — email sem domínio, domínio não
    registado, registo indisponível — devolve ``False``, e o portão do
    consentimento JIT mantém-se. Deixar entrar por engano é pior do que
    recusar por engano.
    """
    email = (getattr(user, "email", "") or "").strip().lower()
    dominio = email.rpartition("@")[2]
    if not dominio:
        return False
    try:
        from src.config.database import AsyncSessionLocal
        from src.services.tenant_domain_service import TenantDomainService

        async with AsyncSessionLocal() as sessao_da_plataforma:
            dono = await TenantDomainService.resolve_by_domain(sessao_da_plataforma, dominio)
    except Exception:  # noqa: BLE001
        logger.warning("rbac.home_tenant_lookup_failed user_id=%s", getattr(user, "id", None))
        return False
    return dono is not None and str(getattr(dono, "id", "")) == str(getattr(ctx, "id", ""))


async def _is_sky_operator_without_jit(user: User, db: AsyncSession) -> bool:
    """Reject Sky operators that lack an active JIT consent session.

    Checks the `support_sessions` table for an active (non-revoked, non-expired)
    session for this operator. If none found, they are blocked.

    The JIT-consent gate only makes sense in multi-tenant mode. When
    ``MULTI_TENANT_ENABLED`` is False the deployment is the Sky
    platform itself (single tenant); operators are accessing their own
    data, not a customer's, so requiring break-glass consent is just
    self-imposed lock-out. The flip side is also implemented below:
    once we route multi-tenant traffic, an operator accessing their
    *home* tenant (the Sky platform DB itself) skips the gate too —
    only cross-tenant access (debugging a customer's space) requires a
    fresh ``support_sessions`` row.
    """
    if not getattr(user, "is_sky_operator", False):
        return False

    # Single-tenant deployment — JIT consent is not applicable. The
    # operator IS the platform; there is no customer to revoke from.
    from src.config.settings import settings

    if not settings.MULTI_TENANT_ENABLED:
        return False

    # Home-tenant access skips the gate too. A Sky operator working on
    # the platform's own default context (e.g. the platform host
    # sky-stg.skyfirstlabs.com, which tenant_resolver maps to the
    # default context via its reserved-slug bypass) is on home turf —
    # there is no customer to break-glass into. Only *cross-tenant*
    # access (debugging a real customer's tenant DB) requires a fresh
    # support_sessions row. This realises the intent documented in this
    # function's docstring, which the multi-tenant path had not yet
    # implemented — operators were being denied even on the platform.
    from src.core.tenant_context import current_tenant

    ctx = current_tenant()
    if ctx.is_default:
        return False

    # Casa deixou de ser só o contexto por omissão.
    #
    # Quando isto foi escrito, a Sky não era cliente de si própria: qualquer
    # cliente resolvido era, por definição, de outra gente. A 16/08/2026 a
    # equipa passou a ter o seu próprio workspace — e a partir daí **toda a
    # equipa ficou trancada fora dele**. Entravam, e o primeiro pedido morria
    # com "Sky support access requires an active JIT consent session": são
    # operadores, o cliente não é o por omissão, e não há sessão de suporte
    # nenhuma — nem faria sentido haver, é a casa deles.
    #
    # A regra certa é a que o docstring já descrevia: o consentimento JIT é
    # para acesso **a outro cliente**. O cliente dono do domínio do email do
    # operador é a casa dele. Um operador da Sky dentro do workspace de um
    # cliente continua a precisar de sessão de suporte, que é o que isto
    # protege.
    if await _e_o_cliente_de_casa(user, ctx):
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


CrewRole = str  # owner | editor | viewer

# Phase 7 (2026-05-01) — the canonical role vocabulary is exclusively
# owner / editor / viewer for both Space and Crew memberships. The
# pre-Phase-7 commander/navigator/explorer triple (and the even older
# admin/member/guest enums) were normalized in DB by the
# `normalize_member_roles_phase7_…` migration; any callsite that still
# emits one of those values is a bug — `_canonicalize_role` no longer
# translates them and floors unknown values to viewer to fail closed.

ROLE_PRECEDENCE: Dict[str, int] = {
    # "no_access" is the deny-all sentinel for users who have NO membership
    # in the requested scope (Space/Crew). It's not a real role — it never
    # appears on a SpaceMember/CrewMember row, only as a return value from
    # the resolver when the user is an outsider to the requested context.
    "no_access": -1,
    "viewer": 0,
    "editor": 1,
    "owner": 2,
}


def _canonicalize_role(role: Optional[str]) -> CrewRole:
    """Floor any unknown / missing role to viewer.

    Phase 7 vocabulary is the only accepted set; this function does NOT
    translate legacy enums anymore. Callers that pass a value outside
    {owner, editor, viewer, no_access} get viewer back so the
    enforcement path defaults closed rather than opens.
    """
    if role in ("owner", "editor", "viewer", "no_access"):
        return role
    return "viewer"


DEFAULT_ROLE_PERMISSIONS: Dict[str, Dict[str, bool]] = {
    # ═══════════════════════════════════════════════════════════════
    # Owner = Manager. Can do everything within their scope.
    # Manages people, creates structure, full CRUD on resources.
    # CANNOT do org-level admin things.
    # ═══════════════════════════════════════════════════════════════
    "owner": {
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
        # Owner uploads still need an Owner/Admin approval —
        # platform-level chokepoint keeps a single audit trail. The
        # owner cannot approve their own scope's uploads anymore.
        "files.approve": False,
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
        # Owner is a CREW role. Platform-level perms below are reserved
        # for platform_admin (and owner above it). Wave 3 of ADR-002 fixed
        # the leak where Owner accidentally had global config powers.
        "settings.view": True,  # read-only config view stays (benign)
        "permissions.view": False,  # RBAC matrix is admin-only
        "apikeys.manage": False,  # global tenant secrets
        "integrations.manage": False,  # global integrations
        "metrics.view": False,  # platform usage/metrics
        # Admin-only (owner cannot)
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
    # Editor = Senior Developer. Can create, edit, use AI, share.
    # Cannot manage people or structure. Cannot delete.
    # ═══════════════════════════════════════════════════════════════
    "editor": {
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
        # Agents (editor can run/pause/resume own runs, no create/edit/delete)
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
        "files.upload": True,  # editor pode fazer upload (fica pending_approval até owner aprovar)
        "files.view": True,
        "files.delete": False,
        "files.approve": False,  # só owner pode aprovar uploads de editor (Knowledge)
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
        # Editor is a CREW role too. Wave 3: metrics.view is platform-
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
    # Viewer = Developer. Creates own pages, uses AI, runs queries.
    # Cannot edit others' work. Cannot manage or delete.
    # ═══════════════════════════════════════════════════════════════
    "viewer": {
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
        # Agents (viewer = view-only; no run/pause/resume)
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
        "files.upload": False,  # viewer só visualiza
        "files.view": True,
        "files.delete": False,
        "files.approve": False,
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
    # Retired (A1): the "guest" role lived here as a 164-line dict
    # that denied AI access by default. Every fresh demo visitor
    # without a crew membership fell through to it via _resolve_*
    # helpers and got "no permission to run queries" on first chat.
    # Replaced by "viewer" as the floor — viewer keeps view + AI
    # but loses creation/edit. Legacy DB rows with role="guest" are
    # mapped via _canonicalize_role() so no migration is required.
    # ═══════════════════════════════════════════════════════════════
    # Tenancy gate. Returned by _best_role_for_user_in_space when the
    # caller has no membership in the requested Space. Empty dict =
    # eff.permissions.get(key, False) returns False for every key →
    # assert_permission denies. Must NEVER appear on a SpaceMember /
    # CrewMember row in the DB; this is a runtime sentinel only.
    "no_access": {},
}

# Phase 7 — alias the new canonical names onto the existing dicts so the
# resolver can serve callers that pass `crew_role="owner"` (the Phase-7
# vocabulary) without having to duplicate hundreds of lines of permission
# tables. _canonicalize_role normalises every read to the new vocabulary,
# so in practice the lookups in this module always go through these
# aliased keys; the legacy keys are retained only so callers that still
# stringify the old names directly (e.g. some unit tests) keep working.
DEFAULT_ROLE_PERMISSIONS["owner"] = DEFAULT_ROLE_PERMISSIONS["owner"]
DEFAULT_ROLE_PERMISSIONS["editor"] = DEFAULT_ROLE_PERMISSIONS["editor"]
DEFAULT_ROLE_PERMISSIONS["viewer"] = DEFAULT_ROLE_PERMISSIONS["viewer"]


# Platform-level grants for users with `user.role == "member"` (or the
# legacy "user"). Lucas's 2026-04-30 brief: Member should be able to
# do almost everything Owner does — ask the AI, build dashboards
# and widgets, run agents, upload to Knowledge (subject to approval),
# view connections / Spaces / Crews / members. The line that
# differentiates Member from Owner / Admin is restricted to:
#   - mint / edit / delete connections
#   - approve Knowledge uploads
#   - manage users (invite / edit / delete / impersonate)
#   - billing & ownership transfer
#   - escalate tickets to SKY support
#   - audit / privacy controls
#
# This mirrors the Owner grant set with members.manage and the
# admin-only knobs flipped off so a Member with no Space membership
# is still productive in their personal scope.
#: Chaves que **nenhum papel de projeto concede**. São decisão do cliente:
#: ou se tem a permissão, ou se pede acesso e um admin aprova.
#:
#: Sem isto, "qualquer pessoa cria um projeto" transformava-se em "qualquer
#: pessoa cunha ligações de dados": quem cria um projeto fica dono dele, e o
#: papel de dono era empilhado por cima do de member, trazendo consigo o
#: `connections.create`. Confirmado em produção a 19/08 — o member criou um
#: projeto e a seguir uma ligação, com 201 nas duas.
#:
#: `connections.sync/test/validate` ficam de fora de propósito: operam uma
#: ligação que **já** foi autorizada, e isso é trabalho de quem conduz o
#: projeto.
CHAVES_QUE_O_PROJETO_NAO_CONCEDE = (
    "connections.create",
    "connections.edit",
    "connections.delete",
)

MEMBER_PLATFORM_PERMISSIONS: Dict[str, bool] = {
    # Pages & Dashboards
    "pages.view": True,
    "pages.create": True,
    "pages.edit": True,
    "pages.edit.others": False,
    "pages.delete": True,
    "pages.share": True,
    "pages.duplicate": True,
    "pages.star": True,
    "pages.members.view": True,
    "pages.members.manage": False,
    # Widgets
    "widgets.view": True,
    "widgets.create": True,
    "widgets.edit": True,
    "widgets.delete": True,
    "widgets.duplicate": True,
    "widgets.export": True,
    "widgets.refresh": True,
    "widgets.feedback": True,
    # Connections — VIEW only. The big one Lucas flagged: Member can
    # see and query connections that Owner/Admin assigned to a Space
    # the Member belongs to, but cannot create / edit / delete the
    # connection itself. Approval / mint stays platform-admin only.
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
    # AI — full chat + query so a Member is productive on day one.
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
    # Agents — Member can author and run their own agents on data
    # they're allowed to query.
    "agents.view": True,
    "agents.create": True,
    "agents.edit": True,
    "agents.delete": True,
    "agents.run": True,
    "agents.pause": True,
    "agents.resume": True,
    "agents.manage": False,
    "agents.findings.view": True,
    "agents.findings.dismiss": True,
    # Events / Intelligence
    "events.view": True,
    "events.create": False,
    "intelligence.view": True,
    "intelligence.create": True,
    "intelligence.dismiss": True,
    # Strategy (write within a Space they belong to; no destructive)
    "strategy.view": True,
    "strategy.pillars.create": True,
    "strategy.pillars.edit": True,
    "strategy.objectives.create": True,
    "strategy.objectives.edit": True,
    "strategy.okrs.create": True,
    "strategy.okrs.edit": True,
    "strategy.keyresults.create": True,
    "strategy.keyresults.edit": True,
    "strategy.initiatives.create": True,
    "strategy.initiatives.edit": True,
    "strategy.assumptions.create": True,
    "strategy.assumptions.edit": True,
    # Projetos (Spaces): **qualquer pessoa cria**. É o modelo decidido a
    # 18/08 — criar um projeto não é privilégio nenhum, o que precisa de
    # autorização é **ligar dados** ao projeto. Quem cria fica dono do seu
    # projeto (SpaceMember role=owner) e a partir daí gere-o; para lhe pôr
    # dados, pede acesso e um admin do cliente aprova.
    #
    # Isto estava a `False` e contradizia o modelo: o member levava 403 em
    # `POST /spaces`. Reparar que `spaces.edit`/`delete` ficam a `False` de
    # propósito — dizem respeito a projetos dos **outros**; sobre o seu, o
    # member passa pela pertença (SpaceMember owner), não por esta tabela.
    "spaces.view": True,
    "spaces.create": True,
    "spaces.edit": False,
    "spaces.delete": False,
    "spaces.members.view": True,
    "spaces.members.manage": False,
    "spaces.connections.view": True,
    "spaces.connections.manage": False,
    "spaces.crews.view": True,
    "spaces.tables.view": True,
    "spaces.stats.view": True,
    "crews.view": True,
    "crews.create": False,
    "crews.edit": False,
    "crews.delete": False,
    "crews.members.view": True,
    "crews.members.manage": False,
    "crews.stats.view": True,
    # Self
    "users.self.edit": True,
    "users.self.permissions": True,
    # Templates / Enterprise
    "templates.view": True,
    "templates.apply": True,
    "templates.create": False,
    "templates.edit": False,
    "templates.delete": False,
    "enterprise.view": True,
    "enterprise.apis.view": True,
    "connectors.view": True,
    "datasets.view": True,
    # Collaboration
    "comments.view": True,
    "comments.create": True,
    "notifications.view": True,
    "notifications.read": True,
    "starred.view": True,
    "starred.manage": True,
    # Files (Knowledge Library) — Member CAN upload but uploads wait
    # in pending_approval; cannot approve, cannot delete other
    # people's files.
    "files.upload": True,
    "files.view": True,
    "files.delete": False,
    "files.approve": False,
    # Settings — read-only config lens.
    "settings.view": True,
    # Admin-only knobs explicitly denied so the matrix is honest.
    "admin.users.manage": False,
    "users.invite": False,
    "users.edit": False,
    "users.delete": False,
    "users.permissions.edit": False,
    "permissions.view": False,
    "permissions.edit": False,
    "settings.edit": False,
    "apikeys.manage": False,
    "integrations.manage": False,
    "metrics.view": False,
    "audit.view": False,
    "audit.verify": False,
    "privacy.export": False,
    "privacy.delete": False,
    "support.settings": False,
    "support.revoke": False,
    "users.impersonate": False,
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
                crew_role="viewer",  # floor; permissions={} denies all anyway
                permissions={},
            )

        # Customer SuperAdmins and Admins bypass crew-level checks. This is
        # the temporary behavior — the Sky Support JIT migration replaces
        # this with the consent flow. Until then, log the bypass so operators
        # can audit post-hoc via application logs.
        #
        # SuperAdmin vs Admin: SuperAdmin is the tenant founder (single seat).
        # SuperAdmin passes EVERY permission, including tenant.delete,
        # billing.manage and tenant.transfer_ownership. Admin passes
        # everything EXCEPT those three — see assert_permission for the
        # enforcement-time split.
        #
        # Tenant-level admins (super_admin + admin) bypass the granular
        # crew/space matrix. The DB migration ``rename_role_20260603``
        # already swapped any legacy ``owner`` tenant rows to
        # ``super_admin``; this code path no longer needs to recognise
        # ``owner`` at the tenant level (owner is now a Space/Crew/Page
        # membership role only).
        SUPER_ADMIN_ROLES = ("super_admin",)
        if is_tenant_admin(user):
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
            # Founder-exclusive perms only apply to ``super_admin``;
            # ``admin`` gets them as False so the assert_permission check
            # can draw the line.
            if user.role in SUPER_ADMIN_ROLES:
                merged["tenant.delete"] = True
                merged["tenant.transfer_ownership"] = True
                merged["billing.manage"] = True
            return EffectivePermissions(
                platform_role=user.role, crew_role="owner", permissions=merged
            )

        # Platform-level Member (or legacy "user") gets a baseline grant
        # set so they can use the AI, build dashboards, run agents and
        # upload to the Knowledge Library on day one — even before
        # joining any Space. Lucas's 2026-04-30 brief: "member pode
        # fazer tudo, so nao pode fazer algumas como de admin".
        # Scope-level grants (owner/editor/viewer) still
        # override on top via the merged path below if the user has a
        # SpaceMember/CrewMember row.
        if user.role in ("member", "user"):
            base = dict(MEMBER_PLATFORM_PERMISSIONS)
            # Stack the scope role on top so a Member who is also a
            # Owner in some Space gets the Owner upgrades for
            # that scope. _resolve_context_crew_role returns "no_access"
            # when the user has nothing in scope — in that case the base
            # Member dict is what they get.
            scope_role = await self._resolve_context_crew_role(
                user.id, crew_id=crew_id, space_id=space_id, connection_id=connection_id
            )
            if scope_role != "no_access":
                scope_defaults = DEFAULT_ROLE_PERMISSIONS.get(scope_role, {})
                db_role = await self.role_perms.get_by_role(scope_role)
                base.update(scope_defaults)
                if db_role and db_role.permissions:
                    base.update(db_role.permissions)
                # O papel de projeto não pode conceder o que é decisão do
                # cliente. Repor essas chaves ao que o member tem por
                # omissão, depois de todo o empilhamento.
                for chave in CHAVES_QUE_O_PROJETO_NAO_CONCEDE:
                    base[chave] = MEMBER_PLATFORM_PERMISSIONS.get(chave, False)
            return EffectivePermissions(
                platform_role=user.role, crew_role=scope_role, permissions=base
            )

        crew_role = await self._resolve_context_crew_role(
            user.id, crew_id=crew_id, space_id=space_id, connection_id=connection_id
        )

        defaults = DEFAULT_ROLE_PERMISSIONS.get(crew_role, DEFAULT_ROLE_PERMISSIONS["viewer"])
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

        # SuperAdmin-exclusive permissions — só o fundador do cliente as corre,
        # independentemente do papel no projeto ou do desvio do admin.
        #
        # **Derivada, não escrita à mão.** Esta lista tinha três chaves; a
        # tabela de regras tem quatro com `owner_only`. A que ficou de fora era
        # `permissions.edit` — ou seja, **um admin do cliente podia editar a
        # matriz de permissões e dar-se a si próprio o que quisesse**, quando o
        # desenho diz que isso é do fundador.
        #
        # Apanhado a 18/08/2026 comparando `Authorization.can()` com
        # `assert_permission()` nas contas de teste do sandbox: para
        # `permissions.edit` o admin dava `can()=False` e `rota=True`. Duas
        # listas com a mesma verdade divergem sempre — mais cedo ou mais tarde
        # alguém acrescenta a uma e esquece a outra, que é exactamente o que
        # aconteceu. Passa a sair de `PERMISSION_RULES`, que é onde a decisão
        # vive.
        from src.services.authorization import PERMISSION_RULES as _REGRAS

        SUPER_ADMIN_EXCLUSIVE_PERMS = {
            chave for chave, (_escopo, exigido) in _REGRAS.items() if exigido == "owner_only"
        }
        OWNER_EXCLUSIVE_PERMS = SUPER_ADMIN_EXCLUSIVE_PERMS  # back-compat alias

        # DATA/CONTENT plane (Option B, 2026-06): platform role does NOT
        # grant content access. For these keys we skip the super_admin/admin
        # bypass and delegate to the membership-aware Authorization resolver,
        # so an admin who is not a Space/Crew member is denied content.
        from src.services.authorization import DATA_PLANE_PERMS

        is_data_plane = permission_key in DATA_PLANE_PERMS

        # SuperAdmin bypass: passes every permission, including the three
        # exclusive ones above. After the 2026-06-03 DB migration the
        # tenant founder role is canonically ``super_admin``; legacy
        # ``owner`` rows were already converted in
        # ``rename_role_20260603`` so we no longer need an alias here.
        if user.role == "super_admin" and not is_data_plane:
            await self._audit_decision(
                user,
                permission_key,
                "allow",
                "super_admin_bypass",
                resource_kind=resource_kind,
                resource_id=resource_id,
            )
            return

        # Admin bypass: passes everything EXCEPT super_admin-exclusive perms.
        if user.role == "admin" and not is_data_plane:
            if permission_key in SUPER_ADMIN_EXCLUSIVE_PERMS:
                await self._audit_decision(
                    user,
                    permission_key,
                    "deny",
                    "admin_cannot_grant_super_admin_exclusive",
                    resource_kind=resource_kind,
                    resource_id=resource_id,
                )
                raise ForbiddenError(
                    f"Permission '{permission_key}' is reserved for the tenant SuperAdmin"
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

        # Phase 1 of the RBAC rewrite: delegate to the new Authorization
        # resolver (deterministic translation table, no editable matrix).
        # The 6×80 DEFAULT_ROLE_PERMISSIONS dict is no longer the source
        # of truth — every key in active use now lives in
        # `src/services/authorization.py::PERMISSION_RULES`.
        from src.services.authorization import Authorization, PERMISSION_RULES

        rule = PERMISSION_RULES.get(permission_key)
        if rule is None:
            await self._audit_decision(
                user,
                permission_key,
                "deny",
                "unknown_permission_key",
                resource_kind=resource_kind,
                resource_id=resource_id,
            )
            raise ForbiddenError(f"Permission denied: {permission_key}")
        scope_kind, _required = rule

        # Resolve the effective Space id for space-scoped checks. Crew checks
        # walk to crew.space_id; connection checks defer to the existing
        # _best_role_for_user_for_connection logic (multi-Space sharing).
        effective_space_id: Optional[UUID] = space_id
        if scope_kind == "space" and effective_space_id is None:
            if crew_id is not None:
                from src.models.crew import Crew

                crew_row = (
                    await self.db.execute(select(Crew).where(Crew.id == crew_id))
                ).scalar_one_or_none()
                if crew_row is not None:
                    effective_space_id = crew_row.space_id
            elif connection_id is not None:
                # Connections fan out across Spaces (SpaceConnection +
                # CrewConnection). Phase 1 uses the existing legacy
                # walker plus an "anywhere" fallback to preserve the
                # current allow/deny matrix; Phase 2 will tighten this
                # via the new resource_acl table (per-resource grants).
                legacy_role = await self._best_role_for_user_for_connection(user.id, connection_id)
                if legacy_role in (None, "no_access"):
                    legacy_role = await self._best_role_for_user_anywhere(user.id)

                from src.services.authorization import (
                    LEGACY_TO_NEW_SPACE_ROLE,
                    SPACE_ROLE_LEVEL,
                    SpaceRole,
                )

                actual = LEGACY_TO_NEW_SPACE_ROLE.get(legacy_role)
                level_to_pass = {
                    "viewer": SpaceRole.VIEWER,
                    "editor": SpaceRole.EDITOR,
                    "owner": SpaceRole.OWNER,
                }[_required]
                allowed = (
                    actual is not None
                    and SPACE_ROLE_LEVEL[actual] >= SPACE_ROLE_LEVEL[level_to_pass]
                )
                if allowed:
                    await self._audit_decision(
                        user,
                        permission_key,
                        "allow",
                        f"connection_role={actual.value if actual else None}",
                        resource_kind=resource_kind,
                        resource_id=resource_id,
                    )
                    return
                await self._audit_decision(
                    user,
                    permission_key,
                    "deny",
                    f"connection_role={actual.value if actual else None}",
                    resource_kind=resource_kind,
                    resource_id=resource_id,
                )
                raise ForbiddenError(f"Permission denied: {permission_key}")

        # No specific scope given for a space-scoped permission: fall back
        # to the user's best role anywhere (matches old behavior). The
        # tight per-resource isolation lands in Phase 2 with resource_acl.
        if scope_kind == "space" and effective_space_id is None:
            # Quem não está em projeto nenhum é dono do SEU mundo, não de tudo.
            #
            # `_best_role_for_user_anywhere` devolve "owner" a quem não tem
            # espaços nem equipas, e a intenção está escrita lá: alguém acabado
            # de entrar tem de conseguir criar a primeira página. O problema é
            # que esse "dono do mundo pessoal" escorregava para permissões que
            # não são do mundo pessoal — cunhar uma ligação de dados e
            # administrar membros de projetos.
            #
            # Confirmado em produção a 18/08/2026 com contas reais no sandbox:
            # um `member` sem um único projeto passava em `connections.create`,
            # `connections.sync`, `spaces.members.manage` e `agents.create`. E
            # a rota `POST /connections` chama exactamente este caminho sem
            # `space_id`, portanto era alcançável do browser. Criar uma ligação
            # é apontar a Sky a uma base de dados à escolha de quem a cria.
            #
            # O `Authorization.can()` já negava tudo isto — as duas vias de
            # autorização discordavam, e a usada nas rotas era a permissiva.
            #
            # `MEMBER_PLATFORM_PERMISSIONS` já diz exactamente o que um member
            # pode fazer sem projeto (páginas sim, ligações não), e é o mapa que
            # escreve a decisão do Lucas de 30/04. Passa a ser ele a mandar.
            if not is_tenant_admin(user) and not await self._tem_projetos(user.id):
                permitido = MEMBER_PLATFORM_PERMISSIONS.get(permission_key, False)
                await self._audit_decision(
                    user,
                    permission_key,
                    "allow" if permitido else "deny",
                    "sem_projetos_grants_de_member",
                    resource_kind=resource_kind,
                    resource_id=resource_id,
                )
                if permitido:
                    return
                raise ForbiddenError(f"Permission denied: {permission_key}")

            legacy_role = await self._best_role_for_user_anywhere(user.id)
            from src.services.authorization import (
                LEGACY_TO_NEW_SPACE_ROLE,
                SPACE_ROLE_LEVEL,
                SpaceRole,
            )

            actual = LEGACY_TO_NEW_SPACE_ROLE.get(legacy_role)
            level_to_pass = {
                "viewer": SpaceRole.VIEWER,
                "editor": SpaceRole.EDITOR,
                "owner": SpaceRole.OWNER,
            }[_required]
            if actual is not None and SPACE_ROLE_LEVEL[actual] >= SPACE_ROLE_LEVEL[level_to_pass]:
                await self._audit_decision(
                    user,
                    permission_key,
                    "allow",
                    f"anywhere_role={actual.value}",
                    resource_kind=resource_kind,
                    resource_id=resource_id,
                )
                return
            await self._audit_decision(
                user,
                permission_key,
                "deny",
                f"anywhere_role={actual.value if actual else None}",
                resource_kind=resource_kind,
                resource_id=resource_id,
            )
            raise ForbiddenError(f"Permission denied: {permission_key}")

        allowed = await Authorization(self.db).can(
            user,
            permission_key,
            space_id=effective_space_id,
            crew_id=crew_id,
        )

        if not allowed:
            await self._audit_decision(
                user,
                permission_key,
                "deny",
                "authorization_resolver",
                resource_kind=resource_kind,
                resource_id=resource_id,
            )
            raise ForbiddenError(f"Permission denied: {permission_key}")

        await self._audit_decision(
            user,
            permission_key,
            "allow",
            "authorization_resolver",
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
            return _canonicalize_role(member.role if member else None)

        # Next: resolve from space_id. Prefer the explicit space_members
        # role (two-axis RBAC) and fall back to the best crew role in
        # that space only when the user isn't a direct member. Space
        # roles (owner / editor / viewer) share vocabulary with crew
        # roles on purpose — no mapping needed, a space owner IS an
        # owner for permission purposes. Platform owner / admin have
        # already bypassed above; this path is for platform `member`
        # users with scoped grants.
        if space_id:
            res = await self.db.execute(
                select(SpaceMember.role).where(
                    SpaceMember.space_id == space_id,
                    SpaceMember.user_id == user_id,
                )
            )
            space_role = res.scalar_one_or_none()
            if space_role:
                # Legacy normalization: pre-A1 demo signups created
                # SpaceMember.role="admin" (and the original two-axis
                # design briefly considered "member"). Treat them as
                # their owner/viewer equivalents so existing rows
                # keep working without a DB migration.
                space_role = {
                    "admin": "owner",
                    "member": "viewer",
                }.get(space_role, space_role)
                if space_role in ("owner", "editor", "viewer"):
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
        # The SpaceMember lookup at the call site already returned None
        # (otherwise we wouldn't be here). If the user has no crew in this
        # Space either, they're an outsider — return the deny-all sentinel
        # so cross-tenant requests don't accidentally inherit viewer's
        # ai.query/view grants. This is the tenancy gate that "guest"
        # used to enforce.
        if not crew_ids:
            return "no_access"

        best_role: CrewRole = "viewer"
        best_score = ROLE_PRECEDENCE[best_role]
        for cid in crew_ids:
            member = await self.crew_members.get_by_crew_and_user(cid, user_id)
            role = _canonicalize_role(member.role if member else None)
            score = ROLE_PRECEDENCE.get(role, 0)
            if score > best_score:
                best_score = score
                best_role = role
        return best_role

    async def _tem_projetos(self, user_id: UUID) -> bool:
        """Está em algum projeto ou equipa?

        Separado de `_best_role_for_user_anywhere` de propósito: aquela função
        responde "que papel tem", e para quem não tem lado nenhum inventa
        "owner" — que é o comportamento certo para o mundo pessoal e errado
        para tudo o resto. Esta responde só à pergunta que interessa ao portão.

        Duas consultas com ``LIMIT 1`` em vez do repositório de equipas: aqui
        basta saber **se** existe alguma, e o repositório carrega a lista toda.
        """
        from src.models.crew import CrewMember

        res = await self.db.execute(
            select(SpaceMember.id).where(SpaceMember.user_id == user_id).limit(1)
        )
        if res.first() is not None:
            return True
        res = await self.db.execute(
            select(CrewMember.id).where(CrewMember.user_id == user_id).limit(1)
        )
        return res.first() is not None

    async def _best_role_for_user_anywhere(self, user_id: UUID) -> CrewRole:
        crew_ids = await self.crew_members.get_crew_ids_by_user(user_id)

        res = await self.db.execute(select(SpaceMember.role).where(SpaceMember.user_id == user_id))
        space_roles = res.scalars().all()

        if not crew_ids and not space_roles:
            # User has no crew/space memberships — they're operating in their own
            # personal workspace (no shared/team context). Treat them as
            # owner of that personal world so they can bootstrap their
            # first page/dashboard. Once invited to crews/spaces, the best-role
            # resolution below takes over.
            return "owner"

        best_role: CrewRole = "viewer"
        best_score = ROLE_PRECEDENCE[best_role]

        for role in space_roles:
            canonical = _canonicalize_role(role)
            score = ROLE_PRECEDENCE.get(canonical, 0)
            if score > best_score:
                best_score = score
                best_role = canonical

        for cid in crew_ids:
            member = await self.crew_members.get_by_crew_and_user(cid, user_id)
            role = _canonicalize_role(member.role if member else None)
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
            return "owner"

        # Look at connection_permissions, if any, and pick best role in any linked crew/space.
        perms = await self.connection_perms.get_by_connection_id(connection_id)
        best_role: CrewRole = "viewer"
        best_score = ROLE_PRECEDENCE[best_role]

        for p in perms:
            if p.crew_id:
                member = await self.crew_members.get_by_crew_and_user(p.crew_id, user_id)
                role = _canonicalize_role(member.role if member else None)
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
