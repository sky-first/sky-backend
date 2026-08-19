"""Authorization — single entry point for every "can this user do X?" check.

Replaces the old 14×80 editable permission matrix (RBACService +
permission_service) with a deterministic, code-defined translation
between permission keys and (scope, required_level) rules. The
matrix UI is gone in favour of explicit per-resource sharing
(see resource_acl table introduced in Phase 2).

Model:
  • Platform roles:  super_admin | admin | member  (legacy alias: owner → super_admin)
  • Space roles:     owner | editor | viewer  (per Space membership)
  • Resource ACL:    explicit overrides on individual connections /
                      dashboards / agents / knowledge files (Phase 2)

Resolution order in `can(...)`:
  1. Sky support without active JIT          → deny
  2. Platform super_admin                    → allow (except never)
  3. Platform admin                          → allow except owner-only
  4. Action category:
       - tenant       → check user.role only (member denied for admin actions)
       - space        → resolve user's role on the resource's Space, compare
                        against required_level
                        (resource_acl override applied in Phase 2)
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError
from src.models.space import SpaceMember
from src.models.user import User


# ─── Role enums ──────────────────────────────────────────────────────────────


class PlatformRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    OWNER = "owner"  # legacy alias — DB rows may still carry this value
    ADMIN = "admin"
    MEMBER = "member"


class SpaceRole(str, Enum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


SPACE_ROLE_LEVEL = {SpaceRole.VIEWER: 1, SpaceRole.EDITOR: 2, SpaceRole.OWNER: 3}


# Phase 7 — the Space-axis vocabulary is exclusively owner/editor/viewer.
# The pre-Phase-7 mapping that translated commander/navigator/explorer
# (and the older admin/member/guest enums) was retired together with the
# resolver-level normalisation in rbac_service.py. DB rows were
# normalised by the `normalize_member_roles_phase7_…` migration; any
# caller that still emits a pre-Phase-7 string falls through this dict
# and is treated as an unknown level by SPACE_ROLE_LEVEL.
SPACE_ROLE_LOOKUP = {
    "owner": SpaceRole.OWNER,
    "editor": SpaceRole.EDITOR,
    "viewer": SpaceRole.VIEWER,
}
# Backwards-compat alias — kept for callers that still import the
# previous name. New code should use SPACE_ROLE_LOOKUP directly.
LEGACY_TO_NEW_SPACE_ROLE = SPACE_ROLE_LOOKUP


# ─── Action rules ────────────────────────────────────────────────────────────

Scope = Literal["tenant", "space"]
RequiredLevel = Literal[
    "owner_only",        # only platform Owner
    "admin_or_above",    # platform Owner or Admin
    "any_member",        # any authenticated platform user
    "viewer",            # space membership ≥ viewer
    "editor",            # space membership ≥ editor
    "owner",             # space membership = owner
]


# Translation between the 32 permission keys still used by call sites
# and the new (scope, required_level) tuples. Phases 2-7 progressively
# move call sites from `assert_permission("foo.bar")` to direct
# `assert_can(action, resource)` calls; this dict is the migration bridge.
# Permission keys that act on the Space itself rather than on a
# resource inside it. For these, only space_role counts — Crew
# membership confers no escalation, even when crew_id is passed.
# Reason: an "Audit Crew" Owner manages Audit, not the Finance
# Space's member list.
SPACE_ADMIN_KEYS: frozenset[str] = frozenset({
    "spaces.members.manage",
})


# ── DATA / CONTENT plane (2026-06, "management vs data plane", Option B) ──
# Permission keys that read/act on a Space/Crew's CONTENT (querying data,
# running agents, seeing agent insights/findings, chat). For these keys the
# platform-role bypass (super_admin/admin/owner) does NOT apply — access
# requires real Space/Crew MEMBERSHIP. A platform admin manages the
# structure but cannot see content of a crew they were not added to.
# Management keys (listing/creating/configuring spaces/crews/members,
# connection config, settings, audit) are NOT here and keep the admin
# bypass. Personal-mode keys (e.g. ``ai.query.personal``) are NOT here —
# they have no space/crew to gate on. Grow this set per-phase as each
# content endpoint is wired to pass the right space_id/crew_id.
# IMPORTANT — two rules for membership of this set:
#  1. The key MUST have a ("space", level) rule in PERMISSION_RULES, else
#     skipping the bypass makes can() fall through to "rule is None →
#     return False" and deny EVERYONE.
#  2. The key MUST always be asserted WITH a space_id/crew_id at every call
#     site. Keys used by "list across my accessible scopes" endpoints
#     (e.g. agents.findings.view in list_all_insights, which asserts with NO
#     context and does its own membership filtering) would wrongly hard-deny
#     here — those are gated per-endpoint via ``assert_content_access`` on
#     the resource's scope instead, NOT through this central set.
# ``ai.query`` qualifies: it is only used when a space_id is present
# (personal queries use the separate ``ai.query.personal`` key).
DATA_PLANE_PERMS: frozenset[str] = frozenset({
    "ai.query",
})


PERMISSION_RULES: dict[str, Tuple[Scope, RequiredLevel]] = {
    # Owner-exclusive (tenant level)
    "billing.manage":            ("tenant", "owner_only"),
    "tenant.delete":             ("tenant", "owner_only"),
    "tenant.transfer_ownership": ("tenant", "owner_only"),
    "permissions.edit":          ("tenant", "owner_only"),

    # Owner + Admin
    "audit.view":                ("tenant", "admin_or_above"),
    "users.impersonate":         ("tenant", "admin_or_above"),
    "users.view":                ("tenant", "admin_or_above"),

    # Any member
    "crews.create":              ("tenant", "any_member"),
    # AI in Personal scope — any authenticated platform user can ask
    # the AI without being a member of any Space. Personal is the
    # aggregated read view of every Space the user belongs to (plus
    # their own data); cross-tenant leakage is prevented at the
    # connection layer, not here. Without this key the FE resolver
    # short-circuits Personal-mode chat (space-scoped rules need a
    # space_id and Personal has none). The /ai/query endpoint picks
    # this key when the request omits space_id, and ai.query (below)
    # when present.
    "ai.query.personal":         ("tenant", "any_member"),

    # Owner / Admin only — Space creation is an org-structure action.
    # Letting platform Members spawn Spaces creates ungoverned silos
    # (each one carries its own service principal, RBAC scope, and
    # knowledge-graph footprint), so we keep it on the same plane as
    # `users.view` / `audit.view`. Demo signup bypasses this rule by
    # going through DemoService → repository directly (system action,
    # not the API gate); see src/services/demo_service.py.
    # Criar projeto é de qualquer pessoa — o que precisa de autorização é
    # ligar-lhe dados. Note-se que `crews.create` já era `any_member` logo
    # acima: as duas tabelas discordavam entre si sobre o mesmo modelo.
    "spaces.create":             ("tenant", "any_member"),

    # Space — read (≥ viewer)
    "ai.query":                  ("space", "viewer"),
    "data.query.run":            ("space", "viewer"),
    "connections.view":          ("space", "viewer"),
    "metrics.view":              ("space", "viewer"),
    "pages.view":                ("space", "viewer"),
    "agents.view":               ("space", "viewer"),
    "agents.findings.view":      ("space", "viewer"),
    "crews.view":                ("space", "viewer"),

    # Space — write (≥ editor)
    # Cunhar e editar ligações é do **dono do projeto**. Esta tabela dizia
    # `editor` enquanto o `DEFAULT_ROLE_PERMISSIONS` do `rbac_service` dizia
    # `False` para editor — as duas vias de autorização do próprio backend a
    # discordarem sobre a fronteira que mais importa, que é ligar dados. As
    # rotas usam o `assert_permission` (a restritiva), por isso na prática
    # ninguém passou; mas basta uma rota nova chamar `Authorization.can()`
    # para um editor cunhar uma ligação.
    "connections.create":        ("space", "owner"),
    "connections.edit":          ("space", "owner"),
    "connections.sync":          ("space", "editor"),
    "connections.validate":      ("space", "editor"),
    "connections.test":          ("space", "editor"),
    "pages.create":              ("space", "editor"),
    "pages.edit":                ("space", "editor"),
    "agents.create":             ("space", "editor"),
    "agents.edit":               ("space", "editor"),
    "agents.run":                ("space", "editor"),
    "agents.pause":              ("space", "editor"),
    "agents.resume":             ("space", "editor"),
    "agents.findings.dismiss":   ("space", "editor"),

    # Space — owner only (admin actions on the Space itself)
    "pages.delete":              ("space", "owner"),
    "agents.delete":             ("space", "owner"),
    # spaces.members.manage acts on the Space's membership list itself —
    # NOT on a sub-resource that could live inside a Crew. So even when
    # a crew_id happens to be in the request context, only space_role
    # counts. A Crew Owner does not get to add/remove members of the
    # parent Space. Tracked here as a SPACE_ADMIN_KEY exception in
    # `Authorization.can()`.
    "spaces.members.manage":     ("space", "owner"),
    "crews.members.manage":      ("space", "owner"),
    # Phase 2 — generic resource sharing key
    "resources.share":           ("space", "owner"),
}


# ─── Resolver ────────────────────────────────────────────────────────────────


class Authorization:
    """Single source of truth for every authorisation decision."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_space_role(
        self, user_id: UUID, space_id: UUID
    ) -> Optional[SpaceRole]:
        """Return the user's role in the given Space, or None if not a member.
        Legacy values are normalised to the new vocabulary."""
        row = (
            await self.db.execute(
                select(SpaceMember).where(
                    SpaceMember.user_id == user_id,
                    SpaceMember.space_id == space_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return LEGACY_TO_NEW_SPACE_ROLE.get(row.role)

    async def get_crew_role(
        self, user_id: UUID, crew_id: UUID
    ) -> Optional[SpaceRole]:
        """Return the user's role in the given Crew, or None if not a member.
        Crew vocabulary mirrors Spaces (owner/editor/viewer); rows are
        looked up directly via SPACE_ROLE_LOOKUP — Phase 7 retired the
        legacy commander/navigator/explorer translation."""
        from src.models.crew import CrewMember

        row = (
            await self.db.execute(
                select(CrewMember).where(
                    CrewMember.user_id == user_id,
                    CrewMember.crew_id == crew_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return LEGACY_TO_NEW_SPACE_ROLE.get(row.role)

    async def get_best_crew_role_in_space(
        self, user_id: UUID, space_id: UUID
    ) -> Optional[SpaceRole]:
        """Highest Crew role the user holds in any Crew that belongs to
        this Space. Used when checking a Space-level resource against a
        user that has no SpaceMember row but is a member of one or more
        Crews inside the Space."""
        from src.models.crew import Crew, CrewMember

        rows = (
            await self.db.execute(
                select(CrewMember.role)
                .join(Crew, Crew.id == CrewMember.crew_id)
                .where(
                    CrewMember.user_id == user_id,
                    Crew.space_id == space_id,
                )
            )
        ).scalars().all()
        best: Optional[SpaceRole] = None
        for raw in rows:
            mapped = LEGACY_TO_NEW_SPACE_ROLE.get(raw)
            if mapped is None:
                continue
            if best is None or SPACE_ROLE_LEVEL[mapped] > SPACE_ROLE_LEVEL[best]:
                best = mapped
        return best

    def _meets_space_level(
        self, actual: Optional[SpaceRole], required: SpaceRole
    ) -> bool:
        if actual is None:
            return False
        return SPACE_ROLE_LEVEL[actual] >= SPACE_ROLE_LEVEL[required]

    async def assert_content_access(
        self,
        user: User,
        *,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
    ) -> None:
        """Require REAL membership for CONTENT access (Option B, 2026-06).

        Unlike :meth:`can`, this NEVER applies a platform-role bypass — a
        super_admin/admin who is not a member is denied. Used by content
        endpoints (AI query against a resolved crew, agent insights, …) to
        gate the SPECIFIC crew, not just "any crew in the space".

        - ``crew_id`` given → the user must be a member of THAT crew
          (owner/editor/viewer all grant access).
        - else ``space_id`` given → the user must be a member of the space
          itself OR of at least one crew inside it.
        - neither → personal context, allowed.

        Raises :class:`ForbiddenError` when the user is not a member.
        """
        if crew_id is not None:
            role = await self.get_crew_role(user.id, crew_id)
            if role is None:
                raise ForbiddenError(
                    "You must be a member of this crew to see its content. "
                    "Ask a crew owner to add you."
                )
            return
        if space_id is not None:
            if await self.get_space_role(user.id, space_id) is not None:
                return
            if await self.get_best_crew_role_in_space(user.id, space_id) is not None:
                return
            raise ForbiddenError(
                "You must be a member of this space to see its content."
            )
        # Personal context (no space/crew) — nothing to gate.
        return

    async def get_resource_acl_level(
        self,
        user_id: UUID,
        resource_type: str,
        resource_id: UUID,
    ) -> Optional[SpaceRole]:
        """Highest level granted to `user` on this resource via the
        resource_acl table. Considers user grants and tenant-wide grants.
        Space-principal grants are not resolved here — callers that need
        them must walk the user's Spaces (Phase 3+ FE concern)."""
        from src.models.resource_acl import ResourceAcl

        rows = (
            await self.db.execute(
                select(ResourceAcl).where(
                    ResourceAcl.resource_type == resource_type,
                    ResourceAcl.resource_id == resource_id,
                    (
                        (ResourceAcl.principal_type == "user")
                        & (ResourceAcl.principal_id == user_id)
                    )
                    | (ResourceAcl.principal_type == "tenant"),
                )
            )
        ).scalars().all()
        best: Optional[SpaceRole] = None
        for r in rows:
            mapped = LEGACY_TO_NEW_SPACE_ROLE.get(r.level)
            if mapped is None:
                continue
            if best is None or SPACE_ROLE_LEVEL[mapped] > SPACE_ROLE_LEVEL[best]:
                best = mapped
        return best

    async def can(
        self,
        user: User,
        permission_key: str,
        *,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[UUID] = None,
    ) -> bool:
        """Return True iff `user` is allowed to perform `permission_key`.

        Three tiers of context, walked in order:
          1. Space membership (resource lives in a Space)
          2. Crew membership (resource lives in a Crew inside a Space —
             a Crew is a sub-team like "Finance > Tax" inside a "Finance"
             Space). User can be in N Crews of the same Space.
          3. Resource ACL (explicit per-resource grant via resource_acl)

        Effective level = max(space_role, crew_role, best_crew_in_space,
                              resource_acl_level). Higher level on any
        rung overrides the rung above it.
        """
        rule = PERMISSION_RULES.get(permission_key)
        if rule is None:
            # Unknown key — deny conservatively. Phases 2-7 will move every
            # call site off the dict; remaining keys at end-of-rewrite must
            # be removed from call sites or registered here.
            return False

        scope, required = rule
        platform = user.role

        # DATA/CONTENT plane (Option B): platform role does NOT grant content
        # access — fall through to real Space/Crew membership evaluation. An
        # admin who is not a member of the crew is denied here. Management
        # keys are unaffected (they keep the bypasses below).
        is_data_plane = permission_key in DATA_PLANE_PERMS

        # Platform SuperAdmin/Owner bypasses everything (management plane).
        # Accept both ``super_admin`` (new) and ``owner`` (legacy alias).
        if not is_data_plane and platform in (
            PlatformRole.SUPER_ADMIN.value,
            PlatformRole.OWNER.value,
        ):
            return True

        # Platform Admin: bypasses everything except super_admin-exclusive perms.
        if not is_data_plane and platform == PlatformRole.ADMIN.value:
            return required != "owner_only"

        # From here, user is a Member.

        if scope == "tenant":
            if required == "any_member":
                return True
            # owner_only / admin_or_above already short-circuited above.
            return False

        # scope == "space"
        if (
            space_id is None
            and crew_id is None
            and (resource_type is None or resource_id is None)
        ):
            return False

        space_level: Optional[SpaceRole] = None
        if space_id is not None:
            space_level = await self.get_space_role(user.id, space_id)

        # Space-admin actions: only space_role counts. Short-circuit
        # before crew_role / best_crew_in_space / acl can contribute,
        # so a Crew Owner cannot manage the Space's member list.
        if permission_key in SPACE_ADMIN_KEYS:
            if space_level is None:
                return False
            if required == "viewer":
                return self._meets_space_level(space_level, SpaceRole.VIEWER)
            if required == "editor":
                return self._meets_space_level(space_level, SpaceRole.EDITOR)
            if required == "owner":
                return self._meets_space_level(space_level, SpaceRole.OWNER)
            return False

        crew_level: Optional[SpaceRole] = None
        if crew_id is not None:
            crew_level = await self.get_crew_role(user.id, crew_id)

        # Crew membership inside a Space confers VISIBILITY only — it lets
        # a user navigate into the Space (so they can reach their Crew),
        # but it does NOT escalate Space-level write/admin permissions.
        # Modelling rationale: Space = department, Crew = team within
        # the department. An "Audit Crew" owner manages Audit, not the
        # whole Finance department — they should not be able to delete a
        # Space-level page like "Company Finance 2026" just because they
        # own a Crew under the Space. So we cap this contribution at
        # viewer level and only consider it when no specific crew_id was
        # passed (when one is, that crew's role is authoritative for the
        # active context). Owner/editor escalation must come through the
        # crew_id explicitly tied to the resource being acted on.
        best_crew_in_space: Optional[SpaceRole] = None
        if space_id is not None and crew_id is None:
            raw = await self.get_best_crew_role_in_space(user.id, space_id)
            if raw is not None:
                best_crew_in_space = SpaceRole.VIEWER

        acl_level: Optional[SpaceRole] = None
        if resource_type is not None and resource_id is not None:
            acl_level = await self.get_resource_acl_level(
                user.id, resource_type, resource_id
            )

        candidates = [
            lv
            for lv in (space_level, crew_level, best_crew_in_space, acl_level)
            if lv is not None
        ]
        if not candidates:
            return False
        actual = max(candidates, key=lambda lv: SPACE_ROLE_LEVEL[lv])

        if required == "viewer":
            return self._meets_space_level(actual, SpaceRole.VIEWER)
        if required == "editor":
            return self._meets_space_level(actual, SpaceRole.EDITOR)
        if required == "owner":
            return self._meets_space_level(actual, SpaceRole.OWNER)
        return False

    async def assert_can(
        self,
        user: User,
        permission_key: str,
        *,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[UUID] = None,
    ) -> None:
        if not await self.can(
            user,
            permission_key,
            space_id=space_id,
            crew_id=crew_id,
            resource_type=resource_type,
            resource_id=resource_id,
        ):
            scope_str = ""
            if space_id:
                scope_str = f" on Space {space_id}"
            elif crew_id:
                scope_str = f" on Crew {crew_id}"
            raise ForbiddenError(
                f"User {user.id} cannot perform '{permission_key}'{scope_str}"
            )
