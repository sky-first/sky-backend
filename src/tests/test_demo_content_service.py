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
                question=f"Pergunta {i}",
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
        question="e a margem?",
        live_answer=lento,
        timeout_s=0.05,
    )

    assert is_fallback is True
    assert live is None
    assert qa is not None, "tem de haver conteúdo curado para onde cair"


@pytest.mark.asyncio
async def test_ask_com_motor_a_rebentar_cai_em_fallback(db_session):
    """Qualquer excepção do motor degrada — não propaga."""
    ds = await _seed(db_session, vertical="saas")

    async def rebenta(_q):
        raise RuntimeError("motor em baixo")

    qa, live, is_fallback = await svc.ask(
        db_session, dataset_id=ds.id, question="e a margem?", live_answer=rebenta
    )

    assert is_fallback is True
    assert qa is not None


@pytest.mark.asyncio
async def test_ask_sem_motor_nenhum_ainda_responde(db_session):
    """Motor completamente indisponível — o bootstrap e as respostas
    curadas continuam a servir."""
    ds = await _seed(db_session, vertical="saas")

    qa, live, is_fallback = await svc.ask(
        db_session, dataset_id=ds.id, question="e a margem?", live_answer=None
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
