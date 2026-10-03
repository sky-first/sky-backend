"""O sector 'food' passa a ser aceite em demo_datasets.

Alimentação e bebidas: a distribuição de comida e vinho à hostelaria.
Já existia um sector de Distribuição genérico e não chega — aqui a
mercadoria tem lote e tem data, o preço leva um rappel que só se aplica
no fim, e o stock parado às vezes é estratégia.

Também é o sexto sector, e isso não é um detalhe de arrumação: o
primeiro ecrã da demo mostra as opções em cartas de três por fila.
Cinco davam 3+2, com uma fila pela metade. Seis dão 3+3.

Revision ID: demo_vertical_food_20261003
Revises: demo_vertical_transport_20261003
"""

from typing import Sequence, Union

from alembic import op

revision = "demo_vertical_food_20261003"
down_revision = "demo_vertical_transport_20261003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOME = "demo_datasets_vertical_check"
_ANTIGO = "('saas', 'distribution', 'services', 'industry', 'transport', 'default')"
_NOVO = (
    "('saas', 'distribution', 'services', 'industry', 'transport', "
    "'food', 'default')"
)


def upgrade() -> None:
    op.drop_constraint(_NOME, "demo_datasets", type_="check")
    op.create_check_constraint(_NOME, "demo_datasets", f"vertical IN {_NOVO}")


def downgrade() -> None:
    # Mesmo critério das duas migrações anteriores: um dataset que o
    # esquema antigo não permitia não pode sobreviver à reposição dele.
    op.execute("DELETE FROM demo_datasets WHERE vertical = 'food'")
    op.drop_constraint(_NOME, "demo_datasets", type_="check")
    op.create_check_constraint(_NOME, "demo_datasets", f"vertical IN {_ANTIGO}")
