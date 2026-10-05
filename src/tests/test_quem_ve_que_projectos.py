# -*- coding: utf-8 -*-
"""Lista-se o que se abre, e nada mais.

── O que o Lucas viu ───────────────────────────────────────────────

> «ele está podendo listar mas quando ele entra ele toma um erro»

O Felipe é admin do `skyfirstlabs`. A barra lateral listava-lhe o
projecto «Remax». Clicava, e apanhava um erro.

── A causa ─────────────────────────────────────────────────────────

O `list_spaces` tinha um atalho para `owner`/`admin`/`super_admin` —
`get_all_with_stats`, todos os projectos do cliente. O **abrir** nunca
teve atalho nenhum. As duas vias discordavam.

O mesmo defeito já tinha sido corrigido nas equipas; o `crew_service`
leva o comentário `SECURITY:` a dizê-lo. Esta é a segunda vez.

── O que estes testes fixam ────────────────────────────────────────

Os casos de stress de `docs/quem-ve-que-projectos.md`. Não a
implementação: o que importa é que a lista e o abrir concordem, seja
qual for o caminho que a pertença tomou.
"""

from __future__ import annotations

import inspect

import pytest


def test_a_listagem_nao_tem_atalho_para_administradores():
    """O caso 1: admin que nunca entrou num projecto não o vê.

    Verificado na fonte porque o caminho alternativo era precisamente
    um `if` sobre o papel — e um teste que monte a base inteira para
    confirmar que um `if` desapareceu custa minutos e prova menos.
    """
    from src.services import space_service

    fonte = inspect.getsource(space_service.SpaceService.list_spaces)
    sem_comentarios = "\n".join(
        linha for linha in fonte.splitlines() if not linha.strip().startswith("#")
    )
    # O corpo não pode voltar a chamar a via sem âmbito.
    corpo = sem_comentarios.split('"""')[-1]
    assert (
        "get_all_with_stats" not in corpo
    ), "a listagem voltou a ter o atalho que mostra projectos que não se abrem"
    assert "get_by_user_with_stats" in corpo


def test_a_listagem_cobre_quem_entra_por_uma_equipa():
    """O caso 3, e é o contrapeso do teste acima.

    Cortar o atalho não pode trancar quem trabalha num projecto por
    pertencer a uma equipa lá dentro, sem ser membro do projecto — que
    é o que o `add_crew_member` faz. Se esta via desaparecesse, o
    remédio seria pior do que a doença.
    """
    from src.repositories import space as repo

    fonte = inspect.getsource(repo.SpaceRepository.get_by_user_with_stats)
    assert "CrewMember" in fonte, "a via por equipa desapareceu da listagem"
    assert "SpaceMember" in fonte


def test_a_adesao_marca_a_origem():
    """O caso 7, que é o que me preocupava.

    A pertença criada pelo interruptor leva `origem="auto_demo"`. Sem
    essa marca, desligá-lo apagaria também a pertença de quem foi
    **convidado** para um projecto de demonstração.
    """
    from src.services import space_service

    aderir = inspect.getsource(space_service.SpaceService.aderir_as_demonstracoes)
    assert 'origem="auto_demo"' in aderir

    sair = inspect.getsource(space_service.SpaceService.sair_das_demonstracoes)
    assert 'SpaceMember.origem == "auto_demo"' in sair, (
        "a saída deixou de filtrar pela origem e passa a tirar acessos "
        "que alguém deu de propósito"
    )


def test_a_adesao_nao_mexe_em_pertencas_que_ja_existem():
    """Também o caso 7, pelo outro lado.

    Se alguém já foi convidado para um `is_demo`, ligar o interruptor
    não pode reescrever essa linha para `auto_demo` — senão o desligar
    seguinte apaga-a na mesma, e o convite perdeu-se por um caminho
    mais comprido.
    """
    from src.services import space_service

    fonte = inspect.getsource(space_service.SpaceService.aderir_as_demonstracoes)
    assert "if space_id in ja:" in fonte
    assert "continue" in fonte


def test_a_saida_so_toca_nos_projectos_de_demonstracao():
    """Desligar o interruptor não pode tirar a pessoa de outros projectos."""
    from src.services import space_service

    fonte = inspect.getsource(space_service.SpaceService.sair_das_demonstracoes)
    assert "Space.is_demo.is_(True)" in fonte


def test_a_coluna_da_origem_existe_no_modelo():
    from src.models.space import SpaceMember

    coluna = SpaceMember.__table__.columns.get("origem")
    assert coluna is not None
    assert coluna.nullable is False
    # O que já existia é convite — ninguém aderiu sozinho antes de isto
    # existir, e deixar a coluna anulável tornava o filtro da saída
    # dependente de um `IS NULL` que ninguém se lembraria de escrever.
    assert coluna.server_default.arg == "convite"


@pytest.mark.parametrize("papel", ["owner", "admin", "super_admin", "member"])
def test_o_papel_da_plataforma_nao_muda_a_listagem(papel: str):
    """Nenhum papel volta a abrir uma excepção na listagem.

    Parametrizado sobre os quatro para o teste falhar se alguém
    acrescentar o atalho de novo só para um deles — que é como estas
    coisas costumam voltar.
    """
    from src.services import space_service

    fonte = inspect.getsource(space_service.SpaceService.list_spaces)
    corpo = fonte.split('"""')[-1]
    assert f'"{papel}"' not in corpo
