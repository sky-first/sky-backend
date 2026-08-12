"""Eventos anónimos do funil da demo.

Hoje só se sabe quem chegou ao fim. Quem sai no passo 2 é invisível, e
portanto o passo que perde gente também é — o que torna impossível
melhorar o fluxo com outra coisa que não seja opinião.

**Sem dados pessoais, e é uma decisão e não um esquecimento.** A
alternativa considerada era pedir nome e email no primeiro ecrã, o que
mediria o mesmo e mais: permitiria contactar quem desistiu. Custa
conversões — este fluxo foi construído sobre a regra de dar antes de
pedir, e um formulário à entrada é exactamente o imposto que faz sair
quem ainda não viu nada.

A ordem certa é medir primeiro. Com a desistência real por passo,
decide-se com números se vale a pena pagar esse preço. Sem eles, é um
palpite caro.

O ``session_id`` é gerado no browser e não identifica ninguém: serve
para ligar os passos da mesma visita e saber onde ela parou. Sem IP,
sem user agent, sem nada que precise de consentimento de cookies.

Revision ID: demo_events_20260804
Revises: demo_vertical_industry_20260804
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "demo_events_20260804"
down_revision = "demo_vertical_industry_20260804"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "demo_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Gerado no browser. Liga os passos de uma visita e mais nada.
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("vertical", sa.String(32), nullable=True),
        sa.Column("locale", sa.String(10), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_demo_events_session", "demo_events", ["session_id"])
    op.create_index("idx_demo_events_created", "demo_events", ["created_at"])
    # A pergunta que este índice serve é a única que interessa:
    # quantas visitas chegaram a cada passo.
    op.create_index("idx_demo_events_step", "demo_events", ["step", "action"])


def downgrade() -> None:
    op.drop_index("idx_demo_events_step", table_name="demo_events")
    op.drop_index("idx_demo_events_created", table_name="demo_events")
    op.drop_index("idx_demo_events_session", table_name="demo_events")
    op.drop_table("demo_events")
