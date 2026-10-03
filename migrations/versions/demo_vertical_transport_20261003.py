"""O sector 'transport' passa a ser aceite em demo_datasets.

A demo pública oferecia quatro sectores — SaaS, Distribuição, Serviços e
Indústria — e nenhum deles é transporte. Quem move mercadoria para viver
não se revê em "lugares de subscrição" nem em "horas faturáveis", e os
primeiros clientes à espera de ver a plataforma são transportadoras.

A restrição mantém-se em vez de se abrir a texto livre, pela razão de
sempre: uma vertical escrita à mão com um erro de escrita cria um
dataset que a demo nunca serve, e ninguém dá por isso. O erro aparece no
`--apply`, que é onde custa um minuto, em vez de aparecer à frente de um
prospect, que é onde custa a venda.

Revision ID: demo_vertical_transport_20261003
Revises: notificacoes_antigas_20260908
"""

from typing import Sequence, Union

from alembic import op

revision = "demo_vertical_transport_20261003"
down_revision = "notificacoes_antigas_20260908"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOME = "demo_datasets_vertical_check"
_ANTIGO = "('saas', 'distribution', 'services', 'industry', 'default')"
_NOVO = "('saas', 'distribution', 'services', 'industry', 'transport', 'default')"


def upgrade() -> None:
    op.drop_constraint(_NOME, "demo_datasets", type_="check")
    op.create_check_constraint(_NOME, "demo_datasets", f"vertical IN {_NOVO}")


def downgrade() -> None:
    # Um dataset de transporte já criado impediria a reposição da
    # restrição antiga. Apagá-lo é o comportamento certo: no esquema
    # antigo ele não podia existir. Mesmo critério da migração que
    # acrescentou a indústria.
    op.execute("DELETE FROM demo_datasets WHERE vertical = 'transport'")
    op.drop_constraint(_NOME, "demo_datasets", type_="check")
    op.create_check_constraint(_NOME, "demo_datasets", f"vertical IN {_ANTIGO}")
