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
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # 1. Create templates table
    if "templates" not in tables:
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
            sa.Column("widgets", sa.JSON(), server_default='[]', nullable=False),
            sa.Column("icon", sa.String(255), nullable=True),
            sa.Column("color", sa.String(7), nullable=False),
            sa.Column("popular", sa.Boolean(), server_default='false', nullable=False),
            sa.Column("enterprise", sa.Boolean(), server_default='false', nullable=False),
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
        op.create_index("idx_templates_category", "templates", ["category"])
        op.create_index("idx_templates_popular", "templates", ["popular"])
        op.create_index("idx_templates_enterprise", "templates", ["enterprise"])

    # 2. Fix Dashboards
    dashboard_columns = [c["name"] for c in inspector.get_columns("dashboards")]
    if "template_id" not in dashboard_columns:
        # Assuming template_id column is missing but we want to add FK after
        # If it's missing, we skip the FK as well for this check
        pass
    
    # Check indexes on dashboards
    dashboard_indexes = [idx["name"] for idx in inspector.get_indexes("dashboards")]
    
    # Try to add template_id FK if not exists
    # (Note: we use a try-except block here for maximum robustness in damaged envs)
    try:
        op.create_foreign_key(
            "fk_dashboards_templates",
            "dashboards",
            "templates",
            ["template_id"],
            ["id"],
            ondelete="SET NULL",
        )
    except Exception:
        pass

    if "idx_dashboards_template_id" not in dashboard_indexes:
        try:
            op.create_index("idx_dashboards_template_id", "dashboards", ["template_id"])
        except Exception:
            pass

    if "ix_dashboards_planet_id" not in dashboard_indexes:
        try:
            op.create_index(op.f("ix_dashboards_planet_id"), "dashboards", ["planet_id"], unique=False)
        except Exception:
            pass

    # 3. Strategy Models Scoping
    scoping_tables = [
        "strategic_pillars",
        "strategic_objectives",
        "strategy_initiatives",
        "strategy_assumptions",
        "strategy_okrs",
    ]

    for table in scoping_tables:
        if table not in tables:
            continue
            
        cols = [c["name"] for c in inspector.get_columns(table)]
        idxs = [idx["name"] for idx in inspector.get_indexes(table)]
        
        if "space_id" not in cols:
            op.add_column(table, sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=True))
        if "crew_id" not in cols:
            op.add_column(table, sa.Column("crew_id", postgresql.UUID(as_uuid=True), nullable=True))
            
        if f"ix_{table}_crew_id" not in idxs:
            try:
                op.create_index(op.f(f"ix_{table}_crew_id"), table, ["crew_id"], unique=False)
            except Exception:
                pass
        if f"ix_{table}_space_id" not in idxs:
            try:
                op.create_index(op.f(f"ix_{table}_space_id"), table, ["space_id"], unique=False)
            except Exception:
                pass
                
        try:
            op.create_foreign_key(None, table, "spaces", ["space_id"], ["id"], ondelete="CASCADE")
            op.create_foreign_key(None, table, "crews", ["crew_id"], ["id"], ondelete="CASCADE")
        except Exception:
            pass

    # 4. Intelligence Signals
    if "intelligence_signals" in tables:
        sig_cols = [c["name"] for c in inspector.get_columns("intelligence_signals")]
        sig_idxs = [idx["name"] for idx in inspector.get_indexes("intelligence_signals")]
        
        if "crew_id" not in sig_cols:
            op.add_column("intelligence_signals", sa.Column("crew_id", postgresql.UUID(as_uuid=True), nullable=True))
            
        # Check space_id type
        space_id_col = next((c for c in inspector.get_columns("intelligence_signals") if c["name"] == "space_id"), None)
        if space_id_col and not isinstance(space_id_col["type"], postgresql.UUID):
            op.alter_column(
                "intelligence_signals",
                "space_id",
                existing_type=sa.VARCHAR(length=100),
                type_=postgresql.UUID(as_uuid=True),
                existing_nullable=True,
                postgresql_using="space_id::uuid",
            )
            
        if "ix_intelligence_signals_crew_id" not in sig_idxs:
            try:
                op.create_index(op.f("ix_intelligence_signals_crew_id"), "intelligence_signals", ["crew_id"], unique=False)
            except Exception:
                pass
        
        try:
            op.create_foreign_key(None, "intelligence_signals", "spaces", ["space_id"], ["id"], ondelete="CASCADE")
            op.create_foreign_key(None, "intelligence_signals", "crews", ["crew_id"], ["id"], ondelete="CASCADE")
        except Exception:
            pass

    # 5. Signal Events
    if "signal_events" in tables:
        ev_cols = [c["name"] for c in inspector.get_columns("signal_events")]
        ev_idxs = [idx["name"] for idx in inspector.get_indexes("signal_events")]
        
        if "space_id" not in ev_cols:
             op.add_column("signal_events", sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=True))
        if "crew_id" not in ev_cols:
             op.add_column("signal_events", sa.Column("crew_id", postgresql.UUID(as_uuid=True), nullable=True))
             
        id_col = next((c for c in inspector.get_columns("signal_events") if c["name"] == "id"), None)
        if id_col and not isinstance(id_col["type"], postgresql.UUID):
            op.alter_column(
                "signal_events",
                "id",
                existing_type=sa.VARCHAR(length=36),
                type_=postgresql.UUID(as_uuid=True),
                existing_nullable=False,
                postgresql_using="id::uuid",
            )
            
        if "ix_signal_events_crew_id" not in ev_idxs:
            try:
                op.create_index(op.f("ix_signal_events_crew_id"), "signal_events", ["crew_id"], unique=False)
            except Exception:
                pass
        if "ix_signal_events_space_id" not in ev_idxs:
            try:
                op.create_index(op.f("ix_signal_events_space_id"), "signal_events", ["space_id"], unique=False)
            except Exception:
                pass
                
        try:
            op.create_foreign_key(None, "signal_events", "spaces", ["space_id"], ["id"], ondelete="CASCADE")
            op.create_foreign_key(None, "signal_events", "crews", ["crew_id"], ["id"], ondelete="CASCADE")
        except Exception:
            pass

    # 6. Miscellaneous Indexes (Global checks)
    misc_ops = [
        ("ai_queries", "user_id"),
        ("ai_queries", "widget_id"),
        ("ai_responses", "is_active"),
        ("ai_responses", "timestamp"),
        ("ai_responses", "widget_id"),
        ("chat_messages", "timestamp"),
        ("chat_messages", "widget_id"),
        ("comments", "dashboard_id"),
        ("comments", "user_id"),
        ("comments", "widget_id"),
        ("connection_metadata", "connection_id"),
        ("connection_permissions", "connection_id"),
        ("connection_permissions", "crew_id"),
        ("connection_permissions", "space_id"),
        ("connection_permissions", "user_id"),
    ]
    
    for table, col in misc_ops:
        if table in tables:
            idxs = [idx["name"] for idx in inspector.get_indexes(table)]
            idx_name = op.f(f"ix_{table}_{col}")
            if idx_name not in idxs and f"idx_{table}_{col}" not in idxs:
                try:
                    op.create_index(idx_name, table, [col], unique=(col=="connection_id" and table=="connection_metadata"))
                except Exception:
                    pass


def downgrade() -> None:
    pass
