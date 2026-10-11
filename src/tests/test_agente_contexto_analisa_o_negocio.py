# -*- coding: utf-8 -*-
"""«Todo lo que ve este proyecto»: analisar o negócio, não contar linhas.

> «Quero que seja inteligente: que olhe para o negócio através dos dados do
>  projeto e traga melhorias, alertas, ameaças e oportunidades — com números
>  concretos e o passo seguinte.» — Lucas, 11/10/2026

O modo «contexto» mandava UMA pergunta com `sql_instructions` a obrigar a
contar as linhas de cada tabela. Agora é um plano de poucas perguntas (no
máximo `MAX_PERGUNTAS_POR_CORRIDA`), guiado pelo objectivo, e uma síntese só
com as secções que trouxeram números.

Estes testes CORREM o worker com o motor falso de
`test_agentes_cadencia_e_corridas`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.models.agent import AgentFinding
from src.services import analise_do_negocio as an
from src.services import limites_do_plano as lim
from src.tests.test_agente_fontes_escolhidas_e_equipa import _agente, _demo, _membro
from src.tests.test_agentes_cadencia_e_corridas import (  # noqa: F401 — fixture
    _MotorFalso,
    _correr,
    _dono,
    corrida,
)


async def _do_projeto(db_session, monkeypatch, focus=None, lingua="es"):
    """Agente «contexto» de equipa, no projeto da sementeira, sem fontes escolhidas."""
    from src.workers import agent_worker

    semente = await _dono(db_session)
    lucas = await _dono(db_session, lingua)
    _, equipa, ligacoes = await _demo(db_session, semente)
    await _membro(db_session, equipa, lucas)

    async def _ambito(db, agent):
        return [c.id for c in ligacoes]

    monkeypatch.setattr(agent_worker, "_ligacoes_do_ambito", _ambito)
    return await _agente(
        db_session, lucas, scope="crew", scope_id=equipa.id, monitor_type="context", focus=focus
    )


def _perguntas():
    return [c["question"] for c in _MotorFalso.chamadas]


# ── 1. O plano segue o objectivo ────────────────────────────────────────


@pytest.mark.asyncio
async def test_oportunidades_de_negocio_pergunta_so_por_oportunidades(
    db_session, corrida, monkeypatch
):
    a = await _do_projeto(db_session, monkeypatch, "Oportunidades de negocio")

    await _correr(db_session, a)

    perguntas = _perguntas()
    assert len(perguntas) == 2, "as duas variantes do ângulo pedido"
    assert "creciendo" in perguntas[0]
    assert "oportunidad de negocio" in perguntas[1]
    for p in perguntas:
        assert "amenaza" not in p.lower() and "fallando" not in p
    # Já não se conta linhas: nada de SQL imposto.
    for c in _MotorFalso.chamadas:
        assert not c.get("sql_instructions")
        assert "Oportunidades de negocio" in c["instructions"]
        assert an.SEM_EVIDENCIA in c["instructions"]
        assert c["agent_mode"] == "context"
        assert c["crew_ids"] == [a.scope_id]


@pytest.mark.parametrize(
    "focus", [None, "", "Scan all data for anomalies, trends, risks, and opportunities."]
)
@pytest.mark.asyncio
async def test_sem_objetivo_faz_os_quatro_angulos(db_session, corrida, monkeypatch, focus):
    a = await _do_projeto(db_session, monkeypatch, focus)

    await _correr(db_session, a)

    perguntas = _perguntas()
    assert len(perguntas) == 4
    assert "creciendo" in perguntas[0]
    assert "fallando" in perguntas[1]
    assert "amenaza" in perguntas[2]
    assert "mejorar" in perguntas[3]
    # Todas as fontes do âmbito em cada pergunta, como o chat.
    assert all(len(c["connection_ids"]) == 3 for c in _MotorFalso.chamadas)
    # O objectivo por omissão continua a ir nas instruções.
    assert "amenazas y alertas" in _MotorFalso.chamadas[0]["instructions"]


@pytest.mark.asyncio
async def test_amenazas_y_alertas_pede_os_dois_angulos(db_session, corrida, monkeypatch):
    a = await _do_projeto(db_session, monkeypatch, "Amenazas y alertas")

    await _correr(db_session, a)

    perguntas = _perguntas()
    assert len(perguntas) == 4
    assert all(
        ("fallando" in p or "amenaza" in p.lower() or "desviado" in p or "empeorando" in p)
        for p in perguntas
    )
    assert not any("creciendo" in p for p in perguntas)


@pytest.mark.asyncio
async def test_objetivo_livre_e_a_primeira_pergunta(db_session, corrida, monkeypatch):
    a = await _do_projeto(db_session, monkeypatch, "¿Qué restaurante vende menos postres?")

    await _correr(db_session, a)

    perguntas = _perguntas()
    assert perguntas[0] == "¿Qué restaurante vende menos postres?"
    assert len(perguntas) == an.MAX_PERGUNTAS_POR_CORRIDA


@pytest.mark.asyncio
async def test_o_tecto_de_perguntas_e_respeitado(db_session, corrida, monkeypatch):
    monkeypatch.setattr(an, "MAX_PERGUNTAS_POR_CORRIDA", 2)
    a = await _do_projeto(db_session, monkeypatch, None)

    await _correr(db_session, a)

    assert len(_MotorFalso.chamadas) == 2


def test_o_plano_nunca_passa_do_maximo():
    for objetivo in (None, "Oportunidades", "Amenazas y alertas", "texto livre qualquer"):
        for maximo in (1, 2, 3, 4):
            assert len(an.plano_de_analise(objetivo, "es", [], maximo=maximo)) <= maximo
    assert an.MAX_PERGUNTAS_POR_CORRIDA <= 4


# ── 2. O catálogo ancora as perguntas — só no que o dono alcança ────────


async def _ligacao_com_catalogo(db, dono):
    from src.models.connection import ConnectionMetadata, DataConnection

    c = DataConnection(
        id=uuid.uuid4(), name="Ventas", connector_id="postgresql", config={}, created_by=dono.id
    )
    db.add(c)
    await db.flush()
    db.add(
        ConnectionMetadata(
            connection_id=c.id,
            tables=[
                {
                    "name": "sales.pedidos",
                    "description": "Pedidos de clientes",
                    "row_count": 5000,
                    "columns": [
                        {"name": "fecha", "type": "date"},
                        {"name": "importe", "type": "numeric"},
                    ],
                },
                {"name": "sales.tmp_x", "columns": [{"name": "a", "type": "text"}]},
            ],
        )
    )
    await db.commit()
    return c


@pytest.mark.asyncio
async def test_o_catalogo_ancora_as_perguntas(db_session, corrida, monkeypatch):
    from src.workers import agent_worker

    lucas = await _dono(db_session, "es")
    c = await _ligacao_com_catalogo(db_session, lucas)

    async def _ambito(db, agent):
        return [c.id]

    monkeypatch.setattr(agent_worker, "_ligacoes_do_ambito", _ambito)
    a = await _agente(
        db_session, lucas, scope="personal", scope_id=lucas.id, monitor_type="context"
    )

    await _correr(db_session, a)

    assert any("«Pedidos de clientes»" in p for p in _perguntas())


@pytest.mark.asyncio
async def test_tabela_fora_do_recorte_da_equipa_nao_e_tema(db_session, corrida, monkeypatch):
    """Equipa sem tabelas concedidas: o catálogo fecha, as perguntas saem genéricas."""
    from src.models.connection import ConnectionMetadata

    a = await _do_projeto(db_session, monkeypatch, None)
    # Catálogo numa das ligações do projeto, sem CrewTable para a equipa.
    from src.workers import agent_worker

    ids = await agent_worker._ligacoes_do_ambito(db_session, a)
    db_session.add(
        ConnectionMetadata(
            connection_id=ids[0],
            tables=[{"name": "rrhh.salarios", "description": "Salarios del personal"}],
        )
    )
    await db_session.commit()

    await _correr(db_session, a)

    assert _perguntas() and not any("Salarios" in p for p in _perguntas())


# ── 3. A quota do plano ─────────────────────────────────────────────────


def _sem_quota():
    return lim.LimiteDoPlanoError(
        recurso="max_queries_per_month", limite=500, atual=500, plano="starter"
    )


@pytest.mark.asyncio
async def test_quota_acaba_a_meio_para_sem_falhar_e_mostra_o_que_ja_tem(
    db_session, corrida, monkeypatch
):
    a = await _do_projeto(db_session, monkeypatch, None)
    _MotorFalso.respostas = [
        {"answer": "La zona Norte crece un 18 % (42.300 €).\nSiguiente paso: reforzar Norte."},
        _sem_quota(),
        {"answer": "nunca se pregunta"},
    ]

    ex = await _correr(db_session, a)

    assert len(_MotorFalso.chamadas) == 2, "parou na pergunta que esgotou a quota"
    assert ex.status == "completed"
    assert a.consecutive_failures == 0 and a.status == "active"
    assert "### Oportunidades" in corrida[-1]["answer"]
    assert "### Alertas" not in corrida[-1]["answer"]


@pytest.mark.asyncio
async def test_quota_acaba_logo_na_primeira_salta_sem_falhar(db_session, corrida, monkeypatch):
    a = await _do_projeto(db_session, monkeypatch, None)
    _MotorFalso.respostas = [_sem_quota()]

    ex = await _correr(db_session, a)

    assert len(_MotorFalso.chamadas) == 1
    assert ex.status == "skipped_plan_quota"
    assert corrida[-1]["chave"] == "agent_skipped_plan_quota"
    assert a.consecutive_failures == 0 and a.status == "active"


# ── 4. A síntese: só secções com evidência, na língua do dono ───────────


@pytest.mark.asyncio
async def test_sintese_so_tem_seccoes_com_evidencia_em_castelhano(db_session, corrida, monkeypatch):
    a = await _do_projeto(db_session, monkeypatch, None, lingua="es")
    _MotorFalso.respostas = [
        {
            "answer": "Los clientes de Madrid crecen un 23 % (12.400 €).\nSiguiente paso: abrir una ruta más."
        },
        {
            "answer": "37 pedidos llegaron tarde esta semana (8 % del total).\n**Siguiente paso:** revisar la ruta 4."
        },
        {"answer": "NO_EVIDENCE"},
        {"answer": "No veo nada relevante que mejorar."},
    ]

    ex = await _correr(db_session, a)

    assert ex.status == "completed" and ex.findings_count == 1
    msg = corrida[-1]["answer"]
    assert msg.startswith("Lo que he visto")
    assert "### Oportunidades" in msg and "### Alertas" in msg
    assert "Amenazas" not in msg and "Mejoras" not in msg
    assert "12.400 €" in msg and "37 pedidos" in msg
    assert msg.count("**Siguiente paso:**") == 2
    assert "NO_EVIDENCE" not in msg
    achado = (await db_session.execute(select(AgentFinding))).scalars().one()
    assert corrida[-1]["finding_id"] == achado.id
    assert achado.title == "Oportunidades · Alertas"
    assert achado.viz_kind == "bullet_list"
    assert "### Oportunidades" in achado.description
    assert a.last_answer and "12.400" in a.last_answer


@pytest.mark.asyncio
async def test_sintese_em_portugues(db_session, corrida, monkeypatch):
    a = await _do_projeto(db_session, monkeypatch, None, lingua="pt")
    _MotorFalso.respostas = [
        {"answer": "NO_EVIDENCE"},
        {"answer": "NO_EVIDENCE"},
        {"answer": "3 clientes valem 61 % da receita.\nPróximo passo: diversificar."},
        {"answer": "A loja do Porto custa mais 14 % por pedido.\nPróximo passo: rever turnos."},
    ]

    await _correr(db_session, a)

    msg = corrida[-1]["answer"]
    assert msg.startswith("O que vi nos dados")
    assert "### Ameaças" in msg and "### Melhorias" in msg
    assert "### Oportunidades" not in msg and "### Alertas" not in msg
    assert msg.count("**Próximo passo:**") == 2
    # A pergunta foi feita em português.
    assert "Onde é que o negócio está a crescer" in _MotorFalso.chamadas[0]["question"]


@pytest.mark.asyncio
async def test_sem_evidencia_nenhuma_diz_nada_a_assinalar(db_session, corrida, monkeypatch):
    a = await _do_projeto(db_session, monkeypatch, None, lingua="es")
    _MotorFalso.respostas = [{"answer": "NO_EVIDENCE"}] * 4

    ex = await _correr(db_session, a)

    assert ex.status == "completed" and ex.findings_count == 0
    assert corrida[-1]["chave"] == "agent_nothing_to_report"
    assert corrida[-1]["answer"].startswith("Acabo de mirar")
    assert a.consecutive_failures == 0


@pytest.mark.asyncio
async def test_uma_pergunta_que_rebenta_nao_estraga_as_outras(db_session, corrida, monkeypatch):
    a = await _do_projeto(db_session, monkeypatch, None, lingua="es")
    _MotorFalso.respostas = [
        RuntimeError("HTTPStatusError 500"),
        {"answer": "12 incidencias abiertas hace más de 7 días.\nSiguiente paso: cerrarlas."},
        {"answer": "NO_EVIDENCE"},
        {"answer": "NO_EVIDENCE"},
    ]

    ex = await _correr(db_session, a)

    assert ex.status == "completed"
    assert "### Alertas" in corrida[-1]["answer"]


@pytest.mark.asyncio
async def test_todas_rebentam_e_falha(db_session, corrida, monkeypatch):
    a = await _do_projeto(db_session, monkeypatch, None)
    _MotorFalso.respostas = [RuntimeError("HTTPStatusError 500")] * 4

    ex = await _correr(db_session, a)

    assert ex.status == "failed"
    assert corrida[-1]["chave"] == "agent_could_not_run"
    assert a.consecutive_failures == 1


# ── 5. Custo: dados iguais não repetem o plano ──────────────────────────


@pytest.mark.asyncio
async def test_dados_iguais_nao_repetem_o_plano(db_session, corrida, monkeypatch):
    a = await _do_projeto(db_session, monkeypatch, None)
    _MotorFalso.respostas = [{"answer": "Crece un 5 % (1.000 €)."}]
    await _correr(db_session, a)
    assert len(_MotorFalso.chamadas) == 4

    _MotorFalso.chamadas = []
    ex = await _correr(db_session, a)  # agendada, sem nada novo nas fontes

    assert ex.status == "skipped_no_delta"
    assert _MotorFalso.chamadas == []


# ── 6. Os outros modos não mudam ────────────────────────────────────────


@pytest.mark.asyncio
async def test_una_pregunta_mia_continua_uma_pergunta(db_session, corrida, monkeypatch):
    from src.workers import agent_worker

    semente = await _dono(db_session)
    lucas = await _dono(db_session, "es")
    _, equipa, ligacoes = await _demo(db_session, semente)
    await _membro(db_session, equipa, lucas)

    async def _ambito(db, agent):
        return [c.id for c in ligacoes]

    monkeypatch.setattr(agent_worker, "_ligacoes_do_ambito", _ambito)
    a = await _agente(
        db_session,
        lucas,
        scope="crew",
        scope_id=equipa.id,
        monitor_type="question",
        focus="¿Cuántas mesas he servido?",
    )
    _MotorFalso.respostas = [{"answer": "1.204 mesas"}]

    await _correr(db_session, a)

    assert len(_MotorFalso.chamadas) == 1
    assert _MotorFalso.chamadas[0]["question"] == "¿Cuántas mesas he servido?"
    assert corrida[-1]["answer"] == "1.204 mesas"


@pytest.mark.asyncio
async def test_una_fuente_continua_uma_pergunta_com_o_objetivo(db_session, corrida, monkeypatch):
    semente = await _dono(db_session)
    lucas = await _dono(db_session, "es")
    _, equipa, (servicio, _, _) = await _demo(db_session, semente)
    await _membro(db_session, equipa, lucas)
    a = await _agente(
        db_session,
        lucas,
        scope="crew",
        scope_id=equipa.id,
        ligacoes=[servicio],
        monitor_type="datasource",
        focus="Formas de mejorar",
    )
    _MotorFalso.respostas = [{"answer": "ok"}]

    await _correr(db_session, a)

    assert len(_MotorFalso.chamadas) == 1
    assert "Formas de mejorar" in _MotorFalso.chamadas[0]["instructions"]
    assert an.SEM_EVIDENCIA not in _MotorFalso.chamadas[0]["instructions"]


# ── 7. Peças puras ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "objetivo,angulos",
    [
        ("Oportunidades de negocio", ["oportunidades"]),
        ("Fallos en mi operación", ["alertas"]),
        ("Formas de mejorar", ["melhorias"]),
        ("Amenazas y alertas", ["alertas", "ameacas"]),
        ("Ameaças e alertas", ["alertas", "ameacas"]),
        ("Business opportunities", ["oportunidades"]),
        (None, list(an.ANGULOS)),
    ],
)
def test_angulos_do_objetivo(objetivo, angulos):
    assert an.angulos_do_objetivo(objetivo) == (angulos, None)


@pytest.mark.parametrize(
    "texto,conta",
    [
        ("", False),
        ("NO_EVIDENCE", False),
        ("SIN_EVIDENCIA", False),
        ("Las ventas van bien.", False),  # sem número é opinião
        ("Las ventas suben un 4 %.", True),
    ],
)
def test_tem_evidencia(texto, conta):
    assert an.tem_evidencia(texto) is conta
