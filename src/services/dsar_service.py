"""DSAR (Data Subject Access Request) service — GDPR Art. 15 + 17.

Provides:
- export: aggregate all data about a user into a single JSON dict
- erasure: soft-delete user + anonymize mentions
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User

logger = logging.getLogger(__name__)

# Tables that contain user data, with (table_name, user_column, extra_columns_to_export)
USER_DATA_TABLES = [
    ("ai_history", "user_id", ["id", "query", "preview", "date", "tags", "category"]),
    ("ai_queries", "user_id", ["id", "query", "connection_id", "created_at"]),
    ("ai_feedback", "user_id", ["id", "rating", "comment", "created_at"]),
    ("comments", "user_id", ["id", "content", "page_id", "created_at"]),
    ("starred_items", "user_id", ["id", "item_id", "item_type", "created_at"]),
    ("notifications", "user_id", ["id", "type", "title", "message", "read", "created_at"]),
    ("pages", "owner_id", ["id", "name", "type", "crew_id", "created_at"]),
    ("page_members", "user_id", ["id", "page_id", "role", "joined_at"]),
    ("crew_members", "user_id", ["id", "crew_id", "role", "created_at"]),
    ("space_members", "user_id", ["id", "space_id", "created_at"]),
    ("data_connections", "created_by", ["id", "name", "connector_id", "status", "created_at"]),
    ("audit_events", "actor_id", ["id", "action", "decision", "occurred_at"]),
    ("dashboard_build_jobs", "user_id", ["id", "status", "created_at"]),
    ("agents", "created_by", ["id", "name", "status", "created_at"]),
]


class DSARService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def export_user_data(self, user_email: str) -> Dict[str, Any]:
        """Export all data related to a user (GDPR Art. 15 right of access)."""
        # Find user
        result = await self.db.execute(
            select(User).where(User.email == user_email)
        )
        user = result.scalar_one_or_none()
        if not user:
            return {"error": "User not found", "email": user_email}

        user_id = str(user.id)

        export: Dict[str, Any] = {
            "subject": {
                "id": user_id,
                "email": user.email,
                "name": user.name,
                "role": user.role,
                "auth_provider": user.auth_provider,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            },
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

        for table_name, user_col, columns in USER_DATA_TABLES:
            try:
                cols = ", ".join(columns)
                query = text(f"SELECT {cols} FROM {table_name} WHERE {user_col} = :uid")
                r = await self.db.execute(query, {"uid": user.id})
                rows = r.fetchall()
                export[table_name] = [
                    {columns[i]: self._serialize(row[i]) for i in range(len(columns))}
                    for row in rows
                ]
            except Exception as e:
                export[table_name] = {"error": str(e)}
                logger.warning("dsar.export.table_error table=%s error=%s", table_name, e)

        return export

    async def erase_user(self, user_email: str) -> Dict[str, Any]:
        """Soft-delete user and anonymize mentions (GDPR Art. 17 right to erasure)."""
        result = await self.db.execute(
            select(User).where(User.email == user_email, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if not user:
            return {"error": "User not found or already deleted", "email": user_email}

        user_id = user.id
        anonymized_email = f"deleted-{str(user_id)[:8]}@deleted.local"

        # 1. Soft-delete the user
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                deleted_at=datetime.now(timezone.utc),
                email=anonymized_email,
                name="Deleted User",
                avatar=None,
            )
        )

        # 2. Anonymize comments
        try:
            await self.db.execute(text(
                "UPDATE comments SET content = '[deleted]' WHERE user_id = :uid"
            ), {"uid": user_id})
        except Exception:
            pass

        # 3. Delete refresh tokens
        try:
            await self.db.execute(text(
                "DELETE FROM refresh_tokens WHERE user_id = :uid"
            ), {"uid": user_id})
        except Exception:
            pass

        # 4. Remove from crews and spaces
        try:
            await self.db.execute(text(
                "DELETE FROM crew_members WHERE user_id = :uid"
            ), {"uid": user_id})
            await self.db.execute(text(
                "DELETE FROM space_members WHERE user_id = :uid"
            ), {"uid": user_id})
            await self.db.execute(text(
                "DELETE FROM page_members WHERE user_id = :uid"
            ), {"uid": user_id})
        except Exception:
            pass

        await self.db.commit()

        return {
            "status": "erased",
            "user_id": str(user_id),
            "anonymized_email": anonymized_email,
            "note": "PII fields hard-purged after 30 days per retention policy",
        }

    @staticmethod
    def _serialize(val: Any) -> Any:
        if isinstance(val, datetime):
            return val.isoformat()
        if isinstance(val, UUID):
            return str(val)
        return val
