"""Leads da demo pública — BE-12.

Separado de ``demo_content_20260803`` porque é conteúdo de outra
natureza: aquelas três tabelas são curadas e versionadas connosco, esta
recebe escrita de visitantes.

Sem verificação de email por desenho. Nada é provisionado no momento da
captura — até o visitante carregar dados próprios, tudo o que vê é
conteúdo estático. Um email falso custa um lead mau, não recursos. A
verificação (magic link) pertence ao passo de provisionamento.

``email`` é único: submeter duas vezes actualiza em vez de duplicar.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "demo_leads_20260803"
down_revision = "demo_content_20260803"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.String(36)
    json_type = postgresql.JSONB if is_pg else sa.JSON

    op.create_table(
        "demo_leads",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column(
            "dataset_id",
            uuid_type,
            sa.ForeignKey("demo_datasets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("questions_asked", json_type, nullable=False, server_default="[]"),
        sa.Column("vertical", sa.String(32), nullable=True),
        sa.Column("locale", sa.String(10), nullable=True),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("email", name="uq_demo_leads_email"),
    )
    op.create_index("idx_demo_leads_created", "demo_leads", ["created_at"])


def downgrade() -> None:
    op.drop_table("demo_leads")
