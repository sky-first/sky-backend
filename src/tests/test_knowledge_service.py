"""Unit tests for KnowledgeService — RBAC, quota, upload flow, delete.

All external dependencies are mocked:
  - No real DB (AsyncMock replaces AsyncSession)
  - No Azure (blob_helper patched)
  - No Celery (patched with noop)
  - RBACService mocked per-test to allow or deny

Run:
    pytest src/tests/test_knowledge_service.py -v
"""

import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError


# ── Factories ─────────────────────────────────────────────────────────────────

def _user(role: str = "member"):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.role = role
    return u


def _file(owner_id=None, scope="crew", scope_id=None, status="ready"):
    f = MagicMock()
    f.id = uuid.uuid4()
    f.user_id = owner_id or uuid.uuid4()
    f.scope = scope
    f.scope_id = scope_id or uuid.uuid4()
    f.status = status
    f.size_bytes = 1024
    f.blob_path = f"{scope}/x/y/test.pdf"
    f.deleted_at = None
    f.original_name = "test.pdf"
    f.mime_type = "application/pdf"
    f.processing_error = None
    return f


def _make_service(rbac_decision: str = "allow"):
    """Build a KnowledgeService with all external deps mocked.

    rbac_decision: "allow" | "deny"
    """
    from src.services.knowledge_service import KnowledgeService
    from src.core.exceptions import ForbiddenError

    db = AsyncMock()
    svc = object.__new__(KnowledgeService)
    svc.db = db
    svc.file_repo = AsyncMock()
    svc.chunk_repo = AsyncMock()
    svc.quota_svc = AsyncMock()

    async def _fake_assert_permission(user, perm, **kwargs):
        if rbac_decision == "deny":
            raise ForbiddenError(f"denied: {perm}")

    mock_rbac_instance = MagicMock()
    mock_rbac_instance.assert_permission = AsyncMock(side_effect=_fake_assert_permission)

    svc._mock_rbac_patcher = patch(
        "src.services.rbac_service.RBACService",
        return_value=mock_rbac_instance,
    )
    svc._mock_rbac_patcher.start()
    svc._mock_rbac_instance = mock_rbac_instance

    return svc


def _stop(svc):
    svc._mock_rbac_patcher.stop()


# ══════════════════════════════════════════════════════════════════════════════
# 1. RBAC — _assert_scope_access
# ══════════════════════════════════════════════════════════════════════════════

class TestAssertScopeAccess:

    @pytest.mark.asyncio
    async def test_personal_scope_always_passes(self):
        svc = _make_service(rbac_decision="deny")
        user = _user()
        # personal never hits RBAC
        await svc._assert_scope_access(user, "personal", None)
        svc._mock_rbac_instance.assert_permission.assert_not_called()
        _stop(svc)

    @pytest.mark.asyncio
    async def test_crew_scope_requires_scope_id(self):
        svc = _make_service()
        user = _user()
        with pytest.raises(BadRequestError):
            await svc._assert_scope_access(user, "crew", None)
        _stop(svc)

    @pytest.mark.asyncio
    async def test_crew_view_passes_files_view_key(self):
        svc = _make_service(rbac_decision="allow")
        user = _user()
        crew_id = uuid.uuid4()
        await svc._assert_scope_access(user, "crew", crew_id)
        svc._mock_rbac_instance.assert_permission.assert_awaited_once_with(
            user, "files.view", crew_id=crew_id
        )
        _stop(svc)

    @pytest.mark.asyncio
    async def test_crew_upload_passes_files_upload_key(self):
        svc = _make_service(rbac_decision="allow")
        user = _user()
        crew_id = uuid.uuid4()
        await svc._assert_scope_access(user, "crew", crew_id, require_write=True)
        svc._mock_rbac_instance.assert_permission.assert_awaited_once_with(
            user, "files.upload", crew_id=crew_id
        )
        _stop(svc)

    @pytest.mark.asyncio
    async def test_crew_delete_passes_files_delete_key(self):
        svc = _make_service(rbac_decision="allow")
        user = _user()
        crew_id = uuid.uuid4()
        await svc._assert_scope_access(user, "crew", crew_id, require_delete=True)
        svc._mock_rbac_instance.assert_permission.assert_awaited_once_with(
            user, "files.delete", crew_id=crew_id
        )
        _stop(svc)

    @pytest.mark.asyncio
    async def test_space_routes_space_id_kwarg(self):
        svc = _make_service(rbac_decision="allow")
        user = _user()
        space_id = uuid.uuid4()
        await svc._assert_scope_access(user, "space", space_id, require_write=True)
        svc._mock_rbac_instance.assert_permission.assert_awaited_once_with(
            user, "files.upload", space_id=space_id
        )
        _stop(svc)

    @pytest.mark.asyncio
    async def test_rbac_deny_raises_forbidden(self):
        svc = _make_service(rbac_decision="deny")
        user = _user()
        with pytest.raises(ForbiddenError):
            await svc._assert_scope_access(user, "crew", uuid.uuid4(), require_write=True)
        _stop(svc)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Upload flow — request_upload_url
# ══════════════════════════════════════════════════════════════════════════════

class TestRequestUploadUrl:

    @pytest.mark.asyncio
    async def test_rejects_invalid_mime(self):
        svc = _make_service()
        user = _user()
        with pytest.raises(BadRequestError, match="not allowed"):
            await svc.request_upload_url(user, "file.exe", "application/x-msdownload", 100, "personal", None)
        _stop(svc)

    @pytest.mark.asyncio
    async def test_rejects_oversized_file(self):
        svc = _make_service()
        user = _user()
        big = 16 * 1024 * 1024  # 16 MB
        with pytest.raises(BadRequestError, match="15 MB"):
            await svc.request_upload_url(user, "big.pdf", "application/pdf", big, "personal", None)
        _stop(svc)

    @pytest.mark.asyncio
    async def test_navigator_cannot_upload_to_crew(self):
        svc = _make_service(rbac_decision="deny")
        user = _user()
        with pytest.raises(ForbiddenError):
            await svc.request_upload_url(
                user, "doc.pdf", "application/pdf", 1024, "crew", uuid.uuid4()
            )
        _stop(svc)

    @pytest.mark.asyncio
    async def test_commander_upload_checks_quota_and_creates_record(self):
        svc = _make_service(rbac_decision="allow")
        user = _user()

        fake_file = _file(owner_id=user.id, scope="personal")
        svc.file_repo.create = AsyncMock(return_value=fake_file)

        with patch("src.services.knowledge_service.generate_upload_sas_url") as mock_sas, \
             patch("src.services.knowledge_service.make_blob_path", return_value="personal/x/y/f.pdf"):
            mock_sas.return_value = {
                "url": "http://dev/upload",
                "expires_at": datetime.now(timezone.utc),
            }
            result = await svc.request_upload_url(
                user, "doc.pdf", "application/pdf", 1024, "personal", None
            )

        svc.quota_svc.check_and_lock.assert_awaited_once()
        svc.quota_svc.add_usage.assert_awaited_once()
        svc.file_repo.create.assert_awaited_once()
        assert result.upload_url == "http://dev/upload"
        _stop(svc)

    @pytest.mark.asyncio
    async def test_quota_exceeded_blocks_upload(self):
        svc = _make_service(rbac_decision="allow")
        user = _user()
        svc.quota_svc.check_and_lock = AsyncMock(
            side_effect=BadRequestError("Storage quota exceeded")
        )
        with patch("src.services.knowledge_service.make_blob_path", return_value="p/x.pdf"):
            with pytest.raises(BadRequestError, match="quota"):
                await svc.request_upload_url(
                    user, "doc.pdf", "application/pdf", 1024, "personal", None
                )
        svc.file_repo.create.assert_not_awaited()
        _stop(svc)


# ══════════════════════════════════════════════════════════════════════════════
# 3. Delete — only owner OR commander+ can delete
# ══════════════════════════════════════════════════════════════════════════════

class TestDeleteFile:

    @pytest.mark.asyncio
    async def test_owner_can_delete_own_file(self):
        svc = _make_service(rbac_decision="deny")  # RBAC denies, but owner bypasses
        user = _user()
        file = _file(owner_id=user.id, scope="crew")
        svc.file_repo.get_by_id = AsyncMock(return_value=file)

        with patch("src.services.knowledge_service.delete_file_and_chunks_task", create=True), \
             patch("src.services.knowledge_service.delete_blob"):
            await svc.delete_file(user, file.id)

        svc.quota_svc.remove_usage.assert_awaited_once()
        svc._mock_rbac_instance.assert_permission.assert_not_called()
        _stop(svc)

    @pytest.mark.asyncio
    async def test_navigator_cannot_delete_others_file(self):
        svc = _make_service(rbac_decision="deny")
        navigator = _user()
        file = _file(owner_id=uuid.uuid4(), scope="crew")  # owned by someone else
        svc.file_repo.get_by_id = AsyncMock(return_value=file)

        with pytest.raises(ForbiddenError):
            await svc.delete_file(navigator, file.id)

        svc.quota_svc.remove_usage.assert_not_awaited()
        _stop(svc)

    @pytest.mark.asyncio
    async def test_commander_can_delete_others_file(self):
        svc = _make_service(rbac_decision="allow")  # RBAC allows (commander)
        commander = _user()
        file = _file(owner_id=uuid.uuid4(), scope="crew")
        svc.file_repo.get_by_id = AsyncMock(return_value=file)

        with patch("src.services.knowledge_service.delete_blob"):
            await svc.delete_file(commander, file.id)

        svc.quota_svc.remove_usage.assert_awaited_once()
        _stop(svc)

    @pytest.mark.asyncio
    async def test_delete_uses_files_delete_permission_key(self):
        svc = _make_service(rbac_decision="allow")
        user = _user()
        crew_id = uuid.uuid4()
        file = _file(owner_id=uuid.uuid4(), scope="crew", scope_id=crew_id)
        svc.file_repo.get_by_id = AsyncMock(return_value=file)

        with patch("src.services.knowledge_service.delete_blob"):
            await svc.delete_file(user, file.id)

        svc._mock_rbac_instance.assert_permission.assert_awaited_once_with(
            user, "files.delete", crew_id=crew_id
        )
        _stop(svc)

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        svc = _make_service()
        user = _user()
        svc.file_repo.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(NotFoundError):
            await svc.delete_file(user, uuid.uuid4())
        _stop(svc)


# ══════════════════════════════════════════════════════════════════════════════
# 4. mention_search — must check files.view before returning results
# ══════════════════════════════════════════════════════════════════════════════

class TestMentionSearch:

    @pytest.mark.asyncio
    async def test_scope_check_runs_before_search(self):
        svc = _make_service(rbac_decision="allow")
        user = _user()
        crew_id = uuid.uuid4()
        svc.file_repo.search_by_name = AsyncMock(return_value=[])

        await svc.mention_search(user, "rep", "crew", crew_id)

        svc._mock_rbac_instance.assert_permission.assert_awaited_once_with(
            user, "files.view", crew_id=crew_id
        )
        svc.file_repo.search_by_name.assert_awaited_once()
        _stop(svc)

    @pytest.mark.asyncio
    async def test_denied_user_cannot_search(self):
        svc = _make_service(rbac_decision="deny")
        user = _user()
        with pytest.raises(ForbiddenError):
            await svc.mention_search(user, "rep", "crew", uuid.uuid4())
        svc.file_repo.search_by_name.assert_not_awaited()
        _stop(svc)

    @pytest.mark.asyncio
    async def test_personal_search_skips_rbac(self):
        svc = _make_service(rbac_decision="deny")
        user = _user()
        svc.file_repo.search_by_name = AsyncMock(return_value=[])

        await svc.mention_search(user, "rep", "personal", None)

        svc._mock_rbac_instance.assert_permission.assert_not_called()
        _stop(svc)


# ══════════════════════════════════════════════════════════════════════════════
# 5. confirm_upload — only file owner or commander+ can confirm
# ══════════════════════════════════════════════════════════════════════════════

class TestConfirmUpload:

    @pytest.mark.asyncio
    async def test_owner_confirms_crew_file_goes_to_pending_approval(self):
        # Owner who lacks files.approve (navigator) confirms their own crew-scoped
        # file → should land in pending_approval, not processing.
        svc = _make_service(rbac_decision="deny")
        user = _user()
        file = _file(owner_id=user.id, scope="crew", status="pending")
        svc.file_repo.get_by_id = AsyncMock(return_value=file)
        svc.file_repo.update = AsyncMock()

        await svc.confirm_upload(user, file.id)

        svc.file_repo.update.assert_called_once()
        assert svc.file_repo.update.call_args[1]["status"] == "pending_approval"
        _stop(svc)

    @pytest.mark.asyncio
    async def test_admin_confirms_crew_file_goes_to_processing(self):
        # Platform Admin / Owner auto-approves → goes straight to processing
        # (Lucas's 2026-04-30 correction: crew-level Owner / Editor must
        # park in pending_approval; only platform Owner/Admin self-approve).
        svc = _make_service(rbac_decision="allow")
        user = _user(role="admin")
        file = _file(owner_id=user.id, scope="crew", status="pending")
        svc.file_repo.get_by_id = AsyncMock(return_value=file)
        svc.file_repo.update = AsyncMock()

        with patch("src.workers.knowledge_worker.process_file_for_context", create=True):
            await svc.confirm_upload(user, file.id)

        svc.file_repo.update.assert_called_once()
        assert svc.file_repo.update.call_args[1]["status"] == "processing"
        _stop(svc)

    @pytest.mark.asyncio
    async def test_navigator_cannot_confirm_others_file(self):
        svc = _make_service(rbac_decision="deny")
        navigator = _user()
        file = _file(owner_id=uuid.uuid4(), scope="crew", status="pending")
        svc.file_repo.get_by_id = AsyncMock(return_value=file)

        with pytest.raises(ForbiddenError):
            await svc.confirm_upload(navigator, file.id)
        _stop(svc)

    @pytest.mark.asyncio
    async def test_non_pending_file_rejected(self):
        svc = _make_service(rbac_decision="allow")
        user = _user()
        file = _file(owner_id=user.id, status="ready")
        svc.file_repo.get_by_id = AsyncMock(return_value=file)

        with pytest.raises(BadRequestError, match="pending"):
            await svc.confirm_upload(user, file.id)
        _stop(svc)
