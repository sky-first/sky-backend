"""Anexar dados a um projeto tem de autorizar a **origem**, não só o destino.

Encontrado em produção a 19/08, no cliente `sandbox`, minutos depois de eu
abrir a criação de projetos a toda a gente:

    GET  /connections/{id}                  (member) -> 403
    POST /spaces/{o_meu}/connections/{id}   (member) -> 201
    GET  /connections/{id}                  (member) -> 200   ← subiu

O member passou de "proibido" a "acesso total" a uma ligação de dados numa
chamada. Bastou criar um projeto — coisa que agora toda a gente faz — e
anexar-lhe uma ligação que não podia sequer ver.

As duas rotas de anexar (`.../connections/{id}` e `.../tables`) verificavam
`spaces.members.manage` **no projeto de destino** e mais nada. Como quem cria
um projeto fica dono dele, essa verificação passou a ser sempre verdadeira
para qualquer pessoa: deixou de ser um portão.

O caminho legítimo para quem não é admin é o **pedido de acesso** — o
`aprovar()` cria o `SpaceConnection` do lado de dentro, depois de um admin ter
visto o que está a conceder.
"""

from __future__ import annotations

import re
from pathlib import Path

FONTE = Path("src/api/v1/spaces.py").read_text(encoding="utf-8")


def _corpo(nome: str) -> str:
    i = FONTE.index(f"async def {nome}(")
    j = FONTE.find("\n@router.", i)
    return FONTE[i : j if j != -1 else len(FONTE)]


def test_anexar_ligacao_autoriza_a_origem():
    corpo = _corpo("add_space_connection")
    assert 'assert_permission(current_user, "connections.edit")' in corpo, (
        "a rota volta a verificar só o projeto de destino — qualquer pessoa "
        "que crie um projeto anexa-lhe dados a que não tem acesso"
    )


def test_anexar_tabela_autoriza_a_origem():
    corpo = _corpo("add_space_table")
    assert 'assert_permission(current_user, "connections.edit")' in corpo


def test_as_duas_continuam_a_verificar_o_destino():
    """A outra metade: autorizar a origem não chega.

    Sem a verificação do destino, um admin podia anexar dados ao projeto de
    outra pessoa sem ser membro dele.
    """
    for nome in ("add_space_connection", "add_space_table"):
        corpo = _corpo(nome)
        assert re.search(
            r'assert_permission\(\s*current_user,\s*"spaces\.members\.manage",\s*space_id=space_id',
            corpo,
        ), nome


def test_a_verificacao_da_origem_vem_primeiro():
    """Ordem deliberada: recusar pela origem antes de tocar no destino.

    Se a do destino corresse primeiro, alguém sem acesso à ligação receberia
    um erro sobre o **projeto** — e ficava a pensar que o problema era outro.
    """
    for nome in ("add_space_connection", "add_space_table"):
        corpo = _corpo(nome)
        origem = corpo.index('"connections.edit"')
        destino = corpo.index('"spaces.members.manage"')
        assert origem < destino, nome
