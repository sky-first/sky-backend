"""Uma mensagem de estado do agente que não se repete.

Três colunas em `messages`, as três a servir o mesmo defeito: a conversa
de um agente enchia-se da mesma frase.

* `repeticoes` — quantas corridas seguidas disseram exactamente isto.
  Uma mensagem normal vale 1 e nunca muda.
* `ultima_repeticao_em` — quando foi a última dessas corridas. O
  `created_at` passa a ser «desde quando», e esta é «até quando».
* `chave_de_texto` — a entrada do catálogo (`src/core/locale.py`) que
  originou o texto. O `content` continua a ser escrito, e é o que se vê
  se o cliente não souber a chave; quem souber mostra-a na língua de
  quem lê, que é coisa que o worker não pode saber na altura em que
  escreve.

Revision ID: agente_nao_repete_20261007
Revises: origem_pertenca_20261005
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa

revision = "agente_nao_repete_20261007"
down_revision = "origem_pertenca_20261005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "repeticoes",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "messages",
        sa.Column("ultima_repeticao_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("chave_de_texto", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "chave_de_texto")
    op.drop_column("messages", "ultima_repeticao_em")
    op.drop_column("messages", "repeticoes")
