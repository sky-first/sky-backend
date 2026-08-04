"""Role gate on the admin-actions endpoints.

Regression cover for a production incident: the tenant founder
(``role="super_admin"``) got 403 from the emergency Pause All switch.

The hand-rolled gate accepted ``{"admin", "superadmin"}`` — no
underscore. After the 2026-06-03 rename the taxonomy emits
``super_admin``, so the founder role matched nothing and the one person
who most needs the emergency switch was the one locked out of it.
``is_tenant_admin`` exists precisely to prevent this, and its docstring
says so; this module now uses it.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.v1.admin_actions import _require_admin


class _User:
    """Minimal stand-in — the gate only reads ``.role``."""

    def __init__(self, role):
        self.role = role


@pytest.mark.parametrize("role", ["super_admin", "admin"])
def test_tenant_admins_pass(role):
    _require_admin(_User(role))  # must not raise


def test_super_admin_is_not_locked_out():
    """The exact production failure: founder → 403 on Pause All."""
    _require_admin(_User("super_admin"))


@pytest.mark.parametrize("role", ["member", "viewer", "editor", "", None])
def test_non_admins_are_rejected(role):
    with pytest.raises(HTTPException) as exc:
        _require_admin(_User(role))
    assert exc.value.status_code == 403


def test_legacy_owner_string_is_rejected():
    """``rename_role_20260603`` converted every ``owner`` row to
    ``super_admin``. Accepting it here would only mask a bug elsewhere —
    ``is_tenant_admin`` is deliberately strict about this."""
    with pytest.raises(HTTPException) as exc:
        _require_admin(_User("owner"))
    assert exc.value.status_code == 403


def test_the_typo_role_is_not_a_backdoor():
    """``superadmin`` (no underscore) was in the old allow-list and is
    not a role the taxonomy ever produces — it must not grant access."""
    with pytest.raises(HTTPException) as exc:
        _require_admin(_User("superadmin"))
    assert exc.value.status_code == 403
