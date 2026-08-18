"""A fronteira de dados: da equipa para o projeto, e sem acreditar em ninguém.

Continua a empresa de mentira do `test_quem_ve_o_que_no_projeto` — Financeiro
com as equipas Contas (Ana) e Payroll (Bruno), Marketing com Campanhas (Diogo),
e a Carla fora de tudo.

Duas coisas se protegem aqui, e são independentes:

1. **`crew_ids` deixou de ser acreditado.** O serviço recebia a lista de
   equipas de quem o chamava e nunca confirmava a pertença. Estava seguro por
   acidente: os chamadores validavam por fora. Foi assim que nasceu o #634. O
   teste passa uma equipa que não é da pessoa e exige zero.
2. **O interruptor `DATA_BOUNDARY`.** Em `crew` é tudo como sempre foi; em
   `project` quem está no projeto vê o que o projeto vê. O teste corre os dois
   lados, porque o valor de omissão vai continuar a ser `crew` em produção
   durante algum tempo e ambos os caminhos são reais.
"""

from __future__ import annotations

import uuid

import pytest

from src.config.settings import settings
from src.models.space import SpaceMember, SpaceTable
from src.services.permission_service import PermissionService
from src.tests.test_quem_ve_o_que_no_projeto import _montar_a_empresa


@pytest.fixture
def fronteira_no_projeto(monkeypatch):
    """Vira o interruptor só durante o teste."""
    monkeypatch.setattr(settings, "DATA_BOUNDARY", "project")


async def _o_projeto_escolhe_os_dados(db, e):
    """O Financeiro fica com faturas + salarios; `clientes` fica de fora.

    De propósito: assim o modo projeto não é apenas "tudo o que a ligação tem",
    e um teste que confunda os dois falha.
    """
    db.add_all(
        [
            SpaceTable(
                space_id=e["financeiro"].id, connection_id=e["erp"].id, table_name="faturas"
            ),
            SpaceTable(
                space_id=e["financeiro"].id, connection_id=e["erp"].id, table_name="salarios"
            ),
        ]
    )
    await db.flush()


# ── A brecha: uma equipa que não é minha ─────────────────────────────────────


@pytest.mark.asyncio
async def test_pedir_a_equipa_do_bruno_nao_da_os_salarios_a_ana(db_session):
    """A Ana pede explicitamente a equipa Payroll. Não é dela — logo, nada.

    Antes disto o serviço devolvia `["salarios"]` sem pestanejar, porque a
    lista de equipas vinha de fora e ninguém a confrontava com a pertença.
    """
    e = await _montar_a_empresa(db_session)
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(
        e["ana"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["payroll"].id]
    )
    assert visto == []


@pytest.mark.asyncio
async def test_misturar_a_minha_equipa_com_a_alheia_so_traz_a_minha(db_session):
    """Duas equipas de uma vez: fica a intersecção, não a união.

    É o caminho por onde uma fuga entraria disfarçada de "modo pessoal".
    """
    e = await _montar_a_empresa(db_session)
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(
        e["ana"].id,
        e["erp"].id,
        space_id=e["financeiro"].id,
        crew_ids=[e["contas"].id, e["payroll"].id],
    )
    assert sorted(visto) == ["clientes", "faturas"]


# ── Com o interruptor na equipa (o de hoje) ──────────────────────────────────


@pytest.mark.asyncio
async def test_por_omissao_a_fronteira_continua_a_ser_a_equipa(db_session):
    """Sem tocar em nada, o comportamento antigo mantém-se — o Bruno vê a
    fatia dele e não o projeto inteiro."""
    assert settings.DATA_BOUNDARY == "crew"
    e = await _montar_a_empresa(db_session)
    await _o_projeto_escolhe_os_dados(db_session, e)
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(
        e["bruno"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["payroll"].id]
    )
    assert visto == ["salarios"]


# ── Com o interruptor no projeto (o modelo decidido) ─────────────────────────


@pytest.mark.asyncio
async def test_no_projeto_a_ana_e_o_bruno_veem_o_mesmo(db_session, fronteira_no_projeto):
    """É o objectivo da decisão, não um efeito colateral: quem está no projeto
    vê os dados do projeto, seja qual for a equipa."""
    e = await _montar_a_empresa(db_session)
    await _o_projeto_escolhe_os_dados(db_session, e)
    svc = PermissionService(db_session)

    ana = await svc.get_authorized_tables(
        e["ana"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["contas"].id]
    )
    bruno = await svc.get_authorized_tables(
        e["bruno"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["payroll"].id]
    )
    assert ana == bruno == ["faturas", "salarios"]


@pytest.mark.asyncio
async def test_o_projeto_nao_e_a_ligacao_inteira(db_session, fronteira_no_projeto):
    """`clientes` existe na ligação e não foi escolhida para o projeto.

    Se aparecer, alguém trocou "as tabelas do projeto" por "as tabelas da
    ligação" — e o recorte deixou de existir.
    """
    e = await _montar_a_empresa(db_session)
    await _o_projeto_escolhe_os_dados(db_session, e)
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(
        e["ana"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["contas"].id]
    )
    assert "clientes" not in visto


@pytest.mark.asyncio
async def test_o_diogo_continua_fora_do_financeiro(db_session, fronteira_no_projeto):
    """Alargar a fronteira dentro do projeto não pode alargá-la entre projetos.

    O Diogo está no Marketing. Se pedir o Financeiro — com a equipa dele ou sem
    equipa nenhuma — não leva nada.
    """
    e = await _montar_a_empresa(db_session)
    await _o_projeto_escolhe_os_dados(db_session, e)
    svc = PermissionService(db_session)

    assert (
        await svc.get_authorized_tables(
            e["diogo"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["campanhas"].id]
        )
        == []
    )
    assert (
        await svc.get_authorized_tables(e["diogo"].id, e["erp"].id, space_id=e["financeiro"].id)
        == []
    )


@pytest.mark.asyncio
async def test_a_carla_sem_equipa_mas_com_o_projeto_ve_o_projeto(db_session, fronteira_no_projeto):
    """A base ainda tem gente ligada ao projeto sem passar por equipa.

    O modelo diz que isso não devia existir, mas existe, e no dia em que o
    interruptor virar essas pessoas não podem ficar sem dados nenhuns.
    """
    e = await _montar_a_empresa(db_session)
    await _o_projeto_escolhe_os_dados(db_session, e)
    db_session.add(
        SpaceMember(
            id=uuid.uuid4(),
            space_id=e["financeiro"].id,
            user_id=e["carla"].id,
            role="viewer",
        )
    )
    await db_session.flush()
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(e["carla"].id, e["erp"].id, space_id=e["financeiro"].id)
    assert visto == ["faturas", "salarios"]


@pytest.mark.asyncio
async def test_projeto_sem_dados_escolhidos_nao_responde_a_nada(db_session, fronteira_no_projeto):
    """Fail-closed também aqui: sem escolha, zero — nunca "tudo".

    É o defeito clássico deste tipo de portão, e o inverso do que faz um
    projeto novo parecer que "já funciona".
    """
    e = await _montar_a_empresa(db_session)  # sem SpaceTable nenhuma
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(
        e["ana"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["contas"].id]
    )
    assert visto == []


@pytest.mark.asyncio
async def test_quem_criou_a_equipa_conta_como_sendo_dela(db_session):
    """O Dono criou as equipas e não tem linha em `crew_members`.

    Recusá-lo seria zelo a mais: foi ele que escolheu o recorte de dados da
    equipa, portanto negar-lho não fecha brecha nenhuma — só tira o acesso a
    quem montou a coisa. A verificação existe contra equipas *alheias*.
    """
    e = await _montar_a_empresa(db_session)
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(
        e["dono"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["payroll"].id]
    )
    assert visto == ["salarios"]


@pytest.mark.asyncio
async def test_sem_projeto_no_pedido_a_equipa_diz_qual_e(db_session, fronteira_no_projeto):
    """O chamador dos agentes nem sempre traz o projeto — traz a equipa.

    A resposta não pode depender de quem chama ter preenchido o campo, senão o
    mesmo utilizador vê coisas diferentes conforme a porta por onde entra.
    """
    e = await _montar_a_empresa(db_session)
    await _o_projeto_escolhe_os_dados(db_session, e)
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(e["ana"].id, e["erp"].id, crew_ids=[e["contas"].id])
    assert visto == ["faturas", "salarios"]
