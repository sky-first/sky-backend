"""consolidated_scoping_and_templates_fix

Revision ID: fd74af4b3c14
Revises: dbb9a0420d3e
Create Date: 2026-03-18 16:30:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "fd74af4b3c14"
down_revision = "dbb9a0420d3e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create templates table
    op.create_table(
        "templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("creator", sa.String(255), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("thumbnail", sa.Text(), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("widgets", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("icon", sa.String(255), nullable=True),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("popular", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("enterprise", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # 2. Add indexes to templates
    op.create_index("idx_templates_category", "templates", ["category"])
    op.create_index("idx_templates_popular", "templates", ["popular"])
    op.create_index("idx_templates_enterprise", "templates", ["enterprise"])

    # 3. Fix Dashboards
    op.create_foreign_key(
        "fk_dashboards_templates",
        "dashboards",
        "templates",
        ["template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_dashboards_template_id", "dashboards", ["template_id"])
    op.create_index(op.f("ix_dashboards_planet_id"), "dashboards", ["planet_id"], unique=False)

    # 4. Strategy Models Scoping
    # Pillars
    op.add_column(
        "strategic_pillars", sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "strategic_pillars", sa.Column("crew_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index(
        op.f("ix_strategic_pillars_crew_id"), "strategic_pillars", ["crew_id"], unique=False
    )
    op.create_index(
        op.f("ix_strategic_pillars_space_id"), "strategic_pillars", ["space_id"], unique=False
    )
    op.create_foreign_key(
        None, "strategic_pillars", "spaces", ["space_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        None, "strategic_pillars", "crews", ["crew_id"], ["id"], ondelete="CASCADE"
    )

    # Objectives
    op.add_column(
        "strategic_objectives", sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "strategic_objectives", sa.Column("crew_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index(
        op.f("ix_strategic_objectives_crew_id"), "strategic_objectives", ["crew_id"], unique=False
    )
    op.create_index(
        op.f("ix_strategic_objectives_space_id"), "strategic_objectives", ["space_id"], unique=False
    )
    op.create_foreign_key(
        None, "strategic_objectives", "spaces", ["space_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        None, "strategic_objectives", "crews", ["crew_id"], ["id"], ondelete="CASCADE"
    )

    # Initiatives
    op.add_column(
        "strategy_initiatives", sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "strategy_initiatives", sa.Column("crew_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index(
        op.f("ix_strategy_initiatives_crew_id"), "strategy_initiatives", ["crew_id"], unique=False
    )
    op.create_index(
        op.f("ix_strategy_initiatives_space_id"), "strategy_initiatives", ["space_id"], unique=False
    )
    op.create_foreign_key(
        None, "strategy_initiatives", "spaces", ["space_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        None, "strategy_initiatives", "crews", ["crew_id"], ["id"], ondelete="CASCADE"
    )

    # Assumptions
    op.add_column(
        "strategy_assumptions", sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "strategy_assumptions", sa.Column("crew_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index(
        op.f("ix_strategy_assumptions_crew_id"), "strategy_assumptions", ["crew_id"], unique=False
    )
    op.create_index(
        op.f("ix_strategy_assumptions_space_id"), "strategy_assumptions", ["space_id"], unique=False
    )
    op.create_foreign_key(
        None, "strategy_assumptions", "spaces", ["space_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        None, "strategy_assumptions", "crews", ["crew_id"], ["id"], ondelete="CASCADE"
    )

    # OKRs
    op.add_column(
        "strategy_okrs", sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "strategy_okrs", sa.Column("crew_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index(op.f("ix_strategy_okrs_crew_id"), "strategy_okrs", ["crew_id"], unique=False)
    op.create_index(op.f("ix_strategy_okrs_space_id"), "strategy_okrs", ["space_id"], unique=False)
    op.create_foreign_key(None, "strategy_okrs", "spaces", ["space_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key(None, "strategy_okrs", "crews", ["crew_id"], ["id"], ondelete="CASCADE")

    # 5. Intelligence Signals / Signal Events Fixes
    # Signals
    op.add_column(
        "intelligence_signals", sa.Column("crew_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.alter_column(
        "intelligence_signals",
        "space_id",
        existing_type=sa.VARCHAR(length=100),
        type_=postgresql.UUID(as_uuid=True),
        existing_nullable=True,
        postgresql_using="space_id::uuid",
    )
    op.create_index(
        op.f("ix_intelligence_signals_crew_id"), "intelligence_signals", ["crew_id"], unique=False
    )
    op.create_foreign_key(
        None, "intelligence_signals", "spaces", ["space_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        None, "intelligence_signals", "crews", ["crew_id"], ["id"], ondelete="CASCADE"
    )

    # Signal Events
    op.add_column(
        "signal_events", sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "signal_events", sa.Column("crew_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.alter_column(
        "signal_events",
        "id",
        existing_type=sa.VARCHAR(length=36),
        type_=postgresql.UUID(as_uuid=True),
        existing_nullable=False,
        postgresql_using="id::uuid",
    )
    op.create_index(op.f("ix_signal_events_crew_id"), "signal_events", ["crew_id"], unique=False)
    op.create_index(op.f("ix_signal_events_space_id"), "signal_events", ["space_id"], unique=False)
    op.create_foreign_key(None, "signal_events", "spaces", ["space_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key(None, "signal_events", "crews", ["crew_id"], ["id"], ondelete="CASCADE")

    # 6. Additional Miscellaneous Indexes for consistency
    op.create_index(op.f("ix_ai_queries_user_id"), "ai_queries", ["user_id"], unique=False)
    op.create_index(op.f("ix_ai_queries_widget_id"), "ai_queries", ["widget_id"], unique=False)
    op.create_index(op.f("ix_ai_responses_is_active"), "ai_responses", ["is_active"], unique=False)
    op.create_index(op.f("ix_ai_responses_timestamp"), "ai_responses", ["timestamp"], unique=False)
    op.create_index(op.f("ix_ai_responses_widget_id"), "ai_responses", ["widget_id"], unique=False)
    op.create_index(
        op.f("ix_chat_messages_timestamp"), "chat_messages", ["timestamp"], unique=False
    )
    op.create_index(
        op.f("ix_chat_messages_widget_id"), "chat_messages", ["widget_id"], unique=False
    )
    op.create_index(op.f("ix_comments_dashboard_id"), "comments", ["dashboard_id"], unique=False)
    op.create_index(op.f("ix_comments_user_id"), "comments", ["user_id"], unique=False)
    op.create_index(op.f("ix_comments_widget_id"), "comments", ["widget_id"], unique=False)
    op.create_index(
        op.f("ix_connection_metadata_connection_id"),
        "connection_metadata",
        ["connection_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_connection_permissions_connection_id"),
        "connection_permissions",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_connection_permissions_crew_id"),
        "connection_permissions",
        ["crew_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_connection_permissions_space_id"),
        "connection_permissions",
        ["space_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_connection_permissions_user_id"),
        "connection_permissions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    # 1. Reverse templates and dashboard FK
    op.drop_index("idx_dashboards_template_id", "dashboards")
    op.drop_constraint("fk_dashboards_templates", "dashboards", type_="foreignkey")
    op.drop_table("templates")

    # 2. Strategy column drops (Simplified)
    for table in [
        "strategic_pillars",
        "strategic_objectives",
        "strategy_okrs",
        "strategy_assumptions",
        "strategy_initiatives",
        "intelligence_signals",
        "signal_events",
    ]:
        try:
            op.drop_column(table, "crew_id")
            op.drop_column(table, "space_id")
        except Exception:
            pass
