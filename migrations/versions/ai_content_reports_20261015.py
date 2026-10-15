"""Respostas da IA reportadas por quem as leu (15/10/2026).

A Google Play (*AI-Generated Content*) exige que uma app com chatbot deixe
reportar conteúdo ofensivo dentro da app. A app móvel passa a ter «Reportar
resposta» em cada resposta da Sky e em cada descoberta; isto é onde fica.

``ai_content_reports`` — um alvo por linha (mensagem OU descoberta), motivo
curto (offensive / wrong / other), texto opcional e uma cópia do conteúdo
reportado. Sem chave estrangeira nos alvos: a mensagem pode ser apagada
depois e a denúncia tem de ficar.

Corre em todas as bases (plataforma e clientes); só a do cliente recebe
linhas, porque o pedido vem com a sessão do cliente.

Revision ID: ai_content_reports_20261015
Revises: fontes_sistema_20261013
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ai_content_reports_20261015"
down_revision = "fontes_sistema_20261013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "ai_content_reports" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "ai_content_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("query_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("motivo", sa.String(length=20), nullable=False),
        sa.Column("texto", sa.Text(), nullable=True),
        sa.Column("conteudo", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "motivo IN ('offensive', 'wrong', 'other')", name="ck_ai_content_reports_motivo"
        ),
        sa.CheckConstraint(
            "(message_id IS NOT NULL AND finding_id IS NULL)"
            " OR (message_id IS NULL AND finding_id IS NOT NULL)",
            name="ck_ai_content_reports_um_alvo",
        ),
    )
    op.create_index("ix_ai_content_reports_user_id", "ai_content_reports", ["user_id"])
    op.create_index("ix_ai_content_reports_message_id", "ai_content_reports", ["message_id"])
    op.create_index("ix_ai_content_reports_finding_id", "ai_content_reports", ["finding_id"])
    op.create_index("idx_ai_content_reports_created_at", "ai_content_reports", ["created_at"])


def downgrade() -> None:
    op.drop_table("ai_content_reports")
