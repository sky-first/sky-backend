"""As tabelas de permissões não podem divergir entre si.

Quatro defeitos numa semana, todos da mesma família — duas listas com a mesma
verdade, escritas à mão, que se afastaram:

1. `permissions.edit` era exclusivo do fundador na tabela de regras e não na
   lista do `RBACService`; um admin editava a matriz e promovia-se.
2. `spaces.create` exigia admin nas duas pontas, contra o modelo de 18/08.
3. `connections.create` era do `editor` no `authorization.py` e do `owner` no
   `rbac_service.py` — o próprio backend a discordar de si sobre a fronteira
   que mais importa, que é ligar dados.
4. `owner` valia fundador no frontend e não no backend.

Este teste compara as tabelas em vez de confiar em quem as escreve. Falha a
apontar a chave, e não com um "algures não bate certo".
"""

from __future__ import annotations

import re
from pathlib import Path

from src.services.authorization import PERMISSION_RULES
from src.services.rbac_service import DEFAULT_ROLE_PERMISSIONS

#: Onde vive a cópia do frontend. Caminho relativo ao repositório irmão — se
#: um dia mudar de sítio, o teste diz que não a encontrou em vez de passar
#: caladamente.
CAN_TS = (
    Path(__file__).resolve().parents[3]
    / "sky-poc-frontend"
    / "src"
    / "lib"
    / "rbac"
    / "can.ts"
)


def _regras_do_frontend() -> dict[str, tuple[str, str]]:
    fonte = CAN_TS.read_text(encoding="utf-8")
    return {
        chave: (escopo, nivel)
        for chave, escopo, nivel in re.findall(
            r'"([a-z0-9_.]+)":\s*\["(\w+)",\s*"(\w+)"\]', fonte
        )
    }


def test_o_backend_nao_discorda_de_si_proprio_sobre_ligacoes():
    """`Authorization.can()` e `assert_permission` sobre a mesma pergunta.

    Ligar dados é a fronteira do modelo: é por causa dela que existe o pedido
    de acesso. As duas vias têm de dar a mesma resposta, senão basta uma rota
    nova escolher a errada.
    """
    for chave in ("connections.create", "connections.edit"):
        _escopo, exigido = PERMISSION_RULES[chave]
        assert exigido == "owner", f"{chave} devia exigir dono do projeto"
        assert DEFAULT_ROLE_PERMISSIONS["editor"][chave] is False
        assert DEFAULT_ROLE_PERMISSIONS["owner"][chave] is True


def test_o_frontend_diz_o_mesmo_que_o_backend():
    """Onde as duas tabelas se sobrepõem, têm de coincidir.

    Não exige que o frontend conheça todas as chaves — conhece mais, e isso é
    legítimo (tem chaves de UI que o backend não precisa). Exige que, quando
    ambos falam da mesma chave, digam o mesmo. Era aqui que o editor via o
    botão de criar ligação e levava 403.
    """
    assert CAN_TS.exists(), f"não encontrei o can.ts em {CAN_TS}"
    frontend = _regras_do_frontend()

    discordam = {
        chave: {"backend": PERMISSION_RULES[chave], "frontend": frontend[chave]}
        for chave in set(PERMISSION_RULES) & set(frontend)
        if tuple(PERMISSION_RULES[chave]) != frontend[chave]
    }
    assert discordam == {}, f"tabelas divergentes: {discordam}"
