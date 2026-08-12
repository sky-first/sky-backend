"""Nome e último passo no lead da demo.

Decisão comercial do Lucas, tomada com o custo à vista: nome e email
passam a ser pedidos no primeiro ecrã, antes de o visitante ter visto
seja o que for.

O que isto compra: saber **quem** parou e **onde**, e poder voltar a
falar com quem não terminou. Com o email só no fim, quem saía a meio era
irrecuperável.

O que isto custa: conversões no primeiro ecrã. Este fluxo foi construído
sobre dar antes de pedir, e um formulário à entrada é exactamente o
imposto que faz sair quem ainda não viu nada. **O custo passa a ser
mensurável** — os eventos anónimos do funil contam as visitas que
chegam ao passo 1 e as que passam ao 2, portanto a diferença é a conta
directa do que este formulário cobra.

``last_step`` é actualizado a cada passo pelo mesmo upsert do lead, que
já era idempotente por email.

Revision ID: demo_lead_progress_20260804
Revises: demo_events_20260804
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision = "demo_lead_progress_20260804"
down_revision = "demo_events_20260804"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("demo_leads", sa.Column("name", sa.String(160), nullable=True))
    op.add_column("demo_leads", sa.Column("last_step", sa.Integer(), nullable=True))
    # A pergunta que este índice serve: quem ficou a meio, e em que passo.
    op.create_index("idx_demo_leads_last_step", "demo_leads", ["last_step"])


def downgrade() -> None:
    op.drop_index("idx_demo_leads_last_step", table_name="demo_leads")
    op.drop_column("demo_leads", "last_step")
    op.drop_column("demo_leads", "name")
