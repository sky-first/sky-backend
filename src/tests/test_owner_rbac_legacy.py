"""Guard tests — legacy `check_permission` must honour the `owner` role.

The helper in `src/core/permissions.py` predates the new role catalogue.
Historically it hard-coded `admin` as the bypass and left every other
platform role (owner, billing_admin, …) falling through to a
`PERMISSIONS` lookup that didn't know about them. That silently denied
Owner users from listing members, reading audit entries, managing
connections, and similar admin-equivalent actions.

These tests pin the fix in place: whenever we extend the role catalogue
again, this suite breaks loud before anything reaches production.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.permissions import PERMISSIONS, check_permission, get_user_permissions


def _user(role: str):
    return SimpleNamespace(id="11111111-1111-1111-1111-111111111111", role=role)


# ─── check_permission ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "resource,action",
    [
        ("workspace", "create"),
        ("workspace", "delete"),
        ("dashboard", "update"),
        ("widget", "delete"),
        ("connection", "create"),
        ("connection", "delete"),
        ("connection", "sync"),
        ("ai", "query"),
        ("ai", "read_history"),
        ("user", "create"),
        ("user", "read"),
        ("user", "update"),
        ("user", "delete"),
    ],
)
def test_owner_passes_every_legacy_check(resource, action):
    assert check_permission(_user("owner"), resource, action) is True


@pytest.mark.parametrize(
    "resource,action",
    [
        ("workspace", "create"),
        ("connection", "delete"),
        ("user", "delete"),
    ],
)
def test_admin_still_passes_after_fix(resource, action):
    """Regression guard — the Owner fix must not change anything for admin."""
    assert check_permission(_user("admin"), resource, action) is True


def test_plain_user_still_limited():
    user = _user("user")
    assert check_permission(user, "user", "read") is True
    assert check_permission(user, "user", "delete") is False
    assert check_permission(user, "connection", "delete") is False


def test_viewer_still_read_only():
    viewer = _user("viewer")
    assert check_permission(viewer, "dashboard", "read") is True
    assert check_permission(viewer, "dashboard", "update") is False


def test_unknown_role_is_denied():
    assert check_permission(_user("something_new"), "dashboard", "read") is False


def test_unknown_resource_or_action_is_denied_for_non_bypass():
    user = _user("user")
    assert check_permission(user, "nonsense_resource", "read") is False
    assert check_permission(user, "dashboard", "nonsense_action") is False


def test_unknown_resource_still_allowed_for_bypass_roles():
    """Owner/admin do not consult the PERMISSIONS dict at all — the bypass
    is intentional so we never deny a founder because of a missing entry.
    """
    assert check_permission(_user("owner"), "nonsense_resource", "read") is True
    assert check_permission(_user("admin"), "nonsense_resource", "read") is True


# ─── PERMISSIONS dict sanity ──────────────────────────────────────────


@pytest.mark.parametrize("resource", list(PERMISSIONS.keys()))
def test_every_resource_action_includes_owner_wherever_admin_is_listed(resource):
    """If admin can do it, owner must too — otherwise the bypass diverges
    from the per-action check and tests like `get_user_permissions` lie."""
    for action, allowed_roles in PERMISSIONS[resource].items():
        if "admin" in allowed_roles:
            assert "owner" in allowed_roles, (
                f"{resource}.{action}: owner is missing where admin is listed"
            )


# ─── get_user_permissions ─────────────────────────────────────────────


def test_owner_permissions_mirror_full_catalogue():
    perms = get_user_permissions(_user("owner"))
    for resource, actions in PERMISSIONS.items():
        assert set(perms[resource]) == set(actions.keys())


def test_user_permissions_still_respect_role_lists():
    perms = get_user_permissions(_user("user"))
    # plain "user" can NOT delete connections — should not leak.
    assert "delete" not in perms["connection"]
