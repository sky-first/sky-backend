"""Liga uma mensagem ao achado que ela apresenta.

A resposta diária de um agente vive agora numa conversa. Mas no ecrã ela não
pode ser um parágrafo de texto: tem de ser o mesmo cartão que o feed de
Insights mostra — o gráfico, os indicadores e a explicação. Esse conteúdo já
existe em ``agent_findings`` (título, descrição, ``rows``, ``viz_kind``,
confiança); o que faltava era o cliente saber QUAL achado corresponde a QUAL
mensagem do fio.

Sem esta coluna a única alternativa seria emparelhar por ordem ou por
carimbo de tempo, e as duas partem-se assim que uma corrida produzir mais do
que um achado.

Aditiva e anulável de propósito: nenhuma linha existente muda, nenhum caminho
antigo repara nela, e a reversão é uma queda de coluna.

Revision ID: message_finding_20260814
Revises: device_registry_20260805
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "message_finding_20260814"
down_revision = "device_registry_20260805"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # SET NULL e não CASCADE: apagar um achado não pode apagar a mensagem do
    # fio. A conversa é o registo de como se chegou a uma decisão — perder uma
    # resposta porque o achado foi limpo seria perder o histórico da equipa.
    op.create_foreign_key(
        "fk_messages_finding_id",
        "messages",
        "agent_findings",
        ["finding_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_messages_finding_id", "messages", ["finding_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_finding_id", table_name="messages")
    op.drop_constraint("fk_messages_finding_id", "messages", type_="foreignkey")
    op.drop_column("messages", "finding_id")
