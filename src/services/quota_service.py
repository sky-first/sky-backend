"""Quota enforcement for Knowledge Library.

Limits (env-configurable, defaults to Lean POC values):
  personal : 15 files / 100 MB
  crew     : 50 files / 500 MB
  space    : 100 files / 1 024 MB (1 GB)

All mutations go through get_or_create_locked() which issues SELECT FOR UPDATE
on the quota row to prevent race conditions on concurrent uploads.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.core.exceptions import BadRequestError
from src.repositories.knowledge import QuotaRepository
from src.schemas.knowledge import QuotaResponse

_MB = 1024 * 1024
_GB = 1024 * _MB

_LIMITS: dict[str, dict] = {
    "personal": {
        "files": int(getattr(settings, "QUOTA_PERSONAL_FILES", 15)),
        "bytes": int(getattr(settings, "QUOTA_PERSONAL_MB", 100)) * _MB,
    },
    "crew": {
        "files": int(getattr(settings, "QUOTA_CREW_FILES", 50)),
        "bytes": int(getattr(settings, "QUOTA_CREW_MB", 500)) * _MB,
    },
    "space": {
        "files": int(getattr(settings, "QUOTA_SPACE_FILES", 100)),
        "bytes": int(getattr(settings, "QUOTA_SPACE_MB", 1024)) * _MB,
    },
}


class QuotaService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = QuotaRepository(db)

    async def check_and_lock(self, scope: str, scope_id: UUID, incoming_bytes: int) -> None:
        """Assert quota is not exceeded. Raises BadRequestError if over limit.

        Caller must be inside a transaction; the SELECT FOR UPDATE row lock is
        released when the transaction commits or rolls back.
        """
        limits = _LIMITS.get(scope, _LIMITS["personal"])
        row = await self.repo.get_for_update(scope, scope_id)

        if row.files_count >= limits["files"]:
            raise BadRequestError(
                f"File limit reached for {scope} ({limits['files']} files maximum)."
            )

        if row.bytes_used + incoming_bytes > limits["bytes"]:
            limit_mb = limits["bytes"] // _MB
            raise BadRequestError(
                f"Storage quota exceeded for {scope} ({limit_mb} MB maximum)."
            )

    async def add_usage(self, scope: str, scope_id: UUID, bytes_delta: int) -> None:
        await self.repo.increment(scope, scope_id, bytes_delta=bytes_delta, files_delta=1)

    async def remove_usage(self, scope: str, scope_id: UUID, bytes_delta: int) -> None:
        await self.repo.increment(scope, scope_id, bytes_delta=-bytes_delta, files_delta=-1)

    async def get_quota(self, scope: str, scope_id: UUID) -> QuotaResponse:
        limits = _LIMITS.get(scope, _LIMITS["personal"])
        row = await self.repo.get_or_create(scope, scope_id)
        bytes_limit = limits["bytes"]
        return QuotaResponse(
            scope=scope,
            scope_id=scope_id,
            bytes_used=row.bytes_used,
            files_count=row.files_count,
            bytes_limit=bytes_limit,
            files_limit=limits["files"],
            percent_used=round((row.bytes_used / bytes_limit) * 100, 1) if bytes_limit > 0 else 0.0,
        )
