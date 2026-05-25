"""Build SecurityConfig for the AI service based on user permissions.

The backend is the source of truth for what data a user can see. This module
constructs a SecurityConfig dict that the AI service applies:
- Row-level filtering (WHERE clauses per table)
- Column-level masking (blocked/allowed columns per table)
- Global blocked columns (PII fields masked for all tables)

The AI service already has the infrastructure to apply these rules
(core/security/security_config.py). This module just provides the
user-specific values.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Default PII columns to mask globally unless the user has data.pii.unmask
DEFAULT_PII_COLUMNS = [
    "email", "phone", "ssn", "social_security", "credit_card",
    "password", "secret", "token", "api_key", "private_key",
    "date_of_birth", "dob", "address", "zip_code", "postal_code",
]


async def build_security_config(
    db: AsyncSession,
    user_id: UUID,
    connection_id: UUID,
    has_pii_unmask: bool = False,
) -> Dict[str, Any]:
    """Build a SecurityConfig dict for the AI service.

    Args:
        db: Database session
        user_id: The requesting user's ID
        connection_id: The connection being queried
        has_pii_unmask: Whether the user has data.pii.unmask permission

    Returns:
        Dict matching the AI service's SecurityConfig Pydantic model
    """
    config: Dict[str, Any] = {
        "blocked_sql_keywords": [
            "DROP", "ALTER", "INSERT", "UPDATE", "DELETE",
            "TRUNCATE", "CREATE", "GRANT", "REVOKE",
        ],
        "tables": {},
        "global_blocked_columns": [] if has_pii_unmask else DEFAULT_PII_COLUMNS,
        "max_rows_limit": 5000,
        "allow_joins": True,
        "allow_subqueries": True,
    }

    # Load table-level permissions from the permission_grants table
    # (table_member_permissions in the current schema)
    try:
        from src.models.permission import TableMemberPermission

        result = await db.execute(
            select(TableMemberPermission).where(
                TableMemberPermission.connection_id == connection_id,
                TableMemberPermission.user_id == user_id,
            )
        )
        grants = result.scalars().all()

        for grant in grants:
            table_name = grant.table_name
            table_config: Dict[str, Any] = {}

            if getattr(grant, "row_filter", None):
                table_config["row_filter"] = grant.row_filter
            if getattr(grant, "allowed_columns", None):
                table_config["allowed_columns"] = grant.allowed_columns
            if getattr(grant, "masked_columns", None):
                table_config["blocked_columns"] = grant.masked_columns

            if table_config:
                config["tables"][table_name] = table_config
    except Exception as exc:
        # If table_member_permissions doesn't exist yet, just use defaults
        logger.debug("security_config.table_grants_skip: %s", exc)

    return config
