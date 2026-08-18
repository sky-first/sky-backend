"""Quem vê o quê num projeto — e o que é dito a quem não vê.

Escrito a pedido do Lucas, com as palavras dele: *"dar permissões a um projeto,
a um time, criar pessoas fake, testar se tem acesso, mensagens para quem não
tem, convites"*.

O cenário é uma empresa pequena montada de raiz em cada teste:

    Projeto "Financeiro"
      ├── ligação "ERP"  →  tabelas: faturas, salarios, clientes
      ├── equipa "Contas"    →  Ana        →  vê faturas + clientes
      ├── equipa "Payroll"   →  Bruno      →  vê salarios
      └── (fora de qualquer equipa)  Carla →  não vê nada

    Projeto "Marketing"
      └── equipa "Campanhas" →  Diogo      →  não vê nada do Financeiro

O que estes testes protegem, e que não se vê a olhar para o ecrã:

1. **A porta fecha por omissão.** Uma equipa sem tabelas concedidas vê zero —
   nunca "todas". É o inverso do que o comentário do modelo `CrewTable` ainda
   diz, e é o comportamento que interessa.
2. **Não há fuga entre equipas do mesmo projeto.** A Ana não vê os salários que
   o Bruno vê, mesmo estando as duas tabelas na mesma ligação.
3. **Não há fuga entre projetos.** O Diogo não vê nada do Financeiro.
4. **Quem não tem acesso recebe uma recusa, não um 500.** Um erro interno diz a
   quem sonda que ali há alguma coisa; uma recusa limpa não diz nada.
5. **O convite dá acesso, e só ao que a equipa tem.** Entrar numa equipa não é
   entrar no projeto todo.
"""
from __future__ import annotations

import uuid

import pytest

from src.core.exceptions import ForbiddenError
from src.models.connection import DataConnection
from src.models.crew import Crew, CrewMember, CrewTable
from src.models.space import Space
from src.models.user import User
from src.services.permission_service import PermissionService
from src.services.rbac_service import RBACService


def _pessoa(nome: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{nome.lower()}@empresa-de-mentira.pt",
        role="member",
        password_hash="x",
        name=nome,
    )


async def _montar_a_empresa(db):
    """A empresa de mentira do cabeçalho, pronta a interrogar."""
    ana, bruno, carla, diogo = (_pessoa(n) for n in ("Ana", "Bruno", "Carla", "Diogo"))
    dono = _pessoa("Dono")
    db.add_all([ana, bruno, carla, diogo, dono])
    await db.flush()

    erp = DataConnection(
        id=uuid.uuid4(),
        name="ERP",
        connector_id="postgres",
        config={},
        created_by=dono.id,
    )
    financeiro = Space(
        id=uuid.uuid4(),
        name="Financeiro",
        created_by=dono.id,
        privacy="private",
        sensitivity="confidential",
        is_demo=False,
    )
    marketing = Space(
        id=uuid.uuid4(),
        name="Marketing",
        created_by=dono.id,
        privacy="private",
        sensitivity="internal",
        is_demo=False,
    )
    db.add_all([erp, financeiro, marketing])
    await db.flush()

    contas = Crew(id=uuid.uuid4(), name="Contas", space_id=financeiro.id, created_by=dono.id)
    payroll = Crew(id=uuid.uuid4(), name="Payroll", space_id=financeiro.id, created_by=dono.id)
    campanhas = Crew(id=uuid.uuid4(), name="Campanhas", space_id=marketing.id, created_by=dono.id)
    db.add_all([contas, payroll, campanhas])
    await db.flush()

    db.add_all(
        [
            # A equipa Contas trata de faturação; a Payroll de salários. A mesma
            # ligação, fatias diferentes — é aqui que uma fuga apareceria.
            CrewTable(crew_id=contas.id, connection_id=erp.id, table_name="faturas"),
            CrewTable(crew_id=contas.id, connection_id=erp.id, table_name="clientes"),
            CrewTable(crew_id=payroll.id, connection_id=erp.id, table_name="salarios"),
            CrewMember(id=uuid.uuid4(), crew_id=contas.id, user_id=ana.id, role="editor"),
            CrewMember(id=uuid.uuid4(), crew_id=payroll.id, user_id=bruno.id, role="editor"),
            CrewMember(id=uuid.uuid4(), crew_id=campanhas.id, user_id=diogo.id, role="editor"),
            # A Carla não entra em equipa nenhuma. É a pessoa que interessa.
        ]
    )
    await db.flush()

    return {
        "ana": ana, "bruno": bruno, "carla": carla, "diogo": diogo, "dono": dono,
        "erp": erp, "financeiro": financeiro, "marketing": marketing,
        "contas": contas, "payroll": payroll, "campanhas": campanhas,
    }


# ── 1. Quem está numa equipa vê o que essa equipa tem ────────────────────────

@pytest.mark.asyncio
async def test_a_ana_ve_a_faturacao_da_sua_equipa(db_session):
    e = await _montar_a_empresa(db_session)
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(
        e["ana"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["contas"].id]
    )
    assert sorted(visto) == ["clientes", "faturas"]


# ── 2. E não vê o que é da equipa do lado ────────────────────────────────────

@pytest.mark.asyncio
async def test_a_ana_nao_ve_os_salarios_do_bruno(db_session):
    """Mesma ligação, mesma empresa, equipa diferente.

    É a fuga mais fácil de ter sem dar por ela: as duas tabelas vivem na mesma
    base de dados e basta um filtro esquecido para a Ana ver os ordenados.
    """
    e = await _montar_a_empresa(db_session)
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(
        e["ana"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["contas"].id]
    )
    assert "salarios" not in visto


# ── 3. Quem não está em equipa nenhuma não vê nada ───────────────────────────

@pytest.mark.asyncio
async def test_a_carla_nao_esta_em_equipa_nenhuma_e_nao_ve_nada(db_session):
    """A porta fecha por omissão.

    Se um dia isto passar a devolver tabelas, alguém trocou "sem concessões"
    por "todas as concessões" — que é o defeito clássico deste tipo de portão.
    """
    e = await _montar_a_empresa(db_session)
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(
        e["carla"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[]
    )
    assert visto == []


# ── 4. Nem quem vem de outro projeto ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_o_diogo_do_marketing_nao_ve_o_financeiro(db_session):
    e = await _montar_a_empresa(db_session)
    svc = PermissionService(db_session)

    visto = await svc.get_authorized_tables(
        e["diogo"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["campanhas"].id]
    )
    assert visto == []


# ── 5. O convite dá acesso — e só ao que aquela equipa tem ───────────────────

@pytest.mark.asyncio
async def test_convidar_a_carla_para_a_payroll_da_lhe_os_salarios_e_mais_nada(db_session):
    """O convite é isto: uma linha de pertença a uma equipa.

    E o teste guarda as duas metades — o que ela passa a ver, e o que **continua**
    a não ver. Um convite que desse o projeto todo seria muito mais fácil de
    escrever, e seria o defeito.
    """
    e = await _montar_a_empresa(db_session)
    svc = PermissionService(db_session)

    antes = await svc.get_authorized_tables(
        e["carla"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[]
    )
    assert antes == []

    db_session.add(
        CrewMember(id=uuid.uuid4(), crew_id=e["payroll"].id, user_id=e["carla"].id, role="viewer")
    )
    await db_session.flush()

    depois = await svc.get_authorized_tables(
        e["carla"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["payroll"].id]
    )
    assert depois == ["salarios"]
    assert "faturas" not in depois, "entrar na Payroll não é entrar na Contas"


# ── 6. E tirar da equipa tira o acesso ───────────────────────────────────────

@pytest.mark.asyncio
async def test_tirar_a_concessao_tira_o_acesso(db_session):
    """Sair da equipa (ou perder a concessão) tem de doer no mesmo instante.

    De nada serve conceder bem se revogar não fizer nada — é a metade que
    ninguém testa e a que dá as notícias más.
    """
    e = await _montar_a_empresa(db_session)
    svc = PermissionService(db_session)

    assert await svc.get_authorized_tables(
        e["bruno"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["payroll"].id]
    ) == ["salarios"]

    concessao = await db_session.get(
        CrewTable,
        (
            await db_session.execute(
                CrewTable.__table__.select().where(CrewTable.crew_id == e["payroll"].id)
            )
        ).first()[0],
    )
    await db_session.delete(concessao)
    await db_session.flush()

    assert await svc.get_authorized_tables(
        e["bruno"].id, e["erp"].id, space_id=e["financeiro"].id, crew_ids=[e["payroll"].id]
    ) == []


# ── 7. O que é dito a quem não tem acesso ────────────────────────────────────

@pytest.mark.asyncio
async def test_a_recusa_e_uma_recusa_limpa_e_nao_um_erro_interno(db_session):
    """Quem não pode tem de levar com um "não pode" — não com um 500.

    A diferença não é cosmética: um erro interno diz a quem sonda que ali houve
    código a rebentar, e às vezes diz **porquê**. Uma recusa limpa não diz nada
    sobre o que existe do outro lado.
    """
    e = await _montar_a_empresa(db_session)
    rbac = RBACService(db_session)

    with pytest.raises(ForbiddenError) as recusa:
        await rbac.assert_permission(e["carla"], "connections.view", crew_id=e["payroll"].id)

    mensagem = str(recusa.value)
    assert mensagem, "uma recusa sem mensagem não ajuda ninguém a perceber o que fazer"
    # E não pode ir lá dentro um traço de pilha nem o nome de uma tabela.
    for fuga in ("Traceback", "SELECT", "psycopg", "salarios"):
        assert fuga not in mensagem


# ── 8. O agente de uma equipa não corre para quem não é da equipa ────────────

@pytest.mark.asyncio
async def test_um_estranho_nao_pode_correr_o_agente_da_payroll(db_session):
    """A fuga que esta sonda encontrou, agora fechada.

    A guarda de âmbito (`_assert_can_act_on_agent_scope`) só passava o
    `space_id` ao RBAC. Num agente de **equipa** ficava tudo a `None`, a
    verificação caía no papel genérico da pessoa no cliente — que qualquer
    membro tem — e passava.

    Não era académico: logo a seguir, o filtro de tabelas usa
    `resolved_crew_ids = [agent.scope_id]`, ou seja **a equipa do agente**, não
    as de quem o corre. E o `get_agent` devolve qualquer agente por id, sem
    filtrar visibilidade. Bastava saber o UUID para receber respostas com os
    dados da equipa alheia.
    """
    from src.api.v1.agents import _assert_can_act_on_agent_scope

    e = await _montar_a_empresa(db_session)

    # O Diogo é do Marketing. A Payroll não é dele.
    with pytest.raises(Exception) as recusa:
        await _assert_can_act_on_agent_scope(
            db_session,
            e["diogo"],
            scope="crew",
            scope_id=str(e["payroll"].id),
            permission="agents.run",
        )
    assert "403" in str(recusa.value) or "denied" in str(recusa.value).lower() or "permission" in str(recusa.value).lower()


@pytest.mark.asyncio
async def test_quem_e_da_equipa_continua_a_poder_correr_o_agente_dela(db_session):
    """A metade que a correção não pode partir."""
    from src.api.v1.agents import _assert_can_act_on_agent_scope

    e = await _montar_a_empresa(db_session)
    # O Bruno É da Payroll — tem de continuar a passar.
    await _assert_can_act_on_agent_scope(
        db_session,
        e["bruno"],
        scope="crew",
        scope_id=str(e["payroll"].id),
        permission="agents.view",
    )
