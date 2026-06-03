"""RBAC (Role-Based Access Control) utilities — legacy helpers.

This module predates the role catalogue (`src/services/rbac_service.py` and
`src/lib/rbac/*` on the frontend) and still backs a set of older endpoints
via `check_permission`. Two notes for maintainers:

1. Whenever a new platform role is added (owner, billing_admin, …), it
   must be taught about here too, otherwise the legacy endpoints silently
   deny it. That was the bug that hid Members lists and Space member
   counts from Owner users in early 2026.
2. The new role catalogue is authoritative for any new endpoint. Do not
   extend `PERMISSIONS` below for new features — wire them through
   `RBACService.assert_permission` with a catalogue key instead.
"""

from typing import Dict, List, Optional

from src.models.user import User

# Tenant-level role taxonomy after the 2026-06-03 rename:
#     super_admin → tenant founder (full bypass, billing + delete tenant)
#     admin       → ops-level admin (full bypass, no founder-only perms)
#     member      → regular user
# Scope (Space / Crew / Page) roles stay owner / editor / viewer and live
# in their own membership tables — ``user.role`` never carries ``owner``
# any more. The DB migration ``rename_role_20260603`` has already
# converted any legacy ``user.role == "owner"`` rows to ``super_admin``,
# so this bypass list does NOT need to include ``owner`` for production
# data; it would only mask bugs elsewhere if it did.
TENANT_ADMIN_ROLES = ("super_admin", "admin")
_BYPASS_ROLES = TENANT_ADMIN_ROLES


def is_tenant_admin(user: "User") -> bool:
    """True iff ``user`` holds a tenant-level admin role.

    Use this anywhere you'd otherwise write ``user.role == "admin"`` —
    that pattern silently locks ``super_admin`` (the tenant founder) out
    of the very things they're supposed to control. The helper is the
    single source of truth for "is this caller a platform-wide admin?"
    and stays in lockstep with :data:`TENANT_ADMIN_ROLES`.
    """
    return user.role in TENANT_ADMIN_ROLES

# Permission definitions. Each allowed-role list MUST include `owner`
# wherever it includes `admin`; otherwise the Owner user is denied by
# the role-list fallback at the bottom of `check_permission`.
PERMISSIONS = {
    "workspace": {
        "create": ["owner", "admin", "user"],
        "read": ["owner", "admin", "user", "viewer"],
        "update": ["owner", "admin", "user"],
        "delete": ["owner", "admin"],
        "manage_members": ["owner", "admin", "user"],
    },
    "dashboard": {
        "create": ["owner", "admin", "user"],
        "read": ["owner", "admin", "user", "viewer"],
        "update": ["owner", "admin", "user"],
        "delete": ["owner", "admin", "user"],
    },
    "widget": {
        "create": ["owner", "admin", "user"],
        "read": ["owner", "admin", "user", "viewer"],
        "update": ["owner", "admin", "user"],
        "delete": ["owner", "admin", "user"],
    },
    "connection": {
        "create": ["owner", "admin", "user"],
        "read": ["owner", "admin", "user", "viewer"],
        "update": ["owner", "admin", "user"],
        "delete": ["owner", "admin"],
        "sync": ["owner", "admin", "user"],
    },
    "ai": {
        "query": ["owner", "admin", "user"],
        "read_history": ["owner", "admin", "user", "viewer"],
    },
    "user": {
        "create": ["owner", "admin"],
        # Red-team HI-001 (2026-04-23): regular users must NOT read
        # other users' profiles via GET /users/{id}. Reading your own
        # profile goes through `current_user.id == user_id` in the
        # route, which bypasses this check. Only owner + admin keep
        # cross-user read rights (they need it for administration).
        "read": ["owner", "admin"],
        "update": ["owner", "admin"],
        "delete": ["owner", "admin"],
    },
}


def get_user_permissions(user: User) -> Dict[str, List[str]]:
    """Return the flat action list a user has per resource.

    Owner short-circuits to the full action list of every resource so
    callers that introspect permissions don't need to know about the
    bypass. Matches the behaviour of `check_permission` for consistency.
    """
    role = user.role

    if role in _BYPASS_ROLES:
        return {resource: list(actions.keys()) for resource, actions in PERMISSIONS.items()}

    user_permissions = {}
    for resource, actions in PERMISSIONS.items():
        user_permissions[resource] = [
            action for action, allowed_roles in actions.items() if role in allowed_roles
        ]
    return user_permissions


def check_permission(
    user: User, resource: str, action: str, workspace_id: Optional[str] = None
) -> bool:
    """True if the user may perform `action` on `resource`.

    Owner and Admin bypass every granular check (owner-exclusive perms
    like tenant.delete are enforced by the newer `RBACService`, not here).
    All other roles fall through to the `PERMISSIONS` lookup.
    """
    if user.role in _BYPASS_ROLES:
        return True

    if resource not in PERMISSIONS:
        return False

    resource_perms = PERMISSIONS[resource]
    if action not in resource_perms:
        return False

    allowed_roles = resource_perms[action]
    return user.role in allowed_roles
