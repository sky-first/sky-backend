"""Add notification_preferences table.

Revision ID: add_notification_preferences_20260412
Revises: add_space_id_to_pages_20260411
Create Date: 2026-04-12 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers
revision = "add_notification_preferences_20260412"
down_revision = "add_space_id_to_pages_20260411"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Widen the active alembic version table's version_num so this
    # revision ID (38 chars) fits — the legacy schema was VARCHAR(32).
    #
    # Before sky-be split off its own version table (env.py:
    # version_table="alembic_version_be"), this migration only knew
    # about the shared ``alembic_version``. On a freshly provisioned
    # tenant DB only ``alembic_version_be`` exists, and the
    # unconditional ALTER on the legacy table raised
    # ``UndefinedTable`` and failed the migrate Job. Cover both
    # cases idempotently via information_schema.
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'alembic_version'
          ) THEN
            ALTER TABLE alembic_version
              ALTER COLUMN version_num TYPE VARCHAR(64);
          END IF;
          IF EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'alembic_version_be'
          ) THEN
            ALTER TABLE alembic_version_be
              ALTER COLUMN version_num TYPE VARCHAR(64);
          END IF;
        END $$;
        """
    )

    op.create_table(
        "notification_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_value", sa.String(255), nullable=True),
        sa.Column("channel", sa.String(20), nullable=False, server_default="all"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "scope_type", "scope_value", "channel", name="uq_notif_pref_user_scope_channel"),
    )
    op.create_index("idx_notif_pref_user_id", "notification_preferences", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_notif_pref_user_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'alembic_version'
          ) THEN
            ALTER TABLE alembic_version
              ALTER COLUMN version_num TYPE VARCHAR(32);
          END IF;
          IF EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'alembic_version_be'
          ) THEN
            ALTER TABLE alembic_version_be
              ALTER COLUMN version_num TYPE VARCHAR(32);
          END IF;
        END $$;
        """
    )
