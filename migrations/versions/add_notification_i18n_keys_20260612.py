"""Add i18n key columns to notifications for frontend locale rendering.

Adds four nullable columns so the frontend can re-render notification
text in the user's current locale rather than using the pre-rendered
strings that were stored at creation time.

Columns added to ``notifications``:
* ``title_key``         — message key e.g. "notif_space_added_title"
* ``title_params``      — JSON interpolation params e.g. {"space": "demo"}
* ``description_key``   — message key for the description string
* ``description_params`` — JSON interpolation params for the description

All four are nullable; existing rows are left with NULL so old clients
continue to use the pre-rendered ``title`` / ``description`` fallback.
No data backfill is required.

Revision ID: add_notification_i18n_keys_20260612
Revises: chat_sessions_20260609
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "notif_i18n_keys_20260612"
down_revision = "chat_sessions_20260609"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("notifications") as batch:
        batch.add_column(
            sa.Column("title_key", sa.String(100), nullable=True)
        )
        batch.add_column(
            sa.Column("title_params", postgresql.JSON(astext_type=sa.Text()), nullable=True)
        )
        batch.add_column(
            sa.Column("description_key", sa.String(100), nullable=True)
        )
        batch.add_column(
            sa.Column("description_params", postgresql.JSON(astext_type=sa.Text()), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("notifications") as batch:
        batch.drop_column("description_params")
        batch.drop_column("description_key")
        batch.drop_column("title_params")
        batch.drop_column("title_key")
