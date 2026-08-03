"""Conteúdo curado da demo pública — BE-12.

Cria ``demo_datasets``, ``demo_insights`` e ``demo_qas``.

A demo tinha o LLM no caminho crítico do primeiro contacto e falhava com
timeout. Estas tabelas guardam conteúdo **curado offline** — insight
herói e respostas pré-calculadas — para que o primeiro ecrã não dependa
de nenhuma geração em runtime.

Notas de esquema:

* ``demo_qas.embedding`` é ``vector(1024)``, não 1536. Tem de bater com
  a coluna que o serviço de AI já usa (migração 005 do sky-poc-ai levou
  tudo para 1024) e com o provider activo,
  ``intfloat/multilingual-e5-large``. Um valor diferente faz o INSERT
  falhar em runtime.
* A extensão ``vector`` é criada por ``CREATE EXTENSION IF NOT EXISTS``:
  o serviço de AI já a activa, mas esta migração pode correr primeiro
  numa base nova.
* O índice parcial ``uq_demo_datasets_one_default_per_locale`` garante
  na base que há **um só** dataset de omissão por locale. Dois defaults
  tornariam a entrada da demo não-determinista, e validar isso só na
  aplicação deixa a porta aberta.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "demo_content_20260803"
down_revision = "seed_gbt_demo_usage_20260624"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 1024


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.String(36)
    json_type = postgresql.JSONB if is_pg else sa.JSON

    op.create_table(
        "demo_datasets",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("vertical", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("connection_ref", sa.String(255), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "vertical IN ('saas','distribution','services','default')",
            name="demo_datasets_vertical_check",
        ),
        sa.UniqueConstraint("vertical", "locale", name="uq_demo_datasets_vertical_locale"),
    )
    op.create_index("idx_demo_datasets_lookup", "demo_datasets", ["vertical", "locale"])
    if is_pg:
        op.execute(
            "CREATE UNIQUE INDEX uq_demo_datasets_one_default_per_locale "
            "ON demo_datasets (locale) WHERE is_default"
        )

    op.create_table(
        "demo_insights",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "dataset_id",
            uuid_type,
            sa.ForeignKey("demo_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("severity_level", sa.String(16), nullable=False, server_default="info"),
        sa.Column("agent_name", sa.String(120), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("series", json_type, nullable=True),
        sa.Column("stat_tiles", json_type, nullable=False, server_default="[]"),
        sa.Column("sources", json_type, nullable=False, server_default="[]"),
        sa.Column("executed_sql", sa.Text(), nullable=True),
        sa.Column("position", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("idx_demo_insights_dataset", "demo_insights", ["dataset_id", "position"])

    op.create_table(
        "demo_qas",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "dataset_id",
            uuid_type,
            sa.ForeignKey("demo_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_markdown", sa.Text(), nullable=False),
        sa.Column("citations", json_type, nullable=False, server_default="[]"),
        sa.Column("chart_spec", json_type, nullable=True),
        sa.Column("executed_sql", sa.Text(), nullable=True),
        sa.Column("position", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("is_suggested", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("idx_demo_qas_dataset", "demo_qas", ["dataset_id", "position"])

    if is_pg:
        op.execute(f"ALTER TABLE demo_qas ADD COLUMN embedding vector({EMBEDDING_DIM})")
        op.execute(
            "CREATE INDEX idx_demo_qas_suggested ON demo_qas (dataset_id, position) "
            "WHERE is_suggested"
        )


def downgrade() -> None:
    op.drop_table("demo_qas")
    op.drop_table("demo_insights")
    op.drop_table("demo_datasets")
