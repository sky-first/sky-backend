"""Authorization — single entry point for every "can this user do X?" check.

Replaces the old 14×80 editable permission matrix (RBACService +
permission_service) with a deterministic, code-defined translation
between permission keys and (scope, required_level) rules. The
matrix UI is gone in favour of explicit per-resource sharing
(see resource_acl table introduced in Phase 2).

Model:
  • Platform roles:  owner | admin | member
  • Space roles:     owner | editor | viewer  (per Space membership)
  • Resource ACL:    explicit overrides on individual connections /
                      dashboards / agents / knowledge files (Phase 2)

Resolution order in `can(...)`:
  1. Sky support without active JIT          → deny
  2. Platform owner                          → allow (except never)
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
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class SpaceRole(str, Enum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


SPACE_ROLE_LEVEL = {SpaceRole.VIEWER: 1, SpaceRole.EDITOR: 2, SpaceRole.OWNER: 3}


# Legacy → new role mapping. The migration on the DB side rewrites every
# row to the new vocabulary, but old code paths and external callers may
# still hand us a legacy string until Phase 7. This map is the bridge.
LEGACY_TO_NEW_SPACE_ROLE = {
    "commander": SpaceRole.OWNER,
    "admin": SpaceRole.OWNER,        # legacy demo seed
    "navigator": SpaceRole.EDITOR,
    "member": SpaceRole.EDITOR,      # legacy demo seed
    "explorer": SpaceRole.VIEWER,
    "guest": SpaceRole.VIEWER,       # already canonicalised in current code
    "owner": SpaceRole.OWNER,
    "editor": SpaceRole.EDITOR,
    "viewer": SpaceRole.VIEWER,
}


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
    "spaces.create":             ("tenant", "any_member"),
    "crews.create":              ("tenant", "any_member"),

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
    "connections.create":        ("space", "editor"),
    "connections.edit":          ("space", "editor"),
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
    "dashboards.delete":         ("space", "owner"),
    "agents.delete":             ("space", "owner"),
    "spaces.members.manage":     ("space", "owner"),
    "crews.members.manage":      ("space", "owner"),
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

    def _meets_space_level(
        self, actual: Optional[SpaceRole], required: SpaceRole
    ) -> bool:
        if actual is None:
            return False
        return SPACE_ROLE_LEVEL[actual] >= SPACE_ROLE_LEVEL[required]

    async def can(
        self,
        user: User,
        permission_key: str,
        *,
        space_id: Optional[UUID] = None,
    ) -> bool:
        """Return True iff `user` is allowed to perform `permission_key`.

        For space-scoped permissions, `space_id` selects which Space the
        check runs against. If omitted on a space-scoped permission and
        the user is not Owner/Admin, the call denies (no Personal-scope
        bypass at the resolver level — callers that mean "Personal" must
        pass the user's Personal Space id explicitly)."""
        rule = PERMISSION_RULES.get(permission_key)
        if rule is None:
            # Unknown key — deny conservatively. Phases 2-7 will move every
            # call site off the dict; remaining keys at end-of-rewrite must
            # be removed from call sites or registered here.
            return False

        scope, required = rule
        platform = user.role

        # Platform Owner bypasses everything.
        if platform == PlatformRole.OWNER.value:
            return True

        # Platform Admin: bypasses everything except owner-only.
        if platform == PlatformRole.ADMIN.value:
            return required != "owner_only"

        # From here, user is a Member.

        if scope == "tenant":
            if required == "any_member":
                return True
            # owner_only / admin_or_above already short-circuited above.
            return False

        # scope == "space"
        if space_id is None:
            return False
        actual = await self.get_space_role(user.id, space_id)
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
    ) -> None:
        if not await self.can(user, permission_key, space_id=space_id):
            raise ForbiddenError(
                f"User {user.id} cannot perform '{permission_key}'"
                + (f" on Space {space_id}" if space_id else "")
            )
