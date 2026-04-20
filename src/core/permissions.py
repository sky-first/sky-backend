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

# Roles that bypass every granular check below. Keep this list narrow —
# it's the escape hatch, not the default. `owner` is here because it is
# defined as "founder seat above admin" in ADR-002 and must see/do
# anything admin can plus the OWNER_EXCLUSIVE_PERMISSIONS in the
# frontend catalogue.
_BYPASS_ROLES = ("owner", "admin")

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
        "read": ["owner", "admin", "user"],
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
