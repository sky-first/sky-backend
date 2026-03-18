"""Add user_datasets table

Revision ID: add_user_datasets
Revises: a1b2c3d4e5f6
Create Date: 2025-01-20 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_user_datasets"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_datasets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", sa.String(255), nullable=False),
        sa.Column("dataset_type", sa.String(50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_user_datasets_user_id", "user_datasets", ["user_id"], unique=False
    )
    op.create_index(
        "idx_user_datasets_dataset_id", "user_datasets", ["dataset_id"], unique=False
    )
    op.create_unique_constraint(
        "uq_user_datasets", "user_datasets", ["user_id", "dataset_id"]
    )


def downgrade() -> None:
    pass
    op.drop_constraint("uq_user_datasets", "user_datasets", type_="unique")
    op.drop_index("idx_user_datasets_dataset_id", table_name="user_datasets")
    op.drop_index("idx_user_datasets_user_id", table_name="user_datasets")
