"""Platform Member role — productive permissions on day one.

Lucas's 2026-04-30 review caught the regression: a freshly signed-up
user with `user.role == "member"` (or legacy `"user"`) was getting
"You don't have permission to use AI in this workspace" when trying
the chat. Root cause: the rbac_service only granted permissions via
two paths — Owner/Admin bypass OR scope-resolved commander/navigator/
explorer. Member fell through to "no_access".

These tests pin the new behaviour: a Member is a productive platform
citizen by default — full AI access, full canvas writes, can upload
to Knowledge (subject to admin approval), but cannot mint connections,
approve uploads, or touch billing/users/spaces.
"""

from __future__ import annotations

import pytest

from src.services.rbac_service import (
    DEFAULT_ROLE_PERMISSIONS,
    MEMBER_PLATFORM_PERMISSIONS,
)


# ── Sanity: the new Member dict exists with the expected keys. ─────────────


def test_member_platform_permissions_dict_exists():
    assert isinstance(MEMBER_PLATFORM_PERMISSIONS, dict)
    assert len(MEMBER_PLATFORM_PERMISSIONS) > 50, (
        "Member dict should be comprehensive enough that an "
        "EffectivePermissions lookup never silently misses."
    )


# ── Capabilities Member SHOULD have (Lucas's 'productive on day one'). ─────


PRODUCTIVE_PERMS = [
    # AI
    "ai.chat",
    "ai.query",
    "ai.history.view",
    "ai.history.pin",
    "ai.history.export",
    "ai.generate",
    # Canvas writes
    "pages.create",
    "pages.edit",
    "pages.duplicate",
    "widgets.create",
    "widgets.edit",
    "widgets.delete",
    # Agents
    "agents.create",
    "agents.run",
    "agents.findings.view",
    # Knowledge upload (the file goes to pending_approval, see
    # KnowledgeService.confirm_upload — Member never auto-approves)
    "files.upload",
    "files.view",
    # Read-only on org structure
    "spaces.view",
    "crews.view",
    "spaces.connections.view",
    "connections.view",
    "connections.metadata.view",
    "connections.tables.view",
    # Self
    "users.self.edit",
]


@pytest.mark.parametrize("perm", PRODUCTIVE_PERMS)
def test_member_can_use_core_capabilities(perm: str):
    assert MEMBER_PLATFORM_PERMISSIONS.get(perm) is True, (
        f"Member must be able to {perm} — Lucas's 2026-04-30 brief: "
        "Member is productive on day one, the only differentiation "
        "from Admin is approve / billing / user / connection-mint."
    )


# ── Capabilities Member should NOT have (admin-only). ─────────────────────


ADMIN_ONLY_PERMS = [
    # Connections — mint + edit + delete is platform-admin only.
    "connections.create",
    "connections.edit",
    "connections.delete",
    "connections.test",
    "connections.sync",
    # Files — approval is platform-admin only.
    "files.approve",
    "files.delete",
    # Spaces / Crews — Member doesn't manage org structure...
    #
    # ...com uma excepção decidida a 19/08: **criar** um projeto é de
    # qualquer pessoa. Um projeto acabado de nascer não tem dados, e ligar-lhe
    # dados exige ser dono dele ou um pedido aprovado por um admin do cliente.
    # O que era preciso governar passou a estar governado na fronteira dos
    # dados, em vez de na criação. Editar e apagar continuam de fora porque
    # dizem respeito aos projetos **dos outros** — sobre o seu, o member passa
    # pela pertença (SpaceMember owner), não por esta tabela.
    "spaces.edit",
    "spaces.delete",
    "spaces.members.manage",
    "spaces.connections.manage",
    "crews.create",
    "crews.edit",
    "crews.delete",
    "crews.members.manage",
    # Users — invite/edit/delete/impersonate are admin-only.
    "admin.users.manage",
    "users.invite",
    "users.edit",
    "users.delete",
    "users.permissions.edit",
    "users.impersonate",
    # Settings & secrets.
    "permissions.view",
    "permissions.edit",
    "settings.edit",
    "apikeys.manage",
    "integrations.manage",
    # Audit / privacy / support.
    "audit.view",
    "audit.verify",
    "privacy.export",
    "privacy.delete",
    "support.settings",
    "support.revoke",
]


@pytest.mark.parametrize("perm", ADMIN_ONLY_PERMS)
def test_member_cannot_do_admin_only(perm: str):
    assert MEMBER_PLATFORM_PERMISSIONS.get(perm) is False, (
        f"Member must NOT be able to {perm} — that's reserved for "
        "Owner / Admin."
    )


# ── Cross-check: every Member key also exists in the matrix elsewhere. ────


def test_member_keys_are_subset_of_known_permissions():
    """Catch typos: every key in the Member dict should also appear in
    at least one of the scope role dicts so the FE catalog can render
    it. Owner-exclusive keys (tenant.delete / billing.manage / ...)
    are intentionally absent here — they're injected dynamically in
    the bypass branch.
    """
    known_keys: set[str] = set()
    for role_map in DEFAULT_ROLE_PERMISSIONS.values():
        known_keys.update(role_map.keys())
    unknown = [k for k in MEMBER_PLATFORM_PERMISSIONS if k not in known_keys]
    assert unknown == [], (
        f"Member dict references keys that are not in any scope role: "
        f"{unknown}. Either add them to commander/navigator/explorer or "
        "remove from MEMBER_PLATFORM_PERMISSIONS."
    )
