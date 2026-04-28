"""RBAC matrix tests for the Knowledge Library.

Tests the permission configuration in DEFAULT_ROLE_PERMISSIONS directly.
No DB, no mocks, no external services — pure dict assertions.

Run:
    pytest src/tests/test_knowledge_rbac_matrix.py -v
"""

import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
from src.services.rbac_service import DEFAULT_ROLE_PERMISSIONS


# ── Helpers ───────────────────────────────────────────────────────────────────

def can(role: str, perm: str) -> bool:
    return DEFAULT_ROLE_PERMISSIONS.get(role, {}).get(perm, False)


# ── files.view — everyone except guest should see files ───────────────────────

class TestFilesView:
    def test_commander_can_view(self):
        assert can("commander", "files.view") is True

    def test_navigator_can_view(self):
        assert can("navigator", "files.view") is True

    def test_explorer_can_view(self):
        assert can("explorer", "files.view") is True

    def test_guest_can_view(self):
        # guests are stakeholders — read-only on files
        assert can("guest", "files.view") is True


# ── files.upload — commander + navigator (navigator → pending_approval) ───────

class TestFilesUpload:
    def test_commander_can_upload(self):
        assert can("commander", "files.upload") is True

    def test_navigator_can_upload(self):
        # Navigator uploads go to pending_approval until a commander approves.
        assert can("navigator", "files.upload") is True

    def test_explorer_cannot_upload(self):
        assert can("explorer", "files.upload") is False

    def test_guest_cannot_upload(self):
        assert can("guest", "files.upload") is False


# ── files.approve — only commander ───────────────────────────────────────────

class TestFilesApprove:
    def test_commander_can_approve(self):
        assert can("commander", "files.approve") is True

    def test_navigator_cannot_approve(self):
        assert can("navigator", "files.approve") is False

    def test_explorer_cannot_approve(self):
        assert can("explorer", "files.approve") is False

    def test_guest_cannot_approve(self):
        assert can("guest", "files.approve") is False


# ── files.delete — only commander ────────────────────────────────────────────

class TestFilesDelete:
    def test_commander_can_delete(self):
        assert can("commander", "files.delete") is True

    def test_navigator_cannot_delete(self):
        assert can("navigator", "files.delete") is False

    def test_explorer_cannot_delete(self):
        assert can("explorer", "files.delete") is False

    def test_guest_cannot_delete(self):
        assert can("guest", "files.delete") is False


# ── Consistency checks ────────────────────────────────────────────────────────

class TestConsistency:
    @pytest.mark.parametrize("role", ["explorer", "guest"])
    def test_explorer_and_guest_cannot_upload_or_delete(self, role):
        """Explorer and guest have no write access at all."""
        assert can(role, "files.upload") is False
        assert can(role, "files.delete") is False

    def test_navigator_can_upload_but_not_delete(self):
        """Navigator can upload (with approval), but cannot delete."""
        assert can("navigator", "files.upload") is True
        assert can("navigator", "files.delete") is False

    def test_only_commander_can_approve(self):
        """Approve permission is exclusively commander."""
        assert can("commander", "files.approve") is True
        for role in ("navigator", "explorer", "guest"):
            assert can(role, "files.approve") is False, f"{role} should not approve"

    def test_all_roles_defined(self):
        for role in ("commander", "navigator", "explorer", "guest"):
            assert role in DEFAULT_ROLE_PERMISSIONS, f"Role '{role}' missing from matrix"
            for perm in ("files.upload", "files.view", "files.delete", "files.approve"):
                assert perm in DEFAULT_ROLE_PERMISSIONS[role], (
                    f"Permission '{perm}' missing from role '{role}'"
                )
