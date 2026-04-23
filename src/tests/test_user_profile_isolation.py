"""Regression for HI-001 (red-team 2026-04-23): regular user B could
read user A's profile via GET /users/{id}, leaking email and
last_active_at to any authenticated caller.

Fix: `user.read` in the permission matrix no longer includes the
`user` role; only `owner`/`admin` keep cross-user read rights."""

from __future__ import annotations

from types import SimpleNamespace

from src.core.permissions import check_permission


def _fake_user(role: str):
    return SimpleNamespace(role=role)


def test_regular_user_cannot_read_other_users_profile():
    assert check_permission(_fake_user("user"), "user", "read") is False


def test_admin_can_still_read_any_profile():
    assert check_permission(_fake_user("admin"), "user", "read") is True


def test_owner_can_still_read_any_profile():
    assert check_permission(_fake_user("owner"), "user", "read") is True


def test_viewer_cannot_read_other_users_profile():
    assert check_permission(_fake_user("viewer"), "user", "read") is False


def test_regular_user_update_delete_still_denied():
    """Baseline sanity — update/delete were already admin-only; just
    confirming they didn't widen when we narrowed read."""
    assert check_permission(_fake_user("user"), "user", "update") is False
    assert check_permission(_fake_user("user"), "user", "delete") is False
