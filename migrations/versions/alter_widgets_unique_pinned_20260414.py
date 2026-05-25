"""Widgets: enforce one widget per pinned message at the DB level.

Implements use case A11 from the agent master plan: if two users race to
pin the same assistant message, only one widget should be created. The
second INSERT hits the unique index and the service layer returns the
pre-existing widget.

A partial unique index (WHERE pinned_message_id IS NOT NULL) is used so
older widgets with null pinned_message_id — which is every widget before
this feature shipped — don't collide with each other.

Revision ID: widgets_uniq_pin_20260414
Revises: exec_delta_20260414
Create Date: 2026-04-14 16:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "widgets_uniq_pin_20260414"
down_revision = "exec_delta_20260414"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_widgets_pinned_message_id",
        "widgets",
        ["pinned_message_id"],
        unique=True,
        postgresql_where=sa.text("pinned_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_widgets_pinned_message_id", table_name="widgets")
