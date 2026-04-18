"""
Regression tests for ADR-002 Wave 3 — Commander platform-level leak cleanup.

Ensures that DEFAULT_ROLE_PERMISSIONS does NOT grant platform-level
permissions to crew-level roles (commander, navigator). Those perms
belong to platform_admin / owner.

If someone accidentally re-adds apikeys.manage or metrics.view back to
commander's defaults, these tests fail loudly.
"""
import pytest
from src.services.rbac_service import DEFAULT_ROLE_PERMISSIONS


# Perms that must never be granted by default to a crew-level role.
PLATFORM_ONLY_PERMISSIONS = [
    "apikeys.manage",
    "integrations.manage",
    "metrics.view",
    "users.view",
    "users.permissions.view",
    "users.invite",
    "users.edit",
    "users.delete",
    "users.permissions.edit",
    "permissions.view",
    "permissions.edit",
    "settings.edit",
    "audit.view",
    "audit.verify",
    "privacy.export",
    "privacy.delete",
    "support.settings",
    "support.revoke",
    "admin.users.manage",
]


CREW_ROLES = ["commander", "navigator", "explorer", "guest"]


@pytest.mark.parametrize("role", CREW_ROLES)
@pytest.mark.parametrize("perm", PLATFORM_ONLY_PERMISSIONS)
def test_crew_role_never_grants_platform_permission(role, perm):
    """Every crew role × every platform perm combo must be False."""
    perms = DEFAULT_ROLE_PERMISSIONS[role]
    # Either the key is absent (falsy) or explicitly False. Never True.
    assert perms.get(perm, False) is False, (
        f"Crew role '{role}' must not grant platform-level '{perm}' "
        f"by default — that's the Wave 3 invariant from ADR-002."
    )


def test_commander_still_has_crew_content_perms():
    """Commander remains able to do Crew-content CRUD after the cleanup."""
    c = DEFAULT_ROLE_PERMISSIONS["commander"]
    # Content CRUD inside the Crew
    assert c["pages.create"] is True
    assert c["pages.edit"] is True
    assert c["pages.delete"] is True
    assert c["dashboards.create"] is True
    assert c["widgets.create"] is True
    # Crew membership management
    assert c["crews.members.manage"] is True
    assert c["pages.members.manage"] is True
    # Agents inside the Crew
    assert c["agents.create"] is True
    assert c["agents.manage"] is True


def test_commander_can_still_view_own_profile():
    """Removing `users.view` must not also remove self-edit."""
    c = DEFAULT_ROLE_PERMISSIONS["commander"]
    assert c["users.self.edit"] is True
    assert c["users.self.permissions"] is True


def test_navigator_no_longer_sees_platform_metrics():
    """Wave 3 specifically flipped this from True to False."""
    assert DEFAULT_ROLE_PERMISSIONS["navigator"]["metrics.view"] is False


def test_settings_view_stays_true_for_crew_roles():
    """settings.view is a read-only config lens — benign, stays visible."""
    for role in CREW_ROLES:
        assert DEFAULT_ROLE_PERMISSIONS[role]["settings.view"] is True, (
            f"{role} must still be able to read the Settings page (it's read-only)"
        )
