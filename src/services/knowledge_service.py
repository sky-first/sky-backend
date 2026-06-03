"""Knowledge Library service — CRUD, SAS URL generation, RBAC gating."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.azure.blob_helper import (
    delete_blob,
    generate_download_sas_url,
    generate_upload_sas_url,
    make_blob_path,
)
from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.knowledge import KnowledgeFile
from src.models.user import User
from src.repositories.knowledge import KnowledgeChunkRepository, KnowledgeFileRepository
from src.schemas.knowledge import (
    KnowledgeFileListResponse,
    KnowledgeFileResponse,
    MentionSearchItem,
    PreviewUrlResponse,
    UploadUrlResponse,
)
from src.services.quota_service import QuotaService

# Allowed MIME types (server-side whitelist)
ALLOWED_MIMES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}

FILE_MAX_BYTES = 15 * 1024 * 1024  # 15 MB


class KnowledgeService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.file_repo = KnowledgeFileRepository(db)
        self.chunk_repo = KnowledgeChunkRepository(db)
        self.quota_svc = QuotaService(db)

    async def _audit(
        self,
        *,
        user: User,
        action: str,
        file: Optional[KnowledgeFile] = None,
        decision: str = "allow",
        decision_reason: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """Best-effort audit write for every Knowledge Library mutation.

        Lucas's 2026-04-30 review: an uploaded file ends up as embeddings
        the AI can cite — so every upload / approve / delete needs a
        chain-linked audit row that says WHO did WHAT to WHICH file.
        Failures here are swallowed; the underlying mutation already
        committed and we don't want a non-functional audit pipe to
        propagate as a 500 to the caller.
        """
        try:
            from src.services.audit_service import AuditService

            metadata: dict = {
                "scope": file.scope if file else None,
                "scope_id": str(file.scope_id) if file and file.scope_id else None,
                "filename": file.original_name if file else None,
                "mime_type": file.mime_type if file else None,
                "size_bytes": file.size_bytes if file else None,
                "status": file.status if file else None,
            }
            if extra:
                metadata.update(extra)

            await AuditService(self.db).log_event(
                actor_kind="sky_support" if getattr(user, "is_sky_operator", False) else "user",
                actor_id=getattr(user, "id", None),
                actor_email=getattr(user, "email", None),
                action=action,
                resource_kind="knowledge_file",
                resource_id=str(file.id) if file else None,
                decision=decision,
                decision_reason=decision_reason,
                metadata={k: v for k, v in metadata.items() if v is not None},
            )
        except Exception:
            # never raise from audit
            pass

    # ── RBAC helpers ──────────────────────────────────────────────────────────

    async def _assert_scope_access(
        self,
        user: User,
        scope: str,
        scope_id: Optional[UUID],
        require_write: bool = False,
        require_delete: bool = False,
        require_approve: bool = False,
    ) -> None:
        """Raise ForbiddenError if user cannot access the requested scope.

        Permission keys used (must exist in DEFAULT_ROLE_PERMISSIONS):
          files.view    — read/list (owner, editor, viewer)
          files.upload  — upload (owner, editor)
          files.delete  — delete (owner only)
          files.approve — approve editor uploads (owner only)
        """
        if scope == "personal":
            return  # always own personal scope

        if scope_id is None:
            raise BadRequestError("scope_id is required for crew/space scope.")

        from src.services.rbac_service import RBACService

        rbac = RBACService(self.db)

        if require_approve:
            perm = "files.approve"
        elif require_delete:
            perm = "files.delete"
        elif require_write:
            perm = "files.upload"
        else:
            perm = "files.view"

        # Route scope_id to the correct keyword so assert_permission can
        # resolve the user's crew/space role correctly.
        kwargs: dict = {"crew_id": scope_id} if scope == "crew" else {"space_id": scope_id}

        try:
            await rbac.assert_permission(user, perm, **kwargs)
        except ForbiddenError:
            raise ForbiddenError(
                f"You do not have permission to {perm.split('.')[-1]} files in this {scope}."
            )

    async def _has_scope_access(
        self,
        user: User,
        scope: str,
        scope_id: Optional[UUID],
        require_approve: bool = False,
    ) -> bool:
        """Return True/False without raising — used to branch on approval workflow."""
        try:
            await self._assert_scope_access(
                user, scope, scope_id, require_approve=require_approve
            )
            return True
        except (ForbiddenError, BadRequestError):
            return False

    async def _assert_file_owner_or_scope(
        self,
        user: User,
        file: KnowledgeFile,
        require_write: bool = False,
        require_delete: bool = False,
    ) -> None:
        """Allow file owner unconditionally; otherwise enforce scope RBAC."""
        if file.user_id == user.id:
            return
        await self._assert_scope_access(
            user, file.scope, file.scope_id,
            require_write=require_write,
            require_delete=require_delete,
        )

    # ── Upload flow ───────────────────────────────────────────────────────────

    async def request_upload_url(
        self,
        user: User,
        filename: str,
        mime_type: str,
        size_bytes: int,
        scope: str,
        scope_id: Optional[UUID],
    ) -> UploadUrlResponse:
        if mime_type not in ALLOWED_MIMES:
            raise BadRequestError(f"File type not allowed: {mime_type}")
        if size_bytes > FILE_MAX_BYTES:
            raise BadRequestError(f"File exceeds 15 MB limit ({size_bytes} bytes).")

        await self._assert_scope_access(user, scope, scope_id, require_write=True)

        effective_scope_id = scope_id if scope != "personal" else user.id

        # Atomic quota check + increment inside the same transaction.
        # SELECT FOR UPDATE prevents two concurrent uploads from racing past the limit.
        await self.quota_svc.check_and_lock(scope, effective_scope_id, size_bytes)
        # Increment immediately while the lock is held — if confirm never comes
        # (e.g. user closes the browser) the quota stays pessimistically used
        # until the pending record is garbage-collected (acceptable for a POC).
        await self.quota_svc.add_usage(scope, effective_scope_id, size_bytes)

        blob_path = make_blob_path(str(user.id), scope, str(effective_scope_id), filename)
        sas = generate_upload_sas_url(blob_path, mime_type, size_bytes, ttl_seconds=600)

        file_record = await self.file_repo.create(
            id=uuid.uuid4(),
            user_id=user.id,
            original_name=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            blob_path=blob_path,
            scope=scope,
            scope_id=effective_scope_id,
            status="pending",
        )
        await self.db.commit()
        await self._audit(user=user, action="knowledge.upload.requested", file=file_record)

        return UploadUrlResponse(
            file_id=file_record.id,
            upload_url=sas["url"],
            expires_at=sas["expires_at"],
        )

    async def confirm_upload(
        self,
        user: User,
        file_id: UUID,
        sha256_hash: Optional[str] = None,
    ) -> KnowledgeFileResponse:
        file = await self.file_repo.get_by_id(file_id)
        if not file or file.deleted_at:
            raise NotFoundError("File not found.")
        await self._assert_file_owner_or_scope(user, file, require_write=True)

        if file.status != "pending":
            raise BadRequestError("File is not in pending state.")

        # Approval gate (Lucas's 2026-04-30 correction):
        #   • Owner / Admin (platform role) → auto-approve, status="processing".
        #   • Owner / Editor → upload allowed but parks the file in
        #     `pending_approval` until an Owner or Admin reviews it.
        #   • Viewer → blocked earlier in request_upload_url.
        # Personal-scope uploads still self-approve when the uploader is
        # owner/admin; otherwise they ALSO go to pending_approval so a
        # owner's "personal" knowledge ends up reviewed before any AI
        # ever cites it. The audit trail in audit_events plus the
        # KnowledgeSourceFlag popover then carry the proveniência forward.
        is_platform_approver = (getattr(user, "role", None) in ("owner", "admin", "super_admin"))
        new_status = "processing" if is_platform_approver else "pending_approval"

        await self.file_repo.update(file_id, status=new_status, sha256_hash=sha256_hash)

        if new_status == "processing":
            try:
                from src.workers.knowledge_worker import process_file_for_context
                process_file_for_context.delay(str(file_id))
            except Exception:
                pass

        await self.db.commit()
        await self.db.refresh(file)
        await self._audit(
            user=user,
            action="knowledge.upload.confirmed",
            file=file,
            decision_reason=f"new_status={new_status}",
            extra={"sha256_hash": sha256_hash},
        )
        return KnowledgeFileResponse.model_validate(file)

    async def approve_upload(self, user: User, file_id: UUID) -> KnowledgeFileResponse:
        """Owner / Admin approves an uploaded file and triggers processing.

        Tightened on 2026-04-30: only platform-level Owner / Admin can
        approve. Owner / Editor can no longer approve their own
        scope's uploads — keeps a single audit chokepoint at the
        tenant level so a owner cannot rubber-stamp an editor's
        unverified CSV into the AI context.
        """
        file = await self.file_repo.get_by_id(file_id)
        if not file or file.deleted_at:
            raise NotFoundError("File not found.")

        if getattr(user, "role", None) not in ("owner", "admin", "super_admin"):
            raise ForbiddenError(
                "Only platform SuperAdmin or Admin can approve Knowledge Library uploads."
            )

        if file.status != "pending_approval":
            raise BadRequestError("File is not awaiting approval.")

        await self.file_repo.update(file_id, status="processing")

        try:
            from src.workers.knowledge_worker import process_file_for_context
            process_file_for_context.delay(str(file_id))
        except Exception:
            pass

        await self.db.commit()
        await self.db.refresh(file)
        await self._audit(user=user, action="knowledge.upload.approved", file=file)
        return KnowledgeFileResponse.model_validate(file)

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_file(self, user: User, file_id: UUID) -> KnowledgeFileResponse:
        file = await self.file_repo.get_by_id(file_id)
        if not file or file.deleted_at:
            raise NotFoundError("File not found.")
        await self._assert_file_owner_or_scope(user, file)
        return KnowledgeFileResponse.model_validate(file)

    async def list_files(
        self,
        user: User,
        scope: str,
        scope_id: Optional[UUID],
        skip: int = 0,
        limit: int = 50,
    ) -> KnowledgeFileListResponse:
        await self._assert_scope_access(user, scope, scope_id)

        if scope == "personal":
            items = await self.file_repo.list_personal(user.id, skip=skip, limit=limit)
        else:
            items = await self.file_repo.list_by_scope(scope, scope_id, skip=skip, limit=limit)

        return KnowledgeFileListResponse(
            items=[KnowledgeFileResponse.model_validate(f) for f in items],
            total=len(items),
            skip=skip,
            limit=limit,
        )

    async def get_preview_url(self, user: User, file_id: UUID) -> PreviewUrlResponse:
        file = await self.file_repo.get_by_id(file_id)
        if not file or file.deleted_at:
            raise NotFoundError("File not found.")
        await self._assert_file_owner_or_scope(user, file)

        url = generate_download_sas_url(file.blob_path, ttl_seconds=300)
        return PreviewUrlResponse(
            url=url,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
        )

    async def mention_search(
        self,
        user: User,
        query: str,
        scope: str,
        scope_id: Optional[UUID],
    ) -> List[MentionSearchItem]:
        # files.view check: user must belong to the scope to search its files
        await self._assert_scope_access(user, scope, scope_id)
        items = await self.file_repo.search_by_name(
            query=query,
            scope=scope,
            scope_id=scope_id,
            user_id=user.id,
            limit=10,
        )
        return [MentionSearchItem.model_validate(f) for f in items]

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete_file(self, user: User, file_id: UUID) -> None:
        file = await self.file_repo.get_by_id(file_id)
        if not file or file.deleted_at:
            raise NotFoundError("File not found.")
        await self._assert_file_owner_or_scope(user, file, require_delete=True)

        # Soft-delete DB record
        await self.file_repo.soft_delete(file_id)

        # Enqueue blob + chunk cleanup
        try:
            from src.workers.knowledge_worker import delete_file_and_chunks
            delete_file_and_chunks.delay(str(file_id))
        except Exception:
            # Fallback: clean chunks synchronously
            await self.chunk_repo.delete_by_file(file_id)
            if file.blob_path:
                delete_blob(file.blob_path)

        # Decrement quota
        await self.quota_svc.remove_usage(file.scope, file.scope_id, file.size_bytes)
        await self.db.commit()
        await self._audit(user=user, action="knowledge.file.deleted", file=file)

    # ── Reprocess ─────────────────────────────────────────────────────────────

    async def reprocess_file(self, user: User, file_id: UUID) -> KnowledgeFileResponse:
        file = await self.file_repo.get_by_id(file_id)
        if not file or file.deleted_at:
            raise NotFoundError("File not found.")
        # require_write=True: only owner+ (or the file owner) can trigger reprocessing
        await self._assert_file_owner_or_scope(user, file, require_write=True)

        if file.status not in ("error", "ready"):
            raise BadRequestError("Only files with status 'error' or 'ready' can be reprocessed.")

        await self.file_repo.update(file_id, status="processing", processing_error=None)
        await self.db.commit()

        try:
            from src.workers.knowledge_worker import process_file_for_context
            process_file_for_context.delay(str(file_id))
        except Exception:
            pass

        await self.db.refresh(file)
        await self._audit(user=user, action="knowledge.file.reprocessed", file=file)
        return KnowledgeFileResponse.model_validate(file)
