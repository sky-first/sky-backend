"""Criar um projeto é de qualquer pessoa; ligar-lhe dados é que não.

O modelo fechado a 18/08 diz: as pessoas criam os projetos que quiserem, e o
que precisa de autorização é **ligar dados** ao projeto — por permissão ou por
um pedido em linguagem natural que um admin do cliente aprova.

O código dizia o contrário: `POST /spaces` devolvia 403 ao member, em produção.
E as duas vias de autorização discordavam entre si sobre o mesmo modelo —
`crews.create` era `any_member` e `spaces.create` era `admin_or_above`.
"""

from __future__ import annotations

import pytest

from src.services.authorization import PERMISSION_RULES
from src.services.rbac_service import MEMBER_PLATFORM_PERMISSIONS


def test_o_member_pode_criar_projetos():
    assert MEMBER_PLATFORM_PERMISSIONS["spaces.create"] is True


def test_as_duas_vias_concordam_sobre_criar_projeto():
    """A divergência entre estas duas tabelas foi a causa de três defeitos
    esta semana. Aqui é a mesma pergunta feita aos dois lados."""
    _escopo, exigido = PERMISSION_RULES["spaces.create"]
    assert exigido == "any_member"


def test_criar_equipa_e_criar_projeto_exigem_o_mesmo():
    """Não faz sentido um projeto ser mais difícil de criar que uma equipa
    lá dentro. Era assim que estava."""
    assert PERMISSION_RULES["spaces.create"] == PERMISSION_RULES["crews.create"]


@pytest.mark.parametrize(
    "chave", ["connections.create", "connections.edit", "connections.delete"]
)
def test_o_member_continua_sem_poder_cunhar_ligacoes(chave):
    """A outra metade, e a que interessa para a segurança: abrir a criação de
    projetos não pode abrir o acesso a dados. Sem isto, "qualquer um cria um
    projeto" transformava-se em "qualquer um liga a base de dados que quiser"."""
    assert MEMBER_PLATFORM_PERMISSIONS[chave] is False
