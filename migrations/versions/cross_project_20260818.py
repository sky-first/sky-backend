"""O cruzamento entre projetos: o que fica de fora, e o que não sai.

Opção C do modelo (``docs/modelo-projeto-equipa-e-pedidos-de-acesso.md`` §4):
cada pessoa cruza o que já alcança, sem pedir nada a ninguém — mas o resultado
não se publica.

O risco não está na leitura: quem cruza já tem acesso a cada peça. Está na
**agregação** e na **redistribuição**. Cruzar RH com Vendas pode reidentificar
pessoas, e quem deu acesso aos salários deu-o no contexto do projeto de RH, não
para publicar salários por vendedor no projeto Comercial. Por isso o travão fica
na saída.

Duas colunas:

``data_connections.nao_cruzavel``
    A fonte fica de fora da união cross-project. Aplica-se ao **construir** a
    união, antes de qualquer query — esconder o resultado depois de ele ter sido
    lido não é segurança (S11).

``messages.cruzou_projetos``
    Marca a resposta que nasceu de mais do que um projeto. É o que permite
    recusar fixá-la numa página (S9). Sem a marca, a proibição teria de ser
    reconstruída a partir do histórico, e isso perde-se.

Aditiva, com omissões que preservam o comportamento actual.

Revision ID: cross_project_20260818
Revises: pedidos_de_acesso_20260818
"""

import sqlalchemy as sa
from alembic import op

revision = "cross_project_20260818"
down_revision = "pedidos_de_acesso_20260818"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "data_connections",
        sa.Column(
            "nao_cruzavel",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "messages",
        sa.Column(
            "cruzou_projetos",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "cruzou_projetos")
    op.drop_column("data_connections", "nao_cruzavel")
