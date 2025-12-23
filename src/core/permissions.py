"""RBAC (Role-Based Access Control) utilities."""

from typing import Dict, List, Optional

from src.models.user import User


# Permission definitions
PERMISSIONS = {
    "workspace": {
        "create": ["admin", "user"],
        "read": ["admin", "user", "viewer"],
        "update": ["admin", "user"],
        "delete": ["admin"],
        "manage_members": ["admin", "user"],
    },
    "dashboard": {
        "create": ["admin", "user"],
        "read": ["admin", "user", "viewer"],
        "update": ["admin", "user"],
        "delete": ["admin", "user"],
    },
    "widget": {
        "create": ["admin", "user"],
        "read": ["admin", "user", "viewer"],
        "update": ["admin", "user"],
        "delete": ["admin", "user"],
    },
    "connection": {
        "create": ["admin", "user"],
        "read": ["admin", "user", "viewer"],
        "update": ["admin", "user"],
        "delete": ["admin"],
        "sync": ["admin", "user"],
    },
    "ai": {
        "query": ["admin", "user"],
        "read_history": ["admin", "user", "viewer"],
    },
    "user": {
        "create": ["admin"],
        "read": ["admin", "user"],
        "update": ["admin"],
        "delete": ["admin"],
    },
}


def get_user_permissions(user: User) -> Dict[str, List[str]]:
    """
    Get permissions for a user based on their role.

    Args:
        user: User object

    Returns:
        Dict[str, List[str]]: Permissions by resource
    """
    role = user.role
    user_permissions = {}

    for resource, actions in PERMISSIONS.items():
        user_permissions[resource] = [
            action for action, allowed_roles in actions.items() if role in allowed_roles
        ]

    return user_permissions


def check_permission(
    user: User, resource: str, action: str, workspace_id: Optional[str] = None
) -> bool:
    """
    Check if user has permission for a resource and action.

    Args:
        user: User object
        resource: Resource name (e.g., 'workspace', 'dashboard')
        action: Action name (e.g., 'create', 'read', 'update', 'delete')
        workspace_id: Optional workspace ID for workspace-specific permissions

    Returns:
        bool: True if user has permission
    """
    # Admin has all permissions
    if user.role == "admin":
        return True

    # Check resource permissions
    if resource not in PERMISSIONS:
        return False

    resource_perms = PERMISSIONS[resource]
    if action not in resource_perms:
        return False

    allowed_roles = resource_perms[action]
    return user.role in allowed_roles

