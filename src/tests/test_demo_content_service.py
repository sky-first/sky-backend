"""Serviço do conteúdo curado da demo — BE-12.

A regra que estes testes protegem: **o caminho crítico da demo nunca
pode falhar nem depender do LLM**. Foi um timeout no primeiro contacto
que motivou todo este trabalho.

Exercitam o serviço directamente. Os testes com TestClient neste repo
estão partidos por incompatibilidade starlette/httpx no ambiente, e um
teste que não corre não protege nada.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from src.models.demo_content import DemoDataset, DemoInsight, DemoQA
from src.services import demo_content_service as svc


async def _seed(db, *, vertical="saas", locale="en", is_default=False, n_qa=4):
    ds = DemoDataset(
        id=uuid.uuid4(),
        vertical=vertical,
        name=f"Demo {vertical}",
        locale=locale,
        is_default=is_default,
    )
    db.add(ds)
    await db.flush()

    db.add(
        DemoInsight(
            id=uuid.uuid4(),
            dataset_id=ds.id,
            severity="opportunity",
            severity_level="info",
            agent_name="Pipeline Watch",
            title="Enterprise pipeline acelerou 23% depois da campanha ABM",
            summary="Fecharam em 41 dias contra 53. O ticket manteve-se.",
            stat_tiles=[{"label": "dias", "value": "41"}],
            sources=[{"table": "crm.deals", "description": "negócios"}],
            executed_sql="SELECT 1",
            position=0,
        )
    )
    for i in range(n_qa):
        db.add(
            DemoQA(
                id=uuid.uuid4(),
                dataset_id=ds.id,
                # Perguntas com palavras a sério: o fallback ordena por
                # palavras em comum, e "Pergunta 0" não tem nenhuma.
                question=f"Que clientes gastaram menos no trimestre {i}?",
                answer_markdown=f"Resposta {i}",
                citations=[{"table": "crm.deals"}],
                position=i,
                is_suggested=i < 3,
            )
        )
    await db.commit()
    return ds


# ─── selecção de dataset ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vertical_desconhecida_cai_no_default(db_session):
    """Nunca 404. Quem chega com um parâmetro estragado tem de ver a demo
    na mesma — 404 transformaria um detalhe em porta fechada."""
    await _seed(db_session, vertical="default", is_default=True)

    ds = await svc.get_dataset(db_session, vertical="nao-existe")

    assert ds is not None
    assert ds.is_default is True


@pytest.mark.asyncio
async def test_vertical_conhecida_devolve_a_certa(db_session):
    await _seed(db_session, vertical="default", is_default=True)
    await _seed(db_session, vertical="saas")

    ds = await svc.get_dataset(db_session, vertical="saas")

    assert ds.vertical == "saas"


@pytest.mark.asyncio
async def test_sem_vertical_devolve_o_default(db_session):
    """É o caminho do botão 'Saltar'."""
    await _seed(db_session, vertical="default", is_default=True)

    ds = await svc.get_dataset(db_session)

    assert ds.is_default is True


@pytest.mark.asyncio
async def test_locale_sem_conteudo_cai_para_ingles(db_session):
    await _seed(db_session, vertical="default", is_default=True, locale="en")

    ds = await svc.get_dataset(db_session, vertical="saas", locale="pt-PT")

    assert ds is not None
    assert ds.locale == "en"


# ─── conteúdo do primeiro ecrã ──────────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_traz_insight_e_tres_perguntas(db_session):
    ds = await _seed(db_session, vertical="saas", n_qa=5)

    insight = await svc.get_insight(db_session, ds.id)
    suggested = await svc.get_suggested(db_session, ds.id)

    assert insight is not None
    assert insight.executed_sql, "o 'ver o SQL' é o elemento de prova do ecrã"
    assert len(suggested) == 3, "só três cabem sem competir com o herói"


@pytest.mark.asyncio
async def test_so_as_marcadas_como_sugeridas_aparecem(db_session):
    """As restantes existem apenas como alvo do fallback."""
    ds = await _seed(db_session, vertical="saas", n_qa=5)

    suggested = await svc.get_suggested(db_session, ds.id, limit=10)

    assert len(suggested) == 3
    assert all(q.is_suggested for q in suggested)


# ─── ask: o caminho que não pode falhar ─────────────────────────────


@pytest.mark.asyncio
async def test_ask_ao_vivo_responde_sem_fallback(db_session):
    ds = await _seed(db_session, vertical="saas")

    async def rapido(_q):
        return {"id": "live", "answer_markdown": "resposta ao vivo"}

    qa, live, is_fallback = await svc.ask(
        db_session, dataset_id=ds.id, question="e a margem?", live_answer=rapido
    )

    assert is_fallback is False
    assert live["answer_markdown"] == "resposta ao vivo"
    assert qa is None


@pytest.mark.asyncio
async def test_ask_com_timeout_cai_em_fallback_sem_erro(db_session):
    """O motor lento não pode virar ecrã de erro numa demo comercial."""
    ds = await _seed(db_session, vertical="saas")

    async def lento(_q):
        await asyncio.sleep(5)
        return {"answer_markdown": "tarde demais"}

    qa, live, is_fallback = await svc.ask(
        db_session,
        dataset_id=ds.id,
        question="que clientes gastaram menos?",
        live_answer=lento,
        timeout_s=0.05,
    )

    assert is_fallback is True
    assert live is None
    assert qa is not None, "há conteúdo curado próximo — tem de cair nele"


@pytest.mark.asyncio
async def test_ask_com_motor_a_rebentar_cai_em_fallback(db_session):
    """Qualquer excepção do motor degrada — não propaga."""
    ds = await _seed(db_session, vertical="saas")

    async def rebenta(_q):
        raise RuntimeError("motor em baixo")

    qa, live, is_fallback = await svc.ask(
        db_session, dataset_id=ds.id, question="que clientes gastaram menos?", live_answer=rebenta
    )

    assert is_fallback is True
    assert qa is not None


@pytest.mark.asyncio
async def test_ask_sem_motor_nenhum_ainda_responde(db_session):
    """Motor completamente indisponível — o bootstrap e as respostas
    curadas continuam a servir."""
    ds = await _seed(db_session, vertical="saas")

    qa, live, is_fallback = await svc.ask(
        db_session, dataset_id=ds.id, question="que clientes gastaram menos?", live_answer=None
    )

    assert is_fallback is True
    assert qa is not None


def test_timeout_nao_e_o_da_spec_original():
    """A spec propunha 8s. Medição em produção: ~13,7s por pergunta real.
    Com 8s, 100% cairia em fallback e o caminho ao vivo seria teatro."""
    assert svc.LIVE_ANSWER_TIMEOUT_S > 13.7


# ─── leads ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lead_e_idempotente_por_email(db_session):
    """Um lead por pessoa, não um por clique."""
    ds = await _seed(db_session, vertical="saas")

    a = await svc.record_lead(db_session, email="Jane@Acme.com", dataset_id=ds.id)
    b = await svc.record_lead(db_session, email="jane@acme.com", dataset_id=ds.id)

    assert a.id == b.id
    assert a.email == "jane@acme.com", "normalizado em minúsculas"


@pytest.mark.asyncio
async def test_lead_acumula_perguntas_entre_visitas(db_session):
    """A segunda visita não apaga o que se aprendeu na primeira."""
    ds = await _seed(db_session, vertical="saas")

    await svc.record_lead(
        db_session, email="jane@acme.com", dataset_id=ds.id, questions_asked=["q1"]
    )
    lead = await svc.record_lead(
        db_session, email="jane@acme.com", dataset_id=ds.id, questions_asked=["q2"]
    )

    assert set(lead.questions_asked) == {"q1", "q2"}


@pytest.mark.asyncio
async def test_lead_aceita_dominios_comuns(db_session):
    """O filtro de 'throwaway providers' da demo antiga barrava clientes
    reais que usam gmail como email de empresa."""
    lead = await svc.record_lead(db_session, email="fundador@gmail.com")

    assert lead.email == "fundador@gmail.com"


# ─── achados do ecrã de agentes ─────────────────────────────────────


@pytest.mark.asyncio
async def test_get_insights_devolve_todos_por_ordem(db_session):
    """A ordem é a da curadoria, e o herói fica em primeiro.

    O ecrã de achados do telemóvel serve esta lista tal como vem. Se a
    ordem escorregasse, o achado escolhido para abrir a demo deixava de
    a abrir sem que ninguém desse por isso.
    """
    ds = await _seed(db_session)
    for i, name in enumerate(["Collections", "Growth"], start=1):
        db_session.add(
            DemoInsight(
                id=uuid.uuid4(),
                dataset_id=ds.id,
                severity="cash_uncollected",
                severity_level="warning",
                agent_name=name,
                title=f"Achado {i}",
                summary="…",
                stat_tiles=[{"label": "n", "value": "17"}],
                sources=[{"table": "finance.invoices"}],
                executed_sql="SELECT 1",
                position=i,
            )
        )
    await db_session.commit()

    rows = await svc.get_insights(db_session, ds.id)
    assert [r.agent_name for r in rows] == ["Pipeline Watch", "Collections", "Growth"]
    # E o herói continua a ser o mesmo objecto que o primeiro ecrã serve.
    hero = await svc.get_insight(db_session, ds.id)
    assert hero is not None and hero.id == rows[0].id


@pytest.mark.asyncio
async def test_get_insights_nao_estoura_o_ecra(db_session):
    """Mais achados curados do que os que cabem — corta, não enche.

    Três é o que cabe no telefone sem cortar o último a meio, e um
    cartão cortado lê-se como um erro de layout e não como "há mais".
    """
    ds = await _seed(db_session)
    for i in range(1, 6):
        db_session.add(
            DemoInsight(
                id=uuid.uuid4(),
                dataset_id=ds.id,
                severity="x",
                severity_level="info",
                agent_name=f"Agente {i}",
                title=f"Achado {i}",
                summary="…",
                stat_tiles=[],
                sources=[],
                executed_sql="SELECT 1",
                position=i,
            )
        )
    await db_session.commit()

    assert len(await svc.get_insights(db_session, ds.id)) == svc.INSIGHTS_LIMIT


# ─── quando não há resposta próxima ─────────────────────────────────


@pytest.mark.asyncio
async def test_pergunta_de_negocio_sem_correspondencia_nao_inventa(db_session):
    """O risco maior da demo não é a recusa — é a resposta trocada.

    Antes, qualquer pergunta que não fosse uma das curadas devolvia a
    **primeira** da lista com o rótulo "a mais próxima que temos".
    Perguntar pelo CAC e receber um relatório de churn é a forma mais
    rápida de um prospect concluir que o produto não percebeu nada — e
    ele só precisa de fazer três perguntas para lá chegar.
    """
    ds = await _seed(db_session, vertical="saas")

    qa, live, is_fallback = await svc.ask(
        db_session,
        dataset_id=ds.id,
        question="qual e o custo de aquisicao por coorte trimestral?",
    )

    assert live is None
    assert is_fallback is True
    assert qa is None, "melhor não responder do que responder outra coisa"


def test_o_limiar_de_correspondencia_distingue_assuntos():
    """Sem embeddings, a ordenação é por palavras em comum.

    Não é semântica e não finge ser. Tem de chegar para não trocar
    faturas por churn, e para saber quando não há nada próximo.
    """
    curada = "How much revenue is sitting in overdue invoices, and who owes it?"

    perto = svc._overlap("how much revenue is overdue?", curada)
    longe = svc._overlap("what is my CAC by cohort?", curada)

    assert perto >= svc.MIN_MATCH_SCORE
    assert longe < svc.MIN_MATCH_SCORE
