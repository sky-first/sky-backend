"""Unit tests for the shared mutation-authorization helper.

Red-team HI-002 (2026-04-23): multiple services let cross-user
mutation happen. This helper is the single point of enforcement —
test every arm of its policy matrix so a regression in any consumer
service is caught immediately.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.services._mutation_guard import (
    require_collaborative_mutation_rights,
    require_mutation_rights,
    require_personal_owner_or_404,
)


def _user(role: str = "user"):
    return SimpleNamespace(id=uuid4(), role=role)


# ---- Personal guard ----------------------------------------------------


def test_personal_owner_can_mutate():
    u = _user()
    entity = SimpleNamespace(owner_user_id=u.id)
    # Should not raise.
    require_personal_owner_or_404(entity, u.id)


def test_personal_non_owner_gets_404():
    owner = uuid4()
    attacker = uuid4()
    entity = SimpleNamespace(owner_user_id=owner)
    with pytest.raises(HTTPException) as ei:
        require_personal_owner_or_404(entity, attacker)
    assert ei.value.status_code == 404


def test_personal_check_skips_when_owner_is_null():
    """Collaborative entities (owner_user_id=None) should NOT trip
    the Personal guard — they need the other helper."""
    entity = SimpleNamespace(owner_user_id=None)
    # Should not raise.
    require_personal_owner_or_404(entity, uuid4())


# ---- Collaborative guard (creator bypass + RBAC) -----------------------


@pytest.mark.asyncio
async def test_creator_bypasses_rbac():
    """A user who created the row can always mutate, even if RBAC would
    normally deny (e.g. explorer creating a widget and later deleting
    it)."""
    u = _user()
    entity = SimpleNamespace(created_by=u.id, space_id=uuid4())

    # RBAC should NOT be called when creator bypass fires.
    with patch(
        "src.services.rbac_service.RBACService.assert_permission",
        new=AsyncMock(side_effect=AssertionError("RBAC was called despite creator bypass")),
    ):
        await require_collaborative_mutation_rights(
            entity, user=u, rbac_permission="widgets.delete", db=None
        )


@pytest.mark.asyncio
async def test_non_creator_falls_through_to_rbac_with_space_scope():
    u = _user()
    creator_id = uuid4()
    space_id = uuid4()
    entity = SimpleNamespace(created_by=creator_id, space_id=space_id)

    rbac_mock = AsyncMock(return_value=None)
    with patch(
        "src.services.rbac_service.RBACService.assert_permission", new=rbac_mock
    ):
        await require_collaborative_mutation_rights(
            entity, user=u, rbac_permission="widgets.delete", db=None
        )
    rbac_mock.assert_awaited_once()
    _, kwargs = rbac_mock.call_args
    assert kwargs.get("space_id") == space_id


@pytest.mark.asyncio
async def test_rbac_denial_propagates():
    u = _user()
    entity = SimpleNamespace(created_by=uuid4(), space_id=uuid4())
    from src.core.exceptions import ForbiddenError

    with patch(
        "src.services.rbac_service.RBACService.assert_permission",
        new=AsyncMock(side_effect=ForbiddenError("nope")),
    ):
        with pytest.raises(ForbiddenError):
            await require_collaborative_mutation_rights(
                entity, user=u, rbac_permission="widgets.delete", db=None
            )


# ---- Dispatcher --------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_routes_personal_then_skips_collab():
    owner = uuid4()
    attacker = _user()  # random id
    entity = SimpleNamespace(owner_user_id=owner, created_by=attacker.id, space_id=uuid4())

    rbac_mock = AsyncMock()
    with patch(
        "src.services.rbac_service.RBACService.assert_permission", new=rbac_mock
    ):
        with pytest.raises(HTTPException) as ei:
            await require_mutation_rights(
                entity, user=attacker, rbac_permission="widgets.delete", db=None
            )
    assert ei.value.status_code == 404
    rbac_mock.assert_not_called()


@pytest.mark.asyncio
async def test_dispatcher_routes_collab_when_owner_null():
    u = _user()
    entity = SimpleNamespace(owner_user_id=None, created_by=u.id, space_id=uuid4())

    # creator bypass → no RBAC call
    with patch(
        "src.services.rbac_service.RBACService.assert_permission",
        new=AsyncMock(side_effect=AssertionError("RBAC was called")),
    ):
        await require_mutation_rights(
            entity, user=u, rbac_permission="widgets.delete", db=None
        )
